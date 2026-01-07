//
//  installinfo.swift
//  munki
//
//  Created by Greg Neagle on 8/31/24.
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

import Foundation

private let display = DisplayAndLog.main

/// Gets info from InstallInfo.plist
func getInstallInfo() -> PlistDict? {
    // TODO: there is at least one other similar function elsewhere; de-dup
    let installInfoPath = managedInstallsDir(subpath: "InstallInfo.plist")
    if pathExists(installInfoPath) {
        do {
            if let plist = try readPlist(fromFile: installInfoPath) as? PlistDict {
                return plist
            } else {
                display.error("\(installInfoPath) does not have the expected format")
            }
        } catch {
            display.error("Could not read \(installInfoPath): \(error.localizedDescription)")
        }
    } else {
        display.info("\(installInfoPath) does not exist")
    }
    return nil
}

/// Returns any available Apple updates
func getAppleUpdates() -> PlistDict? {
    let installAppleUpdates = boolPref("InstallAppleSoftwareUpdates") ?? false
    let appleUpdatesOnly = boolPref("AppleSoftwareUpdatesOnly") ?? false
    let appleUpdatesFile = managedInstallsDir(subpath: "AppleUpdates.plist")
    if pathExists(appleUpdatesFile),
       installAppleUpdates || appleUpdatesOnly
    {
        do {
            if let plist = try readPlist(fromFile: appleUpdatesFile) as? PlistDict {
                return plist
            } else {
                display.error("\(appleUpdatesFile) does not have the expected format")
            }
        } catch {
            display.error("Could not read \(appleUpdatesFile): \(error.localizedDescription)")
        }
    }
    return nil
}

/// Returns age of the oldest pending update in days
func oldestPendingUpdateInDays() -> Double {
    let updateTrackingFile = managedInstallsDir(subpath: "UpdateNotificationTracking.plist")
    guard let pendingUpdates = try? readPlist(fromFile: updateTrackingFile) as? PlistDict else {
        return 0
    }
    var oldestDate = Date()
    // each key has an a dict as a value.
    // In this dict, a key is an update name,
    // and its value is the date it was first seen
    for category in pendingUpdates.keys {
        if let updates = pendingUpdates[category] as? [String: Date] {
            for name in updates.keys {
                if let thisDate = updates[name],
                   thisDate < oldestDate
                {
                    oldestDate = thisDate
                }
            }
        }
    }
    return Date().timeIntervalSince(oldestDate) / (24 * 60 * 60)
}

struct PendingUpdateInfo {
    var pendingUpdateCount: Int
    var oldestUpdateDays: Double
    var forcedUpdateDueDate: Date?
}

/// Returns a dict with some data that
/// managedsoftwareupdate records at the end of a run
func getPendingUpdateInfo() -> PendingUpdateInfo {
    let installInfo = getInstallInfo()
    let managedInstalls = installInfo?["managed_installs"] as? [PlistDict] ?? []
    let removals = installInfo?["removals"] as? [PlistDict] ?? []
    let appleUpdateInfo = getAppleUpdates()
    let appleUpdates = appleUpdateInfo?["AppleUpdates"] as? [PlistDict] ?? []

    // calculate earliest date a forced install (if any) is due
    var earliestForcedDate: Date? = nil
    for install in managedInstalls + appleUpdates {
        if var thisForceInstallDate = install["force_install_after_date"] as? Date {
            thisForceInstallDate = subtractTZOffsetFromDate(thisForceInstallDate)
            if earliestForcedDate == nil {
                earliestForcedDate = thisForceInstallDate
            } else if let unwrappedEarliestForcedDate = earliestForcedDate,
                      thisForceInstallDate < unwrappedEarliestForcedDate
            {
                earliestForcedDate = thisForceInstallDate
            }
        }
    }

    return PendingUpdateInfo(
        pendingUpdateCount: managedInstalls.count + removals.count + appleUpdates.count,
        oldestUpdateDays: oldestPendingUpdateInDays(),
        forcedUpdateDueDate: earliestForcedDate
    )
}

/// Attempt to find the date Apple Updates were first seen since they can
/// appear and disappear from the list of available updates, which screws up
/// our tracking of pending updates that can trigger more aggressive update
/// notifications.
func getAppleUpdatesWithHistory() -> [String: Date] {
    let appleUpdateHistoryPath = managedInstallsDir(subpath: "AppleUpdateHistory.plist")
    let appleUpdateInfo = getAppleUpdates()
    let appleUpdates = appleUpdateInfo?["AppleUpdates"] as? [PlistDict] ?? []
    if appleUpdates.isEmpty {
        // nothing more to do
        return [String: Date]()
    }
    var appleUpdateHistory = (try? readPlist(fromFile: appleUpdateHistoryPath)) as? PlistDict ?? [:]
    var historyInfo = [String: Date]()
    var historyUpdated = false
    let now = Date()
    for item in appleUpdates {
        guard let productKey = item["productKey"] as? String,
              let name = item["name"] as? String
        else {
            continue
        }
        if let historyItem = appleUpdateHistory[productKey] as? PlistDict {
            historyInfo[name] = historyItem["firstSeen"] as? Date ?? now
        } else {
            historyInfo[name] = now
            appleUpdateHistory[productKey] = [
                "firstSeen": now,
                "displayName": item["display_name"] as? String ?? "",
                "version": item["version_to_install"] as? String ?? "",
            ]
            historyUpdated = true
        }
    }
    if historyUpdated {
        do {
            try writePlist(appleUpdateHistory, toFile: appleUpdateHistoryPath)
        } catch {
            display.warning("Could not update \(appleUpdateHistoryPath): \(error.localizedDescription)")
        }
    }
    return historyInfo
}

/// Record the time each update first is made available. We can use this to
/// escalate our notifications if there are items that have been skipped a lot
func savePendingUpdateTimes() {
    let now = Date()
    let pendingUpdatesPath = managedInstallsDir(subpath: "UpdateNotificationTracking.plist")
    let installInfo = getInstallInfo()
    let managedInstalls = installInfo?["managed_installs"] as? [PlistDict] ?? []
    let installNames = managedInstalls.map {
        $0["name"] as? String ?? ""
    }.filter {
        !$0.isEmpty
    }
    let removals = installInfo?["removals"] as? [PlistDict] ?? []
    let removalNames = removals.map {
        $0["name"] as? String ?? ""
    }.filter {
        !$0.isEmpty
    }
    let appleUpdates = getAppleUpdatesWithHistory()
    var stagedOSUpdateNames = [String]()
    if let stagedOSUpdate = getStagedOSInstallerInfo(),
       let updateName = stagedOSUpdate["name"] as? String
    {
        stagedOSUpdateNames = [updateName]
    }
    let updateNames = [
        "managed_installs": installNames,
        "removals": removalNames,
        "AppleUpdates": Array(appleUpdates.keys),
        "StagedOSUpdates": stagedOSUpdateNames,
    ]
    let priorPendingUpdates = (try? readPlist(fromFile: pendingUpdatesPath)) as? [String: [String: Date]] ?? [:]
    var currentPendingUpdates = [String: [String: Date]]()

    for key in updateNames.keys {
        currentPendingUpdates[key] = [String: Date]()
        for name in updateNames[key] ?? [] {
            if let priorCategory = priorPendingUpdates[key],
               let priorItemDate = priorCategory[name]
            {
                // copy the prior date from matching item
                currentPendingUpdates[key]?[name] = priorItemDate
            } else if key == "AppleUpdates" {
                currentPendingUpdates[key]?[name] = appleUpdates[name]
            } else {
                currentPendingUpdates[key]?[name] = now
            }
        }
    }
    do {
        try writePlist(currentPendingUpdates, toFile: pendingUpdatesPath)
    } catch {
        display.warning("Could not write \(pendingUpdatesPath): \(error.localizedDescription)")
    }
}

/// Prints info about available updates
func displayUpdateInfo() {
    //
    /// Displays logout/restart info for item if present and also updates our report
    func displayAndRecordRestartInfo(_ item: PlistDict) {
        let restartAction = item["RestartAction"] as? String ?? ""
        if ["RequireRestart", "RecommendRestart"].contains(restartAction) {
            display.info("       *Restart required")
            Report.shared.record(true, to: "RestartRequired")
        }
        if restartAction == "RequireLogout" {
            display.info("       *Logout required")
            Report.shared.record(true, to: "LogoutRequired")
        }
        // Displays force install deadline if present
        if let forceInstallAfterDate = item["force_install_after_date"] as? Date {
            // format string representation to not include timezone
            let formatter = ISO8601DateFormatter()
            formatter.formatOptions = [
                .withFullDate,
                .withDashSeparatorInDate,
                .withTime,
                .withColonSeparatorInTime,
                .withSpaceBetweenDateAndTime,
            ]
            let formattedDate = formatter.string(from: forceInstallAfterDate)
            display.info("       *Must be installed by \(formattedDate)")
        }
    }

    let installInfo = getInstallInfo() ?? [:]
    let managedInstalls = installInfo["managed_installs"] as? [PlistDict] ?? []
    let removals = installInfo["removals"] as? [PlistDict] ?? []
    if managedInstalls.isEmpty, removals.isEmpty {
        display.info("No changes to managed software are available.")
        return
    }
    if !managedInstalls.isEmpty {
        display.info("")
        display.info("The following items will be installed or upgraded:")
    }
    for item in managedInstalls {
        if let installerItem = item["installer_item"] as? String,
           !installerItem.isEmpty
        {
            let name = item["name"] as? String ?? "UNKNOWN"
            let version = item["version_to_install"] as? String ?? "UNKNOWN"
            display.info("    + \(name)-\(version)")
            if let description = item["description"] as? String {
                display.info("        \(description)")
            }
            displayAndRecordRestartInfo(item)
        }
    }
    if !removals.isEmpty {
        display.info("The following items will be removed:")
    }
    for item in removals {
        if let installed = item["installed"] as? Bool, installed {
            let name = item["name"] as? String ?? "UNKNOWN"
            display.info("    - \(name)")
            displayAndRecordRestartInfo(item)
        }
    }
}

enum ForceInstallStatus: Int {
    case none = 0 // no force installs are pending soon
    case soon = 1 // a force install will occur within FORCE_INSTALL_WARNING_HOURS
    case now = 2 // a force install is about to occur
    case logout = 3 // a force install is about to occur and requires logout
    case restart = 4 // a force install is about to occur and requires restart
}

/// Check installable packages and applicable Apple updates
/// for force install parameters.
///
/// This method modifies InstallInfo and/or AppleUpdates in one scenario:
/// It enables the unattended_install flag on all packages which need to be
/// force installed and do not have a RestartAction.
func forceInstallPackageCheck() -> ForceInstallStatus {
    // This many hours before a force install deadline, start notifying the user.
    let FORCE_INSTALL_WARNING_HOURS = 4.0

    var result = ForceInstallStatus.none

    var installInfoTypes = [
        "InstallInfo.plist": "managed_installs",
    ]
    if boolPref("InstallAppleSoftwareUpdates") ?? false ||
        boolPref("AppleSoftwareUpdatesOnly") ?? false
    {
        installInfoTypes["AppleUpdates.plist"] = "AppleUpdates"
    }

    let now = Date()
    let nowPlusWarningHours = Date(timeIntervalSinceNow: FORCE_INSTALL_WARNING_HOURS * 3600)

    for (infoPlist, plistKey) in installInfoTypes {
        let infoPlistPath = managedInstallsDir(subpath: infoPlist)
        guard var installInfo = (try? readPlist(fromFile: infoPlistPath)) as? PlistDict else {
            continue
        }
        guard let installList = installInfo[plistKey] as? [PlistDict] else {
            continue
        }
        var writeback = false

        for (index, install) in installList.enumerated() {
            guard var forceInstallAfterDate = install["force_install_after_date"] as? Date else {
                continue
            }
            forceInstallAfterDate = subtractTZOffsetFromDate(forceInstallAfterDate)
            let name = install["name"] as? String ?? "UNKNOWN"
            display.debug1("Forced install for \(name) at \(forceInstallAfterDate)")
            let unattendedInstall = install["unattended_install"] as? Bool ?? false
            if now >= forceInstallAfterDate {
                if result == .none {
                    result = .now
                }
                if let restartAction = install["RestartAction"] as? String {
                    if result == .now, restartAction == "RequireLogout" {
                        result = .logout
                    } else if result == .now || result == .logout,
                              ["RequireRestart", "RecommendRestart"].contains(restartAction)
                    {
                        result = .restart
                    }
                } else if !unattendedInstall {
                    display.debug1("Setting unattended install for \(name)")
                    var mutableInstall = install
                    mutableInstall["unattended_install"] = true
                    var mutableList = installList
                    mutableList[index] = mutableInstall
                    installInfo[plistKey] = mutableList
                    writeback = true
                }
            }
            if result == .none, nowPlusWarningHours >= forceInstallAfterDate {
                result = .soon
            }
        }
        if writeback {
            try? writePlist(installInfo, toFile: infoPlistPath)
        }
    }
    return result
}
