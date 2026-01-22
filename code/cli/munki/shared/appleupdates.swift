//
//  appleupdates.swift
//  munki
//
//  Created by Greg Neagle on 9/9/24.
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

/// Removes the AppleUpdates.plist if it exists
func clearAppleUpdateInfo() {
    let appleUpdatesFilePath = managedInstallsDir(subpath: "AppleUpdates.plist")
    if pathExists(appleUpdatesFilePath) {
        try? FileManager.default.removeItem(atPath: appleUpdatesFilePath)
    }
}

/// Parses a new-style (macOS 10.15+) software update line
func parseSULineNewStyle(_ line: String) -> [String: String] {
    var info = [String: String]()
    var trimmedLine = line.trimmingCharacters(in: ["*"])
    trimmedLine = trimmedLine.trimmingCharacters(in: .whitespaces)
    trimmedLine = trimmedLine.trimmingCharacters(in: [","])
    let items = trimmedLine.components(separatedBy: ",")
    for item in items {
        let trimmedItem = item.trimmingCharacters(in: .whitespaces)
        let parts = trimmedItem.components(separatedBy: ":")
        if parts.count == 2 {
            info[parts[0]] = parts[1].trimmingCharacters(in: .whitespaces)
        }
    }
    return info
}

/// Parses two lines from softwareupdate -l output that describe an update and returns a dict
func parseSULines(_ line1: String, _ line2: String) -> [String: String] {
    var info = parseSULineNewStyle(line1)
    info.merge(parseSULineNewStyle(line2)) { _, second in second }
    return info
}

/// Deletes "RecommendedUpdates" from /Library/Preferences/com.apple.SoftwareUpdate.plist
func clearRecommendedUpdates() {
    CFPreferencesSetValue(
        "RecommendedUpdates" as CFString,
        nil,
        "com.apple.SoftwareUpdate" as CFString,
        kCFPreferencesAnyUser,
        kCFPreferencesCurrentHost
    )
}

/// Returns "RecommendedUpdates" from /Library/Preferences/com.apple.SoftwareUpdate.plist
func getRecommendedUpdates() -> [PlistDict]? {
    return CFPreferencesCopyValue(
        "RecommendedUpdates" as CFString,
        "com.apple.SoftwareUpdate" as CFString,
        kCFPreferencesAnyUser,
        kCFPreferencesCurrentHost
    ) as? [PlistDict]
}

/// Attempts to get a Product Key for an update
func getProductKey(for item: PlistDict, recommendedUpdates: [PlistDict]) -> String? {
    if let name = item["name"] as? String,
       let version = item["version_to_install"] as? String
    {
        for update in recommendedUpdates {
            if let displayName = update["Display Name"] as? String,
               let displayVersion = update["Display Version"] as? String,
               displayName == name,
               displayVersion == version
            {
                return update["Product Key"] as? String
            }
        }
    }
    return nil
}

/// Runs softwareupdate tool and returns a list of dictionaries parsed from the output
func getAvailableSoftwareUpdates() -> [[String: String]] {
    var updates = [[String: String]]()
    clearRecommendedUpdates()
    let result = runCLI("/usr/sbin/softwareupdate", arguments: ["-l"])
    guard result.exitcode == 0 else {
        display.error("softwareupdate error \(result.exitcode): \(result.error)")
        return updates
    }
    let lines = result.output.components(separatedBy: .newlines)
    var index = 0
    while index < lines.count {
        let currentLine = lines[index]
        index += 1
        if currentLine.hasPrefix("* Label") {
            if index < lines.count {
                let nextLine = lines[index]
                index += 1
                updates.append(parseSULines(currentLine, nextLine))
            }
        }
    }
    return updates
}

/// FIlters out any majorOS upgrades from a list of Apple updates
func filterOutMajorOSUpgrades(_ appleUpdates: [PlistDict]) -> [PlistDict] {
    // There's a couple of strategies we could use here:
    //
    //  1) Match update names that start with "macOS" and end with a version
    //     number matching the update version, then compare the first part
    //     of that version against the currently installed OS. IOW,
    //     if we are currently running 13.6.9, an update to 14.6.1 or 15.0
    //     would be a major update. This could break if Apple changes its
    //     naming convention, or issues other non-OS updates with names that
    //     start with "macOS".
    //
    //  2) Look at com.apple.SoftwareUpdate's RecommendedUpdates. Currently,
    //     minor updates have identifiers and product keys like
    //       "MSU_UPDATE_22G830_patch_13.6.9_minor"
    //     Major updates have identifiers and product keys like
    //       "MSU_UPDATE_23G93_patch_14.6.1_major"
    //     IOW, all OS updates start with "MSU_UPDATE_" but the majors end with
    //     "_major". This could break if Apple changes the naming conventions
    //     for their update identifiers/product keys
    //
    //  Since when this was written we were not collecting the info from
    //  com.apple.SoftwareUpdate's RecommendedUpdates, we went with
    //  strategy #1.

    let currentOSVersion = getOSVersion() // just gets major.minor
    let versionParts = currentOSVersion.components(separatedBy: ".")
    let currentMajorOSVersion = versionParts[0]

    var filteredUpdates = [PlistDict]()
    for update in appleUpdates {
        guard let name = update["name"] as? String,
              let version = update["version_to_install"] as? String
        else {
            continue
        }
        if !name.hasPrefix("macOS ") {
            filteredUpdates.append(update)
            continue
        }
        // "macOS " update
        if !name.hasSuffix(version) {
            // not the expected name format so maybe not an OS update
            filteredUpdates.append(update)
            continue
        }
        if version.hasPrefix(currentMajorOSVersion + ".") {
            // major version is the same, so this is a minor update
            filteredUpdates.append(update)
            continue
        }
        // "macOS " update with different major version. Do nothing.
    }
    return filteredUpdates
}

/// Returns a list of dictionaries describing available Apple updates.
func getAppleUpdatesList(shouldFilterMajorOSUpdates: Bool = false) -> [PlistDict] {
    let recommendedUpdates = getRecommendedUpdates() ?? []
    var appleUpdates = [PlistDict]()
    let rawUpdates = getAvailableSoftwareUpdates()
    for item in rawUpdates {
        if let label = item["Label"],
           let name = item["Title"],
           let version = item["Version"]
        {
            var info = PlistDict()
            info["Label"] = label
            // MSC.app filters on productKey so we need to set it
            info["productKey"] = label
            info["name"] = name
            info["display_name"] = name
            info["description"] = ""
            info["version_to_install"] = version
            if let sizeStr = item["Size"] {
                let size = Int(sizeStr.trimmingCharacters(in: ["K", "i", "B"])) ?? 0
                info["installer_item_size"] = size
                info["installed_size"] = size
            }
            if let restartAction = item["Action"],
               restartAction == "restart"
            {
                info["RestartAction"] = "RequireRestart"
            }
            info["productKey"] = getProductKey(for: info, recommendedUpdates: recommendedUpdates)
            appleUpdates.append(info)
        }
    }
    if shouldFilterMajorOSUpdates {
        return filterOutMajorOSUpgrades(appleUpdates)
    }
    return appleUpdates
}

/// Gets available Apple updates.
/// Writes a file used by the MSC GUI to display available updates.
/// Returns count of available Apple updates
func findAndRecordAvailableAppleUpdates(shouldFilterMajorOSUpdates: Bool = false) -> Int {
    let appleUpdatesFilePath = managedInstallsDir(subpath: "AppleUpdates.plist")
    let appleUpdates = getAppleUpdatesList(
        shouldFilterMajorOSUpdates: shouldFilterMajorOSUpdates)
    if appleUpdates.isEmpty {
        try? FileManager.default.removeItem(atPath: appleUpdatesFilePath)
        return 0
    }
    let plist: PlistDict = [
        "AppleUpdates": appleUpdates,
    ]
    do {
        try writePlist(plist, toFile: appleUpdatesFilePath)
    } catch {
        display.error("Could not write AppleUpdates.plist: \(error.localizedDescription)")
    }
    return appleUpdates.count
}

/// Returns the number of available/pending Apple updates
func getAppleUpdateCount() -> Int {
    let appleUpdatesFilePath = managedInstallsDir(subpath: "AppleUpdates.plist")
    if !pathExists(appleUpdatesFilePath) {
        return 0
    }
    do {
        guard let plistDict = try readPlist(fromFile: appleUpdatesFilePath) as? PlistDict else {
            // wrong format
            return 0
        }
        let appleUpdates = plistDict["AppleUpdates"] as? [PlistDict] ?? []
        return appleUpdates.count
    } catch {
        // file read/parse error
        return 0
    }
}

/// Prints Apple update information and updates ManagedInstallReport.
func displayAppleUpdateInfo() {
    let appleUpdatesFilePath = managedInstallsDir(subpath: "AppleUpdates.plist")
    if !pathExists(appleUpdatesFilePath) {
        return
    }
    var appleUpdates = [PlistDict]()
    do {
        guard let plistDict = try readPlist(fromFile: appleUpdatesFilePath) as? PlistDict else {
            throw MunkiError("wrong format")
        }
        appleUpdates = plistDict["AppleUpdates"] as? [PlistDict] ?? []
    } catch {
        display.error("Error reading \(appleUpdatesFilePath): \(error.localizedDescription)")
        return
    }
    if appleUpdates.isEmpty {
        display.info("No available Apple Software Updates.")
        return
    }
    Report.shared.record(appleUpdates, to: "AppleUpdates")
    display.info("The following Apple Software Updates are available to install:")
    for item in appleUpdates {
        guard let name = item["display_name"] as? String,
              let version = item["version_to_install"] as? String
        else {
            continue
        }
        display.info("    \(name)-\(version)")
        if let restartAction = item["RestartAction"] as? String {
            if restartAction.contains("Restart") {
                display.info("       *Restart required")
            } else if restartAction.contains("Logout") {
                display.info("       *Logout required")
            }
        }
    }
    display.info("(Apple updates must be manually installed with Apple's tools)")
}
