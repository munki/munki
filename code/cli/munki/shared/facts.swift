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

/// Gets some facts about this machine we use to determine if a given
/// installer is applicable to this OS or hardware
func generateMachineFacts() async -> PlistDict {
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

/// A Singleton class for machine facts, since they are expensive to generate
class MachineFacts {
    static let shared = MachineFacts()

    var facts: PlistDict

    private init() {
        facts = PlistDict()
    }

    func get() async -> PlistDict {
        if facts.isEmpty {
            facts = await generateMachineFacts()
        }
        return facts
    }
}

/// Return 'facts' about this machine
func getMachineFacts() async -> PlistDict {
    return await MachineFacts.shared.get()
}

/// Returns the path to the conditional scripts dir
private func conditionalScriptsDir() -> String {
    // TODO: make this relative to the managedsoftwareupdate binary
    return "/usr/local/munki/conditions"
}

/// Fetches key/value pairs from condition scripts
/// which can be placed into /usr/local/munki/conditions
func getConditions() async -> PlistDict {
    let conditionalScriptDir = conditionalScriptsDir()
    let conditionalItemsPath = managedInstallsDir(subpath: "ConditionalItems.plist")
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

/// Input: NSDate object
/// Output: NSDate object with same date and time as the UTC.
/// In Los Angeles (PDT), '2011-06-20T12:00:00Z' becomes
/// '2011-06-20 12:00:00 -0700'.
/// In New York (EDT), it becomes '2011-06-20 12:00:00 -0400'.
/// This allows a pkginfo item to reference a time in UTC that
/// gets translated to the same relative local time.
/// A force_install_after_date for '2011-06-20T12:00:00Z' will happen
/// after 2011-06-20 12:00:00 local time.
func subtractTZOffsetFromDate(_ date: Date) -> Date {
    // find our time zone offset in seconds
    let timezone = NSTimeZone.default
    let secondsOffset = Double(timezone.secondsFromGMT(for: date))
    // return new Date minus the offset
    return Date(timeInterval: -secondsOffset, since: date)
}

/// Input: NSDate object
/// Output: NSDate object with timezone difference added
/// to the date. This allows conditional_item conditions to
/// be written like so:
///
/// <key>condition</key>
/// <string>date > CAST("2012-12-17T16:00:00Z", "NSDate")</string>
///
/// with the intent being that the comparison is against local time.
func addTZOffsetToDate(_ date: Date) -> Date {
    // find our time zone offset in seconds
    let timezone = NSTimeZone.default
    let secondsOffset = Double(timezone.secondsFromGMT(for: date))
    // return new Date plus the offset
    return Date(timeInterval: secondsOffset, since: date)
}

/// Returns our info object used for predicate comparisons
func generatePredicateInfo() async -> PlistDict {
    // let's do some stuff concurrently
    async let machine = getMachineFacts()
    async let conditions = getConditions()
    var infoObject = await machine
    await infoObject.merge(conditions) { _, new in new }

    // use our start time for "current" date (if we have it)
    // and add the timezone offset to it so we can compare
    // UTC dates as though they were local dates.
    infoObject["date"] = addTZOffsetToDate(Date())

    // generate additional OS version info to use in comparisons
    let osVersComponents = (getOSVersion(onlyMajorMinor: false) + ".0.0").components(separatedBy: ".")
    infoObject["os_vers_major"] = Int(osVersComponents[0])
    infoObject["os_vers_minor"] = Int(osVersComponents[1])
    infoObject["os_vers_patch"] = Int(osVersComponents[2])

    // TODO: get last build number component for easier predicate comparison
    // let build = getOSBuild()
    // infoObject["os_build_last_component"] = <something clever>

    // laptop or desktop?
    if hasInternalBattery() {
        infoObject["machine_type"] = "laptop"
    } else {
        infoObject["machine_type"] = "desktop"
    }

    // add installed applications
    infoObject["applications"] = appData()

    return infoObject
}

/// A Singleton class for predicate info, since it's expensive to generate
class PredicateInfo {
    static let shared = PredicateInfo()

    var info: PlistDict

    private init() {
        info = PlistDict()
    }

    func get() async -> PlistDict {
        if info.isEmpty {
            info = await generatePredicateInfo()
        }
        return info
    }
}

/// Return our (possibly cached) info object
func predicateInfoObject() async -> PlistDict {
    return await PredicateInfo.shared.get()
}

/// Evaluates predicate against the info object; returns a boolean
/// Calls out to an Objective-C function because NSPrediacte methods can
/// raise NSExecption, whcih Swift cannot catch
func predicateEvaluatesAsTrue(
    _ predicateString: String,
    infoObject: PlistDict,
    additionalInfo: PlistDict? = nil
) -> Bool {
    var ourObject = infoObject
    if let additionalInfo {
        ourObject.merge(additionalInfo) { _, new in new }
    }
    displayDebug1("Evaluating predicate: `\(predicateString)`")
    var err: NSError?
    let result = objCpredicateEvaluatesAsTrue(predicateString, ourObject, &err)
    displayDebug1("Predicate `\(predicateString)` is \(result == 1)")
    if result == -1 {
        // exception
        let description = err?.localizedDescription ?? ""
        displayError("Predicate `\(predicateString)` raised an NSException: \(description)")
    }
    return result == 1
}
