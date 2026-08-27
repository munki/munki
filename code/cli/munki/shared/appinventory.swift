//
//  appinventory.swift
//  munki
//
//  Created by Greg Neagle on 8/9/24.
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

/// Do spotlight search for type applications within the
/// list of directories provided. Returns a list of paths to applications.
/// dirList is actually a list of NSMetadataQuery search scopes, which
/// can be paths, or certain constants
/// Typically we'll use NSMetadataQueryLocalComputerScope to search the
/// local computer (skipping mounted network volumes)
func findAppsInDirs(_ dirList: [String]) -> [[String: String]] {
    var appList = [[String: String]]()
    let query = NSMetadataQuery()
    query.predicate = NSPredicate(format: "(kMDItemKind = \"Application\")")
    query.searchScopes = dirList
    query.start()
    // Spotlight isGathering phase - this is the initial search. After the
    // isGathering phase Spotlight keeps running returning live results from
    // filesystem changes. We are not interested in that phase.
    // Run for 0.1 seconds then check if isGathering has completed.
    let maxRuntime = 20.0
    var runtime = 0.0
    while query.isGathering, runtime <= maxRuntime {
        runtime += 0.1
        RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.1))
    }
    query.stop()

    if runtime >= maxRuntime {
        display.warning(
            "Spotlight search for applications terminated due to excessive time. Possible causes: Spotlight indexing is turned off for a volume; Spotlight is reindexing a volume."
        )
    }

    let count = query.resultCount
    for index in 0 ..< count {
        if let result = query.result(at: index) as? NSMetadataItem,
           let path = result.value(forAttribute: NSMetadataItemPathKey) as? String,
           !path.hasPrefix("/Volumes")
        {
            let name = result.value(forAttribute: NSMetadataItemFSNameKey) as? String ?? ""
            let bundleID = result.value(forAttribute: NSMetadataItemCFBundleIdentifierKey) as? String ?? ""
            let version = result.value(forAttribute: NSMetadataItemVersionKey) as? String ?? ""

            if bundleID.isEmpty, version.isEmpty {
                // both bundleid and version are missing. is this really an app?
                if pathIsRegularFile(path), !pathIsExecutableFile(path) {
                    // it's a file, but not executable, so can't really be an app
                    continue
                }
            }

            appList.append(
                ["name": name,
                 "path": path,
                 "bundleid": bundleID,
                 "version": version]
            )
        }
    }
    return appList
}

/// Get paths of currently installed applications per Spotlight.
/// Return value is list of paths.
/// Currently searches only the local computer, but not network volumes
func spotlightInstalledApps() -> [[String: String]] {
    return findAppsInDirs([NSMetadataQueryLocalComputerScope])
}

/// private, undocumented LaunchServices function
@_silgen_name("_LSCopyAllApplicationURLs") func LSCopyAllApplicationURLs(_: UnsafeMutablePointer<NSMutableArray?>) -> OSStatus
func launchServicesInstalledApps() -> [String] {
    var apps: NSMutableArray?
    if LSCopyAllApplicationURLs(&apps) == 0 {
        if let appURLs = (apps! as NSArray) as? [URL] {
            let pathsArray = appURLs.map(\.path)
            return pathsArray
        }
    }
    return [String]()
}

/// Uses system profiler to get application info for this machine
/// Returns a dictionary with app paths as keys
func spApplicationData() async -> PlistDict {
    var applicationData = PlistDict()
    let tool = "/usr/sbin/system_profiler"
    let arguments = ["SPApplicationsDataType", "-xml"]
    do {
        let result = try await runCliAsync(tool, arguments: arguments, timeout: 120)
        if result.exitcode != 0 {
            throw ProcessError.error(description: result.error)
        }
        if let plist = try readPlist(fromString: result.output) as? [PlistDict] {
            // system_profiler xml is an array
            if let items = plist[0]["_items"] as? [PlistDict] {
                for item in items {
                    if let path = item["path"] as? String {
                        applicationData[path] = item
                    }
                }
            } else {
                throw PlistError.readError(description: "output is wrong format")
            }
        } else {
            throw PlistError.readError(description: "output is wrong format")
        }
    } catch let PlistError.readError(description) {
        display.warning("Could not parse output from system_profiler; skipping SPApplicationsDataType query: \(description)")
        return applicationData
    } catch ProcessError.timeout {
        display.warning("system_profiler hung; skipping SPApplicationsDataType query")
        return applicationData
    } catch let ProcessError.error(description) {
        display.warning("Unexpected error with system_profiler; skipping SPApplicationsDataType query: \(description)")
        return applicationData
    } catch {
        display.warning("Unexpected error with system_profiler; skipping SPApplicationsDataType query")
        return applicationData
    }

    return applicationData
}

/// Gets info on currently installed apps.
/// Returns a list of dicts containing path, name, version and bundleid
func getAppData() -> [[String: String]] {
    // one thing I'm not at all sure about is what iOS/iPadOS apps
    // installed on Apple silicon Macs look like and how/if
    // Launch Services, Spotlight, and system_profiler report them
    display.debug1("Getting info on currently installed applications...")
    let lsApps = launchServicesInstalledApps()
    let spotlightApps = spotlightInstalledApps()

    // find apps that are unique to the LaunchServices list
    let spotlightAppPaths = spotlightApps.map { $0["path"] ?? "" }.filter { !$0.isEmpty }
    let uniqueToLS = Set(lsApps).subtracting(Set(spotlightAppPaths))

    var applicationData = spotlightApps
    // add apps found by Launch Services that Spotlight didn't return
    for appPath in uniqueToLS {
        var item = [String: String]()
        item["path"] = appPath
        applicationData.append(item)
    }
    // now make sure as much additional data is populated as possible
    for (index, item) in applicationData.enumerated() {
        var updatedItem = item
        let path = item["path"] ?? ""
        if let bundleInfo = getBundleInfo(path) {
            updatedItem["bundleid"] = bundleInfo["CFBundleIdentifier"] as? String ?? ""
            if let cfBundleName = bundleInfo["CFBundleName"] as? String,
               !cfBundleName.isEmpty
            {
                updatedItem["name"] = cfBundleName
            } else {
                let name = ((item["path"] ?? "") as NSString).lastPathComponent
                updatedItem["name"] = (name as NSString).deletingPathExtension
            }
            updatedItem["version"] = getBundleVersion(path)
            if (updatedItem["version"] ?? "").isEmpty {
                updatedItem["version"] = item["version"] ?? "0.0.0.0.0"
            }
        }
        applicationData[index] = updatedItem
    }
    return applicationData
}

/// A Singleton class for application inventory info, since it's expensive  to generate
class ApplicationInventory {
    static let shared = ApplicationInventory()

    var inventory: [[String: String]]

    private init() {
        inventory = getAppData()
    }

    func get() -> [[String: String]] {
        return inventory
    }

    func rescan() {
        // force a rescan of app inventory
        inventory = getAppData()
    }
}

/// Return (possibly cached) installed application data
func appData() -> [[String: String]] {
    return ApplicationInventory.shared.get()
}

/// Returns a filtered version of app_data, filtering out apps in user
/// home directories for use by compare_application_version()
func filteredAppData() -> [[String: String]] {
    return appData().filter {
        !(($0["path"] ?? "").hasPrefix("/Users") && !($0["path"] ?? "").hasPrefix("/Users/Shared"))
    }
}

/// Save installed application data
/// data from appData() is meant for use by updatecheck
/// we need to massage it a bit for more general usage
func saveAppData() {
    munkiLog("Saving application inventory...")
    var appInventory = [[String: String]]()
    for item in appData() {
        var inventoryItem = [String: String]()
        inventoryItem["CFBundleName"] = item["name"] ?? ""
        inventoryItem["bundleid"] = item["bundleid"] ?? ""
        inventoryItem["version"] = item["version"] ?? ""
        inventoryItem["path"] = item["path"] ?? ""
        // use last path item (minus '.app' if present) as name
        let name = ((item["path"] ?? "") as NSString).lastPathComponent
        inventoryItem["name"] = (name as NSString).deletingPathExtension
        appInventory.append(inventoryItem)
    }
    do {
        let appInventoryPath = managedInstallsDir(subpath: "ApplicationInventory.plist")
        try writePlist(appInventory, toFile: appInventoryPath)
    } catch {
        display.warning("Unable to save application inventory: \(error.localizedDescription)")
    }
}
