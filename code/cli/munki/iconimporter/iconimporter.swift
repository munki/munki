//
//  iconimporter.swift
//  iconimporter
//
//  Created by Greg Neagle on 9/13/24.
//  Copyright 2024-2026 The Munki Project.
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

import ArgumentParser
import Foundation

// MARK: icon generation and copying

/// Copies png file in path to repo as icons/iconname.png
func copyIconToRepo(_ repo: Repo, iconname: String, path: String) async {
    let iconRef = "icons/\(iconname).png"
    do {
        try await repo.put(iconRef, fromFile: path)
        print("\tWrote: \(iconRef)")
    } catch {
        printStderr("\tError uploading \(iconRef): \(error.localizedDescription)")
    }
}

/// Returns filesystem path to installer item, downloading if needed
func getInstallerItemPath(repo: Repo, pkginfo: PlistDict) async -> String? {
    let itemName = pkginfo["name"] as? String ?? "UNKNOWN"
    guard let installerItem = pkginfo["installer_item_location"] as? String else {
        printStderr("Could not get installer item location for \(itemName).")
        return nil
    }
    let installerItemRef = "pkgs/\(installerItem)"
    // first attempt to ask the repo plugin for the filesystem path to the item
    if let tempPath = repo.pathFor(installerItemRef) {
        return tempPath
    } else {
        // need to download the item from the repo because
        // we don't have direct filesystem access to it
        guard let tempFile = tempFile() else {
            printStderr("Could not get temp file to download \(installerItem).")
            return nil
        }
        do {
            try await repo.get(installerItemRef, toFile: tempFile)
            return tempFile
        } catch {
            printStderr("Could not download \(installerItem) from repo: \(error.localizedDescription)")
            return nil
        }
    }
}

/// Generate a PNG from a disk image containing an Install macOS app
func generatePNGFromStartOSInstallItem(_ repo: Repo, item: PlistDict) async {
    let itemName = item["name"] as? String ?? "UNKNOWN"
    guard let dmgPath = await getInstallerItemPath(repo: repo, pkginfo: item) else {
        printStderr("Skipping.")
        return
    }
    guard let mountpoint = try? mountdmg(dmgPath) else {
        printStderr("Could not mount the disk image for \(itemName). Skipping.")
        return
    }
    defer {
        do {
            try unmountdmg(mountpoint)
        } catch {
            printStderr(error.localizedDescription)
        }
    }
    guard let appPath = findInstallMacOSApp(mountpoint) else {
        printStderr("Could not find Install macOS app for \(itemName). Skipping.")
        return
    }
    guard let iconPath = findIconForApp(appPath) else {
        print("\tNo application icons found.")
        return
    }
    if let iconTemp = tempFile(),
       convertIconToPNG(iconPath: iconPath, destinationPath: iconTemp)
    {
        await copyIconToRepo(repo, iconname: itemName, path: iconTemp)
    } else {
        printStderr("\tError converting \(iconPath) to png.")
    }
}

/// Generate a PNG from a disk image containing an application
// TODO: handle case where there are multiple apps in items_to_copy
// (Python version just picks the first one, so that would be an enhancement)
func generatePNGFromDMGItem(_ repo: Repo, item: PlistDict) async {
    let itemName = item["name"] as? String ?? "UNKNOWN"
    guard let dmgPath = await getInstallerItemPath(repo: repo, pkginfo: item) else {
        printStderr("Skipping.")
        return
    }
    guard let mountpoint = try? mountdmg(dmgPath) else {
        printStderr("Could not mount the disk image for \(itemName). Skipping.")
        return
    }
    defer {
        do {
            try unmountdmg(mountpoint)
        } catch {
            printStderr(error.localizedDescription)
        }
    }
    let itemsToCopy = item["items_to_copy"] as? [PlistDict] ?? []
    let apps = itemsToCopy.filter {
        ($0["source_item"] as? String ?? "").hasSuffix(".app")
    }
    if apps.isEmpty {
        print("\tNo application icons found.")
        return
    }
    if let appPath = apps[0]["source_item"] as? String,
       let iconPath = findIconForApp((mountpoint as NSString).appendingPathComponent(appPath))
    {
        if let iconTemp = tempFile(),
           convertIconToPNG(iconPath: iconPath, destinationPath: iconTemp)
        {
            await copyIconToRepo(repo, iconname: itemName, path: iconTemp)
        } else {
            print("\tError converting \(iconPath) to png.")
        }
    } else {
        print("\tNo application icons found.")
    }
}

/// Generate PNGS from applications inside a pkg
func generatePNGsFromPkg(_ repo: Repo, item: PlistDict) async {
    let itemName = item["name"] as? String ?? "UNKNOWN"
    guard let installerItemPath = await getInstallerItemPath(repo: repo, pkginfo: item) else {
        printStderr("Skipping.")
        return
    }
    var pkgPath = ""
    var savedMountPoint: String?
    if hasValidDiskImageExt(installerItemPath) {
        guard let mountpoint = try? mountdmg(installerItemPath) else {
            printStderr("Could not mount the disk image for \(itemName). Skipping.")
            return
        }
        savedMountPoint = mountpoint
        if let packagePath = item["package_path"] as? String {
            pkgPath = (mountpoint as NSString).appendingPathComponent(packagePath)
        } else {
            // find first item that appears to be a pkg at the root
            if let itemList = try? FileManager.default.contentsOfDirectory(atPath: mountpoint) {
                for item in itemList {
                    if hasValidPackageExt(item) {
                        pkgPath = (mountpoint as NSString).appendingPathComponent(item)
                        break
                    }
                }
            }
        }
    } else if hasValidPackageExt(installerItemPath) {
        pkgPath = installerItemPath
    }
    var iconPaths = [String]()
    if !pkgPath.isEmpty {
        if pathIsDirectory(pkgPath) {
            iconPaths = extractAppIconsFromBundlePkg(pkgPath)
        } else {
            iconPaths = extractAppIconsFromFlatPkg(pkgPath)
        }
    }
    if let savedMountPoint {
        do {
            try unmountdmg(savedMountPoint)
        } catch {
            printStderr(error.localizedDescription)
        }
    }
    if iconPaths.count == 1 {
        if let iconTemp = tempFile(),
           convertIconToPNG(iconPath: iconPaths[0], destinationPath: iconTemp)
        {
            await copyIconToRepo(repo, iconname: itemName, path: iconTemp)
        } else {
            printStderr("\tError converting \(iconPaths[0]) to png.")
        }
    } else if iconPaths.count > 1 {
        for (index, iconPath) in iconPaths.enumerated() {
            let iconName = itemName + "_\(index + 1)"
            if let iconTemp = tempFile(),
               convertIconToPNG(iconPath: iconPath, destinationPath: iconTemp)
            {
                await copyIconToRepo(repo, iconname: iconName, path: iconTemp)
            } else {
                printStderr("\tError converting \(iconPath) to png.")
            }
        }
    } else {
        print("\tNo application icons found.")
    }
}

/// Builds a list of items to check; only the latest version of an item is retained.
/// If itemlist is given, include items only on that list.
func findItemsToCheck(_ repo: Repo, items: [String] = []) async -> [PlistDict] {
    var catalogItems = [PlistDict]()
    do {
        let allCatalogData = try await repo.get("catalogs/all")
        catalogItems = try (readPlist(fromData: allCatalogData)) as? [PlistDict] ?? []
    } catch {
        printStderr("Error getting catalog data from repo: \(error.localizedDescription)")
        return []
    }
    var itemDB = [String: PlistDict]()
    for catalogItem in catalogItems {
        let itemName = catalogItem["name"] as? String ?? "UNKNOWN"
        let itemVersion = catalogItem["version"] as? String ?? "UNKNOWN"
        if !items.isEmpty, !items.contains(itemName) {
            continue
        }
        if !itemDB.keys.contains(itemName) {
            itemDB[itemName] = catalogItem
        } else {
            let dbVersion = itemDB[itemName]?["version"] as? String ?? ""
            if MunkiVersion(itemVersion) > MunkiVersion(dbVersion) {
                itemDB[itemName] = catalogItem
            }
        }
    }
    return Array(itemDB.values)
}

/// Generate PNGs from either pkgs or disk images containing applications
func generatePNGsFromMunkiItems(_ repo: Repo, force: Bool = false, items: [String] = []) async {
    let iconsList = await (try? repo.list("icons")) ?? []
    let itemList = await findItemsToCheck(repo, items: items)
    for item in itemList {
        let itemName = item["name"] as? String ?? "UNKNOWN"
        var iconName = item["icon_name"] as? String ?? itemName
        print("Processing \(itemName)...")
        let iconNameExt = (iconName as NSString).pathExtension
        if iconNameExt.isEmpty {
            iconName += ".png"
        }
        if iconsList.contains(iconName), !force {
            print("Found existing icon at \(iconName)")
            continue
        }
        let installerType = item["installer_type"] as? String ?? ""
        if installerType == "copy_from_dmg" {
            await generatePNGFromDMGItem(repo, item: item)
        } else if installerType == "startosinstall" {
            await generatePNGFromStartOSInstallItem(repo, item: item)
        } else if installerType == "" {
            await generatePNGsFromPkg(repo, item: item)
        } else {
            print("\tCan't process installer type: \(installerType)")
        }
    }
    // clean up any temp files we may have generated during this run
    TempDir.shared.cleanUp()
}

// MARK: options and main run command

@main
struct IconImporter: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "iconimporter",
        abstract: "Imports icons into a Munki repo"
    )

    @Flag(name: .shortAndLong,
          help: "Create pngs even if there is an existing icon in the repo.")
    var force = false

    @Option(name: .shortAndLong,
            help: "Only run for given pkginfo item name(s).")
    var item: [String] = []

    @Option(name: .long,
            help: "Optional. Custom plugin to connect to repo.")
    var plugin = "FileRepo"

    @Option(name: [.customLong("repo_url"), .customLong("repo-url")],
            help: "Optional. repo fileshare URL used by repo plugin.")
    var repoURL = ""

    @Argument(help: ArgumentHelp(
        "Optional path to Munki repo directory.",
        valueName: "munki-repo-path"
    ))
    var repoPath = ""

    mutating func validate() throws {
        if repoURL.isEmpty, repoPath.isEmpty {
            if let prefsRepoURL = adminPref("repo_url") as? String {
                repoURL = prefsRepoURL
            } else {
                throw ValidationError("Must specify a repo URL or repo path!")
            }
        }
        if repoURL.isEmpty {
            // repoPath must be defined
            while repoPath.hasSuffix("/") {
                repoPath = String(repoPath.dropLast())
            }
            if let url = URL(string: repoPath),
               url.scheme != nil
            {
                repoURL = url.absoluteString
            } else {
                repoURL = URL(fileURLWithPath: repoPath).absoluteString
            }
        }
    }

    mutating func run() async throws {
        do {
            let repo = try repoConnect(url: repoURL, plugin: plugin)
            await generatePNGsFromMunkiItems(repo, force: force, items: item)
        } catch {
            printStderr("Could not connect to the munki repo: \(error.localizedDescription)")
            throw ExitCode(-1)
        }
    }
}
