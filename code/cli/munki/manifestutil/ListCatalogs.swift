//
//  ListCatalogs.swift
//  manifestutil
//
//  Created by Greg Neagle on 4/13/25.
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

/// Returns a list of available catalogs
func getCatalogNames(repo: Repo) -> [String] {
    do {
        let catalogNames = try repo.list("catalogs")
        return catalogNames.sorted()
    } catch let error {
        printStderr("Could not retrieve catalogs: \(error.localizedDescription)")
    }
    return []
}

extension ManifestUtil {
    struct ListCatalogs: ParsableCommand {
        static var configuration = CommandConfiguration(
            abstract: "Lists available catalogs in Munki repo.")
        
        func run() throws {
            let repo = try connectToRepo()
            let catalogNames = getCatalogNames(repo: repo)
            print(catalogNames.joined(separator: "\n"))
        }
    }
}
