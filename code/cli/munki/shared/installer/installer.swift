//
//  installer.swift
//  munki
//
//  Created by Greg Neagle on 8/5/24.
//  Copyright 2024-2026 The Munki Project.
//

import Foundation

private let display = DisplayAndLog.main

/// Removes filesystem items based on info in itemlist.
/// These items were typically installed via copy_from_dmg
/// This current aborts and returns false on the first error;
/// might it make sense to try to continue and remove as much as we can?
func removeCopiedItems(_ itemList: [PlistDict]) -> Bool {
    if itemList.isEmpty {
        display.error("Nothing to remove!")
        return false
    }
    for item in itemList {
        var itemName = ""
        var destinationPath = ""
        if let destinationItem = item["destination_item"] as? String {
            itemName = (destinationItem as NSString).lastPathComponent
            destinationPath = (destinationItem as NSString).deletingLastPathComponent
        } else {
            itemName = item["source_item"] as? String ?? ""
            itemName = (itemName as NSString).lastPathComponent
        }
        if itemName.isEmpty {
            display.error("Missing item name to remove.")
            return false
        }
        if destinationPath.isEmpty,
           let providedDestinationPath = item["destination_path"] as? String
        {
            destinationPath = providedDestinationPath
        }
        if destinationPath.isEmpty {
            display.error("Missing path for item to remove.")
            return false
        }
        let pathToRemove = (destinationPath as NSString).appendingPathComponent(itemName)
        if pathExists(pathToRemove) {
            display.minorStatus("Removing \(pathToRemove)")
            do {
                try FileManager.default.removeItem(atPath: pathToRemove)
            } catch let err as NSError {
                display.error("Removal error for \(pathToRemove): \(err.localizedDescription)")
                return false
            } catch {
                display.error("Removal error for \(pathToRemove): \(error)")
                return false
            }
        } else {
            // pathToRemove doesn't exist. note it, but not an error
            display.detail("Path \(pathToRemove) doesn't exist.")
        }
    }
    display.minorStatus("The software was successfully removed.")
    return true
}

/// Looks for item prerequisites (requires and update_for) in the list of skipped items.
/// Returns a list of matches.
func itemPrereqsInSkippedItems(currentItem: PlistDict, skippedItems: [PlistDict]) -> [String] {
    var matchedPrereqs = [String]()
    if skippedItems.isEmpty {
        return matchedPrereqs
    }
    let name = currentItem["name"] as? String ?? ""
    let version = currentItem["version"] as? String ?? ""
    display.debug1("Checking for skipped prerequisites for \(name)-\(version)")

    // get list of prerequisites for this item
    var prerequisites = currentItem["requires"] as? [String] ?? [String]()
    prerequisites += currentItem["update_for"] as? [String] ?? [String]()
    if prerequisites.isEmpty {
        display.debug1("\(name)-\(version) has no prerequisites.")
        return matchedPrereqs
    }
    display.debug1("Prerequisites: \(prerequisites.joined(separator: ", "))")

    // build a dictionary of names and versions of skipped items
    var skippedItemDict = PlistDict()
    for item in skippedItems {
        if let name = item["name"] as? String {
            let version = item["version_to_install"] as? String ?? "0.0"
            let normalizedVersion = trimVersionString(version)
            display.debug1("Adding skipped item: \(name)-\(normalizedVersion)")
            var versions = skippedItemDict[name] as? [String] ?? [String]()
            versions.append(normalizedVersion)
            skippedItemDict[name] = versions
        }
    }

    // now check prereqs against the skipped items
    for prereq in prerequisites {
        let (pName, pVersion) = nameAndVersion(prereq, onlySplitOnHyphens: true)
        display.debug1("Comparing \(pName)-\(pVersion) against skipped items")
        if let versionsForMatchedName = skippedItemDict[pName] as? [String] {
            if !pVersion.isEmpty {
                let trimmedVersion = trimVersionString(pVersion)
                if versionsForMatchedName.contains(trimmedVersion) {
                    matchedPrereqs.append(prereq)
                }
            } else {
                matchedPrereqs.append(prereq)
            }
        }
    }
    return matchedPrereqs
}

/// Returns boolean to indicate if the item needs a restart
func requiresRestart(_ item: PlistDict) -> Bool {
    let restartAction = item["RestartAction"] as? String ?? ""
    return ["RequireRestart", "RecommendRestart"].contains(restartAction)
}

/// Process an Apple package for install. Returns retcode, needs_restart
func handleApplePackageInstall(pkginfo: PlistDict, itemPath: String) async -> (Int, Bool) {
    if pkginfo["suppress_bundle_relocation"] as? Bool ?? false {
        display.warning("Item has 'suppress_bundle_relocation' attribute. This feature is no longer supported.")
    }
    if hasValidDiskImageExt(itemPath) {
        let dmgName = (itemPath as NSString).lastPathComponent
        display.minorStatus("Mounting disk image \(dmgName)")
        guard let mountpoint = try? mountdmg(itemPath, skipVerification: true) else {
            let dmgPath = pkginfo["installer_item"] as? String ?? dmgName
            display.error("Could not mount disk image file \(dmgPath)")
            return (-99, false)
        }
        defer {
            do {
                try unmountdmg(mountpoint)
            } catch {
                display.error(error.localizedDescription)
            }
        }

        if let pkgPath = pkginfo["package_path"] as? String,
           hasValidPackageExt(pkgPath)
        {
            // admin has specified the relative path of the pkg on the DMG
            // this is useful if there is more than one pkg on the DMG,
            // or the actual pkg is not at the root of the DMG
            let fullPkgPath = (mountpoint as NSString).appendingPathComponent(pkgPath)
            if pathExists(fullPkgPath) {
                let (retcode, needToRestart) = await install(fullPkgPath, options: pkginfo)
                return (retcode, needToRestart || requiresRestart(pkginfo))
            } else {
                display.error("Did not find \(pkgPath) on disk image \(dmgName)")
                return (-99, false)
            }
        } else {
            // no relative path to pkg on dmg, so just install first
            // pkg found at the root of the mountpoint
            // (hopefully there's only one)
            let (retcode, needToRestart) = await installFromDirectory(mountpoint, options: pkginfo)
            return (retcode, needToRestart || requiresRestart(pkginfo))
        }
    } else if hasValidPackageExt(itemPath) {
        let (retcode, needToRestart) = await install(itemPath, options: pkginfo)
        return (retcode, needToRestart || requiresRestart(pkginfo))
    }
    // we didn't find anything we know how to install
    munkiLog("Found nothing we know how to install in \(itemPath)")
    return (-99, false)
}

/// Attempt to install a single item from the installList
/// Returns an exitcode for the attempted install and a flag to indicate the need to restart
func installItem(_ item: PlistDict) async -> (Int, Bool) {
    var needToRestart = false
    let itemName = item["name"] as? String ?? "<unknown>"
    let installerType = item["installer_type"] as? String ?? "pkg_install"
    let installerItem = item["installer_item"] as? String ?? ""
    let cachePath = managedInstallsDir(subpath: "Cache")
    let installerItemPath = (cachePath as NSString).appendingPathComponent(installerItem)

    // if installer_type is not nopkg, ensure the payload exists
    if installerType != "nopkg" {
        if installerItem.isEmpty {
            display.error("Item \(installerItem) has no defined installer_item. Skipping.")
            return (-99, false)
        }
        if !pathExists(installerItemPath) {
            // can't install, so we should stop. Since later items might
            // depend on this one, we shouldn't continue
            display.error("Installer item \(installerItem) was not found. Skipping.")
            return (-99, false)
        }
    }

    if item["preinstall_script"] is String {
        let retcode = await runEmbeddedScript(name: "preinstall_script", pkginfo: item)
        if retcode != 0 {
            // if preinstall_script fails, do not proceed
            return (retcode, false)
        }
    }

    var retcode = 0
    switch installerType {
    case "pkg_install":
        (retcode, needToRestart) = await handleApplePackageInstall(pkginfo: item, itemPath: installerItemPath)
    case "copy_from_dmg":
        if let itemList = item["items_to_copy"] as? [PlistDict] {
            retcode = await copyFromDmg(dmgPath: installerItemPath, itemList: itemList)
            if retcode == 0, requiresRestart(item) {
                needToRestart = true
            }
        }
    case "stage_os_installer":
        if let itemList = item["items_to_copy"] as? [PlistDict] {
            retcode = await copyFromDmg(dmgPath: installerItemPath, itemList: itemList)
            if retcode == 0 {
                recordStagedOSInstaller(item)
            }
        }
    case "nopkg":
        needToRestart = requiresRestart(item)
    default:
        // unknown or no longer supported installer type
        if ["appdmg", "apple_update_metadata", "startosinstall", "profile"].contains(installerType) ||
            installerType.hasPrefix("Adobe")
        {
            display.error("Installer type '\(installerType)' for \(installerItem) is no longer supported.")
        } else {
            display.error("Installer type '\(installerType)' for \(installerItem) is an unknown installer type.")
        }
        retcode = -99
    }

    // if install succeeded, look for a postinstall_script to run
    if retcode == 0, item["postinstall_script"] is String {
        let scriptexit = await runEmbeddedScript(name: "postinstall_script", pkginfo: item)
        if scriptexit != 0 {
            // we won't consider postinstall script failures as fatal
            // since the item has been installed via package/disk image
            // but admin should be notified
            display.warning("Postinstall script for \(itemName) returned \(scriptexit)")
        }
    }
    return (retcode, needToRestart)
}

/// Uses the installInfo installs list to install items in the correct order and with additional options
func installWithInstallInfo(
    installList: [PlistDict], onlyUnattended: Bool = false
) async -> (Bool, [PlistDict]) {
    var restartFlag = false
    var itemIndex = 0
    var skippedInstalls = [PlistDict]()
    for item in installList {
        if stopRequested() {
            return (restartFlag, skippedInstalls)
        }
        // Keep track of when this particular install started.
        let startTime = Date()
        itemIndex += 1
        let itemName = item["name"] as? String ?? "<unknown>"
        let displayName = item["display_name"] as? String ?? itemName
        let versionToInstall = item["version_to_install"] as? String ?? ""
        let installerType = item["installer_type"] as? String ?? "pkg_install"

        if installerType == "startosinstall" {
            skippedInstalls.append(item)
            display.debug1("Skipping install of \(itemName) because it's a startosinstall item, which is no longer supported.")
            continue
        }
        if onlyUnattended {
            let unattendedInstall = item["unattended_install"] as? Bool ?? false
            if !unattendedInstall {
                skippedInstalls.append(item)
                display.detail("Skipping install of \(itemName) because it's not unattended, and we can only do unattended installs at this time.")
                continue
            }
            if blockingApplicationsRunning(item) {
                skippedInstalls.append(item)
                display.detail("Skipping unattended install of \(itemName) because blocking applications are running.")
                continue
            }
        }

        let skippedPrereqs = itemPrereqsInSkippedItems(currentItem: item, skippedItems: skippedInstalls)
        if !skippedPrereqs.isEmpty {
            // one or more prerequisite for this item was skipped or failed;
            // need to skip this item too
            skippedInstalls.append(item)
            var skipActionText = "not installed"
            if onlyUnattended {
                skipActionText = "skipped"
            }
            display.detail("Skipping unattended install of \(itemName) because these prerequisites were \(skipActionText): \(skippedPrereqs.joined(separator: ", "))")
            continue
        }

        // Attempt actual install
        display.majorStatus("Installing \(displayName) (\(itemIndex) of \(installList.count))")
        let (retcode, restartNeededForThisItem) = await installItem(item)
        restartFlag = restartFlag || restartNeededForThisItem

        // if install was successful and this is a SelfService OnDemand install
        // remove the item from the SelfServeManifest's managed_installs
        if retcode == 0,
           item["OnDemand"] as? Bool ?? false
        {
            removeFromSelfServeInstalls(itemName)
        }

        // log install success/failure
        var logMessage = "Install of \(displayName)-\(versionToInstall): "
        if retcode == 0 {
            logMessage += "SUCCESSFUL"
        } else {
            // if we failed, add to skippedInstalls since later items might rely on this
            skippedInstalls.append(item)
            logMessage += "FAILED with return code: \(retcode)"
        }
        munkiLog(logMessage, logFile: "Install.log")

        // Calculate install duration; note, if a machine is put to sleep
        // during the install this time may be inaccurate.
        let installDuration = Int(Date().timeIntervalSince(startTime))
        let downloadSpeed = item["download_kbytes_per_sec"] as? Int ?? 0
        // add install result to report object
        let installResult: PlistDict = [
            "display_name": displayName,
            "name": item["name"] as? String ?? "<unknown>",
            "version": versionToInstall,
            "applesus": false,
            "status": retcode,
            "time": Date(),
            "duration_seconds": installDuration,
            "download_kbytes_per_sec": downloadSpeed,
            "unattended": onlyUnattended,
        ]
        Report.shared.add(dict: installResult, to: "InstallResults")

        // check to see if this installer item is needed by any additional
        // items in installinfo
        // this might happen if there are multiple things being installed
        // with choicesXML files applied to a distribution package or
        // multiple packages being installed from a single DMG
        let installerItem = item["installer_item"] as? String ?? ""
        let cachePath = managedInstallsDir(subpath: "Cache")
        let installerItemPath = (cachePath as NSString).appendingPathComponent(installerItem)

        var stillNeeded = false
        let currentInstallerItem = installerItem
        // are we at the end of the installlist?
        // (we already incremented itemindex for display
        // so with zero-based arrays itemindex now points to the item
        // after the current item)
        if itemIndex < installList.count {
            // there are remaining items, let's check them
            for laterItem in installList[itemIndex...] {
                let laterInstallerItem = laterItem["installer_item"] as? String ?? ""
                if laterInstallerItem == currentInstallerItem {
                    stillNeeded = true
                    break
                }
            }
        }

        // need to check skipped_installs as well
        if !stillNeeded {
            for skippedItem in skippedInstalls {
                let skippedInstallerItem = skippedItem["installer_item"] as? String ?? ""
                if skippedInstallerItem == currentInstallerItem {
                    stillNeeded = true
                    break
                }
            }
        }

        // check to see if the item is both precache and OnDemand
        let precache = item["precache"] as? Bool ?? false
        let onDemand = item["OnDemand"] as? Bool ?? false
        if !stillNeeded, precache, onDemand {
            // keep precached OnDemand items in the cache indefinitely
            stillNeeded = true
        }

        // cleanup unneeded install_items
        if !stillNeeded, retcode == 0 {
            // remove the item from the install cache
            // (if it's still there)
            if pathExists(installerItemPath) {
                try? FileManager.default.removeItem(atPath: installerItemPath)
                if hasValidDiskImageExt(installerItemPath) {
                    let shadowFile = installerItemPath + ".shadow"
                    if pathExists(shadowFile) {
                        try? FileManager.default.removeItem(atPath: shadowFile)
                    }
                }
            }
        }
    }
    return (restartFlag, skippedInstalls)
}

/// Looks for items in the skipped_items that require or are update_for
/// the current item. Returns a list of matches.
func skippedItemsThatRequire(_ thisItem: PlistDict, skippedItems: [PlistDict]) -> [String] {
    var matchedSkippedItems = [String]()
    if skippedItems.isEmpty {
        return matchedSkippedItems
    }
    let thisItemName = thisItem["name"] as? String ?? "<unknown>"
    display.debug1("Checking for skipped items that require \(thisItemName)")
    for skippedItem in skippedItems {
        // get list of prerequisites for this skipped_item
        var prerequisites = skippedItem["requires"] as? [String] ?? [String]()
        prerequisites += skippedItem["update_for"] as? [String] ?? [String]()
        let skippedItemName = skippedItem["name"] as? String ?? "<unknown>"
        display.debug1("\(skippedItemName) has these prerequisites: \(prerequisites.joined(separator: ", "))")
        for prereq in prerequisites {
            let (prereqName, _) = nameAndVersion(prereq, onlySplitOnHyphens: true)
            if prereqName == thisItemName {
                matchedSkippedItems.append(skippedItemName)
            }
        }
    }
    return matchedSkippedItems
}

/// Attempts to uninstall a single item from the removalList
/// returns an exitcode for the attempted install and a flag to indicate the need to restart
func uninstallItem(_ item: PlistDict) async -> (Int, Bool) {
    var needToRestart = false
    let itemName = item["display_name"] as? String ?? "<unknown>"
    let displayName = item["display_name"] as? String ?? itemName

    // run preuninstall_script if it exists
    if item["preuninstall_script"] is String {
        let retcode = await runEmbeddedScript(name: "preuninstall_script", pkginfo: item)
        if retcode != 0 {
            // if preuninstall_script fails, do not proceed
            return (retcode, false)
        }
    }

    guard let uninstallMethod = item["uninstall_method"] as? String else {
        display.error("\(itemName) has no defined uninstall_method")
        return (-99, false)
    }

    var retcode = 0
    switch uninstallMethod {
    case "removepackages":
        if let packages = item["packages"] as? [String] {
            retcode = await removePackages(packages)
            if retcode == 0 {
                munkiLog("Uninstall of \(displayName) was successful.")
            } else if retcode == -128 {
                display.error("Uninstall of \(displayName) was cancelled.")
                return (retcode, false)
            } else {
                display.error("Uninstall of \(displayName) failed.")
                return (retcode, false)
            }
        } else {
            // error! no packages defined
            display.error("Uninstall of \(displayName) failed: no packages to remove.")
            return (-99, false)
        }
    case "uninstall_package":
        // install a package to remove the software
        guard let uninstallerItem = item["uninstaller_item"] as? String else {
            display.error("No uninstall item specified for \(itemName)")
            return (-99, false)
        }
        let uninstallerItemPath = managedInstallsDir(subpath: "Cache/" + uninstallerItem)
        if !pathExists(uninstallerItemPath) {
            display.error("Uninstall package \(uninstallerItem) for \(itemName) was missing from the cache.")
            return (-99, false)
        }
        (retcode, needToRestart) = await handleApplePackageInstall(pkginfo: item, itemPath: uninstallerItemPath)
    case "remove_copied_items":
        if let itemsToRemove = item["items_to_remove"] as? [PlistDict] {
            if !removeCopiedItems(itemsToRemove) {
                return (-99, false)
            }
        } else {
            display.error("No valid 'items_to_remove' in pkginfo for \(itemName)")
            return (-99, false)
        }
    case "uninstall_script":
        retcode = await runEmbeddedScript(name: "uninstall_script", pkginfo: item)
    default:
        if pathExists(uninstallMethod) {
            // it's a script or program to uninstall
            retcode = await runScript(uninstallMethod, itemName: itemName, scriptName: "uninstall script")
        } else if ["remove_app", "remove_profile"].contains(uninstallMethod) || uninstallMethod.hasPrefix("Adobe") {
            display.error("'\(uninstallMethod)' is no longer a supported uninstall method")
            return (-99, false)
        } else {
            display.error("'\(uninstallMethod)' is not a valid uninstall method")
            return (-99, false)
        }
    }

    // run postuninstall_script if present and main uninstall_method was successful
    if retcode == 0, item["postuninstall_script"] is String {
        let result = await runEmbeddedScript(name: "postuninstall_script", pkginfo: item)
        if result != 0 {
            // we won't consider postuninstall script failures as fatal
            // since the item has been uninstalled
            // but admin should be notified
            display.warning("Postuninstall script for \(itemName) returned \(result)")
        }
    }
    return (retcode, needToRestart)
}

/// Processes removals from the removal list
func processRemovals(_ removalList: [PlistDict], onlyUnattended: Bool = false) async -> (Bool, [PlistDict]) {
    var restartFlag = false
    var index = 0
    var skippedRemovals = [PlistDict]()

    for item in removalList {
        let itemName = item["name"] as? String ?? "<unknown>"
        let displayName = item["display_name"] as? String ?? itemName
        index += 1

        if onlyUnattended {
            let unattendedUninstall = item["unattended_uninstall"] as? Bool ?? false
            if !unattendedUninstall {
                skippedRemovals.append(item)
                display.detail("Skipping removal of \(itemName) because it's not unattended.")
                continue
            }
            if blockingApplicationsRunning(item) {
                skippedRemovals.append(item)
                display.detail("Skipping unattended removal of \(itemName) because blocking applications are running.")
                continue
            }
        }
        let dependentSkippedItems = skippedItemsThatRequire(item, skippedItems: skippedRemovals)
        if !dependentSkippedItems.isEmpty {
            // one or more skipped items require this item, so we should
            // skip this one, too
            skippedRemovals.append(item)
            display.detail("Skipping removal of \(itemName) because these skipped items require it: \(dependentSkippedItems.joined(separator: ", "))")
            continue
        }
        if stopRequested() {
            return (restartFlag, skippedRemovals)
        }

        if (item["installed"] as? Bool ?? false) == false {
            // not installed, so skip it (this shouldn't happen...)
            display.detail("Skipping removal of \(itemName) because does not seem to be installed.")
            continue
        }

        // now actually attempt to uninstall the item!
        display.majorStatus("Removing \(displayName) (\(index) of \(removalList.count))")
        let (retcode, restartForThisItem) = await uninstallItem(item)
        restartFlag = restartFlag || restartForThisItem

        // log removal success/failure
        if retcode == 0 {
            munkiLog("Removal of \(displayName): SUCCESSFUL", logFile: "Install.log")
            removeFromSelfServeUninstalls(itemName)
        } else {
            munkiLog("Removal of \(displayName): FAILED with return code: \(retcode)", logFile: "Install.log")
            // append failed removal to skipped_removals so dependencies
            // aren't removed yet.
            skippedRemovals.append(item)
        }
        let removalResult: PlistDict = [
            "display_name": displayName,
            "name": itemName,
            "status": retcode,
            "time": Date(),
            "unattended": onlyUnattended,
        ]
        Report.shared.add(dict: removalResult, to: "RemovalResults")
    }
    return (restartFlag, skippedRemovals)
}

/// Runs the install/removal session.
///
/// Args:
/// only_unattended: Boolean. If True, only do unattended_(un)install pkgs.
func doInstallsAndRemovals(onlyUnattended: Bool = false) async -> PostAction {
    var removalsNeedRestart = false
    var installsNeedRestart = false

    if onlyUnattended {
        munkiLog("### Beginning unattended installer session ###")
    } else {
        munkiLog("### Beginning managed installer session ###")
    }

    // no sleep assertion
    let caffeinator = Caffeinator(
        reason: "managedsoftwareupdate is installing software")

    let installInfoPath = managedInstallsDir(subpath: "InstallInfo.plist")
    if pathExists(installInfoPath),
       let installInfo = try? readPlist(fromFile: installInfoPath) as? PlistDict
    {
        var updatedInstallInfo = installInfo
        if pref("SuppressStopButtonOnInstall") as? Bool ?? false {
            munkiStatusHideStopButton()
        }
        // process removals
        if let removals = installInfo["removals"] as? [PlistDict] {
            // filter list to items that need to be removed
            let removalList = removals.filter {
                $0["installed"] as? Bool ?? false
            }
            Report.shared.record(removalList, to: "ItemsToRemove")
            if !removalList.isEmpty {
                if removalList.count == 1 {
                    munkiStatusMessage("Removing 1 item...")
                } else {
                    munkiStatusMessage("Removing \(removalList.count) items...")
                }
                munkiStatusDetail("")
                // set indeterminate progress bar
                munkiStatusPercent(-1)
                munkiLog("Processing removals")
                var skippedRemovals = [PlistDict]()
                (removalsNeedRestart, skippedRemovals) = await processRemovals(
                    removalList, onlyUnattended: onlyUnattended
                )
                // if any removals were skipped, record them for later
                updatedInstallInfo["removals"] = skippedRemovals
            }
        }
        // process installs
        if let managedInstalls = installInfo["managed_installs"] as? [PlistDict] {
            // filter list to items that need to be installed
            let installList = managedInstalls.filter {
                !($0["installed"] as? Bool ?? false)
            }
            Report.shared.record(installList, to: "ItemsToInstall")
            if !installList.isEmpty {
                if installList.count == 1 {
                    munkiStatusMessage("Installing 1 item...")
                } else {
                    munkiStatusMessage("Installing \(installList.count) items...")
                }
                munkiStatusDetail("")
                munkiLog("Processing installs")
                var skippedInstalls = [PlistDict]()
                (installsNeedRestart, skippedInstalls) = await installWithInstallInfo(
                    installList: installList, onlyUnattended: onlyUnattended
                )
                // if any installs were skipped record them for later
                updatedInstallInfo["managed_installs"] = skippedInstalls
            }
        }
        // update optional_installs with new installation/removal status
        // this is janky because it relies on stuff being recorded to the report
        var optionalInstalls = installInfo["optional_installs"] as? [PlistDict] ?? [PlistDict]()
        if !optionalInstalls.isEmpty {
            if let removalResults = Report.shared.retrieve(key: "RemovalResults") as? [PlistDict] {
                for (index, optionalInstall) in optionalInstalls.enumerated() {
                    let optionalInstallName = optionalInstall["name"] as? String ?? "<unknown>"
                    for removal in removalResults {
                        let removalName = removal["name"] as? String ?? "<unknown>"
                        if optionalInstallName == removalName {
                            // this optional install may have just been removed
                            if (removal["status"] as? Int ?? 0) != 0 {
                                // a removal error occurred
                                optionalInstalls[index]["removal_error"] = true
                                optionalInstalls[index]["will_be_removed"] = false
                            } else {
                                // was just removed
                                optionalInstalls[index]["installed"] = false
                                optionalInstalls[index]["will_be_removed"] = false
                            }
                        }
                    }
                }
            }
            if let installResults = Report.shared.retrieve(key: "InstallResults") as? [PlistDict] {
                for (index, optionalInstall) in optionalInstalls.enumerated() {
                    let optionalInstallName = optionalInstall["name"] as? String ?? "<unknown>"
                    let optionalInstallVersion = optionalInstall["version_to_install"] as? String ?? ""
                    for install in installResults {
                        let installName = install["name"] as? String ?? "<unknown>"
                        let installVersion = install["version"] as? String ?? "0"
                        if optionalInstallName == installName,
                           optionalInstallVersion == installVersion
                        {
                            // this optional install may have just been installed
                            if (install["status"] as? Int ?? 0) != 0 {
                                optionalInstalls[index]["install_error"] = true
                                optionalInstalls[index]["will_be_installed"] = false
                            } else if optionalInstall["OnDemand"] as? Bool ?? false {
                                optionalInstalls[index]["installed"] = false
                                optionalInstalls[index]["needs_update"] = false
                                optionalInstalls[index]["will_be_installed"] = false
                            } else {
                                optionalInstalls[index]["installed"] = true
                                optionalInstalls[index]["needs_update"] = false
                                optionalInstalls[index]["will_be_installed"] = false
                            }
                        }
                    }
                }
            }
            updatedInstallInfo["optional_installs"] = optionalInstalls
        }
        // write updated installinfo back to disk to reflect current state
        do {
            try writePlist(updatedInstallInfo, toFile: installInfoPath)
        } catch {
            display.warning("Could not write to \(installInfoPath)")
        }
    } else {
        munkiLog("Missing or invalid \(installInfoPath).")
    }
    if onlyUnattended {
        munkiLog("###    End unattended installer session    ###")
    } else {
        munkiLog("###    End managed installer session    ###")
    }
    Report.shared.save()

    if removalsNeedRestart || installsNeedRestart {
        return .restart
    }
    return .none
}
