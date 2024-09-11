//
//  compare.swift
//  munki
//
//  Created by Greg Neagle on 8/19/24.
//

import Foundation

enum MunkiComparisonResult: Int {
    case older = -1
    case notPresent = 0
    case same = 1
    case newer = 2

    static let different = MunkiComparisonResult.older
}

let comparisonResultDescriptions = [
    "older",
    "not present",
    "the same",
    "newer",
]

/// Compares two version numbers to one another.
/// Returns MunkiComparisonResult (one of .older, .same, .newer)
func compareVersions(_ thisVersion: String, _ thatVersion: String) -> MunkiComparisonResult {
    if MunkiVersion(thisVersion) < MunkiVersion(thatVersion) {
        return .older
    }
    if MunkiVersion(thisVersion) == MunkiVersion(thatVersion) {
        return .same
    }
    return .newer
}

/// Gets the version string from the plist at path and compares versions with plistItem
/// May throw a MunkiError if there's an error in the input
func comparePlistVersion(_ item: PlistDict) throws -> MunkiComparisonResult {
    let versionComparisonKey = item["version_comparison_key"] as? String ?? "CFBundleShortVersionString"
    guard let path = item["path"] as? String,
          let versionString = item[versionComparisonKey] as? String
    else {
        throw MunkiError("Missing plist path or version!")
    }
    let minimumUpdateVersion = item["minimum_update_version"] as? String
    displayDebug1("\tChecking \(path) for \(versionComparisonKey) \(versionString)...")
    if !pathExists(path) {
        displayDebug1("\tNo file found at \(path)")
        return .notPresent
    }
    guard let plist = try? readPlist(fromFile: path) as? PlistDict else {
        displayDebug1("\t\(path) can't be read as a plist!")
        return .notPresent
    }
    let installedVersion: String
    if item.keys.contains("version_comparison_key") {
        // specific key has been supplied,
        // so use this to determine installed version
        displayDebug1("\tUsing version_comparison_key \(versionComparisonKey)")
        installedVersion = getVersionString(plist: plist, key: versionComparisonKey)
    } else {
        // just use default behavior
        installedVersion = getVersionString(plist: plist)
    }
    if installedVersion.isEmpty {
        displayDebug1("\tNo version info in \(path).")
        return .notPresent
    }
    displayDebug1("\tInstalled item has version \(installedVersion)")
    if let minimumUpdateVersion {
        if compareVersions(installedVersion, minimumUpdateVersion) == .older {
            displayDebug1("\tInstalled version \(installedVersion) is too old to update (must be \(minimumUpdateVersion) or later)")
            return .notPresent
        }
    }
    let comparisonResult = compareVersions(installedVersion, versionString)
    displayDebug1("\tInstalled item is \(comparisonResultDescriptions[comparisonResult.rawValue + 1])")
    return comparisonResult
}

/// Compares bundle described in bundleItem with what is actually on-disk.
/// May throw a MunkiError if there's an error in the input
func compareBundleVersion(_ bundleItem: PlistDict) throws -> MunkiComparisonResult {
    if let path = bundleItem["path"] as? NSString {
        var infoPlistPath = path.appendingPathComponent("Contents/Info.plist")
        if !pathExists(infoPlistPath) {
            displayDebug1("\tNo Info.plist found at \(infoPlistPath)")
            infoPlistPath = path.appendingPathComponent("Resources/Info.plist")
            if !pathExists(infoPlistPath) {
                displayDebug1("\tNo Info.plist found at \(infoPlistPath)")
                return .notPresent
            }
        }
        displayDebug1("\tFound Info.plist at \(infoPlistPath)")
        var plistItem = bundleItem
        plistItem["path"] = infoPlistPath
        return try comparePlistVersion(plistItem)
    }
    return .notPresent
}

/// Compares app described in appItem with what is actually on-disk.
/// Checks the given path if it's available,
/// otherwise uses LaunchServices and/or Spotlight to look for the app
/// May throw a MunkiError if there's an error in the input
func compareApplicationVersion(_ appItem: PlistDict) throws -> MunkiComparisonResult {
    if let path = appItem["path"] as? String {
        if !pathExists(path) {
            displayDebug2("Application is not present at \(path).")
            return .notPresent
        }
        let infoPlistPath = (path as NSString).appendingPathComponent("Contents/Info.plist")
        if !pathExists(infoPlistPath) {
            displayDebug2("Application Info.plist does not exist.")
            return .notPresent
        }
        return try compareBundleVersion(appItem)
    }
    // no 'path' in appItem
    displayDebug2("No path provided for application item.")
    let bundleName = appItem["CFBundleName"] as? String ?? ""
    let bundleID = appItem["CFBundleIdentifier"] as? String ?? ""
    let versionComparisonKey = appItem["version_comparison_key"] as? String ?? "CFBundleShortVersionString"
    let versionString = appItem[versionComparisonKey] as? String ?? ""

    if bundleName.isEmpty, bundleID.isEmpty {
        // we have no path, no bundleName, no bundle identifier. Error!
        throw MunkiError("No path, bundle name or bundle identifier was specified!")
    }

    displayDebug1("Looking for application \(bundleName) with bundleid: \(bundleID), version \(versionString)...")

    // find installed apps that match this item by name or bundleid
    let appData = filteredAppData()
    var appInfo = appData.filter {
        $0["path"] != nil &&
            (($0["bundleid"] ?? "<nobundleid>") == bundleID ||
                ($0["name"] ?? "<nobundlename>") == bundleName)
    }

    if appInfo.isEmpty {
        // no matching apps found
        displayDebug1("\tFound no matching applications on the startup disk.")
        return .notPresent
    }

    // sort highest version first
    appInfo.sort {
        MunkiVersion($0["version"] ?? "") > MunkiVersion($1["version"] ?? "")
    }

    // iterate through matching apps
    var endResult = MunkiComparisonResult.notPresent
    for item in appInfo {
        displayDebug2("\tFound name: \(item["name"] ?? "<none>")")
        displayDebug2("\tFound path: \(item["path"] ?? "<none>")")
        displayDebug2("\tFound CFBundleIdentifier: \(item["bundleid"] ?? "<none>")")
        // create a test item to use for comparison
        var testItem = appItem
        testItem["path"] = item["path"]
        let compareResult = try compareBundleVersion(testItem)
        if compareResult == .same || compareResult == .newer {
            return compareResult
        }
        if compareResult == .older {
            endResult = .older
        }
    }

    // didn't find an app with the same or higher version
    if endResult == .older {
        displayDebug1("An older version of this application is present.")
    }
    return endResult
}

/// Returns the status of the local filesystem item as compared to
/// the passed-in dictionary
///
/// If item has md5checksum attribute, compares on disk file's checksum.
///
/// Throws a MunkiError if there's a problwm with the input
func filesystemItemStatus(_ item: PlistDict) throws -> MunkiComparisonResult {
    guard let filepath = item["path"] as? String else {
        throw MunkiError("No path specified for filesystem item")
    }
    displayDebug1("Checking existence of \(filepath)...")
    if pathExists(filepath) {
        displayDebug2("\tExists.")
        if let expectedChecksum = item["md5checksum"] as? String {
            displayDebug2("Comparing checksums...")
            let onDiskChecksum = md5hash(file: filepath)
            if onDiskChecksum == expectedChecksum {
                displayDebug2("Checksums match.")
                return .same
            }
            // onDiskChecksum != expectedChecksum
            displayDebug2("Checksums differ: expected \(expectedChecksum), found \(onDiskChecksum)")
            return .different
        }
        // md5checksum not in item, but item is present
        return .same
    }
    // path doesn't exist
    return .notPresent
}

/// Compares an installs_item with what's on the startup disk.
/// Wraps other comparison functions.
/// Returns a MunkiComparisonResult
/// Can throw MunkiError on bad input
func compareItem(_ item: PlistDict) throws -> MunkiComparisonResult {
    guard let type = item["type"] as? String else {
        throw MunkiError("Item type was not defined")
    }
    switch type {
    case "application":
        return try compareApplicationVersion(item)
    case "bundle":
        return try compareBundleVersion(item)
    case "plist":
        return try comparePlistVersion(item)
    case "file":
        return try filesystemItemStatus(item)
    default:
        throw MunkiError("Unknown or unsupported installs item type: \(type)")
    }
}

/// Determines if the given package is already installed.
/// Input: dict with receipt info
/// Returns a MunkiComparisonResult
/// Can throw MunkiError on bad input
func compareReceipt(_ item: PlistDict) async throws -> MunkiComparisonResult {
    if item["optional"] as? Bool ?? false {
        // receipt has been marked as optional, so it doesn't matter
        // if it's installed or not. Return .same
        // only check receipts not marked as optional
        return .same
    }
    guard let pkgid = item["packageid"] as? String,
          let receiptVersion = item["version"] as? String
    else {
        throw MunkiError("Receipt item is missing packageid or version info!")
    }
    displayDebug1("Looking for package \(pkgid), version \(receiptVersion)")
    let installedPkgs = await getInstalledPackages()
    if let installedVersion = installedPkgs[pkgid] {
        return compareVersions(installedVersion, receiptVersion)
    }
    // no installedVersion
    displayDebug1("\tThis package is not currently installed.")
    return .notPresent
}

/// Attempts to determine the currently installed version of an item.
///
/// Args:
/// pkginfo: pkginfo plist of an item to get the version for.
///
/// Returns:
/// String version of the item, or 'UNKNOWN' if unable to determine
func getInstalledVersion(_ pkginfo: PlistDict) -> String {
    func versionFromPlist(_ path: String) -> String? {
        do {
            if let plist = try readPlist(fromFile: path) as? PlistDict {
                return plist["CFBundleShortVersionString"] as? String ?? "UNKNOWN"
            }
            displayDebug2("plist \(path) in wrong format")
        } catch {
            displayDebug2("plist \(path) read error: \(error.localizedDescription)")
        }
        return nil
    }

    let itemName = pkginfo["name"] as? String ?? "<unknown>"
    let itemVersion = pkginfo["version"] as? String ?? "-1"

    // try receipts
    let receipts = pkginfo["receipts"] as? [PlistDict] ?? []
    for receipt in receipts {
        // look for a receipt whose version matches the pkginfo version
        // (there is no guarantee at all that a receipt/pkg version matches
        //  the version of the software installed by the package)
        if let pkgid = receipt["packageid"] as? String,
           let receiptVersion = receipt["version"] as? String,
           compareVersions(receiptVersion, itemVersion) == .same
        {
            displayDebug2("Using receipt \(pkgid) to determine installed version of \(itemName)")
            if let pkgVersion = getInstalledPackageVersion(pkgid) {
                return pkgVersion
            }
        }
    }
    // try using installs_array
    if let installItems = pkginfo["installs"] as? [PlistDict] {
        // filter out items that don't actually have version info
        let installItemsWithVersions = installItems.filter {
            $0["CFBundleShortVersionString"] != nil
        }
        for installItem in installItemsWithVersions {
            // look for an installs item whose version matches the pkginfo version
            guard let itemType = installItem["type"] as? String,
                  let installItemVersion = installItem["CFBundleShortVersionString"] as? String
            else {
                continue
            }
            if compareVersions(installItemVersion, itemVersion) != .same {
                continue
            }
            let path = installItem["path"] as? String ?? "<unknown>"
            if itemType == "application" {
                displayDebug2("Using application \(path) to determine installed version of \(itemName)")
                if path != "<unknown>" {
                    let infopath = (path as NSString).appendingPathComponent("Contents/Info.plist")
                    if let installedVersion = versionFromPlist(infopath) {
                        return installedVersion
                    }
                }
                // find installed apps that match this item by name or bundleid
                let bundleName = installItem["CFBundleName"] as? String ?? ""
                let bundleID = installItem["CFBundleIdentifier"] as? String ?? ""
                let appData = filteredAppData()
                var appInfo = appData.filter {
                    $0["path"] != nil &&
                        (($0["bundleid"] ?? "<nobundleid>") == bundleID ||
                            ($0["name"] ?? "<nobundlename>") == bundleName)
                }

                if appInfo.isEmpty {
                    // no matching apps found
                    displayDebug1("\tFound no matching applications on the startup disk.")
                    continue
                }

                // sort highest version first
                appInfo.sort {
                    MunkiVersion($0["version"] ?? "") > MunkiVersion($1["version"] ?? "")
                }
                if let installedVersion = appInfo[0]["version"] {
                    return installedVersion
                }
            } else if itemType == "bundle" {
                displayDebug2("Using bundle \(path) to determine installed version of \(itemName)")
                let infopath = (path as NSString).appendingPathComponent("Contents/Info.plist")
                if let installedVersion = versionFromPlist(infopath) {
                    return installedVersion
                }
            } else if itemType == "plist" {
                displayDebug2("Using plist \(path) to determine installed version of \(itemName)")
                if let installedVersion = versionFromPlist(path) {
                    return installedVersion
                }
            }
        }
    }
    // if we fall through to here we have no idea what version we have
    return "UNKNOWN"
}
