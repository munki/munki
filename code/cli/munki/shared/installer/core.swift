//
//  core.swift
//  munki
//
//  Created by Greg Neagle on 8/5/24.
//

import Foundation

func removeCopiedItems(_ itemList: [PlistDict]) -> Bool {
    // Removes filesystem items based on info in itemlist.
    // These items were typically installed via copy_from_dmg
    // This current aborts and returns false on the first error;
    // might it make sense to try to continue and remove as much
    // as we can?
    if itemList.isEmpty {
        displayError("Nothing to remove!")
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
            displayError("Missing item name to remove.")
            return false
        }
        if destinationPath.isEmpty,
           let providedDestinationPath = item["destination_path"] as? String
        {
            destinationPath = providedDestinationPath
        }
        if destinationPath.isEmpty {
            displayError("Missing path for item to remove.")
            return false
        }
        let pathToRemove = (destinationPath as NSString).appendingPathComponent(itemName)
        if pathExists(pathToRemove) {
            displayMinorStatus("Removing \(pathToRemove)")
            do {
                try FileManager.default.removeItem(atPath: pathToRemove)
            } catch let err as NSError {
                displayError("Removal error for \(pathToRemove): \(err.localizedDescription)")
                return false
            } catch {
                displayError("Removal error for \(pathToRemove): \(error)")
                return false
            }
        } else {
            // pathToRemove doesn't exist. note it, but not an error
            displayDetail("Path \(pathToRemove) doesn't exist.")
        }
    }
    return true
}

func itemPrereqsInSkippedItems(currentItem: PlistDict, skippedItems: [PlistDict]) -> [String] {
    // Looks for item prerequisites (requires and update_for) in the list
    // of skipped items. Returns a list of matches.
    var matchedPrereqs = [String]()
    if skippedItems.isEmpty {
        return matchedPrereqs
    }
    let name = currentItem["name"] as? String ?? ""
    let version = currentItem["version"] as? String ?? ""
    displayDebug1("Checking for skipped prerequisites for \(name)-\(version)")

    // get list of prerequisites for this item
    var prerequisites = currentItem["requires"] as? [String] ?? [String]()
    prerequisites += currentItem["update_for"] as? [String] ?? [String]()
    if prerequisites.isEmpty {
        displayDebug1("\(name)-\(version) has no prerequisites.")
        return matchedPrereqs
    }
    displayDebug1("Prerequisites: \(prerequisites.joined(separator: ", "))")

    // build a dictionary of names and versions of skipped items
    var skippedItemDict = PlistDict()
    for item in skippedItems {
        if let name = item["name"] as? String {
            let version = item["version_to_install"] as? String ?? "0.0"
            let normalizedVersion = trimVersionString(version)
            displayDebug1("Adding skipped item: \(name)-\(normalizedVersion)")
            var versions = skippedItemDict[name] as? [String] ?? [String]()
            versions.append(normalizedVersion)
            skippedItemDict[name] = versions
        }
    }

    // now check prereqs against the skipped items
    for prereq in prerequisites {
        let (pName, pVersion) = nameAndVersion(prereq, onlySplitOnHyphens: true)
        displayDebug1("Comparing \(pName)-\(pVersion) against skipped items")
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

func requiresRestart(_ item: PlistDict) -> Bool {
    // Returns boolean to indicate if the item needs a restart
    let restartAction = item["RestartAction"] as? String ?? ""
    return ["RequireRestart", "RecommendRestart"].contains(restartAction)
}

func handleApplePackageInstall(pkginfo: PlistDict, itemPath: String) async -> (Int, Bool) {
    // Process an Apple package for install. Returns retcode, needs_restart
    if let suppressBundleRelocation = pkginfo["suppress_bundle_relocation"] as? Bool {
        displayWarning("Item has 'suppress_bundle_relocation' attribute. This feature is no longer supported.")
    }
    if hasValidDiskImageExt(itemPath) {
        let dmgName = (itemPath as NSString).lastPathComponent
        displayMinorStatus("Mounting disk image \(dmgName)")
        guard let mountpoint = try? mountdmg(itemPath, skipVerification: true) else {
            let dmgPath = pkginfo["installer_item"] as? String ?? dmgName
            displayError("Could not mount disk image file \(dmgPath)")
            return (-99, false)
        }
        defer { unmountdmg(mountpoint) }

        if let pkgPath = pkginfo["package_path"] as? String,
           hasValidPackageExt(pkgPath)
        {
            // admin has specified the relative path of the pkg on the DMG
            // this is useful if there is more than one pkg on the DMG,
            // or the actual pkg is not at the root of the DMG
            let fullPkgPath = (mountpoint as NSString).appendingPathComponent(pkgPath)
            if pathExists(fullPkgPath) {
                let (retcode, needToRestart) = await install(pkgPath, options: pkginfo)
                return (retcode, needToRestart || requiresRestart(pkginfo))
            } else {
                displayError("Did not find \(pkgPath) on disk image \(dmgName)")
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

// TODO: break this long confusing function up
func installWithInstallInfo(
    cachePath: String,
    installList: [PlistDict],
    onlyUnattended: Bool = false
) async -> (Bool, [PlistDict]) {
    // Uses the installInfo installs list to install items in the
    // correct order and with additional options

    var restartFlag = false
    var itemIndex = 0
    var skippedInstalls = [PlistDict]()
    for item in installList {
        // Keep track of when this particular install started.
        let startTime = Date()
        itemIndex += 1
        let installerType = item["installer_type"] as? String ?? "pkg_install"
        let itemName = item["name"] as? String ?? "<unknown>"
        if installerType == "startosinstall" {
            skippedInstalls.append(item)
            displayDebug1("Skipping install of \(itemName) because it's a startosinstall item. Will install later.")
            continue
        }
        if onlyUnattended {
            let unattendedInstall = item["unattended_install"] as? Bool ?? false
            if !unattendedInstall {
                skippedInstalls.append(item)
                displayDetail("Skipping install of \(itemName) because it's not unattended, and we can only do unattended installs at this time.")
                continue
            }
            if blockingApplicationsRunning(item) {
                skippedInstalls.append(item)
                displayDetail("Skipping unattended install of \(itemName) because blocking applications are running.")
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
            displayDetail("Skipping unattended install of \(itemName) because these prerequisites were \(skipActionText): \(skippedPrereqs.joined(separator: ", "))")
            continue
        }

        // TODO: implement processes.stop_requested()
        // return (restartflag, skipped_installs)

        let displayName = item["display_name"] as? String ?? item["name"] as? String ?? "<unknown>"
        let versionToInstall = item["version_to_install"] as? String ?? ""
        let installerItem = item["installer_item"] as? String ?? ""
        let installerItemPath = (cachePath as NSString).appendingPathComponent(installerItem)
        displayMajorStatus("Installing \(displayName) (\(itemIndex) of \(installList.count))")

        var retcode = 0
        if item["preinstall_script"] is String {
            retcode = await runEmbeddedScript(name: "preinstall_script", pkginfo: item)
        }

        if retcode == 0 {
            if installerType != "nopkg" {
                if installerItem.isEmpty {
                    displayError("Item \(installerItem) has no defined installer_item. Skipping.")
                    retcode = -99
                }
                if !pathExists(installerItemPath) {
                    // can't install, so we should stop. Since later items might
                    // depend on this one, we shouldn't continue
                    displayError("Installer item \(installerItem) was not found. Skipping.")
                    retcode = -99
                }
            }
            switch installerType {
            case "pkg_install":
                let (result, restartNeeded) = await handleApplePackageInstall(pkginfo: item, itemPath: installerItemPath)
                retcode = result
                if restartNeeded {
                    restartFlag = true
                }
            case "copy_from_dmg":
                if let itemList = item["items_to_copy"] as? [PlistDict] {
                    retcode = await copyFromDmg(dmgPath: installerItemPath, itemList: itemList)
                    if retcode == 0, requiresRestart(item) {
                        restartFlag = true
                    }
                }
            case "stage_os_installer":
                if let itemList = item["items_to_copy"] as? [PlistDict] {
                    retcode = await copyFromDmg(dmgPath: installerItemPath, itemList: itemList)
                    if retcode == 0 {
                        // TODO: implement osinstaller.record_staged_os_installer
                        // osinstaller.record_staged_os_installer(item)
                    }
                }
            case "nopkg":
                restartFlag = restartFlag || requiresRestart(item)
            default:
                // unknown or no longer supported installer type
                if ["appdmg", "profiles"].contains(installerType) || installerType.hasPrefix("Adobe") {
                    displayError("Installer type '\(installerType)' for \(installerItem) is no longer supported.")
                } else {
                    displayError("Installer type '\(installerType)' for \(installerItem) is an unknown installer type.")
                }
                retcode = -99
            }
        }
        // If install failed, add to skippedInstalls so that any item later in the list
        // that requires this item is skipped as well.
        if retcode != 0 {
            skippedInstalls.append(item)
        }
        // if install succeeded, look for a postinstall_script to run
        if retcode == 0, item["postinstall_script"] is String {
            let scriptexit = await runEmbeddedScript(name: "postinstall_script", pkginfo: item)
            if scriptexit != 0 {
                // we won't consider postinstall script failures as fatal
                // since the item has been installed via package/disk image
                // but admin should be notified
                displayWarning("Postinstall script for \(itemName) returned \(scriptexit)")
            }
        }
        // if install was successful and this is a SelfService OnDemand install
        // remove the item from the SelfServeManifest's managed_installs
        if retcode == 0,
           item["OnDemand"] as? Bool ?? false
        {
            // TODO: manifestutils.remove_from_selfserve_installs(item['name'])
        }

        // log install success/failure
        var logMessage = "Install of \(displayName)-\(versionToInstall): "
        if retcode == 0 {
            logMessage += "SUCCESSFUL"
        } else {
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
