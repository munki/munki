//
//  appleupdates.swift
//  munki
//
//  Created by Greg Neagle on 9/9/24.
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

func clearAppleUpdateInfo() {
    /// Removes the AppleUpdates.plist if it exists
    let appleUpdatesFilePath = managedInstallsDir(subpath: "AppleUpdates.plist")
    if pathExists(appleUpdatesFilePath) {
        try? FileManager.default.removeItem(atPath: appleUpdatesFilePath)
    }
}

func parseSULineNewStyle(_ line: String) -> [String: String] {
    /// Parses a new-style (macOS 10.15+) software update line
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

func parseSULines(_ line1: String, _ line2: String) -> [String: String] {
    /// Parses two lines from softwareupdate -l output that describe an update and returns a dict
    var info = parseSULineNewStyle(line1)
    info.merge(parseSULineNewStyle(line2)) { _, second in second }
    return info
}

func clearRecommendedUpdates() {
    /// Deletes "RecommendedUpdates" from /Library/Preferences/com.apple.SoftwareUpdate.plist
    CFPreferencesSetValue(
        "RecommendedUpdates" as CFString,
        nil,
        "com.apple.SoftwareUpdate" as CFString,
        kCFPreferencesAnyUser,
        kCFPreferencesCurrentHost
    )
}

func getAvailableSoftwareUpdates() -> [[String: String]] {
    /// runs softwareupdate tool and returns a list of dictionaries parsed from the output
    var updates = [[String: String]]()
    clearRecommendedUpdates()
    let result = runCLI("/usr/sbin/softwareupdate", arguments: ["-l"])
    guard result.exitcode == 0 else {
        displayError("softwareupdate error \(result.exitcode): \(result.error)")
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

func getAppleUpdatesList() -> [PlistDict] {
    /// Returns a list of dictionaries describing available Apple updates.
    var appleUpdates = [PlistDict]()
    let rawUpdates = getAvailableSoftwareUpdates()
    for item in rawUpdates {
        if let label = item["Label"],
           let name = item["Title"],
           let version = item["Version"]
        {
            var info = PlistDict()
            info["Label"] = label
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
            appleUpdates.append(item)
        }
    }
    return appleUpdates
}

func findAndRecordAvailableAppleUpdates() -> Int {
    /// Gets available Apple updates.
    /// writes a file used by the MSC GUI to display available updates.
    /// Returns count of available Apple updates
    let appleUpdatesFilePath = managedInstallsDir(subpath: "AppleUpdates.plist")
    let appleUpdates = getAppleUpdatesList()
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
        displayError("Could not write AppleUpdates.plist: \(error.localizedDescription)")
    }
    return appleUpdates.count
}

func getAppleUpdateCount() -> Int {
    /// Returns the number of available/pending Apple updates
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

func displayAppleUpdateInfo() {
    /// Prints Apple update information and updates ManagedInstallReport.
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
        displayError("Error reading \(appleUpdatesFilePath): \(error.localizedDescription)")
        return
    }
    if appleUpdates.isEmpty {
        displayInfo("No available Apple Software Updates.")
        return
    }
    Report.shared.record(appleUpdates, to: "AppleUpdates")
    displayInfo("The following Apple Software Updates are available to install:")
    for item in appleUpdates {
        guard let name = item["display_name"] as? String,
              let version = item["version_to_install"] as? String
        else {
            continue
        }
        displayInfo("    \(name)-\(version)")
        if let restartAction = item["RestartAction"] as? String {
            if restartAction.contains("Restart") {
                displayInfo("       *Restart required")
            } else if restartAction.contains("Logout") {
                displayInfo("       *Logout required")
            }
        }
    }
    displayInfo("(Apple updates must be manually installed with Apple's tools)")
}
