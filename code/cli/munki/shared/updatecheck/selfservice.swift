//
//  selfservice.swift
//  munki
//
//  Created by Greg Neagle on 8/20/24.
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

/// Returns path to "system" SelfServeManifest/
func selfServiceManifestPath() -> String {
    return managedInstallsDir(subpath: "manifests/SelfServeManifest")
}

/// Promotes a user-writable plist from /Users/Shared into a root-owned location:
/// validates it by reading, writes it to the system path, then removes the
/// staging file. Includes a symlink guard, since the staging file is
/// user-writable and a symlink there could point at things unprivileged users
/// should not be able to read.
func promoteUserWritablePlist(from userPath: String, to systemPath: String, label: String) {
    if pathIsSymlink(userPath) {
        // not allowed as it could link to things not normally
        // readable by unprivileged users
        try? FileManager.default.removeItem(atPath: userPath)
        display.warning("Found symlink at \(userPath). Ignoring and removing.")
    }
    if !pathExists(userPath) {
        // nothing to do!
        return
    }
    // read the user-generated file to ensure it's valid, then write it
    // to the system location
    do {
        if let plist = try readPlist(fromFile: userPath) {
            try writePlist(plist, toFile: systemPath)
            try? FileManager.default.removeItem(atPath: userPath)
        } else {
            display.error("Could not read \(userPath): data was nil")
            try? FileManager.default.removeItem(atPath: userPath)
        }
    } catch let PlistError.readError(description) {
        display.error("Could not read \(userPath): \(description)")
        try? FileManager.default.removeItem(atPath: userPath)
    } catch let PlistError.writeError(description) {
        display.error("Could not write \(systemPath): \(description)")
    } catch {
        display.error("Unexpected error reading or writing \(label): \(error.localizedDescription)")
    }
}

/// Updates the SelfServeManifest from a user-writable copy if it exists.
func updateSelfServeManifest() {
    promoteUserWritablePlist(
        from: "/Users/Shared/.SelfServeManifest",
        to: selfServiceManifestPath(),
        label: "SelfServeManifest")
}

/// Returns the path to the root-owned low-data overrides plist. This records the
/// items the user has chosen to "Download anyway" while on a low-data
/// connection. Format: a dict with an "items" key holding an array of item
/// names, e.g. { "items": ["GoogleChrome"] }.
func lowDataOverridesPath() -> String {
    return managedInstallsDir(subpath: "LowDataOverrides.plist")
}

/// Updates the low-data overrides from a user-writable copy if it exists.
/// Managed Software Center (running as the user) writes the user's "Download
/// anyway" choices to /Users/Shared/.low_data_overrides.plist; this promotes
/// that staging file into the root-owned location and removes it.
func updateLowDataOverrides() {
    promoteUserWritablePlist(
        from: "/Users/Shared/.low_data_overrides.plist",
        to: lowDataOverridesPath(),
        label: "low-data overrides")
}

private var cachedLowDataOverrideItems: [String]?

/// Returns the list of item names the user has chosen to download anyway on a
/// low-data connection. Cached once per run: the overrides file is staged at the
/// start of the check and does not change while items are processed, so we don't
/// re-read it for every deferred item.
func lowDataOverrideItems() -> [String] {
    if let cached = cachedLowDataOverrideItems {
        return cached
    }
    var items = [String]()
    if let raw = try? readPlist(fromFile: lowDataOverridesPath()),
       let plist = raw as? PlistDict,
       let list = plist["items"] as? [String]
    {
        items = list
    }
    cachedLowDataOverrideItems = items
    return items
}

/// Removes the given item names from the low-data overrides. Used to consume a
/// one-time "download anyway" override when the item is being downloaded, so a
/// stale override can't later authorize a newer version over low data.
func removeLowDataOverrides(names: [String]) {
    let systemOverrides = lowDataOverridesPath()
    guard pathExists(systemOverrides),
          let raw = try? readPlist(fromFile: systemOverrides),
          var plist = raw as? PlistDict,
          let items = plist["items"] as? [String]
    else {
        return
    }
    let remaining = items.filter { !names.contains($0) }
    if remaining.count == items.count {
        // nothing to prune
        return
    }
    if remaining.isEmpty {
        try? FileManager.default.removeItem(atPath: systemOverrides)
        return
    }
    plist["items"] = remaining
    do {
        try writePlist(plist, toFile: systemOverrides)
    } catch {
        display.error("Could not write \(systemOverrides): \(error.localizedDescription)")
    }
}

/// Process a default installs item. Potentially add it to managed_installs
/// in the SelfServeManifest
func processDefaultInstalls(_ defaultItems: [String]) {
    let selfServeManifest = selfServiceManifestPath()
    var manifest = PlistDict()
    if pathExists(selfServeManifest) {
        do {
            manifest = try readPlist(fromFile: selfServeManifest) as? PlistDict ?? PlistDict()
        } catch {
            display.error("Could not read \(selfServeManifest): \(error.localizedDescription)")
            return
        }
    }

    for key in ["default_installs", "managed_installs"] {
        if !manifest.keys.contains(key) {
            manifest[key] = [String]()
        }
    }

    var manifestChanged = false
    for item in defaultItems {
        if var defaultInstalls = manifest["default_installs"] as? [String],
           !defaultInstalls.contains(item)
        {
            defaultInstalls.append(item)
            manifest["default_installs"] = defaultInstalls
            if var managedInstalls = manifest["managed_installs"] as? [String],
               !managedInstalls.contains(item)
            {
                managedInstalls.append(item)
                manifest["managed_installs"] = managedInstalls
            }
            manifestChanged = true
        }
    }

    if manifestChanged {
        do {
            try writePlist(manifest, toFile: selfServeManifest)
        } catch {
            display.error("Could not write \(selfServeManifest): \(error.localizedDescription)")
        }
    }
}

/// Removes any already-removed items from the SelfServeManifest's
/// managed_uninstalls (So the user can later install them again if they wish)
func cleanUpSelfServeManagedUninstalls(_ installInfoRemovals: [PlistDict]) {
    let selfServeManifest = selfServiceManifestPath()
    if !pathExists(selfServeManifest) {
        // nothing to do
        return
    }
    var plist: PlistDict
    do {
        plist = try readPlist(fromFile: selfServeManifest) as? PlistDict ?? PlistDict()
    } catch {
        display.error("Could not read \(selfServeManifest): \(error.localizedDescription)")
        return
    }
    let removedItemNames: [String]
    // filter removals to get items already removed
    // (or never installed)
    removedItemNames = installInfoRemovals.filter {
        $0["installed"] is Bool && !($0["installed"] as? Bool ?? false)
    }.map {
        $0["name"] as? String ?? ""
    }
    // for any item in the managed_uninstalls in the self-serve
    // manifest that is not installed, we should remove it from
    // the list
    if var managedUninstalls = plist["managed_uninstalls"] as? [String] {
        managedUninstalls = managedUninstalls.filter {
            !removedItemNames.contains($0)
        }
        plist["managed_uninstalls"] = managedUninstalls
        do {
            try writePlist(plist, toFile: selfServeManifest)
        } catch {
            display.error("Could not write \(selfServeManifest): \(error.localizedDescription)")
        }
    }
}
