//
//  osutils.swift
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

import Foundation
import IOKit
import SystemConfiguration

/// Returns the macOS version
func getOSVersion(onlyMajorMinor: Bool = true) -> String {
    let version = ProcessInfo().operatingSystemVersion

    if version.patchVersion == 0 || onlyMajorMinor {
        return "\(version.majorVersion).\(version.minorVersion)"
    } else {
        return "\(version.majorVersion).\(version.minorVersion).\(version.patchVersion)"
    }
}

/// Returns console user (the current GUI user)
func getConsoleUser() -> String {
    return SCDynamicStoreCopyConsoleUser(nil, nil, nil) as? String ?? ""
}

/// Gets a list of GUI users by parsing the output of /usr/bin/who
func currentGUIUsers() -> [String] {
    var guiUsers = [String]()
    let result = runCLI("/usr/bin/who")
    for line in result.output.components(separatedBy: .newlines) {
        let parts = line.components(separatedBy: .whitespaces).filter {
            !$0.isEmpty
        }
        if parts.count > 1, parts[1] == "console" {
            guiUsers.append(parts[0])
        }
    }
    return guiUsers
}

/// Returns the number of seconds since the last mouse or keyboard event.
func getIdleSeconds() -> Int {
    return Int(hidIdleTime() / 1_000_000_000)
}

/// Determine if the network is up by looking for any non-loopback
/// internet network interfaces.
///
/// Returns:
/// Boolean. true if non-loopback is found (network is up), false otherwise.
func networkUp() -> Bool {
    // TODO: replace this with something better that also handles IPv6
    let result = runCLI("/sbin/ifconfig", arguments: ["-a", "inet"])
    if result.exitcode == 0 {
        for line in result.output.components(separatedBy: .newlines) {
            if line.contains("inet") {
                let parts = line.components(separatedBy: .whitespaces)
                if parts.count > 2 {
                    let ip = parts[2]
                    if ip.components(separatedBy: ".").count == 4,
                       !["127.0.0.1", "0.0.0.0"].contains(ip)
                    {
                        // found an IPv4 address that's not a loopback address
                        return true
                    }
                }
            }
        }
    }
    return false
}

/// Trigger the detection of new network hardware, like a USB-to-Ethernet adapter
func detectNetworkHardware() {
    _ = runCLI("/usr/sbin/networksetup", arguments: ["-detectnewhardware"])
}
