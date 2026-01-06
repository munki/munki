//
//  makecatalogslib.swift
//  munki
//
//  Created by Greg Neagle on 6/27/24.
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

enum MakeCatalogsError: Error {
    case PkginfoAccessError(description: String)
    case CatalogWriteError(description: String)
}

struct MakeCatalogOptions {
    var skipPkgCheck: Bool = false
    var force: Bool = false
    var verbose: Bool = false
}

/// Struct that handles building catalogs
struct CatalogsMaker {
    var repo: Repo
    var options: MakeCatalogOptions
    var pkgsinfoList: [String]
    var pkgsList: [String]
    var catalogs: [String: [PlistDict]]
    var errors: [String]
    var warnings: [String]

    init(repo: Repo,
         options: MakeCatalogOptions = MakeCatalogOptions()) async throws
    {
        self.repo = repo
        self.options = options
        catalogs = [String: [PlistDict]]()
        errors = [String]()
        warnings = [String]()
        pkgsinfoList = [String]()
        pkgsList = [String]()
        try await getPkgsinfoList()
        try await getPkgsList()
    }

    /// Returns a list of pkginfo identifiers
    mutating func getPkgsinfoList() async throws {
        do {
            pkgsinfoList = try await repo.list("pkgsinfo")
        } catch is MunkiError {
            throw MakeCatalogsError.PkginfoAccessError(
                description: "Error getting list of pkgsinfo items")
        }
    }

    /// Returns a list of pkg identifiers
    mutating func getPkgsList() async throws {
        do {
            pkgsList = try await repo.list("pkgs")
        } catch is MunkiError {
            throw MakeCatalogsError.PkginfoAccessError(
                description: "Error getting list of pkgs items")
        }
    }

    /// Builds a dictionary containing hashes for all our repo icons
    mutating func hashIcons() async -> [String: String] {
        if options.verbose {
            print("Getting list of icons...")
        }
        var iconHashes = [String: String]()
        if var iconList = try? await repo.list("icons") {
            // remove plist of hashes from the list
            if let index = iconList.firstIndex(of: "_icon_hashes.plist") {
                iconList.remove(at: index)
            }
            for icon in iconList {
                if options.verbose {
                    print("Hashing \(icon)...")
                }
                do {
                    let icondata = try await repo.get("icons/" + icon)
                    iconHashes[icon] = sha256hash(data: icondata)
                } catch let error as MunkiError {
                    errors.append("Error reading icons/\(icon): \(error.description)")
                } catch {
                    errors.append("Unexpected error reading icons/\(icon): \(error)")
                }
            }
        }
        return iconHashes
    }

    /// Returns a case-insensitive match for installer_item from pkgsList, if any
    func caseInsensitivePkgsListContains(_ installer_item: String) -> String? {
        for repo_pkg in pkgsList {
            if installer_item.lowercased() == repo_pkg.lowercased() {
                return repo_pkg
            }
        }
        return nil
    }

    /// Returns true if referenced installer items are present, false otherwise. Updates list of errors.
    mutating func verify(_ identifier: String, _ pkginfo: PlistDict) -> Bool {
        if let installer_type = pkginfo["installer_type"] as? String {
            if ["nopkg", "apple_update_metadata"].contains(installer_type) {
                // no associated installer item (pkg) for these types
                return true
            }
        }
        if !((pkginfo["PackageCompleteURL"] as? String ?? "").isEmpty) {
            // installer item may be on a different server
            return true
        }
        if !((pkginfo["PackageURL"] as? String ?? "").isEmpty) {
            // installer item may be on a different server
            return true
        }

        // Build path to installer item
        let installeritemlocation = pkginfo["installer_item_location"] as? String ?? ""
        if installeritemlocation.isEmpty {
            warnings.append(
                "WARNING: empty or invalid installer_item_location in \(identifier)")
            return false
        }

        // Check if the installer item actually exists
        if !(pkgsList.contains(installeritemlocation)) {
            // didn't find it in the pkgsList; let's look case-insensitive
            if let match = caseInsensitivePkgsListContains(installeritemlocation) {
                warnings.append(
                    "WARNING: \(identifier) refers to installer item: \(installeritemlocation). The pathname of the item in the repo has different case: \(match). This may cause issues depending on the case-sensitivity of the underlying filesystem."
                )
            } else {
                warnings.append(
                    "WARNING: \(identifier) refers to missing installer item: \(installeritemlocation)"
                )
                return false
            }
        }

        // uninstaller checking
        if let uninstalleritemlocation = pkginfo["uninstaller_item_location"] as? String {
            if uninstalleritemlocation.isEmpty {
                warnings.append(
                    "WARNING: empty or invalid uninstaller_item_location in \(identifier)")
                return false
            }
            // Check if the uninstaller item actually exists
            if !(pkgsList.contains(uninstalleritemlocation)) {
                // didn't find it in the pkgsList; let's look case-insensitive
                if let match = caseInsensitivePkgsListContains(uninstalleritemlocation) {
                    warnings.append(
                        "WARNING: \(identifier) refers to uninstaller item: \(uninstalleritemlocation). The pathname of the item in the repo has different case: \(match). This may cause issues depending on the case-sensitivity of the underlying filesystem."
                    )
                } else {
                    warnings.append(
                        "WARNING: \(identifier) refers to missing uninstaller item: \(uninstalleritemlocation)"
                    )
                    return false
                }
            }
        }
        // if we get here we passed all the checks
        return true
    }

    /// Processes pkginfo files and updates catalogs and errors instance variables
    mutating func processPkgsinfo() async {
        catalogs["all"] = [PlistDict]()
        // Walk through the pkginfo files
        for pkginfoName in pkgsinfoList {
            // Try to read the pkginfo file
            var pkginfo = PlistDict()
            let pkginfoIdentifier = "pkgsinfo/" + pkginfoName
            do {
                let data = try await repo.get(pkginfoIdentifier)
                pkginfo = try readPlist(fromData: data) as? PlistDict ?? PlistDict()
            } catch {
                errors.append("Unexpected error reading \(pkginfoIdentifier): \(error)")
                continue
            }
            if !(pkginfo.keys.contains("name")) {
                warnings.append("WARNING: \(pkginfoIdentifier) is missing name key")
                continue
            }
            // don't copy admin notes to catalogs
            if pkginfo.keys.contains("notes") {
                pkginfo["notes"] = nil
            }
            // strip out any keys that start with "_"
            for key in pkginfo.keys {
                if key.hasPrefix("_") {
                    pkginfo[key] = nil
                }
            }
            // sanity checking
            if !options.skipPkgCheck {
                let verified = verify(pkginfoIdentifier, pkginfo)
                if !verified, !options.force {
                    // Skip this pkginfo unless we're running with force flag
                    continue
                }
            }
            // append the pkginfo to the relevant catalogs
            catalogs["all"]?.append(pkginfo)
            if let catalog_list = pkginfo["catalogs"] as? [String] {
                if catalog_list.isEmpty {
                    warnings.append("WARNING: \(pkginfoIdentifier) has an empty catalogs array!")
                } else {
                    for catalog in catalog_list {
                        if !catalogs.keys.contains(catalog) {
                            catalogs[catalog] = [PlistDict]()
                        }
                        catalogs[catalog]?.append(pkginfo)
                        if options.verbose {
                            print("Adding \(pkginfoIdentifier) to \(catalog)...")
                        }
                    }
                }
            } else {
                warnings.append("WARNING: \(pkginfoIdentifier) has no catalogs array!")
            }
        }
        // look for catalog names that differ only in case
        var duplicateCatalogs = [String]()
        for name in catalogs.keys {
            let filtered_lowercase_names = catalogs.keys.filter { $0 != name }.map { $0.lowercased() }
            if filtered_lowercase_names.contains(name.lowercased()) {
                duplicateCatalogs.append(name)
            }
        }
        if !duplicateCatalogs.isEmpty {
            warnings.append(
                "WARNING: There are catalogs with names that differ only by case. " +
                    "This may cause issues depending on the case-sensitivity of the " +
                    "underlying filesystem: \(duplicateCatalogs)")
        }
    }

    /// Clear out old catalogs
    mutating func cleanupCatalogs() async {
        do {
            let catalogList = try await repo.list("catalogs")
            for catalogName in catalogList {
                if !(catalogs.keys.contains(catalogName)) {
                    let catalogIdentifier = "catalogs/" + catalogName
                    do {
                        try await repo.delete(catalogIdentifier)
                    } catch {
                        errors.append("Could not delete catalog \(catalogName): \(error)")
                    }
                }
            }
        } catch {
            errors.append("Could not get list of current catalogs to clean up: \(error)")
        }
    }

    /// Assembles all pkginfo files into catalogs.
    /// User calling this needs to be able to write to the repo/catalogs directory.
    /// Returns a list of any errors it encountered
    mutating func makecatalogs() async {
        // process pkgsinfo items
        await processPkgsinfo()

        // clean up old catalogs no longer needed
        await cleanupCatalogs()

        // write the new catalogs
        for key in catalogs.keys {
            if !(catalogs[key]?.isEmpty ?? true) {
                let catalogIdentifier = "catalogs/" + key
                do {
                    if let value = catalogs[key] {
                        let data = try plistToData(value)
                        try await repo.put(catalogIdentifier, content: data)
                        if options.verbose {
                            print("Created \(catalogIdentifier)...")
                        }
                    }
                } catch let PlistError.writeError(description) {
                    errors.append("Could not serialize catalog \(key): \(description)")
                } catch let error as MunkiError {
                    errors.append("Failed to create catalog \(key): \(error.description)")
                } catch {
                    errors.append("Unexpected error creating catalog \(key): \(error)")
                }
            }
        }

        // make icon hashes
        let iconHashes = await hashIcons()
        // create icon_hashes resource
        if !iconHashes.isEmpty {
            let iconHashesIdentifier = "icons/_icon_hashes.plist"
            do {
                let iconHashesData = try plistToData(iconHashes)
                try await repo.put(iconHashesIdentifier, content: iconHashesData)
                if options.verbose {
                    print("Created \(iconHashesIdentifier)...")
                }
            } catch let PlistError.writeError(description) {
                errors.append("Could not serialize icon hashes: \(description)")
            } catch let error as MunkiError {
                errors.append("Failed to create \(iconHashesIdentifier): \(error.description)")
            } catch {
                errors.append("Unexpected error creating \(iconHashesIdentifier): \(error)")
            }
        }
        return
    }
}
