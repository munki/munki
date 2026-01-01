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

/// Updates the SelfServeManifest from a user-writable copy if it exists.
func updateSelfServeManifest() {
    let userManifest = "/Users/Shared/.SelfServeManifest"
    let systemManifest = selfServiceManifestPath()
    if pathIsSymlink(userManifest) {
        // not allowed as it could link to things not normally
        // readable by unprivileged users
        try? FileManager.default.removeItem(atPath: userManifest)
        display.warning("Found symlink at \(userManifest). Ignoring and removing.")
    }
    if !pathExists(userManifest) {
        // nothing to do!
        return
    }
    // read the user-generated manifest to ensure it's valid, then write it
    // to the system manifest location
    do {
        if let plist = try readPlist(fromFile: userManifest) {
            try writePlist(plist, toFile: systemManifest)
            try? FileManager.default.removeItem(atPath: userManifest)
        } else {
            display.error("Could not read \(userManifest): data was nil")
            try? FileManager.default.removeItem(atPath: userManifest)
        }
    } catch let PlistError.readError(description) {
        display.error("Could not read \(userManifest): \(description)")
        try? FileManager.default.removeItem(atPath: userManifest)
    } catch let PlistError.writeError(description) {
        display.error("Could not write \(systemManifest): \(description)")
    } catch {
        display.error("Unexpected error reading or writing SelfServeManifest: \(error.localizedDescription)")
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
