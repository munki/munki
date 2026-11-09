//
//  catalogs.swift
//  munki
//
//  Created by Greg Neagle on 8/16/24.
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

/// a Singleton class to track catalog data
class Catalogs {
    static let shared = Catalogs()

    var db: [String: PlistDict]

    private init() {
        db = [String: PlistDict]()
    }

    func list() -> [String] {
        // returns a list of catalogs in our db
        return Array(db.keys)
    }

    func set(_ key: String, to value: PlistDict?) {
        db[key] = value
    }

    func get(_ key: String) -> PlistDict? {
        return db[key]
    }
}

/// a Singleton class to track what deployments decided during this run
class DeploymentRecords {
    static let shared = DeploymentRecords()

    /// one time for the whole run, so a step can't open partway through
    var now = Date()
    /// versions already logged as not usable, since an item can be looked up many times in a run
    var logged = Set<String>()
    /// items with no available version only because of a deployment
    var rejectedByDeployment = Set<String>()
    /// entries for the report's Deployments key, by item name and version
    var reportEntries = [String: PlistDict]()
    /// --deploy-percent, for this run only
    var commandLineDeployPercent: Int?

    private init() {}

    func reset() {
        now = Date()
        logged = []
        rejectedByDeployment = []
        reportEntries = [:]
        commandLineDeployPercent = nil
    }

    /// True if a deployment is the only reason a name from a manifest or `requires`,
    /// which can have a path and a version, has no available version
    func isOnlyRejectedByDeployment(_ manifestItem: String) -> Bool {
        let itemName = (manifestItem as NSString).lastPathComponent
        let name = nameAndVersion(itemName, onlySplitOnHyphens: true).0
        return rejectedByDeployment.contains((name as NSString).precomposedStringWithCanonicalMapping)
    }
}

/// Picks the deploy_percent override in effect, if any. --deploy-percent wins over the
/// preference, and a preference outside 1-100 is ignored. The values are passed in so this
/// stays a pure function that is easy to test.
func deployPercentOverride(commandLine: Int?, preference: Int?) -> (value: Int, source: String)? {
    if let commandLine {
        return (commandLine, "command_line")
    }
    if let preference, (1 ... 100).contains(preference) {
        return (preference, "preference")
    }
    return nil
}

/// Returns the deploy_percent override in effect for this run, if any
func currentDeployPercentOverride() -> (value: Int, source: String)? {
    return deployPercentOverride(
        commandLine: DeploymentRecords.shared.commandLineDeployPercent,
        preference: intPref("DeployPercentOverride")
    )
}

/// Logs the override in effect, once per run, along with a preference we're ignoring
func logDeployPercentOverride() {
    if let preference = intPref("DeployPercentOverride"), !(1 ... 100).contains(preference) {
        display.warning("Ignoring DeployPercentOverride preference of \(preference): it must be from 1 to 100")
    }
    if let override = currentDeployPercentOverride() {
        let source = override.source == "command_line" ? "--deploy-percent" : "DeployPercentOverride preference"
        display.info("deploy_percent overridden to \(override.value) by \(source)")
    }
}

/// Returns the identifier this machine's deploy_percent is based on
private func deployPercentIdentifier(machine: PlistDict) -> String? {
    let serial = machine["serial_number"] as? String
    if let identifier = deployPercentIdentifier(serial: serial, hardwareUUID: nil) {
        return identifier
    }
    // not a machine fact, so it stays out of reports. Tests can supply it there.
    return deployPercentIdentifier(serial: nil, hardwareUUID: machine["hardware_uuid"] as? String ?? hardwareUUID())
}

/// The deploy_percent fact for predicates: the machine's unsalted value, or the override
func deployPercentFact(machine: PlistDict) -> Int {
    return currentDeployPercentOverride()?.value ??
        machineDeployPercent(identifier: deployPercentIdentifier(machine: machine))
}

/// Returns the entries for the report's Deployments key
func deploymentReportEntries() -> [PlistDict] {
    let entries = DeploymentRecords.shared.reportEntries
    return entries.keys.sorted().compactMap { entries[$0] }
}

/// Why an item's deployment stops this machine from using it
enum DeploymentRejection {
    case notEligible(String)
    case invalid(String)
}

/// Checks an item's deployment for this machine. The rejection is nil if there's no deployment or
/// the machine is eligible. The report entry is nil if there's no deployment or it's invalid,
/// since an invalid one has no percents to report.
func evaluateDeployment(
    _ item: PlistDict,
    machine: PlistDict
) -> (rejection: DeploymentRejection?, reportEntry: PlistDict?) {
    guard item["deployment"] != nil else {
        return (nil, nil)
    }
    let name = item["name"] as? String ?? "<unknown>"
    let version = item["version"] as? String ?? "<unknown>"
    let deployment: Deployment
    do {
        deployment = try Deployment(item["deployment"])
    } catch {
        return (.invalid("\(name) \(version) has an invalid deployment: \(error)"), nil)
    }
    let state = deployment.state(at: DeploymentRecords.shared.now, toRealDate: subtractTZOffsetFromDate)
    let packagePercent = currentDeployPercentOverride()?.value ??
        packageDeployPercent(identifier: deployPercentIdentifier(machine: machine), itemName: name)
    var reportEntry: PlistDict = [
        "name": name,
        "version": version,
        "package_deploy_percent": packagePercent,
        "current_deploy_percent": state.currentPercent,
        "eligible": true,
    ]
    reportEntry["next_step_date"] = state.nextIncreaseDate
    if packagePercent <= state.currentPercent {
        return (nil, reportEntry)
    }
    reportEntry["eligible"] = false
    var message = "\(name) \(version) not eligible: package_deploy_percent \(packagePercent) > current_deploy_percent \(state.currentPercent)"
    if let nextStep = state.nextStepDate {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd HH:mm"
        message += " (next step \(formatter.string(from: nextStep)))"
    }
    return (.notEligible(message), reportEntry)
}

typealias CatalogDBTable = [String: [String: [Int]]]

/// Creates a dict we use like a database to query the catalogs for info
func makeCatalogDB(_ catalogItems: [PlistDict]) -> PlistDict {
    var nameTable = CatalogDBTable()
    var pkgidTable = CatalogDBTable()

    for (index, item) in catalogItems.enumerated() {
        guard var name = item["name"] as? String,
              var version = item["version"] as? String
        else {
            display.warning("Bad pkginfo: \(item)")
            continue
        }
        // normalize the version
        version = trimVersionString(version)
        // unicode normalize the name
        name = (name as NSString).precomposedStringWithCanonicalMapping

        // build indexes for items by name and version
        if nameTable[name] == nil {
            nameTable[name] = [String: [Int]]()
        }
        if nameTable[name]?[version] == nil {
            nameTable[name]?[version] = [Int]()
        }
        nameTable[name]?[version]?.append(index)

        // build 'table' of receipts
        for receipt in item["receipts"] as? [PlistDict] ?? [] {
            if let pkgid = receipt["packageid"] as? String,
               let vers = receipt["version"] as? String
            {
                if pkgidTable[pkgid] == nil {
                    pkgidTable[pkgid] = [String: [Int]]()
                }
                if pkgidTable[pkgid]?[vers] == nil {
                    pkgidTable[pkgid]?[vers] = [Int]()
                }
                pkgidTable[pkgid]?[vers]?.append(index)
            }
        }
    }

    // build a list of update items
    var updaters = catalogItems.filter {
        $0["update_for"] != nil
    }

    // now fix possible admin errors where 'update_for' is a string instead
    // of a list of strings
    for (index, update) in updaters.enumerated() {
        if let updateFor = update["update_for"] as? String {
            // whoops it's a string instead of a list of strings
            // let's fix it
            updaters[index]["update_for"] = [updateFor]
        }
    }

    // build a list of autoremove items
    var autoremoveItems = catalogItems.filter {
        $0["autoremove"] as? Bool ?? false
    }.map {
        $0["name"] as? String ?? ""
    }.filter {
        !$0.isEmpty
    }
    // now convert to a Set and back to get a list of unique items
    autoremoveItems = Array(Set(autoremoveItems))

    // now assemble the entire thing
    var pkgdb = PlistDict()
    pkgdb["named"] = nameTable // [String:[String:[Int]]]
    pkgdb["receipts"] = pkgidTable // [String:[String:[Int]]]
    pkgdb["updaters"] = updaters // [PlistDict]
    pkgdb["autoremoveitems"] = autoremoveItems // [String]
    pkgdb["items"] = catalogItems // [PlistDict]

    return pkgdb
}

/// Adds packageids from each catalogitem to two dictionaries.
/// One maps itemnames to receipt pkgids, the other maps receipt pkgids
/// to itemnames
func addPackageIDs(
    _ catalogItems: [PlistDict],
    itemNameToPkgID: inout [String: [String: [String]]],
    pkgidToItemName: inout [String: [String: [String]]]
) {
    for item in catalogItems {
        guard let name = item["name"] as? String else {
            continue
        }
        if let receipts = item["receipts"] as? [PlistDict] {
            if itemNameToPkgID[name] == nil {
                itemNameToPkgID[name] = [String: [String]]()
            }
            for receipt in receipts {
                guard let pkgid = receipt["packageid"] as? String,
                      let version = receipt["version"] as? String
                else {
                    continue
                }
                if itemNameToPkgID[name]?[pkgid] == nil {
                    itemNameToPkgID[name]?[pkgid] = [String]()
                }
                if let versions = itemNameToPkgID[name]?[pkgid],
                   !versions.contains(version)
                {
                    itemNameToPkgID[name]?[pkgid]?.append(version)
                }

                if pkgidToItemName[pkgid] == nil {
                    pkgidToItemName[pkgid] = [String: [String]]()
                }
                if pkgidToItemName[pkgid]?[name] == nil {
                    pkgidToItemName[pkgid]?[name] = [String]()
                }
                if let versions = pkgidToItemName[pkgid]?[name],
                   !versions.contains(version)
                {
                    pkgidToItemName[pkgid]?[name]?.append(version)
                }
            }
        }
    }
}

/// Searches the catalogs in a list for all items matching a given name.
///
/// Returns:
///    list of pkginfo items; sorted with newest version first. No precedence
///    is given to catalog order.
func getAllItemsWithName(_ name: String, catalogList: [String]) -> [PlistDict] {
    var itemList = [PlistDict]()
    let itemName = nameAndVersion(name, onlySplitOnHyphens: true).0

    display.debug1("Looking for all items matching: \(name)")
    for catalogName in catalogList {
        if let catalogDB = Catalogs.shared.get(catalogName),
           let items = catalogDB["items"] as? [PlistDict],
           let nameTable = catalogDB["named"] as? CatalogDBTable,
           let versionsDict = nameTable[itemName]
        {
            for (version, indexes) in versionsDict {
                if version == "latest" {
                    continue
                }
                for index in indexes {
                    do {
                        let item = items[index]
                        // need to compare encoded representations because
                        // PlistDict (aka [String: Any] is not hashable
                        let itemEncoded = try plistToData(item)
                        let alreadyAddedItem = try itemList.contains(
                            where: { try plistToData($0) == itemEncoded })
                        if !alreadyAddedItem {
                            let version = item["version"] as? String ?? "<unknown>"
                            display.debug1("Adding item \(itemName), version \(version) from catalog \(catalogName)...")
                            itemList.append(item)
                        }
                    } catch {
                        // error converting an item to plistData. Really unlikely,
                        // but if it happens we just don't add the item and continue on
                    }
                }
            }
        }
    }

    // sort itemList so latest is first
    itemList.sort {
        MunkiVersion($0["version"] as? String ?? "") > MunkiVersion($1["version"] as? String ?? "")
    }

    return itemList
}

/// Gets a list of items marked for automatic removal from the catalogs
/// in cataloglist. Filters those against items in the processed_installs
/// list, and managed_install list, which, together, should contain everything
/// that is supposed to be installed.
/// Then filters against the removals list, which contains all the removals
/// that have already been processed.
func getAutoRemovalItems(installInfo: PlistDict, catalogList: [String]) -> [String] {
    var autoremovalNames = [String]()
    for catalogName in catalogList {
        if let catalogDB = Catalogs.shared.get(catalogName),
           let moreAutoremovalNames = catalogDB["autoremoveitems"] as? [String]
        {
            autoremovalNames += moreAutoremovalNames
        }
    }

    var processedInstallsNames = [String]()
    if let processedInstalls = installInfo["processed_installs"] as? [String] {
        processedInstallsNames = processedInstalls.map {
            nameAndVersion($0, onlySplitOnHyphens: true).0
        }
    }
    var managedInstallsNames = [String]()
    if let managedInstalls = installInfo["managed_installs"] as? [PlistDict] {
        managedInstallsNames = managedInstalls.map {
            $0["name"] as? String ?? ""
        }
    }
    let processedUninstallsNames = installInfo["processed_uninstalls"] as? [String] ?? []
    autoremovalNames = autoremovalNames.filter {
        !processedInstallsNames.contains($0) &&
            !managedInstallsNames.contains($0) &&
            !processedUninstallsNames.contains($0)
    }

    return autoremovalNames
}

/// Looks for updates for a given manifest item that is either
/// installed or scheduled to be installed or removed. This handles not only
/// specific application updates, but also updates that aren't simply
/// later versions of the manifest item.
/// For example, AdobeCameraRaw might be an update for Adobe Photoshop, but
/// doesn't update the version of Adobe Photoshop.
/// Returns a list of item names that are updates for manifestItem.
func lookForUpdatesFor(_ manifestItem: String, catalogList: [String]) -> [String] {
    display.debug1("Looking for updates for: \(manifestItem)")
    // get a list of catalog items that are updates for other items
    var updateList = [String]()
    for catalogName in catalogList {
        if let catalogDB = Catalogs.shared.get(catalogName),
           let updaters = catalogDB["updaters"] as? [PlistDict]
        {
            let updateItems = updaters.filter {
                ($0["update_for"] as? [String] ?? []).contains(manifestItem)
            }.map {
                $0["name"] as? String ?? ""
            }
            if !updateItems.isEmpty {
                updateList += updateItems
            }
        }
    }
    // make sure the list has only unique items
    updateList = Array(Set(updateList))

    if !updateList.isEmpty {
        display.debug1("Found \(updateList.count) update(s): \(updateList.joined(separator: ", "))")
    }

    return updateList
}

func lookForUpdatesForName(_ manifestname: String,
                           version: String,
                           catalogList: [String]) -> [String]
{
    /// Looks for updates for a specific version of an item. Since these
    /// can appear in manifests and pkginfo as item-version or item--version
    /// we have to search twice.

    let nameAndVersion = "\(manifestname)-\(version)"
    let altNameAndVersion = "\(manifestname)--\(version)"
    var updateList = lookForUpdatesFor(nameAndVersion, catalogList: catalogList)
    updateList += lookForUpdatesFor(altNameAndVersion, catalogList: catalogList)

    // make sure the list has only unique items
    return Array(Set(updateList))
}

/// Attempts to find the best match in itemDict for version
func bestVersionMatch(version: String, itemDict: [String: [String]]) -> String? {
    let versionComponents = version.components(separatedBy: ".")
    var precision = 1
    while precision <= versionComponents.count {
        let testVersion = versionComponents[0 ..< precision].joined(separator: ".")
        var matchNames = [String]()
        for (item, versions) in itemDict {
            for itemVersion in versions {
                if itemVersion.hasPrefix(testVersion),
                   !matchNames.contains(item)
                {
                    matchNames.append(item)
                }
            }
        }
        if matchNames.count == 1 {
            return matchNames[0]
        }
        precision += 1
    }
    return nil
}

/// Analyze catalog data and installed packages in an attempt to determine what is installed.
func analyzeInstalledPkgs() async -> PlistDict {
    var itemNameToPkgID = [String: [String: [String]]]()
    var pkgidToItemName = [String: [String: [String]]]()
    for catalogName in Catalogs.shared.list() {
        if let catalogDB = Catalogs.shared.get(catalogName),
           let catalogItems = catalogDB["items"] as? [PlistDict]
        {
            addPackageIDs(
                catalogItems,
                itemNameToPkgID: &itemNameToPkgID,
                pkgidToItemName: &pkgidToItemName
            )
        }
    }
    // itemNameToPkgID now contains all receipts (pkgids) we know about
    // from items in all available catalogs

    let installedPkgs = await getInstalledPackages()

    var installed = [String]()
    var partiallyInstalled = [String]()
    var installedPkgsMatchedToName = [String: [String]]()
    for (name, pkgidVersDict) in itemNameToPkgID {
        // name is a pkgino name/manifest item name
        var foundPkgCount = 0
        for pkgid in pkgidVersDict.keys {
            if installedPkgs.keys.contains(pkgid) {
                foundPkgCount += 1
                if installedPkgsMatchedToName[name] == nil {
                    installedPkgsMatchedToName[name] = [String]()
                }
                installedPkgsMatchedToName[name]?.append(pkgid)
            }
        }
        if foundPkgCount == pkgidVersDict.count {
            // we found all receipts by pkgid on disk
            installed.append(name)
        } else if foundPkgCount > 0 {
            // we found only some receipts for the item on disk
            partiallyInstalled.append(name)
        }
    }
    // we pay special attention to the items that seem partially installed.
    // we need to see if there are any packages that are unique to this item
    // if there aren't, then this item probably isn't installed, and we're
    // just finding receipts that are shared with other items.
    for name in partiallyInstalled {
        // get a list of pkgs for this item that are installed
        let pkgsForThisName = installedPkgsMatchedToName[name] ?? []
        // now build a list of all the pkgs referred to by all the other
        // items that are either partially or entirely installed
        var allOtherPkgs = [String]()
        for otherName in installed {
            allOtherPkgs += installedPkgsMatchedToName[otherName] ?? []
        }
        for otherName in partiallyInstalled {
            if otherName != name {
                allOtherPkgs += installedPkgsMatchedToName[otherName] ?? []
            }
        }
        let uniquePkgs = Set(pkgsForThisName).subtracting(Set(allOtherPkgs))
        if !uniquePkgs.isEmpty {
            installed.append(name)
        }
    }

    // now filter partiallyinstalled to remove those items we moved to installed
    partiallyInstalled = partiallyInstalled.filter {
        !installed.contains($0)
    }

    // build our reference table. For each item we think is installed,
    // record the receipts on disk matched to the item
    var references = [String: [String]]()
    for name in installed {
        for pkgid in installedPkgsMatchedToName[name] ?? [] {
            if references[pkgid] == nil {
                references[pkgid] = [String]()
            }
            references[pkgid]?.append(name)
        }
    }

    // look through all our installedpkgs, looking for ones that have not been
    // attached to any Munki names yet
    let orphans = Array(installedPkgs.keys).filter {
        !references.keys.contains($0)
    }

    // attempt to match orphans to Munki item names
    var matchedOrphans = [String]()
    for pkgid in orphans {
        if let possibleMatchItems = pkgidToItemName[pkgid],
           let installedPkgidVersion = installedPkgs[pkgid]
        {
            if let bestMatch = bestVersionMatch(
                version: installedPkgidVersion,
                itemDict: possibleMatchItems
            ) {
                matchedOrphans.append(bestMatch)
            }
        }
    }

    // process matched orphans
    partiallyInstalled = partiallyInstalled.filter {
        !matchedOrphans.contains($0)
    }
    for name in matchedOrphans {
        if !installed.contains(name) {
            installed.append(name)
        }
        for pkgid in installedPkgsMatchedToName[name] ?? [] {
            if references[pkgid] == nil {
                references[pkgid] = []
            }
            if let nameList = references[pkgid],
               !nameList.contains(name)
            {
                references[pkgid]?.append(name)
            }
        }
    }

    // assemble everything
    return [
        "receipts_for_name": installedPkgsMatchedToName, // [String:[String]]
        "installed_names": installed, // [String]
        "pkg_references": references, // [String:[String]]
    ]
}

/// Searches the catalogs in list for an item matching the given name that
/// can be installed on the current hardware/OS (optionally skipping the
/// minimum OS check so we can return an item that requires a higher OS)
///
/// If no version is supplied, but the version is appended to the name
/// ('TextWrangler--2.3.0.0.0') that version is used.
/// If no version is given at all, the latest version is assumed.
/// Returns a pkginfo item, or nil.
func getItemDetail(
    _ itemName: String,
    catalogList: [String],
    version itemVersion: String = "",
    skipMinimumOSCheck: Bool = false,
    suppressWarnings: Bool = false,
    skipDeploymentCheck: Bool = false,
    acceptNotEligible: Bool = false
) async -> PlistDict? {
    var rejectedItems = [String]()
    var foundDeploymentRejection = false
    let machine = await getMachineFacts()
    let records = DeploymentRecords.shared

    /// Returns a boolean to indicate if the current Munki version is high
    /// enough to install this item. If not, also adds the failure reason to
    /// the rejected_items list.
    func munkiVersionOK(_ item: PlistDict) -> Bool {
        guard let name = item["name"] as? String,
              let version = item["version"] as? String,
              let munkiVersion = machine["munki_version"] as? String
        else {
            display.error("Unexpected error getting item name or version or getting Munki version")
            return false
        }
        if let minimumMunkiVersion = item["minimum_munki_version"] as? String {
            display.debug1("Considering item \(name), version \(version) with minimum Munki version required: \(minimumMunkiVersion)")
            display.debug1("Our Munki version is \(munkiVersion)")
            if MunkiVersion(munkiVersion) < MunkiVersion(minimumMunkiVersion) {
                rejectedItems.append(
                    "Rejected item \(name), version \(version) with minimum Munki version required \(minimumMunkiVersion). Our Munki version is \(munkiVersion)."
                )
                return false
            }
        }
        return true
    }

    /// Returns a boolean to indicate if the item is ok to install under
    /// the current OS. If not, also adds the failure reason to the
    /// rejected_items list. If skipMinimumOSCheck is true, skips the minimum os
    /// version check.
    func osVersionOK(_ item: PlistDict) -> Bool {
        guard let name = item["name"] as? String,
              let version = item["version"] as? String,
              let osVersion = machine["os_vers"] as? String
        else {
            display.error("Unexpected error getting item name or version or getting OS version")
            return false
        }
        // Is the current OS version >= minimum_os_version for the item?
        if !skipMinimumOSCheck,
           let minimumOSVersion = item["minimum_os_version"] as? String,
           !minimumOSVersion.isEmpty
        {
            display.debug1("Considering item \(name), version \(version) with minimum os version required \(minimumOSVersion)")
            display.debug1("Our OS version is \(osVersion)")
            if MunkiVersion(osVersion) < MunkiVersion(minimumOSVersion) {
                rejectedItems.append(
                    "Rejected item \(name), version \(version) with minimum os version required \(minimumOSVersion). Our OS version is \(osVersion)."
                )
                return false
            }
        }
        // current OS version <= maximum_os_version?
        if let maximumOSVersion = item["maximum_os_version"] as? String,
           !maximumOSVersion.isEmpty
        {
            display.debug1("Considering item \(name), version \(version) with maximum os version required \(maximumOSVersion)")
            display.debug1("Our OS version is \(osVersion)")
            if MunkiVersion(osVersion) > MunkiVersion(maximumOSVersion) {
                rejectedItems.append(
                    "Rejected item \(name), version \(version) with maximum os version required \(maximumOSVersion). Our OS version is \(osVersion)."
                )
                return false
            }
        }
        return true
    }

    /// Returns a boolean to indicate if the item is ok to install under
    /// the current CPU architecture. If not, also adds the failure reason to
    /// the rejected_items list.
    func cpuArchOK(_ item: PlistDict) -> Bool {
        guard let name = item["name"] as? String,
              let version = item["version"] as? String,
              let currentArch = machine["arch"] as? String
        else {
            display.error("Unexpected error getting item name or version or getting machine architecture")
            return false
        }
        if let supportedArchitectures = item["supported_architectures"] as? [String],
           !supportedArchitectures.isEmpty
        {
            display.debug1("Considering item \(name), version \(version) with supported architectures: \(supportedArchitectures)")
            display.debug1("Our architecture is \(currentArch)")
            if supportedArchitectures.contains(currentArch) {
                return true
            }
            if supportedArchitectures.contains("x86_64"),
               currentArch == "i386",
               machine["x86_64_capable"] as? Bool ?? false
            {
                return true
            }
            // we didn't find a supported architecture that
            // matches this machine
            rejectedItems.append(
                "Rejected item \(name), version \(version) with supported architectures \(supportedArchitectures). Our architecture is \(currentArch)."
            )
            return false
        }
        return true
    }

    /// Returns a boolean to indicate if an installable_condition predicate
    /// in the current item passes. If not, also adds the failure reason to
    /// the rejected_items list.
    func installableConditionOK(_ item: PlistDict) async -> Bool {
        guard let name = item["name"] as? String,
              let version = item["version"] as? String
        else {
            display.error("Unexpected error getting item name or version")
            return false
        }
        if let installableCondition = item["installable_condition"] as? String {
            let infoObject = await predicateInfoObject()
            if !predicateEvaluatesAsTrue(installableCondition, infoObject: infoObject) {
                rejectedItems.append(
                    "Rejected item \(name), version \(version) with installable_condition \(installableCondition)"
                )
                return false
            }
        }
        return true
    }

    /// Returns a boolean to indicate if this machine can use the item under
    /// its deployment, if any. Not being eligible is the feature working as intended,
    /// so it's logged at info level. An invalid deployment is logged as an error.
    /// Neither adds to the rejected_items list. If acceptNotEligible is true, a machine
    /// that isn't eligible can use the item anyway. An invalid deployment still fails.
    func deploymentOK(_ item: PlistDict) -> Bool {
        if skipDeploymentCheck {
            return true
        }
        let (rejection, reportEntry) = evaluateDeployment(item, machine: machine)
        let entryKey = "\(item["name"] as? String ?? "") \(item["version"] as? String ?? "")"
        if acceptNotEligible, case .notEligible = rejection {
            records.reportEntries[entryKey]?["eligible"] = true
            return true
        }
        // the first entry stays, so a later lookup doesn't undo the line above
        if let reportEntry, records.reportEntries[entryKey] == nil {
            records.reportEntries[entryKey] = reportEntry
        }
        guard let rejection else {
            return true
        }
        foundDeploymentRejection = true
        if !records.logged.insert(entryKey).inserted {
            return false
        }
        switch rejection {
        case let .notEligible(message):
            display.info(message)
        case let .invalid(message):
            display.error(message)
        }
        return false
    }

    var version = itemVersion
    var (name, includedVersion) = nameAndVersion(itemName, onlySplitOnHyphens: true)
    if !includedVersion.isEmpty, version.isEmpty {
        version = includedVersion
    }
    if !version.isEmpty {
        version = trimVersionString(version)
    } else {
        version = "latest"
    }
    if skipMinimumOSCheck {
        display.debug1("Looking for detail for: \(name), version \(version), ignoring minimum_os_version...")
    } else {
        display.debug1("Looking for detail for: \(name), version \(version)...")
    }
    // unicode normalize the name
    name = (name as NSString).precomposedStringWithCanonicalMapping

    for catalogName in catalogList {
        if let catalogDB = Catalogs.shared.get(catalogName),
           let namedTable = catalogDB["named"] as? CatalogDBTable,
           let itemsMatchingName = namedTable[name]
        {
            var indexList = [Int]()
            if version == "latest" {
                // order all our itemss, highest version first
                var versionList = Array(itemsMatchingName.keys)
                versionList.sort {
                    MunkiVersion($0) > MunkiVersion($1)
                }
                for versionKey in versionList {
                    indexList += itemsMatchingName[versionKey] ?? []
                }
            } else if let indexes = itemsMatchingName[version] {
                indexList = indexes
            }
            if !indexList.isEmpty {
                display.debug1("Considering \(indexList.count) items with name \(name) from catalog \(catalogName)")
            }
            for index in indexList {
                // iterate through list of items with matching name, highest
                // version first, looking for first one that passes all the
                // conditional tests (if any)
                if let items = catalogDB["items"] as? [PlistDict] {
                    let item = items[index]
                    if munkiVersionOK(item),
                       osVersionOK(item),
                       cpuArchOK(item),
                       await installableConditionOK(item),
                       deploymentOK(item)
                    {
                        display.debug1("Found \(item["name"] as? String ?? "<unknown>"), version \(item["version"] as? String ?? "<unknown>") in catalog \(catalogName)")
                        records.rejectedByDeployment.remove(name)
                        return item
                    }
                }
            }
        }
    }
    // if we got this far, we didn't find it
    display.debug1("No applicable item found for name '\(name)'")
    if foundDeploymentRejection, rejectedItems.isEmpty {
        records.rejectedByDeployment.insert(name)
    } else {
        records.rejectedByDeployment.remove(name)
    }
    for reason in rejectedItems {
        if suppressWarnings {
            display.debug1(reason)
        } else {
            display.warning(reason)
        }
    }
    return nil
}

/// Retrieves the catalogs from the server and populates our Catalogs object.
func getCatalogs(_ catalogList: [String]) {
    for catalogName in catalogList {
        if Catalogs.shared.list().contains(catalogName) {
            continue
        }
        guard let catalogPath = downloadCatalog(catalogName) else {
            display.error("Could not download catalog \(catalogName)")
            continue
        }
        do {
            if let catalogData = try readPlist(fromFile: catalogPath) as? [PlistDict] {
                Catalogs.shared.set(
                    catalogName,
                    to: makeCatalogDB(catalogData)
                )
            } else {
                throw PlistError.readError(description: "plist is in wrong format")
            }
        } catch {
            display.error("Retrieved catalog is invalid: \(error.localizedDescription)")
        }
    }
}

/// Removes any catalog files that are no longer in use by this client
func cleanUpCatalogs() {
    let catalogsToKeep = Catalogs.shared.list()
    let catalogsDir = managedInstallsDir(subpath: "catalogs")
    cleanUpDir(catalogsDir, keeping: catalogsToKeep)
}
