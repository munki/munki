//
//  MUmanifestEditing.swift
//  manifestutil
//
//  Created by Greg Neagle on 4/14/25.
//
//  Copyright 2024-2025 Greg Neagle.
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

import ArgumentParser
import Foundation

/// Adds an item to a section of a manifest
func addManifestItem(repo: Repo, manifestName: String, section: String, item: String, addToTop: Bool = false) -> Bool {
    guard var manifest = getManifest(repo: repo, name: manifestName) else {
        return false
    }
    var sectionItems = manifest[section] as? [String] ?? []
    if sectionItems.contains(item) {
        printStderr("'\(item)' is already in \(section) of manifest \(manifestName)")
        return false
    }
    if addToTop {
        sectionItems.insert(item, at: 0)
    } else {
        sectionItems.append(item)
    }
    manifest[section] = sectionItems
    if saveManifest(repo: repo, manifest: manifest, name: manifestName, overwrite: true) {
        print("Added '\(item)' to \(section) of manifest \(manifestName).")
        return true
    }
    return false
}

/// Remove item from section of manifest
func removeManifestItem(repo: Repo, manifestName: String, section: String, item: String) -> Bool {
    guard var manifest = getManifest(repo: repo, name: manifestName) else {
        return false
    }
    var sectionItems = manifest[section] as? [String] ?? []
    if let index = sectionItems.firstIndex(of: item) {
        sectionItems.remove(at: index)
        manifest[section] = sectionItems
        if saveManifest(repo: repo, manifest: manifest, name: manifestName, overwrite: true) {
            print("Removed '\(item)' from \(section) of manifest \(manifestName).")
            return true
        }
    }
    printStderr("'\(item)' is not in \(section) of manifest \(manifestName).")
    return false
}

/// Adds a catalog to a manifest.
func addCatalog(repo: Repo, manifestName: String, catalogName: String) -> Bool {
    let availableCatalogs = getCatalogNames(repo: repo) ?? []
    if !availableCatalogs.contains(catalogName) {
        printStderr("Unknown catalog name: '\(catalogName)'")
        return false
    }
    return addManifestItem(repo: repo, manifestName: manifestName, section: "catalogs", item: catalogName, addToTop: true)
}

/// Adds a pkg (item) to a manifest
func addPkg(repo: Repo, manifestName: String, pkgName: String, section: String = "managed_installs") -> Bool {
    let validPkgSections = [
        "managed_installs",
        "managed_uninstalls",
        "managed_updates",
        "optional_installs",
        "featured_items",
        "default_installs",
    ]
    let mutuallyExclusiveSections = [
        "managed_installs",
        "managed_uninstalls",
        "optional_installs",
    ]
    let optionalInstallsNeededSections = [
        "featured_items",
        "default_installs",
    ]
    if !validPkgSections.contains(section) {
        printStderr("Section name: '\(section)' is not supported for adding packages")
        return false
    }
    guard let manifest = getManifest(repo: repo, name: manifestName) else {
        return false
    }
    if mutuallyExclusiveSections.contains(section) {
        for checkSection in mutuallyExclusiveSections {
            if let sectionItems = manifest[checkSection] as? [String] {
                if sectionItems.contains(pkgName) {
                    printStderr("Item '\(pkgName)' is already in \(checkSection) of manifest \(manifestName)")
                    return false
                }
            }
        }
    }
    let defaultInstallsItems = manifest["optional_installs"] as? [String] ?? []
    if optionalInstallsNeededSections.contains(section), !defaultInstallsItems.contains(pkgName) {
        printStderr("Item '\(pkgName)' must also be in optional_installs of manifest \(manifestName)")
        return false
    }
    if let manifestCatalogs = manifest["catalogs"] as? [String],
       !manifestCatalogs.isEmpty
    {
        let availablePkgNames = getInstallerItemNames(repo: repo, catalogs: manifestCatalogs)
        if !availablePkgNames.contains(pkgName) {
            printStderr("WARNING: Item '\(pkgName)' is not available in any catalog of manifest \(manifestName)")
        }
    }
    return addManifestItem(repo: repo, manifestName: manifestName, section: section, item: pkgName)
}

/// Moves an item from managed\_installs to managed\_uninstalls
func moveInstallToUninstall(repo: Repo, manifestName: String, item: String) -> Bool {
    guard var manifest = getManifest(repo: repo, name: manifestName) else {
        return false
    }
    var managedInstalls = manifest["managed_installs"] as? [String] ?? []
    if let index = managedInstalls.firstIndex(of: item) {
        managedInstalls.remove(at: index)
    } else {
        printStderr("Item '\(item)' not found in managed_installs of manifest \(manifestName). No changes made.")
        return false
    }
    var managedUninstalls = manifest["managed_uninstalls"] as? [String] ?? []
    var managedUninstallsMessage = ""
    if managedUninstalls.contains(item) {
        managedUninstallsMessage = "Item '\(item)' is already in managed_uninstalls of manifest \(manifestName)."
    } else {
        managedUninstalls.append(item)
        managedUninstallsMessage = "Added '\(item)' to managed_uninstalls of manifest \(manifestName)."
    }
    manifest["managed_installs"] = managedInstalls
    manifest["managed_uninstalls"] = managedUninstalls
    if saveManifest(repo: repo, manifest: manifest, name: manifestName, overwrite: true) {
        print("Removed '\(item)' from managed_installs of manifest \(manifestName)")
        print(managedUninstallsMessage)
        return true
    }
    return false
}

/// Add a (pkg) item to a manifest
extension ManifestUtil {
    struct AddPkg: ParsableCommand {
        static var configuration = CommandConfiguration(
            abstract: "Adds a package to a manifest")

        @Option(help: ArgumentHelp("Name of manifest",
                                   valueName: "manifest-name"))
        var manifest: String

        @Option(help: ArgumentHelp("Manifest section",
                                   valueName: "manifest-section"))
        var section: String = "managed_installs"

        @Argument(help: ArgumentHelp(
            "Name of the pkgitem to be added",
            valueName: "pkgitem-name"
        ))
        var pkgName: String

        func run() throws {
            guard let repo = try? connectToRepo() else { return }
            _ = addPkg(repo: repo, manifestName: manifest, pkgName: pkgName, section: section)
        }
    }
}

/// Remove a pkg from a manifest
extension ManifestUtil {
    struct RemovePkg: ParsableCommand {
        static var configuration = CommandConfiguration(
            abstract: "Removes a package from a manifest")

        @Option(help: ArgumentHelp("Name of manifest",
                                   valueName: "manifest-name"))
        var manifest: String

        @Option(help: ArgumentHelp("Manifest section",
                                   valueName: "manifest-section"))
        var section: String = "managed_installs"

        @Argument(help: ArgumentHelp(
            "Name of the pkgitem to be removed",
            valueName: "pkgitem-name"
        ))
        var pkgName: String

        func run() throws {
            guard let repo = try? connectToRepo() else { return }
            _ = removeManifestItem(repo: repo, manifestName: manifest, section: section, item: pkgName)
        }
    }
}

/// Move a pkg from managed\_installs to managed\_uninstalls in a manifest
extension ManifestUtil {
    struct MoveInstallToUninstall: ParsableCommand {
        static var configuration = CommandConfiguration(
            abstract: "Moves a pkgitem from managed_installs to managed_uninstalls in a manifest")

        @Option(help: ArgumentHelp("Name of manifest",
                                   valueName: "manifest-name"))
        var manifest: String

        @Argument(help: ArgumentHelp(
            "Name of the pkgitem to be moved",
            valueName: "pkgitem-name"
        ))
        var pkgName: String

        func run() throws {
            guard let repo = try? connectToRepo() else { return }
            _ = moveInstallToUninstall(repo: repo, manifestName: manifest, item: pkgName)
        }
    }
}

/// Add a catalog to a manifest
extension ManifestUtil {
    struct AddCatalog: ParsableCommand {
        static var configuration = CommandConfiguration(
            abstract: "Adds a catalog to a manifest")

        @Option(help: ArgumentHelp("Name of manifest",
                                   valueName: "manifest-name"))
        var manifest: String

        @Argument(help: ArgumentHelp(
            "Name of the catalog to be added",
            valueName: "catalog-name"
        ))
        var catalogName: String

        func run() throws {
            guard let repo = try? connectToRepo() else { return }
            _ = addCatalog(repo: repo, manifestName: manifest, catalogName: catalogName)
        }
    }
}

/// Remove a catalog from a manifest
extension ManifestUtil {
    struct RemoveCatalog: ParsableCommand {
        static var configuration = CommandConfiguration(
            abstract: "Removes a catalog from a manifest")

        @Option(help: ArgumentHelp("Name of manifest",
                                   valueName: "manifest-name"))
        var manifest: String

        @Argument(help: ArgumentHelp(
            "Name of the catalog to be removed",
            valueName: "catalog-name"
        ))
        var catalogName: String

        func run() throws {
            guard let repo = try? connectToRepo() else { return }
            _ = removeManifestItem(repo: repo, manifestName: manifest, section: "catalogs", item: catalogName)
        }
    }
}
