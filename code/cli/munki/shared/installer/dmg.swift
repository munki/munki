//
//  dmg.swift
//  munki
//
//  Created by Greg Neagle on 8/4/24.
//  Copyright 2024-2026 The Munki Project. All rights reserved.
//

import Foundation

private let display = DisplayAndLog.main

/// Sets owner, group and mode for path from info in itemInfo.
/// Returns 0 on success, non-zero otherwise.
func setPermissions(_ itemInfo: PlistDict, path: String) -> Int {
    // Yes, we could call FileManager methods like setAttributes(_:ofItemAtPath:),
    // But the user and group might be names or numbers, and the mode is
    // supposed to be symbolic (but could also be in the format of "777",
    // So we're just going to call `chown` and `chmod`. This also allow us to easily
    // set these attributes recursively.

    let itemName = (path as NSString).lastPathComponent
    // set owner and group
    let user = itemInfo["user"] as? String ?? "root"
    let group = itemInfo["group"] as? String ?? "admin"
    display.detail("Setting owner and group for '\(itemName)' to '\(user):\(group)'")
    let chownResult = runCLI("/usr/sbin/chown", arguments: ["-R", user + ":" + group, path])
    if chownResult.exitcode != 0 {
        display.error("Error setting owner and group for \(itemName): (\(chownResult.exitcode)) \(chownResult.error)")
        return chownResult.exitcode
    }

    // set mode
    let mode = itemInfo["mode"] as? String ?? "o-w,go+rX"
    display.detail("Setting mode for '\(itemName)' to '\(mode)'")
    let chmodResult = runCLI("/bin/chmod", arguments: ["-R", mode, path])
    if chmodResult.exitcode != 0 {
        display.error("Error setting mode for \(itemName): \(chmodResult.error)")
        return chownResult.exitcode
    }

    // success!
    return 0
}

/// Validates source and destination for item to be copied from a mounted disk image.
/// Returns a tuple of (success, source_path, destination_path)
func validateSourceAndDestination(mountpoint: String, item: PlistDict) -> (Bool, String, String) {
    // Ensure source item is defined
    guard let sourceItemName = item["source_item"] as? String else {
        display.error("Missing name of item to copy!")
        return (false, "", "")
    }
    // Ensure source item exists
    let sourceItemPath = (mountpoint as NSString).appendingPathComponent(sourceItemName)
    if !pathExists(sourceItemPath) {
        display.error("Source item \(sourceItemName) does not exist!")
        return (false, "", "")
    }
    // get destination path and name
    var destinationPath = item["destination_path"] as? String ?? ""
    var destinationItemName = item["destination_item"] as? String ?? ""
    if destinationPath.isEmpty {
        destinationPath = item["destination_item"] as? String ?? ""
        if !destinationPath.isEmpty {
            destinationItemName = (destinationPath as NSString).lastPathComponent
            destinationPath = (destinationPath as NSString).deletingLastPathComponent
        }
    }
    if destinationPath.isEmpty {
        // fatal!
        display.error("Missing destination path for item!")
        return (false, "", "")
    }
    // create any needed intermediate directories for the destpath or fail
    if !createMissingDirs(destinationPath) {
        return (false, "", "")
    }
    // setup full destination path using 'destination_item', if supplied,
    // source_item if not.
    var fullDestinationPath = ""
    if destinationItemName.isEmpty {
        fullDestinationPath = (destinationPath as NSString).appendingPathComponent(baseName(sourceItemName))
    } else {
        fullDestinationPath = (destinationPath as NSString).appendingPathComponent(baseName(destinationItemName))
    }
    return (true, sourceItemPath, fullDestinationPath)
}

/// Subclass of AsyncProcessRunner that handles the progress output from /usr/bin/ditto
class DittoRunner: AsyncProcessRunner {
    var remainingErrorOutput = ""
    var totalBytesCopied = 0
    var sourceItemSize = 1

    init(sourcePath: String, destinationPath: String) {
        let tool = "/usr/bin/ditto"
        let arguments = ["-V", "--noqtn", sourcePath, destinationPath]
        sourceItemSize = getSize(sourcePath)
        super.init(tool, arguments: arguments)
    }

    func linesAndRemainderOf(_ str: String) -> ([String], String) {
        var lines = str.components(separatedBy: "\n")
        var remainder = ""
        if lines.count > 0, !str.hasSuffix("\n") {
            // last line of string did not end with a newline; might be a partial
            remainder = lines.last ?? ""
            lines.removeLast()
        }
        return (lines, remainder)
    }

    // ditto -V progress output goes to stderr(!)
    override func processError(_ str: String) {
        super.processError(str)
        let (lines, remainder) = linesAndRemainderOf(remainingErrorOutput + str)
        remainingErrorOutput = remainder
        for line in lines {
            let words = line.components(separatedBy: .whitespaces)
            if words.count > 1, words[1] == "bytes" {
                let bytesCopied = Int(words[0]) ?? 0
                totalBytesCopied += bytesCopied
                displayPercentDone(current: totalBytesCopied, maximum: sourceItemSize)
            }
        }
    }
}

/// Uses ditto to copy an item and provides progress output
func dittoWithProgress(sourcePath: String, destinationPath: String) async -> Int {
    let proc = DittoRunner(sourcePath: sourcePath, destinationPath: destinationPath)
    await proc.run()
    return proc.results.exitcode
}

/// Copies items from the mountpoint to the startup disk
/// Returns 0 if no issues; some error code otherwise.
func copyItemsFromMountpoint(_ mountpoint: String, itemList: [PlistDict]) async -> Int {
    guard let tempDestinationDir = TempDir.shared.makeTempDir() else {
        display.error("Could not create a temporary directory!")
        return -1
    }
    for item in itemList {
        let (success, sourcePath, destinationPath) = validateSourceAndDestination(mountpoint: mountpoint, item: item)
        if !success {
            return -1
        }
        // validation passed, OK to copy
        display.minorStatus("Copying \((sourcePath as NSString).lastPathComponent) to \(destinationPath)")
        let tempDestinationPath = (tempDestinationDir as NSString).appendingPathComponent((destinationPath as NSString).lastPathComponent)
        // copy the file or directory, removing the quarantine xattr and
        // preserving HFS+ compression
        let dittoresult = await dittoWithProgress(sourcePath: sourcePath, destinationPath: tempDestinationPath)
        if dittoresult != 0 {
            display.error("Error copying \(sourcePath) to \(tempDestinationPath)")
            return dittoresult
        }
        // remove com.apple.quarantine xattr since `man ditto` lies and doesn't
        // seem to actually always remove it
        do {
            try removeQuarantineXattrsRecursively(tempDestinationPath)
        } catch {
            display.error(
                "Failed to remove quarantine xattr for \(destinationPath): \(error.localizedDescription)")
        }
        // set desired permissions for item
        let permsresult = setPermissions(item, path: tempDestinationPath)
        if permsresult != 0 {
            // setPermissions already displayed an error
            return permsresult
        }
        // remove any previously exiting item at destinationPath
        if pathExists(destinationPath) {
            do {
                try FileManager.default.removeItem(atPath: destinationPath)
            } catch let err as NSError {
                display.error("Error removing existing item at destination: \(err.localizedDescription)")
                return -1
            } catch {
                display.error("Error removing existing item at destination: \(error)")
                return -1
            }
        }
        // move tempDestinationPath to final destination path
        do {
            try FileManager.default.moveItem(atPath: tempDestinationPath, toPath: destinationPath)
        } catch let err as NSError {
            display.error("Error moving item to destination: \(err.localizedDescription)")
            return -1
        } catch {
            display.error("Error moving item to destination: \(error)")
            return -1
        }
    }
    // all items were copied successfully, clean up
    try? FileManager.default.removeItem(atPath: tempDestinationDir)
    return 0
}

/// Copies items from disk image to local disk
func copyFromDmg(dmgPath: String, itemList: [PlistDict]) async -> Int {
    if itemList.isEmpty {
        display.error("No items to copy!")
        return -1
    }
    display.minorStatus("Mounting disk image \((dmgPath as NSString).lastPathComponent)")
    if let mountpoint = try? mountdmg(dmgPath, skipVerification: true) {
        let retcode = await copyItemsFromMountpoint(mountpoint, itemList: itemList)
        if retcode == 0 {
            display.minorStatus("The software was successfully installed.")
        }
        do {
            try unmountdmg(mountpoint)
        } catch {
            display.error(error.localizedDescription)
        }
        return retcode
    } else {
        display.error("Could not mount disk image file \((dmgPath as NSString).lastPathComponent)")
        return -1
    }
}

/// Creates any missing intermediate directories so we can copy item.
/// Returns boolean to indicate success or failure
func createMissingDirs(_ path: String) -> Bool {
    let filemanager = FileManager.default
    if filemanager.fileExists(atPath: path) {
        // the path exists; don't need to create anything
        return true
    }
    var parentPath = path
    // find a parent path that actually exists
    while !filemanager.fileExists(atPath: parentPath) {
        parentPath = (parentPath as NSString).deletingLastPathComponent
    }
    // get the owner, group and mode of this directory
    do {
        let attrs = try filemanager.attributesOfItem(atPath: parentPath)
        let user = (attrs as NSDictionary).fileOwnerAccountID() ?? NSNumber(0)
        let group = (attrs as NSDictionary).fileGroupOwnerAccountID() ?? NSNumber(0)
        var mode = (attrs as NSDictionary).filePosixPermissions()
        if mode == 0 {
            mode = 0o755
        }
        let preservedAttrs = [
            FileAttributeKey.ownerAccountID: user,
            FileAttributeKey.groupOwnerAccountID: group,
            FileAttributeKey.posixPermissions: mode,
        ] as [FileAttributeKey: Any]
        try filemanager.createDirectory(atPath: path, withIntermediateDirectories: true, attributes: preservedAttrs)
        return true
    } catch {
        display.error("Error creating path \(path): \(error.localizedDescription)")
        return false
    }
}
