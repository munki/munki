//
//  pkginfolib.swift
//  functions used by makepkginfo to create pkginfo files
//  munki
//
//  Created by Greg Neagle on 7/2/24.
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

// This implementation drops support for:
//   - pkginfo creation for configuration profiles
//   - pkginfo creation for Apple Update Metadata
//   - special handling of Adobe installers

import Foundation

/// Helps us record  information about the environment in which the pkginfo was
/// created so we have a bit of an audit trail. Returns a dictionary.
func pkginfoMetadata() -> PlistDict {
    var metadata = PlistDict()
    metadata["created_by"] = NSUserName()
    metadata["creation_date"] = Date()
    metadata["munki_version"] = getVersion()
    metadata["os_version"] = getOSVersion(onlyMajorMinor: false)
    return metadata
}

/// Gets package metadata for the package at pkgpath.
/// Returns pkginfo
func createPkgInfoFromPkg(_ pkgpath: String,
                          options: PkginfoOptions) throws -> PlistDict
{
    var info = PlistDict()

    if hasValidPackageExt(pkgpath) {
        info = try getPackageMetaData(pkgpath)
        if options.pkg.installerChoices {
            if let installerChoices = getChoiceChangesXML(pkgpath) {
                info["installer_choices_xml"] = installerChoices
            }
        }
        if !pathIsDirectory(pkgpath) {
            // generate and add installer_item_size
            if let attributes = try? FileManager.default.attributesOfItem(atPath: pkgpath) {
                let filesize = (attributes as NSDictionary).fileSize()
                info["installer_item_size"] = Int(filesize / 1024)
            }
            info["installer_item_hash"] = sha256hash(file: pkgpath)
        }
    }
    return info
}

/// Creates an item for a pkginfo "installs" array
/// Determines if the item is an application, bundle, Info.plist, or a file or
/// directory and gets additional metadata for later comparison.
func createInstallsItem(_ itempath: String) -> PlistDict {
    var info = PlistDict()
    if let plist = getBundleInfo(itempath) {
        if isApplication(itempath) {
            info["type"] = "application"
        } else {
            info["type"] = "bundle"
        }
        for key in ["CFBundleName", "CFBundleIdentifier",
                    "CFBundleShortVersionString", "CFBundleVersion"]
        {
            if let value = plist[key] as? String {
                info[key] = value
            }
        }
        if let minOSVers = plist["LSMinimumSystemVersion"] as? String {
            info["minosversion"] = minOSVers
        } else if let minOSVersByArch = plist["LSMinimumSystemVersionByArchitecture"] as? [String: String] {
            // get the highest/latest of all the minimum os versions
            let minOSVersions = minOSVersByArch.values
            let versions = minOSVersions.map { MunkiVersion($0) }
            if let maxVersion = versions.max() {
                info["minosversion"] = maxVersion.value
            }
        } else if let minSysVers = plist["SystemVersionCheck:MinimumSystemVersion"] as? String {
            info["minosversion"] = minSysVers
        }
    } else if let plist = try? readPlist(fromFile: itempath) as? PlistDict {
        // we must be a plist
        info["type"] = "plist"
        for key in ["CFBundleShortVersionString", "CFBundleVersion"] {
            if let value = plist[key] as? String {
                info[key] = value
            }
        }
    }
    // help the admin by switching to CFBundleVersion if CFBundleShortVersionString
    // value seems invalid
    if let shortVersionString = info["CFBundleShortVersionString"] as? String {
        let shortVersionStringFirst = String(shortVersionString.first ?? "X")
        if !"0123456789".contains(shortVersionStringFirst) {
            if info["CFBundleVersion"] != nil {
                info["version_comparison_key"] = "CFBundleVersion"
            }
        } else {
            info["version_comparison_key"] = "CFBundleShortVersionString"
        }
    } else if info["CFBundleVersion"] != nil {
        info["version_comparison_key"] = "CFBundleVersion"
    }

    if !info.keys.contains("CFBundleShortVersionString"), !info.keys.contains("CFBundleVersion") {
        // no version keys, so must be either a plist without version info
        // or just a simple file or directory
        info["type"] = "file"
        if pathIsRegularFile(itempath) || pathIsSymlink(itempath) {
            info["md5checksum"] = md5hash(file: itempath)
        }
    }
    if !info.isEmpty {
        info["path"] = itempath
    }
    return info
}

/// Returns names of applications found directly inside a directory
func applicationsInDirectory(_ dirpath: String) -> [String] {
    guard let contents = try? FileManager.default.contentsOfDirectory(atPath: dirpath) else {
        return []
    }
    return contents.filter {
        isApplication((dirpath as NSString).appendingPathComponent($0))
    }.sorted()
}

/// Looks for a non-application folder at the root of mountpoint that contains at least one app.
/// Returns the folder name and the sorted list of app names inside it, or nil if not found.
func findFolderWithApps(at mountpoint: String) -> (folderName: String, appNames: [String])? {
    guard let filelist = try? FileManager.default.contentsOfDirectory(atPath: mountpoint) else {
        return nil
    }
    for item in filelist.sorted() {
        let itempath = (mountpoint as NSString).appendingPathComponent(item)
        guard pathIsDirectory(itempath), !isApplication(itempath) else { continue }
        let apps = applicationsInDirectory(itempath)
        if !apps.isEmpty {
            return (item, apps)
        }
    }
    return nil
}

/// Builds pkginfo for a drag-n-drop folder containing one or more applications.
/// The folder is copied to destinationpath (default /Applications) and each app
/// inside it becomes an entry in the installs array.
func createPkgInfoForFolderWithApps(
    _ mountpoint: String,
    folderName: String,
    appNames: [String],
    options: PkginfoOptions
) -> PlistDict {
    var info = PlistDict()
    let destinationpath = options.dmg.destinationpath ?? "/Applications"

    var destFolderName = folderName
    var itemsToCopyItem = PlistDict()
    itemsToCopyItem["source_item"] = folderName
    itemsToCopyItem["destination_path"] = destinationpath
    if let destitemname = options.dmg.destitemname {
        destFolderName = destitemname
        itemsToCopyItem["destination_item"] = destitemname
    }
    if let user = options.dmg.user { itemsToCopyItem["user"] = user }
    if let group = options.dmg.group { itemsToCopyItem["group"] = group }
    if let mode = options.dmg.mode { itemsToCopyItem["mode"] = mode }

    let folderInstallPath = (destinationpath as NSString).appendingPathComponent(destFolderName)
    let folderpath = (mountpoint as NSString).appendingPathComponent(folderName)

    var installsItems = [PlistDict]()
    var highestVersion = MunkiVersion("0.0.0.0.0")
    var highestMinOSVersion: MunkiVersion? = nil

    for appName in appNames {
        let apppath = (folderpath as NSString).appendingPathComponent(appName)
        var installsItem = createInstallsItem(apppath)
        if installsItem.isEmpty { continue }
        installsItem["path"] = (folderInstallPath as NSString).appendingPathComponent(appName)
        installsItems.append(installsItem)

        let comparisonKey = installsItem["version_comparison_key"] as? String ?? "CFBundleShortVersionString"
        let appVersion = MunkiVersion(installsItem[comparisonKey] as? String ?? "0.0.0.0.0")
        if appVersion > highestVersion {
            highestVersion = appVersion
        }
        if let minOSStr = installsItem["minosversion"] as? String {
            let appMinOS = MunkiVersion(minOSStr)
            if highestMinOSVersion == nil || appMinOS > highestMinOSVersion! {
                highestMinOSVersion = appMinOS
            }
        }
    }

    guard !installsItems.isEmpty else { return info }

    info["name"] = (destFolderName as NSString).deletingPathExtension
    info["version"] = highestVersion.value
    if let highestMinOSVersion {
        info["minimum_os_version"] = highestMinOSVersion.value
    }
    info["installs"] = installsItems
    info["installer_type"] = "copy_from_dmg"
    info["items_to_copy"] = [itemsToCopyItem]
    info["uninstallable"] = true
    info["uninstall_method"] = "remove_copied_items"
    return info
}

/// Processes a drag-n-drop dmg to build pkginfo
func createPkgInfoForDragNDrop(_ mountpoint: String, options: PkginfoOptions) throws -> PlistDict {
    var info = PlistDict()
    var dragNDropItem = ""
    var installsitem = PlistDict()
    if let item = options.dmg.item {
        dragNDropItem = item
    } else {
        // no item specified; look for an application at root of mounted dmg
        let filemanager = FileManager.default
        if let filelist = try? filemanager.contentsOfDirectory(atPath: mountpoint) {
            for item in filelist {
                let itempath = (mountpoint as NSString).appendingPathComponent(item)
                if isApplication(itempath) {
                    dragNDropItem = item
                    break
                }
            }
        }
    }

    // If no app found at root and no item explicitly specified, check for a
    // folder containing apps (e.g. folder named "Nuke 17.0v2/" with several .app bundles)
    if dragNDropItem.isEmpty, options.dmg.item == nil {
        if let (folderName, appNames) = findFolderWithApps(at: mountpoint) {
            return createPkgInfoForFolderWithApps(
                mountpoint, folderName: folderName, appNames: appNames, options: options
            )
        }
    }

    // If --item pointed at a folder (not an app), treat it as a folder-with-apps
    if !dragNDropItem.isEmpty {
        var mountpointPattern = mountpoint
        if !mountpointPattern.hasSuffix("/") { mountpointPattern += "/" }
        var resolvedItem = dragNDropItem
        if resolvedItem.hasPrefix(mountpointPattern) {
            // remove mountpoint sequence to make relative path
            resolvedItem = String(resolvedItem.dropFirst(mountpointPattern.count))
        }
        let itempath = (mountpoint as NSString).appendingPathComponent(resolvedItem)
        if pathIsDirectory(itempath), !isApplication(itempath) {
            let appNames = applicationsInDirectory(itempath)
            if !appNames.isEmpty {
                return createPkgInfoForFolderWithApps(
                    mountpoint, folderName: resolvedItem, appNames: appNames, options: options
                )
            }
        }
    }

    guard !dragNDropItem.isEmpty else {
        throw MunkiError("No application found on disk image.")
    }

    // continue as copy_from_dmg item
    let itempath = (mountpoint as NSString).appendingPathComponent(dragNDropItem)
    installsitem = createInstallsItem(itempath)

    if !installsitem.isEmpty {
        var itemsToCopyItem = PlistDict()
        var mountpointPattern = mountpoint
        if !mountpointPattern.hasSuffix("/") {
            mountpointPattern += "/"
        }
        if dragNDropItem.hasPrefix(mountpointPattern) {
            let startIndex = dragNDropItem.index(
                dragNDropItem.startIndex, offsetBy: mountpointPattern.count
            )
            dragNDropItem = String(dragNDropItem[startIndex...])
        }
        var destItem = dragNDropItem
        if let destitemname = options.dmg.destitemname {
            destItem = destitemname
            itemsToCopyItem["destination_item"] = destItem
        }

        let destItemFilename = (destItem as NSString).lastPathComponent
        if let destinationpath = options.dmg.destinationpath {
            installsitem["path"] = (destinationpath as NSString).appendingPathComponent(destItemFilename)
        } else {
            installsitem["path"] = ("/Applications" as NSString).appendingPathComponent(destItemFilename)
        }
        if let name = installsitem["CFBundleName"] as? String {
            info["name"] = name
        } else {
            info["name"] = (dragNDropItem as NSString).deletingPathExtension
        }
        let comparisonKey = installsitem["version_comparison_key"] as? String ?? "CFBundleShortVersionString"
        let version = installsitem[comparisonKey] as? String ?? "0.0.0.0.0"
        if let minOSVers = installsitem["minosversion"] as? String {
            info["minimum_os_version"] = minOSVers
        }
        info["version"] = version
        info["installs"] = [installsitem]
        info["installer_type"] = "copy_from_dmg"
        // build items_to_copy array
        itemsToCopyItem["source_item"] = dragNDropItem
        if let destinationpath = options.dmg.destinationpath {
            itemsToCopyItem["destination_path"] = destinationpath
        } else {
            itemsToCopyItem["destination_path"] = "/Applications"
        }
        if let user = options.dmg.user {
            itemsToCopyItem["user"] = user
        }
        if let group = options.dmg.group {
            itemsToCopyItem["group"] = group
        }
        if let mode = options.dmg.mode {
            itemsToCopyItem["mode"] = mode
        }
        info["items_to_copy"] = [itemsToCopyItem]
        info["uninstallable"] = true
        info["uninstall_method"] = "remove_copied_items"

        // Should we add extra info for a stage_os_installer item?
        if pathIsInstallMacOSApp(itempath),
           options.type.installerType == nil || options.type.installerType == .stage_os_installer
        {
            let additionalInfo = try makeStageOSInstallerPkgInfo(itempath)
            // merge the additionalPkgInfo, giving it priority
            info.merge(additionalInfo) { _, second in second }
        }
    }

    return info
}

/// Mounts a disk image if it"s not already mounted
/// Builds pkginfo for the first installer item found at the root level,
/// or a specific one if specified by options.pkgname or options.item
/// Unmounts the disk image if it wasn't already mounted
func createPkgInfoFromDmg(_ dmgpath: String,
                          options: PkginfoOptions) throws -> PlistDict
{
    var info = PlistDict()
    let wasAlreadyMounted = diskImageIsMounted(dmgpath)
    var mountpoint = ""
    do {
        mountpoint = try mountdmg(dmgpath, useExistingMounts: true)
    } catch let error as MunkiError {
        throw MunkiError("Could not mount \(dmgpath): \(error.description)")
    }
    guard !mountpoint.isEmpty else {
        throw MunkiError("No mountpoint for \(dmgpath)")
    }
    if let pkgname = options.pkg.pkgname {
        // a package was specified
        let pkgpath = (mountpoint as NSString).appendingPathComponent(pkgname)
        info = try createPkgInfoFromPkg(pkgpath, options: options)
        info["package_path"] = pkgname
    } else if options.dmg.item == nil {
        // look for first package at the root of the mounted dmg
        if let filelist = try? FileManager.default.contentsOfDirectory(atPath: mountpoint) {
            for item in filelist {
                if hasValidPackageExt(item) {
                    let pkgpath = (mountpoint as NSString).appendingPathComponent(item)
                    info = try createPkgInfoFromPkg(pkgpath, options: options)
                    break
                }
            }
        }
    }
    if info.isEmpty {
        // maybe this is a drag-n-drop disk image
        if let dragNDropInfo = try? createPkgInfoForDragNDrop(
            mountpoint, options: options
        ) {
            info = dragNDropInfo
        }
    }
    if !info.isEmpty {
        // generate and add installer_item_size
        if let attributes = try? FileManager.default.attributesOfItem(atPath: dmgpath) {
            let filesize = (attributes as NSDictionary).fileSize()
            info["installer_item_size"] = Int(filesize / 1024)
        }
        info["installer_item_hash"] = sha256hash(file: dmgpath)
    }
    // eject the dmg
    if !wasAlreadyMounted {
        do {
            try unmountdmg(mountpoint)
        } catch {
            printStderr(error.localizedDescription)
        }
    }
    return info
}

/// Attempt to read a file with the same name as the input string and return its text,
/// otherwise return the input string
func readFileOrString(_ fileNameOrString: String) throws -> String {
    let expandedPath = (fileNameOrString as NSString).expandingTildeInPath
    if !pathExists(expandedPath) {
        return fileNameOrString
    }
    return try fileContents(fileNameOrString)
}

/// If path appears to be inside the repo's pkgs directory, return a path relative to the pkgs dir
/// Otherwise, return the basename
func repoPkgPath(_ path: String) -> String {
    let absPath = getAbsolutePath(path)
    if let repourl = adminPref("repo_url") as? String,
       let url = URL(string: repourl),
       url.scheme == "file"
    {
        let repoPkgsPath = (url.path as NSString).appendingPathComponent("pkgs")
        if absPath.hasPrefix(repoPkgsPath) {
            // return portion of absPath after /pkgs/
            let pkgsPath = absPath.components(separatedBy: "/").drop(while: { $0 != "pkgs" })
            return pkgsPath.dropFirst().joined(separator: "/")
        }
    }
    return (path as NSString).lastPathComponent
}

/// Extract a minimum_os_version from pkginfo installs
func getMinimumOSVersionFromInstallsApps(_ pkginfo: PlistDict) -> String? {
    if let installer_type = pkginfo["installer_type"] as? String,
       installer_type == "stage_os_installer"
    {
        // don't use the app for this
        return nil
    }
    guard let installs = pkginfo["installs"] as? [PlistDict] else {
        // no valid installs array
        return nil
    }
    var minimumOSVersions = [MunkiVersion]()
    for install in installs {
        if let version = install["minosversion"] as? String {
            minimumOSVersions.append(MunkiVersion(version))
        }
    }
    if let pkgInfoMinimumOSVersion = pkginfo["minimum_os_version"] as? String {
        minimumOSVersions.append(MunkiVersion(pkgInfoMinimumOSVersion))
    }
    return minimumOSVersions.max()?.value
}

/// return contents of file at path, expanding tilde as needed
func fileContents(_ path: String) throws -> String {
    let expandedPath = (path as NSString).expandingTildeInPath
    do {
        return try String(contentsOfFile: expandedPath, encoding: .utf8)
    } catch {
        throw MunkiError("Failed to read file \(expandedPath): \(error)")
    }
}

/// Return a pkginfo dictionary for installeritem
func makepkginfo(_ filepath: String?,
                 options: PkginfoOptions) throws -> PlistDict
{
    var installeritem = filepath ?? ""
    var pkginfo = PlistDict()

    if !installeritem.isEmpty {
        if !FileManager.default.fileExists(atPath: installeritem) {
            throw MunkiError("File \(installeritem) does not exist")
        }

        // is this the mountpoint for a mounted disk image?
        if pathIsVolumeMountPoint(installeritem) {
            // Get the disk image path for the mountpoint
            // and use that instead of the original item
            if let dmgPath = diskImageForMountPoint(installeritem) {
                installeritem = dmgPath
            }
        }

        // is this a disk image?
        if hasValidDiskImageExt(installeritem) {
            pkginfo = try createPkgInfoFromDmg(installeritem, options: options)
            if pkginfo.isEmpty {
                throw MunkiError("Could not find a supported installer item in \(installeritem)")
            }
            if dmgIsWritable(installeritem), options.hidden.printWarnings {
                printStderr("WARNING: \(installeritem) is a writable disk image. Checksum verification is not supported.")
                pkginfo["installer_item_hash"] = "N/A"
            }
            // is this a package?
        } else if hasValidPackageExt(installeritem) {
            if let installerTypeRequested = options.type.installerType, options.hidden.printWarnings {
                printStderr("WARNING: installer_type requested is \(installerTypeRequested.rawValue). Provided installer item appears to be an Apple pkg.")
            }
            pkginfo = try createPkgInfoFromPkg(installeritem, options: options)
            if pkginfo.isEmpty {
                throw MunkiError("\(installeritem) doesn't appear to be a valid installer item.")
            }
            if pathIsDirectory(installeritem), options.hidden.printWarnings {
                printStderr("WARNING: \(installeritem) is a bundle-style package!\nTo use it with Munki, you should encapsulate it in a disk image.")
            }
        } else {
            throw MunkiError("\(installeritem) is not a supported installer item!")
        }
        pkginfo["installer_item_location"] = repoPkgPath(installeritem)

        if let uninstalleritem = options.pkg.uninstalleritem {
            pkginfo["uninstallable"] = true
            pkginfo["uninstall_method"] = "uninstall_package"
            let minMunkiVers = pkginfo["minimum_munki_version"] as? String ?? "0"
            if MunkiVersion(minMunkiVers) > MunkiVersion("6.2") {
                pkginfo["minimum_munki_version"] = "6.2"
            }
            if !FileManager.default.fileExists(atPath: uninstalleritem) {
                throw MunkiError("No uninstaller item at \(uninstalleritem)")
            }
            pkginfo["uninstaller_item_location"] = repoPkgPath(uninstalleritem)

            pkginfo["uninstaller_item_hash"] = sha256hash(file: uninstalleritem)
            if let attributes = try? FileManager.default.attributesOfItem(atPath: uninstalleritem) {
                let filesize = (attributes as NSDictionary).fileSize()
                pkginfo["uninstaller_item_size"] = Int(filesize / 1024)
            }
        }

        // No uninstall method yet?
        // if we have receipts, assume we can uninstall using them
        if !pkginfo.keys.contains("uninstall_method") {
            if let receipts = pkginfo["receipts"] as? [PlistDict] {
                if !receipts.isEmpty {
                    pkginfo["uninstallable"] = true
                    pkginfo["uninstall_method"] = "removepackages"
                }
            }
        }

    } else {
        // no installer item
        if options.type.nopkg {
            pkginfo["installer_type"] = "nopkg"
        }
    }

    if !options.other.catalog.isEmpty {
        pkginfo["catalogs"] = options.other.catalog
    }
    if let description = options.override.description {
        pkginfo["description"] = try readFileOrString(description)
    }
    if let displayname = options.override.displayname {
        pkginfo["display_name"] = displayname
    }
    if let name = options.override.name {
        pkginfo["name"] = name
    }
    if let version = options.override.pkgvers {
        pkginfo["version"] = version
    }
    if let category = options.other.category {
        pkginfo["category"] = category
    }
    if let developer = options.other.developer {
        pkginfo["developer"] = developer
    }
    if let iconName = options.other.iconName {
        pkginfo["icon_name"] = iconName
    }

    // process items for installs array
    var installs = [PlistDict]()
    for var file in options.installs.file {
        if file != "/", file.hasSuffix("/") {
            file.removeLast()
        }
        if FileManager.default.fileExists(atPath: file) {
            let installsItem = createInstallsItem(file)
            installs.append(installsItem)
        } else {
            printStderr("Item \(file) doesn't exist. Skipping.")
        }
    }
    if !installs.isEmpty {
        pkginfo["installs"] = installs
    }

    // use apps in installs list to figure out a minimum os version
    if let minimumOSVersion = getMinimumOSVersionFromInstallsApps(pkginfo) {
        pkginfo["minimum_os_version"] = minimumOSVersion
    }

    // add pkginfo scripts if specified
    // TODO: verify scripts start with a shebang line?
    if let installcheckScript = options.script.installcheckScript {
        pkginfo["installcheck_script"] = try fileContents(installcheckScript)
    }
    if let uninstallcheckScript = options.script.uninstallcheckScript {
        pkginfo["uninstallcheck_script"] = try fileContents(uninstallcheckScript)
    }
    if let postinstallScript = options.script.postinstallScript {
        pkginfo["postinstall_script"] = try fileContents(postinstallScript)
    }
    if let preinstallScript = options.script.preinstallScript {
        pkginfo["preinstall_script"] = try fileContents(preinstallScript)
    }
    if let postuninstallScript = options.script.postuninstallScript {
        pkginfo["postuninstall_script"] = try fileContents(postuninstallScript)
    }
    if let preuninstallScript = options.script.preuninstallScript {
        pkginfo["preuninstall_script"] = try fileContents(preuninstallScript)
    }
    if let uninstallScript = options.script.uninstallScript {
        pkginfo["uninstall_script"] = try fileContents(uninstallScript)
        pkginfo["uninstall_method"] = "uninstall_script"
        pkginfo["uninstallable"] = true
    }
    if let versionScript = options.script.versionScript {
        pkginfo["version_script"] = try fileContents(versionScript)
    }
    // more options and pkginfo bits
    if !installeritem.isEmpty || options.type.nopkg {
        pkginfo["_metadata"] = pkginfoMetadata()
        pkginfo["autoremove"] = options.other.autoremove
        if pkginfo["catalogs"] == nil {
            pkginfo["catalogs"] = ["testing"]
        }
    }
    if let minimumMunkiVersion = options.other.minimumMunkiVersion {
        pkginfo["minimum_munki_version"] = minimumMunkiVersion
    }
    if options.other.onDemand {
        pkginfo["OnDemand"] = true
    }
    if options.force.unattendedInstall {
        pkginfo["unattended_install"] = true
    }
    if options.force.unattendedUninstall {
        pkginfo["unattended_uninstall"] = true
    }
    if let minimumOSVersion = options.other.minimumOSVersion {
        pkginfo["minimum_os_version"] = minimumOSVersion
    }
    if let maximumOSVersion = options.other.maximumOSVersion {
        pkginfo["maximum_os_version"] = maximumOSVersion
    }
    if !options.other.supportedArchitectures.isEmpty {
        let rawValues = options.other.supportedArchitectures.map(\.rawValue)
        pkginfo["supported_architectures"] = rawValues
    }
    if let forceInstallAfterDate = options.force.forceInstallAfterDate {
        pkginfo["force_install_after_date"] = forceInstallAfterDate
    }
    if let restartAction = options.override.restartAction {
        pkginfo["RestartAction"] = restartAction.rawValue
    }
    if !options.other.updateFor.isEmpty {
        pkginfo["update_for"] = options.other.updateFor
    }
    if !options.other.requires.isEmpty {
        pkginfo["requires"] = options.other.requires
    }
    if !options.other.blockingApplication.isEmpty {
        pkginfo["blocking_applications"] = options.other.blockingApplication
    }
    if let uninstallMethod = options.override.uninstallMethod {
        pkginfo["uninstall_method"] = uninstallMethod
        pkginfo["uninstallable"] = true
    }
    if !options.pkg.installerEnvironment.isEmpty {
        pkginfo["installer_environment"] = options.pkg.installerEnvironmentDict
    }
    if let notes = options.other.notes {
        pkginfo["notes"] = try readFileOrString(notes)
    }

    return pkginfo
}

/// prints a warning to stdout if the pkginfo lack info needed to determine if an item is installed
func warnIfNoValidInstallsCriteria(_ pkginfo: PlistDict) {
    if pkginfo["OnDemand"] as? Bool == true ||
        !(pkginfo["installcheck_script"] as? String ?? "").isEmpty ||
        !(pkginfo["version_script"] as? String ?? "").isEmpty ||
        !(pkginfo["installs"] as? [PlistDict] ?? []).isEmpty ||
        !(pkginfo["receipts"] as? [PlistDict] ?? []).isEmpty
    {
        return
    }
    let name = pkginfo["name"] as? String ?? "UNKNOWN"
    printStderr(
        """

        WARNING: pkginfo for \(name) contains no installation check info!
            No useful receipts were detected, and no 'installs' items were provided.
            If you do not add an 'installs' item, a version_script, or an installcheck_script,
            Munki will have no way to determine the item's installation state.
            This can result in repeated installation attempts or failure to
            attempt installation at all.

        """
    )
}
