//
//  manifests.swift
//  munki
//
//  Created by Greg Neagle on 8/9/24.
//

import Foundation

func manifestData(_ path: String) -> PlistDict? {
    // Reads a manifest file, returns a dictionary.
    if pathExists(path) {
        do {
            if let plist = try readPlist(fromFile: path) as? PlistDict {
                return plist
            } else {
                // could not coerce to correct format
                displayError("\(path) is the wrong format")
            }
        } catch let PlistError.readError(description) {
            displayError("file error for \(path): \(description)")
        } catch {
            displayError("file error for \(path): \(error.localizedDescription)")
        }
        // if we get here there's something wrong with the file. Try to remove it
        try? FileManager.default.removeItem(atPath: path)
    } else {
        displayError("\(path) does not exist")
    }
    return nil
}

func getManifestValue(_ path: String, forKey key: String) -> Any? {
    if let manifest = manifestData(path) {
        if let value = manifest[key] {
            return value
        } else {
            displayError("Failed to get manifest value for key: \(key) (\(path))")
        }
    }
    return nil
}

func removeItemFromSelfServeSection(itemname: String, section: String) {
    // Remove the given itemname from the self-serve manifest's
    // managed_uninstalls list
    displayDebug1("Removing \(itemname) from SelfServeManifest's \(section)...")
    let manifestPath = (managedInstallsDir() as NSString).appendingPathComponent("manifests/SelfServeManifest")
    if !pathExists(manifestPath) {
        displayDebug1("\(manifestPath) doesn't exist.")
        return
    }
    guard var manifest = manifestData(manifestPath) else {
        // manifestData displays its own errors
        return
    }
    // section should be a list of strings
    guard var sectionContents = manifest[section] as? [String] else {
        displayDebug1("\(manifestPath): missing or invalid \(section)")
        return
    }
    sectionContents = sectionContents.filter {
        $0 != itemname
    }
    manifest[section] = sectionContents
    do {
        try writePlist(manifest, toFile: manifestPath)
    } catch {
        displayDebug1("Error writing \(manifestPath): \(error.localizedDescription)")
    }
}

func removeFromSelfServeInstalls(_ itemName: String) {
    // Remove the given itemname from the self-serve manifest's
    // managed_installs list
    removeItemFromSelfServeSection(itemname: itemName, section: "managed_installs")
}

func removeFromSelfServeUninstalls(_ itemName: String) {
    // Remove the given itemname from the self-serve manifest's
    // managed_uninstalls list
    removeItemFromSelfServeSection(itemname: itemName, section: "managed_uninstalls")
}
