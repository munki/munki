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
