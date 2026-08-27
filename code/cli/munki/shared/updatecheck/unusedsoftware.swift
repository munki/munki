//
//  unusedsoftware.swift
//  munki
//
//  Created by Greg Neagle on 10/25/24.
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

import AppKit
import Foundation

private let display = DisplayAndLog.main

/// Returns a boolean indicating if the application with the given
/// bundleid is currently running.
func bundleIDisRunning(_ appBundleID: String) -> Bool {
    let runningApps = NSWorkspace.shared.runningApplications
    for app in runningApps {
        if app.bundleIdentifier == appBundleID {
            return true
        }
    }
    return false
}

/// Extracts a list of application bundle_ids from the installs list of a
/// pkginfo item
func bundleIDsFromInstallsList(_ pkginfo: PlistDict) -> [String] {
    func installsItemHasAppBundleIdentifier(_ item: PlistDict) -> Bool {
        let bundleIdentifier = item["CFBundleIdentifier"] as? String ?? ""
        let type = item["type"] as? String ?? ""
        let path = item["path"] as? String ?? ""
        if bundleIdentifier.isEmpty {
            return false
        }
        if type == "application" {
            return true
        }
        if type == "bundle", path.hasSuffix(".app") {
            return true
        }
        return false
    }

    let installsList = pkginfo["installs"] as? [PlistDict] ?? []
    let bundleIDs = installsList.filter {
        installsItemHasAppBundleIdentifier($0)
    }.map {
        $0["CFBundleIdentifier"] as? String ?? ""
    }
    return bundleIDs
}

/// Determines if an optional install item should be removed due to lack of use.
func shouldBeRemovedIfUnused(_ pkginfo: PlistDict) -> Bool {
    let name = pkginfo["name"] as? String ?? "UNKNOWN"
    let removalInfo = pkginfo["unused_software_removal_info"] as? PlistDict ?? PlistDict()
    if removalInfo.isEmpty {
        return false
    }
    display.debug1("\tChecking to see if \(name) should be removed due to lack of use...")
    let removalDays = removalInfo["removal_days"] as? Int ?? 0
    if removalDays < 1 {
        display.warning("Invalid removal days: \(String(describing: removalInfo["removal_days"])) for \(name)")
        return false
    }
    display.debug1("\t\tNumber of days until removal is \(removalDays)")
    let usage = ApplicationUsageQuery(logger: MunkiLogger.standard)
    let usageDataDays = usage.daysOfData()
    if usageDataDays < removalDays {
        // we don't have usage data old enough to judge
        display.debug1("\t\tApplication usage data covers fewer than \(removalDays) days.")
        return false
    }

    // check to see if we have an install request within the removal_days
    let daysSinceInstallRequest = usage.daysSinceLastInstallEvent("install", itemName: name)
    if daysSinceInstallRequest >= 0,
       daysSinceInstallRequest <= removalDays
    {
        display.debug1("\t\t\(name) had an install request \(daysSinceInstallRequest) days ago.")
        return false
    }

    // get list of application bundle_ids to check
    let bundleIDs = removalInfo["bundle_ids"] as? [String] ?? bundleIDsFromInstallsList(pkginfo)
    if bundleIDs.isEmpty {
        display.debug1("\tNo application bundle_ids to check.")
        return false
    }

    // now check each bundleid to see if it's currently running or has been
    // activated in the past removal_days days
    display.debug1("\t\tChecking bundle ids: \(bundleIDs)")
    for bundleID in bundleIDs {
        if bundleIDisRunning(bundleID) {
            display.debug1("\t\tApplication \(bundleID) is currently running.")
            return false
        }
        let daysSinceLastActivation = usage.daysSinceLastUsageEvent("activate", bundleID: bundleID)
        if daysSinceLastActivation == -1 {
            display.debug1("\t\t\(bundleID) has not been activated in more than \(usageDataDays) days...")
        } else {
            display.debug1("\t\t\(bundleID) was last activated \(daysSinceLastActivation) days ago")
            if daysSinceLastActivation <= removalDays {
                return false
            }
        }
    }
    // if we get this far we must not have found any apps used in the past
    // removal_days days, so we should set up a removal
    display.info("Will add \(name) to the removal list since it has been unused for at least \(removalDays) days...")
    return true
}
