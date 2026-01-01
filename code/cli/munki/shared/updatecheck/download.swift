//
//  download.swift
//  munki
//
//  Created by Greg Neagle on 8/15/24.
//  Copyright 2024-2026 The Munki Project. All rights reserved.
//

import Foundation

private let display = DisplayAndLog.main

/// For a URL, return the path that the download should cache to.
func getDownloadCachePath(_ urlString: String) -> String {
    return managedInstallsDir(subpath: "Cache/" + baseName(urlString))
}

/// Determine if there is enough disk space to download and install the installer item.
func enoughDiskSpaceFor(
    _ item: PlistDict,
    installList: [PlistDict] = [],
    uninstalling: Bool = false,
    warn: Bool = true,
    precaching: Bool = false
) -> Bool {
    // fudgefactor is 100MB
    let fudgefactor = 102_400 // KBytes
    var alreadyDownloadedSize = 0
    if let installerItemLocation = item["installer_item_location"] as? String {
        let downloadedPath = getDownloadCachePath(installerItemLocation)
        if pathExists(downloadedPath) {
            alreadyDownloadedSize = getSize(downloadedPath) / 1024 // KBytes
        }
    }
    display.debug2("\tAlready downloaded size: \(alreadyDownloadedSize)KB")
    var installerItemSize = item["installer_item_size"] as? Int ?? 0 // KBytes
    var installedSize = item["installed_size"] as? Int ?? installerItemSize // KBytes
    if uninstalling {
        installedSize = 0
        installerItemSize = 0
        if let uninstallerItemSize = item["uninstaller_item_size"] as? Int {
            installerItemSize = uninstallerItemSize // KBytes
        }
    }
    display.debug2("\tInstaller item size: \(installerItemSize)KB")
    display.debug2("\tInstalled size: \(installedSize)KB")
    let diskSpaceNeeded = installerItemSize - alreadyDownloadedSize + installedSize + fudgefactor
    display.debug2("\tDisk space needed: \(diskSpaceNeeded)KB")

    var diskSpace = availableDiskSpace() // KBytes
    display.debug2("\tAvailable disk space: \(diskSpace)KB")
    var additionalItemSpace = 0
    for additionalItem in installList {
        // subtract space needed for other items that are to be installed
        if additionalItem["installer_item"] != nil,
           let installedSize = additionalItem["installed_size"] as? Int
        {
            additionalItemSpace += installedSize
            if let name = additionalItem["name"] as? String {
                display.debug2("\tSubtracting \(installedSize)KB needed for \(name)...")
            }
        }
    }
    diskSpace -= additionalItemSpace
    display.debug2("\tAvailable disk space after subtracting additional items: \(diskSpace)KB")

    if diskSpaceNeeded > diskSpace, !precaching {
        // try to clear space by deleting some precached items
        display.debug2("\tAttempting to free up space by clearing precached items...")
        uncache(diskSpaceNeeded - diskSpace)
        // now re-calc
        diskSpace = availableDiskSpace() - additionalItemSpace
        display.debug2("\tAvailable disk space after clearing precached items: \(diskSpace)KB")
    }

    if diskSpace >= diskSpaceNeeded {
        return true
    }

    // we don't have enough space
    if warn {
        let itemName = item["name"] as? String ?? "<unknown>"
        if uninstalling {
            display.warning("There is insufficient disk space to download the uninstaller for \(itemName)")
        } else {
            display.warning("There is insufficient disk space to download and install \(itemName)")
        }
        display.warning("\(Int(diskSpaceNeeded / 1024))MB needed, \(Int(diskSpace / 1024))MB available")
    }
    return false
}

/// Downloads an (un)installer item.
/// Returns true if the item was downloaded, false if it was already cached.
/// Throws an error if there are issues
func downloadInstallerItem(
    _ item: PlistDict,
    installInfo: PlistDict,
    uninstalling: Bool = false,
    precaching: Bool = false
) throws -> Bool {
    let downloadItemKey = if uninstalling, item.keys.contains("uninstaller_item_location") {
        "uninstaller_item_location"
    } else {
        "installer_item_location"
    }
    let itemHashKey = if uninstalling, item.keys.contains("uninstaller_item_location") {
        "uninstaller_item_hash"
    } else {
        "installer_item_hash"
    }
    guard let location = item[downloadItemKey] as? String else {
        throw FetchError.download(
            errorCode: -1,
            description: "No \(downloadItemKey) in pkginfo"
        )
    }

    // pkginfos support two keys that can essentially override the
    // normal URL generation for Munki repo items. But they are not
    // commonly used.
    let alternatePkgURL: String = if let packageCompleteURL = item["PackageCompleteURL"] as? String {
        packageCompleteURL
    } else if let packageURL = item["PackageURL"] as? String {
        composedURLWithBase(packageURL, adding: location)
    } else {
        ""
    }

    let pkgName = baseName(location)
    display.debug2("Package name is: \(pkgName)")
    if !alternatePkgURL.isEmpty {
        display.debug2("Download URL is: \(alternatePkgURL)")
    }

    let destinationPath = getDownloadCachePath(location)
    display.debug2("Downloading to: \(destinationPath)")

    if !pathExists(destinationPath) {
        // check to see if there is enough free space to download and install
        let installList = installInfo["managed_installs"] as? [PlistDict] ?? []
        if !enoughDiskSpaceFor(
            item,
            installList: installList,
            uninstalling: uninstalling,
            precaching: precaching
        ) {
            throw FetchError.download(
                errorCode: -1,
                description: "Insufficient disk space to download and install \(pkgName)"
            )
        }
    }
    display.detail("Downloading \(pkgName) from \(location)")
    let downloadMessage = "Downloading \(pkgName)..."
    let expectedHash = item[itemHashKey] as? String
    if alternatePkgURL.isEmpty {
        return try fetchMunkiResource(
            kind: .package,
            name: location,
            destinationPath: destinationPath,
            message: downloadMessage,
            resume: true,
            expectedHash: expectedHash,
            verify: true
        )
    } else {
        // use alternatePkgURL
        return try fetchMunkiResourceByURL(
            alternatePkgURL,
            destinationPath: destinationPath,
            message: downloadMessage,
            resume: true,
            expectedHash: expectedHash,
            verify: true
        )
    }
}

let ICON_HASHES_PLIST_NAME = "_icon_hashes.plist"

/// Remove any cached/downloaded icons that aren't in the list of ones to keep
func cleanUpIconsDir(keepList: [String] = []) {
    let itemsToKeep = keepList + [ICON_HASHES_PLIST_NAME]
    let iconsDir = managedInstallsDir(subpath: "icons")
    cleanUpDir(iconsDir, keeping: itemsToKeep)
}

func getIconHashes() -> [String: String] {
    /// Attempts to download the dictionary of compiled icon hashes
    let iconsHashesPlist = managedInstallsDir(subpath: "icons/\(ICON_HASHES_PLIST_NAME)")
    do {
        _ = try fetchMunkiResource(
            kind: .icon,
            name: ICON_HASHES_PLIST_NAME,
            destinationPath: iconsHashesPlist,
            message: "Getting list of available icons"
        )
        return try readPlist(fromFile: iconsHashesPlist) as? [String: String] ?? [:]
    } catch {
        display.debug1("Error while retrieving icon hashes: \(error.localizedDescription)")
        return [String: String]()
    }
}

/// Attempts to download icons (actually image files) for items in itemList
func downloadIcons(_ itemList: [PlistDict]) {
    var iconsToKeep = [String]()
    let iconsDir = managedInstallsDir(subpath: "icons")
    let iconHashes = getIconHashes()
    let supportedIconExtensions = ["bmp", "gif", "icns", "jpg", "jpeg", "png", "psd", "tga", "tif", "tiff", "yuv"]

    for item in itemList {
        var iconName = item["icon_name"] as? String ?? item["name"] as? String ?? "<unknown>"
        if !supportedIconExtensions.contains((iconName as NSString).pathExtension) {
            iconName += ".png"
        }
        iconsToKeep.append(iconName)
        let serverHash: String = if let iconHash = item["icon_hash"] as? String {
            iconHash
        } else {
            iconHashes[iconName] ?? "<noserverhash>"
        }
        let iconPath = (iconsDir as NSString).appendingPathComponent(iconName)
        var localHash = "<nolocalhash>"
        if pathIsRegularFile(iconPath) {
            // have we already downloaded it? If so get the local hash
            if let data = try? getXattr(named: XATTR_SHA, atPath: iconPath) {
                localHash = String(data: data, encoding: .utf8) ?? "<nolocalhash>"
            } else {
                // get hash and also store for future use
                localHash = storeCachedChecksum(toPath: iconPath) ?? "<nolocalhash>"
            }
        }
        let iconSubDir = (iconPath as NSString).deletingLastPathComponent
        if !pathIsDirectory(iconSubDir) {
            let success = createMissingDirs(iconSubDir)
            if !success {
                display.error("Could not create \(iconSubDir)")
                continue
            }
        }
        if serverHash != localHash {
            // hashes don't match, so download the icon
            if !iconHashes.isEmpty, !iconHashes.keys.contains(iconName) {
                // if we have a dict of icon hashes, and the icon name is not
                // in that dict, then there's no point in attempting to
                // download this icon
                continue
            }
            let itemName = item["display_name"] as? String ?? item["name"] as? String ?? "<unknown>"
            do {
                _ = try fetchMunkiResource(
                    kind: .icon,
                    name: iconName,
                    destinationPath: iconPath,
                    message: "Getting icon \(iconName) for \(itemName)..."
                )
                _ = storeCachedChecksum(toPath: iconPath)
            } catch {
                display.debug1("Error when retrieving icon \(iconName) from the server: \(error.localizedDescription)")
            }
        }
    }
    cleanUpIconsDir(keepList: iconsToKeep)
}

/// Download client customization resources (if any).

/// Munki's preferences can specify an explicit name under ClientResourcesFilename
/// if that doesn't exist, use the primary manifest name as the filename.
/// If that fails, try site_default.zip
func downloadClientResources() {
    // build a list of resource names to request from the server
    var filenames = [String]()
    if let resourcesName = pref("ClientResourcesFilename") as? String {
        if (resourcesName as NSString).pathExtension.isEmpty {
            filenames.append(resourcesName + ".zip")
        } else {
            filenames.append(resourcesName)
        }
    } else {
        // TODO: make a better way to retrieve the current manifest name
        if let manifestName = Report.shared.retrieve(key: "ManifestName") as? String {
            filenames.append(manifestName + ".zip")
        }
    }
    filenames.append("site_default.zip")

    let resourceDir = managedInstallsDir(subpath: "client_resources")
    // make sure local resource directory exists
    if !pathIsDirectory(resourceDir) {
        let success = createMissingDirs(resourceDir)
        if !success {
            display.error("Could not create \(resourceDir)")
            return
        }
    }
    let resourceArchivePath = (resourceDir as NSString).appendingPathComponent("custom.zip")
    let message = "Getting client resources..."
    var downloadedResourcePath = ""
    for filename in filenames {
        do {
            _ = try fetchMunkiResource(
                kind: .clientResource,
                name: filename,
                destinationPath: resourceArchivePath,
                message: message
            )
            downloadedResourcePath = resourceArchivePath
            break
        } catch {
            display.debug1("Could not retrieve client resources with name \(filename): \(error.localizedDescription)")
        }
    }
    if downloadedResourcePath.isEmpty {
        // make sure we don't have an old custom.zip hanging around
        if pathExists(resourceArchivePath) {
            do {
                try FileManager.default.removeItem(atPath: resourceArchivePath)
            } catch {
                display.error("Could not remove stale \(resourceArchivePath): \(error.localizedDescription)")
            }
        }
    }
}

/// Attempt to download a catalog from the Munki server. Returns the path to the downloaded catalog file.
func downloadCatalog(_ catalogName: String) -> String? {
    let catalogPath = managedInstallsDir(subpath: "catalogs/\(catalogName)")
    display.detail("Getting catalog \(catalogName)...")
    let message = "Retrieving catalog \(catalogName)..."
    do {
        _ = try fetchMunkiResource(
            kind: .catalog,
            name: catalogName,
            destinationPath: catalogPath,
            message: message
        )
        return catalogPath
    } catch {
        display.error("Could not retrieve catalog \(catalogName) from server: \(error.localizedDescription)")
    }
    return nil
}

/// Returns a list of items from InstallInfo.plist's optional_installs
/// that have precache=true and (installed=false or needs_update=true)
private func itemsToPrecache(_ installInfo: PlistDict) -> [PlistDict] {
    if let optionalInstalls = installInfo["optional_installs"] as? [PlistDict] {
        return optionalInstalls.filter {
            ($0["precache"] as? Bool ?? false) &&
                (($0["installed"] as? Bool ?? false) ||
                    ($0["needs_update"] as? Bool ?? false))
        }
    }
    return [PlistDict]()
}

/// Download any applicable precache items into our Cache folder
func precache() {
    guard let installInfo = getInstallInfo() else {
        // nothing to do
        return
    }
    display.info("###   Beginning precaching session   ###")
    for item in itemsToPrecache(installInfo) {
        do {
            _ = try downloadInstallerItem(
                item, installInfo: installInfo, precaching: true
            )
        } catch {
            let itemName = item["name"] as? String ?? "<unknown>"
            display.warning("Failed to precache the installer for \(itemName) because \(error.localizedDescription)")
        }
    }
    display.info("###   Ending precaching session   ###")
}

/// Discard precached items to free up space for managed installs
func uncache(_ spaceNeededInKB: Int) {
    guard let installInfo = getInstallInfo() else {
        return
    }
    // make a list of names of precachable items
    let precachableItems = itemsToPrecache(installInfo).filter {
        $0["installer_item_location"] != nil
    }.map {
        $0["installer_item_location"] as? String ?? ""
    }.map {
        ($0 as NSString).lastPathComponent
    }
    if precachableItems.isEmpty {
        return
    }

    let cacheDir = managedInstallsDir(subpath: "Cache")
    let itemsInCache = (try? FileManager.default.contentsOfDirectory(atPath: cacheDir)) ?? [String]()
    // now filter our list to items actually downloaded
    let precachedItems = precachableItems.filter {
        itemsInCache.contains($0)
    }
    if precachedItems.isEmpty {
        return
    }

    var precachedSize = 0
    var itemsWithSize = [(String, Int)]()
    for item in precachedItems {
        let itemPath = (cacheDir as NSString).appendingPathComponent(item)
        let itemSize = getSize(itemPath) / 1024
        precachedSize += itemSize
        itemsWithSize.append((itemPath, itemSize))
    }

    if precachedSize < spaceNeededInKB {
        // we can't clear enough space, so don't bother removing anything.
        // otherwise we'll clear some space, but still can't download the large
        // managed install, but then we'll have enough space to redownload the
        // precachable items and so we will (and possibly do this over and
        // over -- delete some, redownload, delete some, redownload...)
        return
    }

    // sort by size; smallest first
    itemsWithSize.sort {
        $0.1 < $1.1
    }
    var deletedKB = 0
    let filemanager = FileManager.default
    for (path, size) in itemsWithSize {
        // we delete the smallest item first, proceeding until
        // we've freed up enough space or deleted all the items
        if deletedKB >= spaceNeededInKB {
            break
        }
        do {
            try filemanager.removeItem(atPath: path)
            deletedKB += size
        } catch {
            display.error("Could not remove precached item \(path): \(error.localizedDescription)")
        }
    }
}

let PRECACHING_AGENT_LABEL = "com.googlecode.munki.precache_agent"

/// Kick off a run of our precaching agent, which allows the precaching to
/// run in the background after a normal Munki run
func startPrecachingAgent() {
    if itemsToPrecache(getInstallInfo() ?? PlistDict()).isEmpty {
        // nothing to precache
        display.debug1("Nothing found to precache.")
        return
    }
    // first look in same dir as the current executable
    var precacheAgentPath = currentExecutableDir(appendingPathComponent: "libexec/precache_agent")
    if !pathExists(precacheAgentPath) {
        precacheAgentPath = "/usr/local/munki/libexec/precache_agent"
    }
    if pathExists(precacheAgentPath) {
        display.info("Starting precaching agent")
        display.debug1("Launching precache_agent from \(precacheAgentPath)")
        do {
            let job = try LaunchdJob(
                cmd: [precacheAgentPath],
                jobLabel: PRECACHING_AGENT_LABEL,
                cleanUpAtExit: false
            )
            try job.start()
        } catch {
            display.error("Error with launchd job (\(precacheAgentPath)): \(error.localizedDescription)")
        }
    } else {
        display.error("Could not find precache_agent")
    }
}

/// Stop the precaching_agent if it's running
func stopPrecachingAgent() {
    let agentInfo = launchdJobInfo(PRECACHING_AGENT_LABEL)
    if agentInfo.state != .unknown {
        // it's either running or stopped. Removing it will stop it.
        if agentInfo.state == .running {
            display.info("Stopping precaching agent")
        }
        do {
            try removeLaunchdJob(PRECACHING_AGENT_LABEL)
        } catch {
            display.error("Error stopping precaching agent: \(error.localizedDescription)")
        }
    }
}
