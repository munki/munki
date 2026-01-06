//
//  munkiimportlib.swift
//  munki
//
//  Created by Greg Neagle on 7/10/24.
//  Copyright 2024-2026 The Munki Project. All rights reserved.
//
//  Licensed under the Apache License, Version 2.0 (the "License");
//  you may not use this file except in compliance with the License.
//  You may obtain a copy of the License at
//
//       https://www.apache.org/licenses/LICENSE-2.0
//
//  Unless required by applicable law or agreed to in writing, software
//  distributed under the License is distributed on an "AS IS" BASIS,
//  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
//  See the License for the specific language governing permissions and
//  limitations under the License.

import Darwin.C
import Foundation

/// If there is exactly one supported architecture, return a string with it
/// Otherwise return empty string
func getSingleArch(_ pkginfo: PlistDict) -> String {
    if let archList = pkginfo["supported_architectures"] as? [String],
       archList.count == 1
    {
        return archList[0]
    }
    return ""
}

/// Copies an item to the appropriate place in the repo.
/// If itempath is a path within the repo/pkgs directory, copies nothing.
/// Renames the item if an item already exists with that name.
/// Returns the identifier for the item in the repo.
func copyInstallerItemToRepo(_ repo: Repo, itempath: String, version: String, subdirectory: String = "") async throws -> String {
    let destPath = ("pkgs" as NSString).appendingPathComponent(subdirectory)
    var itemName = (itempath as NSString).lastPathComponent
    var destIdentifier = (destPath as NSString).appendingPathComponent(itemName)

    // don't copy if the file is already in the repo
    if let filerepo = repo as? FileRepo {
        // FileRepo and subclasses have a fulPath method
        let repoPath = (filerepo.fullPath(destIdentifier) as NSString).standardizingPath
        let localPath = getAbsolutePath(itempath)
        if repoPath == localPath {
            // same file, no need to copy
            return destIdentifier
        }
    }
    let name = (itemName as NSString).deletingPathExtension
    var ext = (itemName as NSString).pathExtension
    if !ext.isEmpty {
        ext = "." + ext
    }
    if !version.isEmpty, !name.hasSuffix(version) {
        // add the version number to the end of the filename
        itemName = "\(name)-\(version)\(ext)"
        destIdentifier = (destPath as NSString).appendingPathComponent(itemName)
    }
    do {
        let pkgsList = try await listItemsOfKind(repo, "pkgs")
        var index = 0
        while pkgsList.contains(destIdentifier) {
            // try appending numbers until we have a unique name
            index += 1
            itemName = "\(name)__\(index)\(ext)"
            destIdentifier = (destPath as NSString).appendingPathComponent(itemName)
        }
    } catch let error as MunkiError {
        throw MunkiError("Unable to get list of current pkgs: \(error.description)")
    } catch {
        throw MunkiError("Unexpected error: \(error)")
    }
    do {
        try await repo.put(destIdentifier, fromFile: itempath)
        return destIdentifier
    } catch let error as MunkiError {
        throw MunkiError("Unable to copy \(itempath) to pkgs/\(destIdentifier): \(error.description)")
    } catch {
        throw MunkiError("Unexpected error when copying \(itempath) to pkgs/\(destIdentifier): \(error)")
    }
}

/// Saves pkginfo to <munki_repo>/pkgsinfo/subdirectory
/// Can throw PlistError.writeError, RepoError, or RepoCopyError
func copyPkgInfoToRepo(_ repo: Repo, pkginfo: PlistDict, subdirectory: String = "") async throws -> String {
    let pkginfoData = try plistToData(pkginfo)
    let destinationPath = ("pkgsinfo" as NSString).appendingPathComponent(subdirectory)
    var pkginfoExt = adminPref("pkginfo_extension") as? String ?? ""
    if !pkginfoExt.isEmpty, !pkginfoExt.hasPrefix(".") {
        pkginfoExt = "." + pkginfoExt
    }
    var arch = getSingleArch(pkginfo)
    if !arch.isEmpty {
        arch = "-" + arch
    }
    guard let name = pkginfo["name"] as? String else {
        throw MunkiError("pkginfo is missing value for 'name'")
    }
    guard let version = pkginfo["version"] as? String else {
        throw MunkiError("pkginfo is missing value for 'version'")
    }
    var pkginfoName = "\(name)-\(version)\(arch)\(pkginfoExt)"
    var pkginfoIdentifier = (destinationPath as NSString).appendingPathComponent(pkginfoName)
    do {
        let pkgsinfoList = try await listItemsOfKind(repo, "pkgsinfo")
        var index = 0
        while pkgsinfoList.contains(pkginfoIdentifier) {
            // try appending numbers until we have a unique name
            index += 1
            pkginfoName = "\(name)-\(version)\(arch)__\(index)\(pkginfoExt)"
            pkginfoIdentifier = (destinationPath as NSString).appendingPathComponent(pkginfoName)
        }
    } catch let error as MunkiError {
        throw MunkiError("Unable to get list of current pkgsinfo: \(error.description)")
    } catch {
        throw MunkiError("Unexpected error: \(error)")
    }
    do {
        try await repo.put(pkginfoIdentifier, content: pkginfoData)
        return pkginfoIdentifier
    }
}

enum CatalogError: Error {
    case dbError(description: String)
    case readError(description: String)
    case decodeError(description: String)
}

typealias IndexDict = [String: [Int]]

struct CatalogDatabase {
    var hashes: IndexDict
    var receipts: [String: IndexDict]
    var applications: [String: IndexDict]
    var installerItems: [String: IndexDict]
    var items: [PlistDict]
}

/// Builds a dictionary we use like a database to look up info
func makeCatalogDB(_ repo: Repo) async throws -> CatalogDatabase {
    let allCatalog: Data
    let catalogItems: [PlistDict]
    do {
        allCatalog = try await repo.get("catalogs/all")
    } catch let error as MunkiError {
        throw CatalogError.readError(
            description: "Could not read 'all' catalog: \(error.description)")
    } catch {
        throw CatalogError.readError(
            description: "Unexpected error while attempting to read 'all' catalog: \(error)")
    }

    do {
        catalogItems = try readPlist(fromData: allCatalog) as? [PlistDict] ?? [PlistDict]()
    } catch let PlistError.readError(description) {
        throw CatalogError.decodeError(
            description: "Could not decode data from catalogs/all: \(description)")
    } catch {
        throw CatalogError.decodeError(
            description: "Unexpected error when decoding data from catalogs/all: \(error)")
    }

    var pkgidTable = [String: IndexDict]()
    var appTable = [String: IndexDict]()
    var installerItemTable = [String: IndexDict]()
    var hashTable = IndexDict()

    var itemindex = -1
    for item in catalogItems {
        itemindex += 1
        guard item["name"] is String else {
            printStderr("WARNING: pkginfo item missing 'name': \(item)")
            continue
        }
        guard let version = item["version"] as? String else {
            printStderr("WARNING: pkginfo item missing 'version': \(item)")
            continue
        }
        // add to hash table
        if let installerItemHash = item["installer_item_hash"] as? String {
            if !hashTable.keys.contains(installerItemHash) {
                hashTable[installerItemHash] = [itemindex]
            } else {
                hashTable[installerItemHash]?.append(itemindex)
            }
        }
        // add to installerItem table
        if let installerItemLocation = item["installer_item_location"] as? String {
            var installerItemName = (installerItemLocation as NSString).lastPathComponent
            var name = (installerItemName as NSString).deletingPathExtension
            var version = ""
            var ext = (installerItemName as NSString).pathExtension
            if !ext.isEmpty {
                ext = "." + ext
            }
            if name.contains("-") {
                (name, version) = nameAndVersion(name)
            }
            installerItemName = name + ext
            if !installerItemTable.keys.contains(installerItemName) {
                installerItemTable[installerItemName] = IndexDict()
            }
            if !(installerItemTable[installerItemName]!.keys.contains(version)) {
                installerItemTable[installerItemName]![version] = [itemindex]
            } else {
                installerItemTable[installerItemName]?[version]?.append(itemindex)
            }
        }
        // add to table of receipts
        if let receipts = item["receipts"] as? [PlistDict] {
            for receipt in receipts {
                if let pkgid = receipt["packageid"] as? String,
                   let version = receipt["version"] as? String
                {
                    if !pkgidTable.keys.contains(pkgid) {
                        pkgidTable[pkgid] = IndexDict()
                    }
                    if !pkgidTable[pkgid]!.keys.contains(version) {
                        pkgidTable[pkgid]![version] = [itemindex]
                    } else {
                        pkgidTable[pkgid]?[version]?.append(itemindex)
                    }
                }
            }
        }
        // add to table of installed applications
        if let installs = item["installs"] as? [PlistDict] {
            for install in installs {
                if install["type"] as? String == "application" {
                    // should we also be pulling version from the installs item?
                    if let path = install["path"] as? String {
                        if !appTable.keys.contains(path) {
                            appTable[path] = IndexDict()
                        }
                        if !appTable[path]!.keys.contains(version) {
                            appTable[path]![version] = [itemindex]
                        } else {
                            appTable[path]?[version]?.append(itemindex)
                        }
                    }
                }
            }
        }
    }

    let catalogDB = CatalogDatabase(
        hashes: hashTable,
        receipts: pkgidTable,
        applications: appTable,
        installerItems: installerItemTable,
        items: catalogItems
    )

    return catalogDB
}

/// Looks through repo catalogs looking for matching pkginfo
/// Returns a pkginfo dictionary, or nil
func findMatchingPkginfo(_ repo: Repo, _ pkginfo: PlistDict) async -> PlistDict? {
    var catalogDB: CatalogDatabase

    do {
        catalogDB = try await makeCatalogDB(repo)
    } catch let CatalogError.readError(description) {
        // couldn't get the all catalog and build a db; maybe we don't have one
        // yet because this is a new repo
        if await (try? repo.list("pkgs")) != nil {
            // definitely have pkgsinfo item
            printStderr("Could not read existing catalogs: \(description)")
        }
        return nil
    } catch {
        printStderr("Could not read existing catalogs: \(error)")
        return nil
    }
    // do we have an installer item with the matching hash already in the repo?
    if let installerItemHash = pkginfo["installer_item_hash"] as? String,
       let matchingIndexes = catalogDB.hashes[installerItemHash]
    {
        return catalogDB.items[matchingIndexes[0]]
    }
    // do we have an item with matching receipts?
    if let receipts = pkginfo["receipts"] as? [PlistDict] {
        let pkgids = receipts.filter { $0.keys.contains("packageid") }.map { $0["packageid"] as? String ?? "" }
        if !pkgids.isEmpty {
            if let possibleMatches = catalogDB.receipts[pkgids[0]] {
                var versions = possibleMatches.keys.map { MunkiVersion($0) }
                // sort the versions descending
                versions.sort { $0 > $1 }
                for version in versions {
                    guard let testPkgIndexes = possibleMatches[version.value] else { continue }
                    for index in testPkgIndexes {
                        let testPkgInfo = catalogDB.items[index]
                        if let testReceipts = testPkgInfo["receipts"] as? [PlistDict] {
                            let testPkgIds = testReceipts.filter
                                { $0.keys.contains("packageid") }.map
                                { $0["packageid"] as? String ?? "" }
                            if Set(testPkgIds) == Set(pkgids) {
                                return testPkgInfo
                            }
                        }
                    }
                }
            }
        }
    }
    // do we have matching installed applications?
    if let installs = pkginfo["installs"] as? [PlistDict] {
        let appList = installs.filter {
            $0["type"] as? String == "application" &&
                !($0["path"] as? String ?? "").isEmpty
        }
        if !appList.isEmpty,
           let app = appList[0]["path"] as? String,
           let possibleMatches = catalogDB.applications[app]
        {
            var versions = possibleMatches.keys.map { MunkiVersion($0) }
            // sort the versions descending
            versions.sort { $0 > $1 }
            let highestVersion = versions[0].value
            if let indexes = possibleMatches[highestVersion] {
                return catalogDB.items[indexes[0]]
            }
        }
    }
    // no matches by hash, receipts or installed applications
    // let's try to match based on installer_item_name
    if let installerItemLocation = pkginfo["installer_item_location"] as? String {
        let installerItemName = (installerItemLocation as NSString).lastPathComponent
        if let possibleMatches = catalogDB.installerItems[installerItemName] {
            var versions = possibleMatches.keys.map { MunkiVersion($0) }
            // sort the versions descending
            versions.sort { $0 > $1 }
            let highestVersion = versions[0].value
            if let indexes = possibleMatches[highestVersion] {
                return catalogDB.items[indexes[0]]
            }
        }
    }
    // if we get here, we found no matches
    return nil
}

/// Return repo identifier for icon
func getIconIdentifier(_ pkginfo: PlistDict) -> String {
    var iconName = pkginfo["icon_name"] as? String ?? pkginfo["name"] as? String ?? ""
    if (iconName as NSString).pathExtension.isEmpty {
        iconName += ".png"
    }
    return ("icons" as NSString).appendingPathComponent(iconName)
}

/// Returns true if there is an icon for this item in the repo
func iconIsInRepo(_ repo: Repo, pkginfo: PlistDict) async -> Bool {
    let iconIdentifier = getIconIdentifier(pkginfo)
    do {
        let iconList = try await listItemsOfKind(repo, "icons")
        return iconList.contains(iconIdentifier)
    } catch let error as MunkiError {
        printStderr("Unable to get list of icons: \(error.description)")
        return false
    } catch {
        printStderr("Unable to get list of icons: \(error)")
        return false
    }
}

/// Convert icon file to png and save to repo icon path.
/// Returns resource path to icon in repo
func convertAndInstallIcon(_ repo: Repo, name: String, iconPath: String) async throws -> String {
    guard let tmpDir = TempDir.shared.makeTempDir() else {
        throw MunkiError("Could not create a temp directory")
    }
    defer {
        try? FileManager.default.removeItem(atPath: tmpDir)
    }
    let pngName = "\(name).png"
    let iconIdentifier = "icons/" + pngName
    let localPNGpath = (tmpDir as NSString).appendingPathComponent(pngName)
    if convertIconToPNG(iconPath: iconPath, destinationPath: localPNGpath) {
        do {
            try await repo.put(iconIdentifier, fromFile: localPNGpath)
            return iconIdentifier
        } catch let error as MunkiError {
            throw MunkiError("Could not create icon \(pngName) in repo: \(error.description)")
        } catch {
            throw MunkiError("Could not create icon \(pngName) in repo: \(error)")
        }
    }
    throw MunkiError("Could not create icon \(pngName) in repo: failed to convert icon to png")
}

/// Generates a product icon from a startosinstall item
/// and uploads to the repo. Returns repo identifier for icon
func generatePNGFromStartOSInstallItem(_ repo: Repo, installerDMG: String, itemname: String) async throws -> String {
    do {
        let mountpoint = try mountdmg(installerDMG)
        defer {
            do {
                try unmountdmg(mountpoint)
            } catch {
                printStderr(error.localizedDescription)
            }
        }
        if let appPath = findInstallMacOSApp(mountpoint),
           let iconPath = findIconForApp(appPath)
        {
            let repoIconIdentifier = try await convertAndInstallIcon(
                repo, name: itemname, iconPath: iconPath
            )
            return repoIconIdentifier
        }
        throw MunkiError("Unexpected error generating PNG from installer dmg")
    } catch let error as MunkiError {
        throw MunkiError("Could not mount installer dmg: \(error.description)")
    } catch {
        throw MunkiError("Unexpected error generating PNG from app on disk image: \(error)")
    }
}

/// Generates a product icon from a copy_from_dmg item
/// and uploads to the repo. Returns repo path to icon
func generatePNGFromDMGitem(_ repo: Repo, dmgPath: String, pkginfo: PlistDict) async throws -> String {
    guard let itemname = pkginfo["name"] as? String else {
        throw MunkiError("pkginfo is missing 'name'")
    }
    do {
        let mountpoint = try mountdmg(dmgPath)
        defer {
            do {
                try unmountdmg(mountpoint)
            } catch {
                printStderr(error.localizedDescription)
            }
        }
        if let itemsToCopy = pkginfo["items_to_copy"] as? [PlistDict] {
            let apps = itemsToCopy.filter {
                ($0["source_item"] as? String ?? "").hasSuffix(".app")
            }.map {
                $0["source_item"] as? String ?? ""
            }
            if !apps.isEmpty {
                let appPath = (mountpoint as NSString).appendingPathComponent(apps[0])
                if let iconPath = findIconForApp(appPath) {
                    let repoIconIdentifier = try await convertAndInstallIcon(
                        repo, name: itemname, iconPath: iconPath
                    )
                    return repoIconIdentifier
                }
            }
        }
        // it's not an error if nothing we copy is an app
        return ""
    } catch let error as MunkiError {
        throw MunkiError("Could not mount installer dmg: \(error.description)")
    } catch {
        throw MunkiError("Unexpected error generating PNG from app on disk image: \(error)")
    }
}

/// Generates a product icon (or candidate icons) from an installer pkg
/// and uploads to the repo. Returns repo path(s) to icon(s)
/// itemPath can be a path to a disk image or to a package
func generatePNGsFromPkg(_ repo: Repo, itemPath: String, pkginfo: PlistDict, importMultiple: Bool = true) async throws -> [String] {
    guard let itemname = pkginfo["name"] as? String else {
        // this should essentially never happen
        throw MunkiError("Pkginfo is missing 'name': \(pkginfo)")
    }
    var iconPaths = [String]()
    var importedPaths = [String]()
    var pkgPath = ""
    var mountpoint = ""
    defer {
        if !mountpoint.isEmpty {
            do {
                try unmountdmg(mountpoint)
            } catch {
                printStderr(error.localizedDescription)
            }
        }
    }
    if hasValidDiskImageExt(itemPath) {
        let dmgPath = itemPath
        mountpoint = try mountdmg(dmgPath)
        if let pkginfoPkgPath = pkginfo["package_path"] as? String {
            pkgPath = (mountpoint as NSString).appendingPathComponent(pkginfoPkgPath)
        } else {
            // look for first package at root of mounted disk image
            let filelist = try FileManager.default.contentsOfDirectory(atPath: mountpoint)
            for item in filelist {
                if hasValidPackageExt(item) {
                    pkgPath = (mountpoint as NSString).appendingPathComponent(item)
                    break
                }
            }
        }
    } else if hasValidPackageExt(itemPath) {
        pkgPath = itemPath
    }
    if !pkgPath.isEmpty {
        if pathIsDirectory(pkgPath) {
            iconPaths = extractAppIconsFromBundlePkg(pkgPath)
        } else {
            iconPaths = extractAppIconsFromFlatPkg(pkgPath)
        }
    }
    if iconPaths.count == 1 {
        let importedPath = try await convertAndInstallIcon(
            repo, name: itemname, iconPath: iconPaths[0]
        )
        if !importedPath.isEmpty {
            importedPaths = [importedPath]
        }
    } else if iconPaths.count > 1, importMultiple {
        var index = 0
        for icon in iconPaths {
            index += 1
            let iconname = itemname + "_\(index)"
            let importedPath = try await convertAndInstallIcon(
                repo, name: iconname, iconPath: icon
            )
            if !importedPath.isEmpty {
                importedPaths.append(importedPath)
            }
        }
    }
    return importedPaths
}

/// Saves a product icon to the repo. Returns repo path.
func copyIconToRepo(_ repo: Repo, iconPath: String) async throws -> String {
    let destPath = "icons"
    let iconName = (iconPath as NSString).lastPathComponent
    let repoIdentifier = (destPath as NSString).appendingPathComponent(iconName)
    do {
        let iconList = try await listItemsOfKind(repo, "icon")
        if iconList.contains(repoIdentifier) {
            // need to first remove existing icon
            do {
                try await repo.delete(repoIdentifier)
            } catch let error as MunkiError {
                throw MunkiError("Could not delete existing icon in repo: \(error.description)")
            } catch {
                throw MunkiError("Could not delete existing icon in repo: \(error)")
            }
        }
    } catch let error as MunkiError {
        throw MunkiError("Could not get list of icons on repo: \(error.description)")
    } catch {
        throw MunkiError("Could not get list of icons on repo: \(error)")
    }
    print("Copying \(iconName) to \(repoIdentifier)...")
    do {
        try await repo.put(repoIdentifier, fromFile: iconPath)
        return repoIdentifier
    } catch let error as MunkiError {
        throw MunkiError("Could not copy icon to repo: \(error.description)")
    } catch {
        throw MunkiError("Could not copy icon to repo: \(error)")
    }
}

/// Extracts an icon (or icons) from an installer item, converts to png, and
/// copies to repo. Returns repo path to imported icon(s)
func extractAndCopyIcon(_ repo: Repo, installerItem: String, pkginfo: PlistDict, importMultiple: Bool = true) async throws -> [String] {
    let installerType = pkginfo["installer_type"] as? String ?? ""
    switch installerType {
    case "copy_from_dmg", "stage_os_installer":
        let importedPath = try await generatePNGFromDMGitem(repo, dmgPath: installerItem, pkginfo: pkginfo)
        if !importedPath.isEmpty {
            return [importedPath]
        }
    case "startosinstall":
        let itemname = pkginfo["name"] as? String ?? "UNKNOWN"
        let importedPath = try await generatePNGFromStartOSInstallItem(repo, installerDMG: installerItem, itemname: itemname)
        if !importedPath.isEmpty {
            return [importedPath]
        }
    case "":
        let importedPaths = try await generatePNGsFromPkg(repo, itemPath: installerItem, pkginfo: pkginfo, importMultiple: importMultiple)
        return importedPaths
    default:
        throw MunkiError("Can't generate icons for installer_type \(installerType)")
    }
    return [String]()
}

/// A subclass of ProcessRunner to create disk images
class HdiUtilCreateFromFolderRunner: ProcessRunner {
    init(sourceDir: String, outputPath: String) {
        let tool = "/usr/bin/hdiutil"
        let arguments = ["create", "-fs", "HFS+", "-srcfolder", sourceDir, outputPath]
        super.init(tool, arguments: arguments)
    }

    override func processError(_ str: String) {
        super.processError(str)
        printStderr(str, terminator: "")
        fflush(stderr)
    }

    override func processOutput(_ str: String) {
        super.processOutput(str)
        print(str, terminator: "")
        fflush(stderr)
    }
}

/// Wraps dirPath (generally an app bundle or bundle-style pkg into a disk image.
/// Returns path to the created dmg file
/// It can take a while, depending on the size of the item
func makeDmg(_ dirPath: String) -> String {
    let itemname = (dirPath as NSString).lastPathComponent
    print("Making disk image containing \(itemname)...")
    let dmgName = (itemname as NSString).deletingPathExtension + ".dmg"
    guard let tmpDir = TempDir.shared.makeTempDir() else {
        printStderr("Disk image creation failed: Can't get a temporary directory")
        return ""
    }
    let dmgPath = (tmpDir as NSString).appendingPathComponent(dmgName)
    let dmgCreator = HdiUtilCreateFromFolderRunner(sourceDir: dirPath, outputPath: dmgPath)
    dmgCreator.run()
    if dmgCreator.results.exitcode != 0 {
        printStderr("Disk image creation failed.")
        return ""
    }
    print("Disk image created at: \(dmgPath)")
    return dmgPath
}

/// Prompts the user for a subdirectory for the pkg and pkginfo
func promptForSubdirectory(_ repo: Repo, _ subdirectory: String?) async -> String {
    var existingSubdirs: Set<String> = []
    let pkgsinfoList = await (try? repo.list("pkgsinfo")) ?? [String]()
    for item in pkgsinfoList {
        existingSubdirs.insert((item as NSString).deletingLastPathComponent)
    }

    while true {
        if let selectedDir = getInput(prompt: "Upload item to subdirectory: ", defaultText: subdirectory) {
            if existingSubdirs.contains(selectedDir) {
                return selectedDir
            } else {
                print("pkgsinfo/\(selectedDir) does not exist or is empty. Use this directory? [y/N] ", terminator: "")
                if let answer = readLine(),
                   answer.lowercased().hasPrefix("y")
                {
                    return selectedDir
                }
            }
        }
    }
}

/// Opens pkginfo list in the user's chosen editor.
func editPkgInfoInExternalEditor(_ pkginfo: PlistDict) -> PlistDict {
    guard let editor = adminPref("editor") as? String, !editor.isEmpty else {
        return pkginfo
    }
    print("Edit pkginfo before upload? [y/N]: ", terminator: "")
    if let answer = readLine(),
       answer.lowercased().hasPrefix("y")
    {
        guard let tempDir = TempDir.shared.makeTempDir() else {
            printStderr("Could not get a temporary working directory")
            return pkginfo
        }
        defer {
            try? FileManager.default.removeItem(atPath: tempDir)
        }
        let name = pkginfo["name"] as? String ?? "pkginfo"
        let version = pkginfo["version"] as? String ?? ""
        let ext = adminPref("pkginfo_extension") as? String ?? ""
        let filename = "\(name)-\(version)\(ext)"
        let filePath = (tempDir as NSString).appendingPathComponent(filename)
        do {
            try writePlist(pkginfo, toFile: filePath)
        } catch let PlistError.writeError(description) {
            printStderr("Could not write pkginfo to temp file: \(filePath): \(description)")
            return pkginfo
        } catch {
            printStderr("Could not write pkginfo to temp file: \(error)")
            return pkginfo
        }
        var cmd = ""
        var args = [String]()
        if editor.hasSuffix(".app") {
            cmd = "/usr/bin/open"
            args = ["-a", editor, filePath]
            let result = runCLI(cmd, arguments: args)
            if result.exitcode != 0 {
                printStderr("Problem running editor \(editor): \(result.error)")
                return pkginfo
            }
            // wait for editor to exit
            var response: String? = "no"
            while let answer = response,
                  !answer.lowercased().hasPrefix("y")
            {
                print("Pkginfo editing complete? [y/N]: ", terminator: "")
                response = readLine()
            }
        } else {
            do {
                try posixSpawn(editor, filePath)
            } catch {
                printStderr(error.localizedDescription)
                return pkginfo
            }
        }
        // read edited pkginfo
        do {
            if let editedPkginfo = try readPlist(fromFile: filePath) as? PlistDict {
                return editedPkginfo
            } else {
                throw PlistError.readError(description: "Plist has bad format")
            }
        } catch let PlistError.readError(description) {
            printStderr("Problem reading edited pkginfo: \(description)")
            return pkginfo
        } catch {
            printStderr("Problem reading edited pkginfo: \(error)")
            return pkginfo
        }
    }
    return pkginfo
}
