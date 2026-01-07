//
//  analyze.swift
//  munki
//
//  Created by Greg Neagle on 8/19/24.
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

// TODO: this file has very long, very complex functions that are hard to follow
// and hard to understand.
// (Notably processInstall, processOptionalInstall, and processRemoval)
// Need to refactor these

import Foundation

private let display = DisplayAndLog.main

/// Determines if an item is in a list of processed items.
///
/// Returns true if the item has already been processed (it's in the list)
/// and, optionally, the version is the same or greater.
func itemInInstallInfo(_ thisItem: PlistDict, theList: [PlistDict], version: String = "") -> Bool {
    for listItem in theList {
        if let listItemName = listItem["name"] as? String,
           let thisItemName = thisItem["name"] as? String
        {
            if listItemName == thisItemName {
                if version.isEmpty {
                    return true
                }
                // if the version already installed or processed to be
                // installed is the same or greater, then we're good.
                if let installed = listItem["installed"] as? Bool,
                   installed == true,
                   let installedVersion = listItem["installed_version"] as? String,
                   compareVersions(installedVersion, version).rawValue > 0
                {
                    return true
                }
                if let versionToInstall = listItem["version_to_install"] as? String,
                   compareVersions(versionToInstall, version).rawValue > 0
                {
                    return true
                }
            }
        }
    }
    return false
}

/// Returns true if the item to be installed or removed appears to be from
/// Apple. If we are installing or removing any Apple items in a check/install
/// cycle, we skip checking/installing Apple updates from an Apple Software
/// Update server so we don't stomp on each other
func isAppleItem(_ pkginfo: PlistDict) -> Bool {
    // is this a startosinstall item?
    if let installerType = pkginfo["installer_type"] as? String,
       installerType == "startosinstall"
    {
        return true
    }
    // check receipts
    if let receipts = pkginfo["receipts"] as? [PlistDict] {
        for receipt in receipts {
            if let pkgid = receipt["packageid"] as? String,
               pkgid.hasPrefix("com.apple.")
            {
                return true
            }
        }
    }
    // check installs items
    if let installs = pkginfo["installs"] as? [PlistDict] {
        for install in installs {
            if let bundleID = install["CFBundleIdentifier"] as? String,
               bundleID.hasPrefix("com.apple.")
            {
                return true
            }
        }
    }
    // if we get here, no receipts or installs items have Apple
    // identifiers
    return false
}

/// Returns true if itemname has already been added to installinfo in one
/// of the given sections
func alreadyProcessed(_ itemName: String, installInfo: PlistDict, sections: [String]) -> Bool {
    let description = [
        "processed_installs": "install",
        "processed_uninstalls": "uninstall",
        "managed_updates": "update",
        "optional_installs": "optional install",
    ]
    for section in sections {
        if let listOfNames = installInfo[section] as? [String],
           listOfNames.contains(itemName)
        {
            display.debug1("\(itemName) has already been processed for \(description[section] ?? "")")
            return true
        } else if let listOfPkgInfos = installInfo[section] as? [PlistDict] {
            for pkginfo in listOfPkgInfos {
                if let pkginfoName = pkginfo["name"] as? String {
                    if itemName == pkginfoName {
                        display.debug1("\(itemName) has already been processed for \(description[section] ?? "")")
                        return true
                    }
                }
            }
        }
    }
    return false
}

/// Processes a manifest item for install. Determines if it needs to be
/// installed, and if so, if any items it is dependent on need to
/// be installed first.  Installation detail is added to
/// installinfo['managed_installs']
/// Calls itself recursively as it processes dependencies.
/// Returns a boolean; when processing dependencies, a false return
/// will stop the installation of a dependent item
func processInstall(
    _ manifestItem: String,
    catalogList: [String],
    installInfo: inout PlistDict,
    isManagedUpdate: Bool = false,
    isOptionalInstall: Bool = false
) async -> Bool {
    /// helper function
    func appendToProcessedManagedInstalls(_ item: PlistDict) {
        var managedInstalls = installInfo["managed_installs"] as? [PlistDict] ?? []
        managedInstalls.append(item)
        installInfo["managed_installs"] = managedInstalls
    }

    let manifestItemName = (manifestItem as NSString).lastPathComponent
    display.debug1("* Processing manifest item \(manifestItemName) for install")
    let (manifestItemNameWithoutVersion, includedVersion) = nameAndVersion(manifestItemName, onlySplitOnHyphens: true)

    // have we processed this already?
    if let processedInstalls = installInfo["processed_installs"] as? [String],
       processedInstalls.contains(manifestItemName)
    {
        display.debug1("\(manifestItemName) has already been processed for install.")
        return true
    }
    if let processedUninstalls = installInfo["processed_uninstalls"] as? [String],
       processedUninstalls.contains(manifestItemNameWithoutVersion)
    {
        display.debug1("Will not process \(manifestItemName) for install because it has already been processed for uninstall!")
        return false
    }

    guard let pkginfo = await getItemDetail(manifestItemName, catalogList: catalogList) else {
        display.warning("Could not process item \(manifestItemName) for install. No pkginfo found in catalogs: \(catalogList)")
        return false
    }

    if let managedInstalls = installInfo["managed_installs"] as? [PlistDict],
       let itemName = pkginfo["name"] as? String,
       let itemVersion = pkginfo["version"] as? String,
       itemInInstallInfo(pkginfo, theList: managedInstalls, version: itemVersion)
    {
        // item has been processed for install; now check to see if there
        // was a problem when it was processed
        let problemItemNames: [String]
        problemItemNames = managedInstalls.filter {
            $0["installed"] is Bool &&
                ($0["installed"] as? Bool ?? true) == false &&
                $0["installer_item"] == nil
        }.map {
            $0["name"] as? String ?? ""
        }.filter {
            !$0.isEmpty
        }

        if problemItemNames.contains(itemName) {
            // item was processed, but not successfully downloaded
            display.debug1("\(manifestItemName) was processed earlier, but download failed.")
            return false
        }

        // item was processed successfully
        display.debug1("\(manifestItem) is or will be installed.")
        return true
    }

    // check dependencies
    var dependenciesMet = true

    // there are two kinds of dependencies/relationships.
    //
    // 'requires' are prerequisites:
    //  package A requires package B be installed first.
    //  if package A is removed, package B is unaffected.
    //  requires can be a one to many relationship.
    //
    //  The second type of relationship is 'update_for'.
    //  This signifies that that current package should be considered an update
    //  for the packages listed in the 'update_for' array. When processing a
    //  package, we look through the catalogs for other packages that declare
    //  they are updates for the current package and install them if needed.
    //  This can be a one-to-many relationship - one package can be an update
    //  for several other packages; for example, 'PhotoshopCS4update-11.0.1'
    //  could be an update for PhotoshopCS4 and for AdobeCS4DesignSuite.
    //
    //  When removing an item, any updates for that item are removed as well.

    let name = pkginfo["name"] as? String ?? "<unknown>"
    let version = pkginfo["version"] as? String ?? "<unknown>"

    // get list of dependencies. 'requires' should be a list of strings, but
    // sometimes admins define it as just a single string. Account for both
    // possibilities
    var dependencies = [String]()
    if let requires = pkginfo["requires"] as? [String] {
        dependencies = requires
    } else if let requires = pkginfo["requires"] as? String {
        dependencies = [requires]
    }
    for item in dependencies {
        display.detail("\(name)-\(version) requires \(item). Getting info on \(item)...")
        let success = await processInstall(
            item,
            catalogList: catalogList,
            installInfo: &installInfo,
            isManagedUpdate: isManagedUpdate,
            isOptionalInstall: isOptionalInstall
        )
        if !success {
            dependenciesMet = false
        }
    }

    var processedItem = PlistDict()
    processedItem["name"] = name
    let displayName = pkginfo["display_name"] as? String ?? name
    processedItem["display_name"] = displayName
    processedItem["description"] = pkginfo["description"] as? String ?? ""
    processedItem["localized_strings"] = pkginfo["localized_strings"]
    processedItem["developer"] = pkginfo["developer"]
    processedItem["icon_name"] = pkginfo["icon_name"]

    let installedState = await installedState(pkginfo)
    if installedState == .thisVersionNotInstalled {
        if !dependenciesMet {
            // we should not attempt to install
            display.warning("Didn't attempt to install \(manifestItemName) because could not resolve all dependencies.")
            // add information to managed_installs so we have some feedback
            // to display in MSC.app
            processedItem["installed"] = false
            processedItem["note"] = "Can't install \(displayName) because could not verify all other items it requires are or will be installed."
            appendToProcessedManagedInstalls(processedItem)
            return false
        }

        display.detail("Need to install \(manifestItemName)")
        processedItem["installed"] = false
        processedItem["version_to_install"] = version
        let installerItemSize = pkginfo["installer_item_size"] as? Int ?? 0
        processedItem["installer_item_size"] = installerItemSize
        processedItem["installed_size"] = pkginfo["installer_item_size"] as? Int ?? installerItemSize
        var downloadSeconds = 0.0
        var filename = ""
        if let installerType = pkginfo["installer_type"] as? String,
           installerType == "nopkg"
        {
            // "install" that has no actual download
            filename = "packageless_install"
        } else {
            do {
                // record starttime
                let startTime = Date()
                if try downloadInstallerItem(pkginfo, installInfo: installInfo) {
                    // Record the download speed for the InstallResults output.
                    downloadSeconds = Date().timeIntervalSince(startTime)
                } else {
                    // item was in cache and unchanged
                }
            } catch let FetchError.fileSystem(description) {
                display.warning("Can't install \(manifestItemName) because \(description).")
                processedItem["installed"] = false
                processedItem["note"] = description
                if let installerItemLocation = pkginfo["installer_item_location"] as? String {
                    processedItem["partial_installer_item"] = baseName(installerItemLocation)
                }
                processedItem["version_to_install"] = version
                appendToProcessedManagedInstalls(processedItem)
                return false
            } catch {
                // download unsuccessful
                if let installerItemLocation = pkginfo["installer_item_location"] as? String {
                    processedItem["partial_installer_item"] = baseName(installerItemLocation)
                }
                if let err = error as? FetchError {
                    switch err {
                    case .verification:
                        display.warning("Can't install \(manifestItemName) because the integrity check failed.")
                        processedItem["note"] = "Integrity check failed"
                        processedItem["partial_installer_item"] = nil
                    case let .fileSystem(description):
                        display.warning("Can't install \(manifestItemName) because \(description).")
                        processedItem["note"] = description
                    case let .connection(errorCode, description),
                         let .download(errorCode, description),
                         let .http(errorCode, description):
                        display.warning("Download of \(manifestItemName) failed: error \(errorCode): \(description)")
                        processedItem["note"] = "Download failed: \(description)"
                    }
                } else {
                    display.warning("Can't install \(manifestItemName) because \(error.localizedDescription)")
                    processedItem["note"] = error.localizedDescription
                }
                processedItem["version_to_install"] = version
                appendToProcessedManagedInstalls(processedItem)
                return false
            }
            // download succeeded or cached item is current
            if let installerItemLocation = pkginfo["installer_item_location"] as? String {
                filename = baseName(installerItemLocation)
            }
            if installerItemSize >= 1024, downloadSeconds > 0 {
                let downloadSpeed = Int(Double(installerItemSize) / downloadSeconds)
                processedItem["download_kbytes_per_sec"] = downloadSpeed
                display.detail("\(filename) downloaded at \(downloadSpeed) KB/sec")
            }
        }
        processedItem["installer_item"] = filename
        // we will ignore the unattended_install key if the item needs a
        // restart or logout...
        if (pkginfo["unattended_install"] as? Bool ?? false) || (pkginfo["forced_install"] as? Bool ?? false) {
            let restartAction = pkginfo["RestartAction"] as? String ?? "None"
            if restartAction != "None" {
                display.warning("Ignoring unattended_install key for \(name) because RestartAction is \(restartAction).")
            } else {
                processedItem["unattended_install"] = true
            }
        }

        // optional keys to copy if they exist
        var optionalKeys = [
            "force_install_after_date",
            "additional_startosinstall_options",
            "allow_untrusted",
            "installer_choices_xml",
            "installer_environment",
            "adobe_install_info",
            "RestartAction",
            "installer_type",
            "adobe_package_name",
            "package_path",
            "blocking_applications",
            "installs",
            "requires",
            "update_for",
            "payloads",
            "preinstall_script",
            "postinstall_script",
            "items_to_copy", // used w/ copy_from_dmg
            "apple_item",
            "category",
            "developer",
            "icon_name",
            "PayloadIdentifier",
            "icon_hash",
            "OnDemand",
            "precache",
            "display_name_staged", // used w/ stage_os_installer
            "description_staged",
            "installed_size_staged",
        ]

        if isOptionalInstall {
            let someVersionInstalled = await someVersionInstalled(pkginfo)
            if !someVersionInstalled {
                // For optional installs where no version is installed yet
                // we do not enforce force_install_after_date
                optionalKeys = optionalKeys.filter {
                    $0 != "force_install_after_date"
                }
            }
        }

        for key in optionalKeys {
            processedItem[key] = pkginfo[key]
        }

        if pkginfo["apple_item"] == nil {
            // admin did not explicitly mark this item; let's determine if
            // it's from Apple
            if isAppleItem(pkginfo) {
                munkiLog("Marking \(name) as an apple_item - this will block Apple SUS updates")
                processedItem["apple_item"] = true
            }
        }

        appendToProcessedManagedInstalls(processedItem)

        // now look for update_for items
        var updateList = [String]()
        if !includedVersion.isEmpty {
            // a specific version was specified in the manifest
            // so look only for updates for this specific version
            updateList = lookForUpdatesForName(
                manifestItemNameWithoutVersion,
                version: includedVersion,
                catalogList: catalogList
            )
        } else {
            // didn't specify a specific version, so
            // now look for all updates for this item
            updateList = lookForUpdatesFor(
                manifestItemNameWithoutVersion,
                catalogList: catalogList
            )
            // now append any updates specifically
            // for the version to be installed
            updateList += lookForUpdatesForName(
                manifestItemNameWithoutVersion,
                version: version,
                catalogList: catalogList
            )
        }
        // if we have any update items, process them
        for updateItem in updateList {
            _ = await processInstall(
                updateItem,
                catalogList: catalogList,
                installInfo: &installInfo
            )
        }
    } else {
        // same or higher version installed
        processedItem["installed"] = true

        if !dependenciesMet {
            display.warning("Could not resolve all dependencies for \(manifestItemName), but no install or update needed.")
        }

        if let installerType = pkginfo["installer_type"] as? String,
           installerType == "stage_os_installer",
           installedState == .thisVersionInstalled
        {
            // installer appears to be staged; make sure the info is recorded
            // so we know we can launch the installer later
            // TODO: maybe filter the actual info recorded
            display.info("Recording staged macOS installer...")
            recordStagedOSInstaller(pkginfo)
        }
        // record installed size and version
        let installedSize = pkginfo["installed_size"] as? Int ?? pkginfo["installer_item_size"] as? Int ?? 0
        processedItem["installed_size"] = installedSize
        if installedState == .thisVersionInstalled {
            // just use the version from the pkginfo
            processedItem["installed_version"] = version
        } else {
            // might be newer; attempt to figure out the version
            var installedVersion = getInstalledVersion(pkginfo)
            if installedVersion == "UNKNOWN" {
                installedVersion = "(newer than \(version))"
            }
            processedItem["installed_version"] = installedVersion
        }
        appendToProcessedManagedInstalls(processedItem)
        display.detail("\(manifestItemNameWithoutVersion) version \(version) (or newer) is already installed.")

        // now look for update_for items
        var updateList = [String]()
        let installedVersion = processedItem["installed_version"] as? String ?? ""
        if includedVersion.isEmpty {
            // no specific version is specified;
            // the item is already installed;
            // now look for updates for this item
            updateList = lookForUpdatesFor(name, catalogList: catalogList)
            // and also any for this specific version
            if !installedVersion.hasPrefix("(newer than") {
                updateList += lookForUpdatesForName(
                    name,
                    version: installedVersion,
                    catalogList: catalogList
                )
            }
        } else if compareVersions(includedVersion, installedVersion) == .same {
            // manifest specifies a specific version.
            // if that's what's installed, look for any updates
            // specific to this version
            updateList = lookForUpdatesForName(
                name,
                version: includedVersion,
                catalogList: catalogList
            )
        }
        // if we have any update items, process them
        for updateItem in updateList {
            _ = await processInstall(
                updateItem,
                catalogList: catalogList,
                installInfo: &installInfo,
                isManagedUpdate: isManagedUpdate,
                isOptionalInstall: isOptionalInstall
            )
        }
    }
    // done successfully processing this install; add it to our list
    // of processed installs so we don't process it again in the future
    // (unless it is a managed_update)
    if !isManagedUpdate {
        display.debug2("Adding \(manifestItemName) to the list of processed installs")
        var processedInstalls = installInfo["processed_installs"] as? [String] ?? []
        processedInstalls.append(manifestItemName)
        installInfo["processed_installs"] = processedInstalls
    }
    return true
}

/// Process a managed_updates item to see if it is installed, and if so, if it needs an update.
func processManagedUpdate(
    _ manifestItem: String,
    catalogList: [String],
    installInfo: inout PlistDict
) async {
    let manifestItemName = (manifestItem as NSString).lastPathComponent
    display.debug1("* Processing manifest item \(manifestItemName) for update")

    if alreadyProcessed(
        manifestItemName,
        installInfo: installInfo,
        sections: ["managed_updates", "processed_installs", "processed_uninstalls"]
    ) { return }

    guard let pkginfo = await getItemDetail(manifestItemName, catalogList: catalogList) else {
        display.warning("Could not process item \(manifestItemName) for update. No pkginfo found in catalogs: \(catalogList) ")
        return
    }

    // we only offer to update if some version of the item is already
    // installed, so let's check
    if await someVersionInstalled(pkginfo) {
        // add to the list of processed managed_updates
        var managedUpdates = installInfo["managed_updates"] as? [String] ?? []
        managedUpdates.append(manifestItemName)
        installInfo["managed_updates"] = managedUpdates
        _ = await processInstall(
            manifestItemName,
            catalogList: catalogList,
            installInfo: &installInfo,
            isManagedUpdate: true
        )
    } else {
        display.debug1("\(manifestItemName) does not appear to be installed, so no managed updates.")
    }
}

/// Process an optional install item to see if it should be added to
/// the list of optional installs
func processOptionalInstall(
    _ manifestItem: String,
    catalogList: [String],
    installInfo: inout PlistDict
) async {
    let manifestItemName = (manifestItem as NSString).lastPathComponent
    display.debug1("* Processing manifest item \(manifestItemName) for optional install")

    if alreadyProcessed(
        manifestItemName,
        installInfo: installInfo,
        sections: ["optional_installs", "processed_installs", "processed_uninstalls"]
    ) {
        return
    }

    var processedItem = PlistDict()
    var pkginfo = PlistDict()
    if let testPkginfo = await getItemDetail(
        manifestItemName,
        catalogList: catalogList,
        suppressWarnings: true
    ) {
        pkginfo = testPkginfo
    }

    if pkginfo.isEmpty,
       let show = boolPref("ShowOptionalInstallsForHigherOSVersions"),
       show == true
    {
        // could not find an item valid for the current OS and hardware
        // try again to see if there is an item for a higher OS
        if let testPkginfo = await getItemDetail(
            manifestItemName,
            catalogList: catalogList,
            skipMinimumOSCheck: true,
            suppressWarnings: true
        ) {
            pkginfo = testPkginfo
        }
        if !pkginfo.isEmpty {
            // found an item that requires a higher OS version
            let pkginfoName = pkginfo["name"] as? String ?? "<unknown>"
            let pkginfoVersion = pkginfo["version"] as? String ?? "<unknown>"
            display.debug1("Found \(pkginfoName), version \(pkginfoVersion) that requires a higher os version")
            // insert a note about the OS version requirement
            if let minimumOSVersion = pkginfo["minimum_os_version"] {
                processedItem["note"] = "Requires macOS version \(minimumOSVersion)."
            }
            processedItem["update_available"] = true
        }
    }
    if pkginfo.isEmpty {
        // could not find anything that matches and is applicable
        display.warning("Could not process item \(manifestItemName) for optional install. No pkginfo found in catalogs: \(catalogList)")
        return
    }

    let isCurrentlyInstalled = await someVersionInstalled(pkginfo)
    var needsUpdate = false
    if isCurrentlyInstalled {
        if shouldBeRemovedIfUnused(pkginfo) {
            _ = await processRemoval(manifestItemName, catalogList: catalogList, installInfo: &installInfo)
            removeFromSelfServeInstalls(manifestItemName)
            return
        }
        if pkginfo["installcheck_script"] == nil {
            // installcheck_scripts can be expensive and only tell us if
            // an item is installed or not. So if iteminfo['installed'] is
            // True, and we're using an installcheck_script,
            // installedState() is going to return 1
            // (which does not equal 0), so we can avoid running it again.
            // We should really revisit all of this in the future to avoid
            // repeated checks of the same data.
            // (installcheck_script isn't called if OnDemand is True, but if
            // OnDemand is true, is_currently_installed would be False, and
            // therefore we would not be here!)
            //
            // TL;DR: only check installed_state if no installcheck_script
            let installationState = await installedState(pkginfo)
            if let installerType = pkginfo["installer_type"] as? String,
               installerType == "stage_os_installer"
            {
                // .thisVersionInstalled means installer is staged, but not _installed_
                // (if it's installed, it will be .newerVersionInstalled
                needsUpdate = installationState != .newerVersionInstalled
            } else {
                needsUpdate = installationState == .thisVersionNotInstalled
            }
        }

        if !needsUpdate,
           let show = boolPref("ShowOptionalInstallsForHigherOSVersions"),
           show == true
        {
            // the version we have installed is the newest for the current OS.
            // check again to see if there is a newer version for a higher OS
            display.debug1("Checking for versions of \(manifestItemName) that require a higher OS version")
            if let anotherPkgInfo = await getItemDetail(
                manifestItemName,
                catalogList: catalogList,
                skipMinimumOSCheck: true,
                suppressWarnings: true
            ) {
                if !NSDictionary(dictionary: anotherPkgInfo).isEqual(to: NSDictionary(dictionary: pkginfo)) {
                    // we found a different item. Replace the one we found
                    // previously with this one.
                    pkginfo = anotherPkgInfo
                    let pkginfoName = pkginfo["name"] as? String ?? "<unknown>"
                    let pkginfoVersion = pkginfo["version"] as? String ?? "<unknown>"
                    display.debug1("Found \(pkginfoName), version \(pkginfoVersion) that requires a higher os version")
                    // insert a note about the OS version requirement
                    if let minimumOSVersion = pkginfo["minimum_os_version"] {
                        processedItem["note"] = "Requires macOS version \(minimumOSVersion)."
                    }
                    processedItem["update_available"] = true
                }
            }
        }
    }
    // if we get to this point we can add this item
    // to the list of optional installs
    processedItem["name"] = pkginfo["name"] as? String ?? manifestItemName
    processedItem["display_name"] = pkginfo["display_name"] ?? ""
    processedItem["description"] = pkginfo["description"] ?? ""
    processedItem["version_to_install"] = pkginfo["version"] ?? "UNKNOWN"
    processedItem["needs_update"] = needsUpdate
    for key in [
        "category",
        "developer",
        "featured",
        "icon_name",
        "icon_hash",
        "requires",
        "RestartAction",
    ] {
        processedItem[key] = pkginfo[key]
    }
    processedItem["installed"] = isCurrentlyInstalled
    processedItem["licensed_seat_info_available"] = pkginfo["licensed_seat_info_available"] as? Bool ?? false
    processedItem["uninstallable"] = (pkginfo["uninstallable"] as? Bool ?? false) && !(pkginfo["uninstall_method"] as? String ?? "").isEmpty
    // If the item is a precache item, record the precache flag
    // and also the installer item location (as long as item doesn't have a note
    // explaining why it's not available and as long as available seats is not 0)
    if let installerItemLocation = pkginfo["installer_item_location"] as? String,
       !installerItemLocation.isEmpty,
       pkginfo["precache"] as? Bool ?? false,
       pkginfo["note"] == nil,
       pkginfo["licensed_seats_available"] as? Bool ?? true
    {
        processedItem["precache"] = true
        for key in [
            "installer_item_location",
            "installer_item_hash",
            "PackageCompleteURL",
            "PackageURL",
        ] {
            processedItem[key] = pkginfo[key]
        }
    }
    let installerSize = pkginfo["installer_item_size"] as? Int ?? 0
    processedItem["installer_item_size"] = installerSize
    processedItem["installed_size"] = pkginfo["installed_size"] as? Int ?? installerSize
    if let pkgInfoNote = pkginfo["note"] as? String,
       processedItem["note"] == nil
    {
        processedItem["note"] = pkgInfoNote
    } else if needsUpdate || !isCurrentlyInstalled {
        if let installerType = pkginfo["installer_type"] as? String,
           installerType == "stage_os_installer",
           await installedState(pkginfo) == .thisVersionInstalled
        {
            // Install macOS app is already staged so there's nothing to download
        } else if !enoughDiskSpaceFor(
            pkginfo,
            installList: installInfo["managed_installs"] as? [PlistDict] ?? [],
            warn: false
        ) {
            processedItem["note"] = "Insufficient disk space to download and install."
            if needsUpdate {
                processedItem["needs_update"] = false
                processedItem["update_available"] = true
            }
        }
    }
    let optionalKeys = [
        "preinstall_alert",
        "preuninstall_alert",
        "preupgrade_alert",
        "OnDemand",
        "minimum_os_version",
        "update_available",
        "localized_strings",
    ]
    for key in optionalKeys {
        processedItem[key] = pkginfo[key]
    }
    let itemName = processedItem["name"] as? String ?? "<unknown>"
    display.debug1("Adding \(itemName) to the optional install list")
    var optionalInstalls = installInfo["optional_installs"] as? [PlistDict] ?? []
    optionalInstalls.append(processedItem)
    installInfo["optional_installs"] = optionalInstalls
}

/// Processes a manifest item; attempts to determine if it
/// needs to be removed, and if it can be removed.
///
/// Unlike installs, removals aren't really version-specific -
/// If we can figure out how to remove the currently installed
/// version, we do, unless the admin specifies a specific version
/// number in the manifest. In that case, we only attempt a
/// removal if the version installed matches the specific version
/// in the manifest.
///
/// Any items dependent on the given item need to be removed first.
/// Items to be removed are added to installinfo['removals'].
///
/// Calls itself recursively as it processes dependencies.
/// Returns a boolean; when processing dependencies, a false return
/// will stop the removal of a dependent item.
func processRemoval(
    _ manifestItem: String,
    catalogList: [String],
    installInfo: inout PlistDict
) async -> Bool {
    func getReceiptsToRemove(_ item: PlistDict) async -> [String] {
        /// Returns a list of (installed/present) receipts to remove for item
        if let name = item["name"] as? String {
            let pkgdata = await analyzeInstalledPkgs()
            if let receiptsForName = pkgdata["receipts_for_name"] as? [String: [String]] {
                return receiptsForName[name] ?? [String]()
            }
        }
        return [String]()
    }

    func appendToProcessedRemovals(_ item: PlistDict) {
        /// helper function
        var removals = installInfo["removals"] as? [PlistDict] ?? []
        removals.append(item)
        installInfo["removals"] = removals
    }

    let manifestItemNameWithVersion = (manifestItem as NSString).lastPathComponent
    display.debug1("* Processing manifest item \(manifestItemNameWithVersion) for removal")

    let (manifestItemName, manifestItemVersion) = nameAndVersion(manifestItemNameWithVersion, onlySplitOnHyphens: true)

    // have we processed this item already?
    let processedInstalls = installInfo["processed_installs"] as? [String] ?? []
    let processedInstallsNames = processedInstalls.map {
        nameAndVersion($0, onlySplitOnHyphens: true).0
    }
    if processedInstallsNames.contains(manifestItemName) {
        display.warning("Will not attempt to remove \(manifestItemName) because some version of it is in the list of managed installs, or it is required by another managed install.")
        return false
    }
    var processedUninstallsNames = installInfo["processed_uninstalls"] as? [String] ?? []
    if processedUninstallsNames.contains(manifestItemName) {
        display.debug1("\(manifestItemName) has already been processed for removal.")
        return true
    }
    processedUninstallsNames.append(manifestItemName)
    installInfo["processed_uninstalls"] = processedUninstallsNames

    var pkginfos = [PlistDict]()
    if !manifestItemVersion.isEmpty {
        // a specific version was specified
        if let pkginfo = await getItemDetail(manifestItemName, catalogList: catalogList, version: manifestItemVersion) {
            pkginfos.append(pkginfo)
        }
    } else {
        // get all items matching the name provided
        pkginfos = getAllItemsWithName(manifestItemName, catalogList: catalogList)
    }

    if pkginfos.isEmpty {
        display.warning("Could not process item \(manifestItemName) for removal. No pkginfo found in catalogs: \(catalogList)")
        return false
    }

    var installEvidence = false
    var foundItem = PlistDict()
    for pkginfo in pkginfos {
        let name = pkginfo["name"] as? String ?? "<unknown>"
        let version = pkginfo["version"] as? String ?? "<unknown>"
        display.debug2("Considering item \(name)-\(version) for removal info")
        if await evidenceThisIsInstalled(pkginfo) {
            installEvidence = true
            foundItem = pkginfo
            break
        }
        display.debug2("\(name)-\(version) is not installed")
    }

    if !installEvidence {
        display.detail("\(manifestItemNameWithVersion) doesn\'t appear to be installed.")
        var processedItem = PlistDict()
        processedItem["name"] = manifestItemName
        processedItem["installed"] = false
        appendToProcessedRemovals(processedItem)
        return true
    }

    // if we get here, installEvidence is true, and foundItem
    // holds the item we found install evidence for, so we
    // should use that item to do the removal
    var uninstallItem = PlistDict()
    var packagesToRemove = [String]()
    let foundItemName = foundItem["name"] as? String ?? "<unknown>"
    let foundItemVersion = foundItem["version"] as? String ?? "<unknown>"
    let uninstallable = foundItem["uninstallable"] as? Bool ?? false
    let uninstallMethod = foundItem["uninstall_method"] as? String ?? ""
    if !uninstallable {
        display.warning("Item \(foundItemName)-\(foundItemVersion) is not marked as uninstallable.")
    } else if uninstallMethod.isEmpty {
        display.warning("No uninstall_method in \(foundItemName)-\(foundItemVersion).")
    } else if uninstallMethod.hasPrefix("Adobe") {
        display.warning("Adobe-specific uninstall methods are no longer supported.")
    } else if ["remove_app", "remove_profile"].contains(uninstallMethod) {
        display.warning("Uninstall method \(uninstallMethod) is no longer supported.")
    } else if uninstallMethod == "removepackages" {
        packagesToRemove = await getReceiptsToRemove(foundItem)
        if !packagesToRemove.isEmpty {
            uninstallItem = foundItem
        } else {
            display.warning("uninstall_method for \(manifestItemNameWithVersion) is removepackages, but no packages found to remove")
        }
    } else if ["remove_copied_items", "uninstall_script", "uninstall_package"].contains(uninstallMethod) {
        uninstallItem = foundItem
    } else {
        // might be a path to a locally-installed script/executable
        if pathIsExecutableFile(uninstallMethod) {
            uninstallItem = foundItem
        } else {
            display.warning("Uninstall method \(uninstallMethod) is not a valid method.")
        }
    }

    if uninstallItem.isEmpty {
        // could not find usable uninstall_method
        return false
    }

    // if we got this far, we have enough info to attempt an uninstall.
    // the pkginfo is in uninstall_item
    // Now check for dependent items
    //
    // First, look through catalogs for items that are required by this item;
    // if any are installed, we need to remove them as well
    //
    // still not sure how to handle references to specific versions --
    // if another package says it requires SomePackage--1.0.0.0.0
    // and we're supposed to remove SomePackage--1.0.1.0.0... what do we do?
    var dependentItemsRemoved = true
    let uninstallItemName = uninstallItem["name"] as? String ?? "<unknown>"
    let uninstallItemVersion = uninstallItem["version"] as? String ?? "<unknown>"
    let uninstallItemNameWVersion = "\(uninstallItemName)-\(uninstallItemVersion)"
    let altUninstallItemNameWVersion = "\(uninstallItemName)--\(uninstallItemVersion)"
    var processedNames = [String]()
    for catalogName in catalogList {
        guard let catalogDB = Catalogs.shared.get(catalogName) else {
            // in case the list refers to a non-existent catalog
            continue
        }
        let catalogItems = catalogDB["items"] as? [PlistDict] ?? []
        for catalogItem in catalogItems {
            let name = catalogItem["name"] as? String ?? "<unknown>"
            if processedNames.contains(name) {
                // already added
                continue
            }
            guard let requires = catalogItem["requires"] as? [String] else {
                // no requires, so skip to next
                processedNames.append(name)
                continue
            }
            if requires.contains(uninstallItemName) ||
                requires.contains(uninstallItemNameWVersion) ||
                requires.contains(altUninstallItemNameWVersion)
            {
                display.debug1("\(name) requires \(manifestItemName), checking to see if it's installed...")
                if await evidenceThisIsInstalled(catalogItem) {
                    display.detail("\(name) requires \(manifestItemName). \(name) must be removed as well.")
                    let success = await processRemoval(
                        name, catalogList: catalogList, installInfo: &installInfo
                    )
                    if !success {
                        dependentItemsRemoved = false
                        break
                    }
                }
            }
            processedNames.append(name)
        }
    }
    if !dependentItemsRemoved {
        display.warning("Will not attempt to remove \(uninstallItemName) because could not remove all items dependent on it.")
        return false
    }

    // Finally! We can record the removal information!
    var processedItem = PlistDict()
    processedItem["name"] = uninstallItemName
    processedItem["display_name"] = uninstallItem["display_name"]
    processedItem["description"] = "Will be removed."

    // we will ignore the unattended_uninstall key if the item needs a restart
    // or logout...
    if (uninstallItem["unattended_uninstall"] as? Bool ?? false) || (uninstallItem["forced_uninstall"] as? Bool ?? false) {
        let restartAction = uninstallItem["RestartAction"] as? String ?? "None"
        if restartAction != "None" {
            display.warning("Ignoring unattended_uninstall key for \(uninstallItemName) because RestartAction is \(restartAction).")
        } else {
            processedItem["unattended_uninstall"] = true
        }
    }

    // some keys we'll copy if they exist
    let optionalKeys = [
        "RestartAction",
        "blocking_applications",
        "installs",
        "requires",
        "update_for",
        "payloads",
        "preuninstall_script",
        "postuninstall_script",
        "apple_item",
        "category",
        "developer",
        "icon_name",
        "PayloadIdentifier",
    ]
    for key in optionalKeys {
        processedItem[key] = uninstallItem[key]
    }

    if processedItem["apple_item"] == nil {
        // admin did not explicitly mark this item; let's determine if
        // it's from Apple
        if isAppleItem(uninstallItem) {
            munkiLog("Marking \(uninstallItemName) as an apple_item - this will block Apple SUS updates")
            processedItem["apple_item"] = true
        }
    }

    if !packagesToRemove.isEmpty {
        // remove references for each package
        var packagesToReallyRemove = [String]()
        let pkgdata = await analyzeInstalledPkgs()
        let pkgReferences = pkgdata["pkg_references"] as? [String: [String]] ?? [:]
        var pkgReferencesMessages = [String]()
        for pkg in packagesToRemove {
            display.debug1("Considering \(pkg) for removal...")
            // find pkg in pkgdata["pkg_references"] and remove the reference
            // so we only remove packages if we're the only reference to it
            // pkgdata["pkg_references"] is [String:[String]]
            guard let references = pkgReferences[pkg] else {
                // This shouldn't happen
                display.warning("pkg id \(pkg) missing from pkgdata")
                continue
            }
            let msg = "Package \(pkg) references are: \(references)"
            display.debug1(msg)
            pkgReferencesMessages.append(msg)
            if references.contains(uninstallItemName) {
                let filteredReferences = references.filter {
                    $0 != uninstallItemName
                }
                if filteredReferences.isEmpty {
                    // no other references than this item
                    display.debug1("Adding \(pkg) to removal list.")
                    packagesToReallyRemove.append(pkg)
                } else {
                    display.debug1("Will not attempt to remove \(pkg)")
                }
            }
        }
        if !packagesToReallyRemove.isEmpty {
            processedItem["packages"] = packagesToReallyRemove
        } else {
            // no packages that belong to this item only
            display.warning("could not find unique packages to remove for \(uninstallItemName)")
            for msg in pkgReferencesMessages {
                display.warning(msg)
            }
            return false
        }
    }
    processedItem["uninstall_method"] = uninstallMethod
    if uninstallMethod == "remove_copied_items" {
        if let itemsToCopy = uninstallItem["items_to_copy"] as? [PlistDict] {
            processedItem["items_to_remove"] = itemsToCopy
        } else {
            display.warning("Can't uninstall \(uninstallItemName) because there is no info on installed items.")
            return false
        }
    } else if uninstallMethod == "uninstall_script" {
        if let uninstallScript = uninstallItem["uninstall_script"] as? String {
            processedItem["uninstall_script"] = uninstallScript
        } else {
            display.warning("Can't uninstall \(uninstallItemName) because uninstall_script is undefined or invalid.")
            return false
        }
    } else if uninstallMethod == "uninstall_package" {
        if let location = uninstallItem["uninstaller_item_location"] as? String {
            do {
                _ = try downloadInstallerItem(
                    uninstallItem, installInfo: installInfo, uninstalling: true
                )
                processedItem["uninstaller_item"] = baseName(location)
            } catch FetchError.verification {
                display.warning("Can't uninstall \(uninstallItemName) because the integrity check for the uninstall package failed.")
                return false
            } catch {
                display.warning("Failed to download the uninstaller for \(uninstallItemName) because \(error.localizedDescription)")
                return false
            }
        } else {
            display.warning("Can't uninstall \(uninstallItemName) because there is no URL for the uninstall package.")
            return false
        }
    }
    // before we add this removal to the list,
    // check for installed updates and add them to the
    // removal list as well
    var updateList = lookForUpdatesFor(uninstallItemName, catalogList: catalogList)
    updateList += lookForUpdatesFor(uninstallItemNameWVersion, catalogList: catalogList)
    updateList += lookForUpdatesFor(altUninstallItemNameWVersion, catalogList: catalogList)
    updateList = Array(Set(updateList))
    for updateItem in updateList {
        // call us recursively
        _ = await processRemoval(
            updateItem, catalogList: catalogList, installInfo: &installInfo
        )
    }

    // finish recording info for this removal
    processedItem["installed"] = true
    processedItem["installed_version"] = uninstallItemVersion
    appendToProcessedRemovals(processedItem)
    display.detail("Removal of \(manifestItemNameWithVersion) added to managedsoftwareupdate tasks.")
    return true
}
