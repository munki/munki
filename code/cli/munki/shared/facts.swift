//
//  facts.swift
//  munki
//
//  Created by Greg Neagle on 8/9/24.
//
//  Copyright 2024 Greg Neagle.
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

func getMachineFacts() async -> PlistDict {
    // Gets some facts about this machine we use to determine if a given
    // installer is applicable to this OS or hardware

    // these all call system_profiler so see if we can do
    // them concurrently
    async let ip4addresses = await getIPAddresses("IPv4")
    async let ip6addresses = await getIPAddresses("IPv6")
    async let iBridgeInfo = await getIBridgeInfo()

    var machine = PlistDict()

    machine["hostname"] = hostname()
    var arch = platform()
    if arch == "x86_64" {
        // we might be natively Intel64, or running under Rosetta.
        // uname's 'platform' returns the current execution arch, which under Rosetta
        // will be x86_64. Since what we want here is the _native_ arch, we're
        // going to use a hack for now to see if we're natively arm64
        if uname_version().contains("ARM64") {
            arch = "arm64"
        }
    }
    machine["arch"] = arch
    if arch == "x86_64" {
        machine["x86_64_capable"] = true
    } else if arch == "i386" {
        // I don't think current Swift is even supported on 32-bit Intel
        // so this is probably useless
        machine["x86_64_capable"] = hasIntel64Support()
    }
    machine["os_vers"] = getOSVersion(onlyMajorMinor: false)
    machine["os_build_number"] = getOSBuild()
    machine["machine_model"] = hardwareModel()
    machine["munki_version"] = getVersion()
    machine["ipv4_address"] = await ip4addresses
    machine["ipv6_address"] = await ip6addresses
    machine["serial_number"] = serialNumber()
    machine["product_name"] = productName()
    machine["ibridge_model_name"] = await iBridgeInfo["ibridge_model_name"] as? String ?? "NO IBRIDGE CHIP"
    machine["board_id"] = boardID()
    machine["device_id"] = deviceID()

    return machine
}

private func conditionalScriptsDir() -> String {
    // returns the path to the conditional scripts dir
    // TODO: make this relative to the managedsoftwareupdate binary
    return "/usr/local/munki/conditions"
}

func getConditions() async -> PlistDict {
    // Fetches key/value pairs from condition scripts
    // which can be placed into /usr/local/munki/conditions

    let conditionalScriptDir = conditionalScriptsDir()
    let conditionalItemsPath = (managedInstallsDir() as NSString).appendingPathComponent("ConditionalItems.plist")
    let filemanager = FileManager.default
    try? filemanager.removeItem(atPath: conditionalItemsPath)

    if pathExists(conditionalScriptDir), !pathIsDirectory(conditionalScriptDir) {
        displayWarning("\(conditionalScriptDir) exists but is not a directory.")
        return PlistDict()
    }

    if let scriptDirItems = try? filemanager.contentsOfDirectory(atPath: conditionalScriptDir) {
        for item in scriptDirItems {
            if item.hasPrefix(".") {
                // skip it
                continue
            }
            let itemPath = (conditionalScriptDir as NSString).appendingPathComponent(item)
            if pathIsDirectory(itemPath) {
                // skip it
                continue
            }
            do {
                let _ = try await runExternalScript(itemPath, timeout: 60)
            } catch {
                displayError(error.localizedDescription)
            }
        }
        if pathExists(conditionalItemsPath) {
            do {
                if let conditions = try readPlist(fromFile: conditionalItemsPath) as? PlistDict {
                    // success!!
                    try? filemanager.removeItem(atPath: conditionalItemsPath)
                    return conditions
                } else {
                    // data is in wrong formet
                    displayWarning("\(conditionalItemsPath) contents are in an unexpected format.")
                }
            } catch {
                // file was invalid
                displayWarning("\(conditionalItemsPath) contents are invalid.")
            }
        } else {
            // file doesn't exist. Not an error to warn about
        }
    } else {
        // could not get script items from dir
        displayWarning("Unexpected filesyem issue getting contents of \(conditionalScriptDir)")
    }
    return PlistDict() // empty results
}
