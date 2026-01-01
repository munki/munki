//
//  MUcatalogs.swift
//  manifestutil
//
//  Created by Greg Neagle on 4/13/25.
//
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

import ArgumentParser
import Foundation

/// Returns a list of available catalogs
func getCatalogNames(repo: Repo) async -> [String]? {
    do {
        let catalogNames = try await repo.list("catalogs")
        return catalogNames.sorted()
    } catch {
        printStderr("Could not retrieve catalogs: \(error.localizedDescription)")
        return nil
    }
}

/// Prints the names of the available catalogs
extension ManifestUtil {
    struct ListCatalogs: AsyncParsableCommand {
        static var configuration = CommandConfiguration(
            abstract: "Lists available catalogs in Munki repo.")

        func run() async throws {
            if let repo = try? connectToRepo(),
               let catalogNames = await getCatalogNames(repo: repo)
            {
                print(catalogNames.joined(separator: "\n"))
            }
        }
    }
}

/// Returns a list of unique installer item (pkg) names from the given list of catalogs
func getInstallerItemNames(repo: Repo, catalogs: [String]) async -> [String] {
    var itemList = [String]()
    guard let catalogNames = await getCatalogNames(repo: repo) else {
        return itemList
    }
    for catalogName in catalogNames {
        if catalogs.contains(catalogName) {
            do {
                let data = try await repo.get("catalogs/\(catalogName)")
                if let catalog = (try? readPlist(fromData: data)) as? [PlistDict] {
                    let itemNames = catalog.filter {
                        ($0["update_for"] as? String ?? "").isEmpty &&
                            !(($0["name"] as? String ?? "").isEmpty)
                    }.map {
                        $0["name"] as? String ?? ""
                    }
                    itemList.append(contentsOf: itemNames)
                } else {
                    printStderr("Catalog \(catalogName) is malformed")
                }
            } catch {
                printStderr("Could not retrieve catalog: \(catalogName): \(error.localizedDescription)")
            }
        }
    }
    return Array(Set(itemList)).sorted()
}

/// Lists items in the given catalogs
extension ManifestUtil {
    struct ListCatalogItems: AsyncParsableCommand {
        static var configuration = CommandConfiguration(
            abstract: "Lists items in the given catalogs.")

        @Argument(help: ArgumentHelp(
            "Catalog name",
            valueName: "catalog-name"
        ))
        var catalogNames: [String] = []

        func validate() throws {
            if catalogNames.isEmpty {
                throw ValidationError("At least one catalog name must be provided.")
            }
        }

        func run() async throws {
            guard let repo = RepoConnection.shared.repo else { return }
            guard let availableCatalogs = await getCatalogNames(repo: repo) else {
                return
            }

            for catalogName in catalogNames {
                if !availableCatalogs.contains(catalogName) {
                    printStderr("Catalog '\(catalogName)' does not exist.")
                    throw ExitCode(-1)
                }
            }
            let installerItemNames = await getInstallerItemNames(repo: repo, catalogs: catalogNames)
            print(installerItemNames.joined(separator: "\n"))
        }
    }
}
