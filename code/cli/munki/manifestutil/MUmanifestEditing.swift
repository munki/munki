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

/// Adds a catalog to a manifest.
func addCatalog(repo: Repo, manifestName: String, catalogName: String) -> Bool {
    let availableCatalogs = getCatalogNames(repo: repo) ?? []
    if !availableCatalogs.contains(catalogName) {
        printStderr("Unknown catalog name: \(catalogName)")
        return false
    }
    guard var manifest = getManifest(repo: repo, name: manifestName) else {
        return false
    }
    var catalogs = manifest["catalogs"] as? [String] ?? []
    if catalogs.contains(catalogName) {
        printStderr("Catalog \(catalogName) is already in manifest \(manifestName)")
        return false
    }
    // put it at the front of the catalog list as that is usually
    // what is wanted...
    catalogs.insert(catalogName, at: 0)
    manifest["catalogs"] = catalogs
    if saveManifest(repo: repo, manifest: manifest, name: manifestName, overwrite: true) {
        print("Added \(catalogName) to catalogs of manifest \(manifestName).")
        return true
    }
    return false
}

func removeCatalog(repo: Repo, manifestName: String, catalogName: String) -> Bool {
    guard var manifest = getManifest(repo: repo, name: manifestName) else {
        return false
    }
    var catalogs = manifest["catalogs"] as? [String] ?? []
    if let index = catalogs.firstIndex(of: catalogName) {
        catalogs.remove(at: index)
        manifest["catalogs"] = catalogs
        if saveManifest(repo: repo, manifest: manifest, name: manifestName, overwrite: true) {
            print("Removed \(catalogName) from catalogs of manifest \(manifestName).")
            return true
        }
    }
    printStderr("Catalog \(catalogName) is not in manifest \(manifestName).")
    return false
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
            _ = removeCatalog(repo: repo, manifestName: manifest, catalogName: catalogName)
        }
    }
}
