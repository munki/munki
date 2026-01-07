//
//  MUfind.swift
//  manifestutil
//
//  Created by Greg Neagle on 4/15/25.
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

/// find text in manifests, optionally limiting the search to a single section
func findTextInManifests(repo: Repo, findText: String, section: String = "") async {
    var count = 0
    let manifestNames = await getManifestNames(repo: repo) ?? []
    for name in manifestNames {
        guard let manifest = await getManifest(repo: repo, name: name) else {
            continue
        }
        // if section is not specified, check all sections
        // of the manifest, otherwise just the one
        let sectionsToCheck = section.isEmpty ? Array(manifest.keys) : [section]
        for key in sectionsToCheck {
            if let items = manifest[key] as? [String] {
                for item in items {
                    if item.uppercased().contains(findText.uppercased()) {
                        count += 1
                        if section.isEmpty {
                            // print key along with manifest name
                            print("\(name) (\(key)): \(item)")
                        } else {
                            print("\(name): \(item)")
                        }
                    }
                }
            } else if let item = manifest[section] as? String {
                if item.uppercased().contains(findText.uppercased()) {
                    count += 1
                    if section.isEmpty {
                        // print section along with manifest name
                        print("\(name) (\(key)): \(item)")
                    } else {
                        print("\(name): \(item)")
                    }
                }
            }
        }
    }
    print("\(count) matches found.")
}

/// Finds text in manifests
extension ManifestUtil {
    struct Find: AsyncParsableCommand {
        static var configuration = CommandConfiguration(
            abstract: "Finds text in manifests")

        @Option(help: ArgumentHelp("Limit the search to a specific manifest section",
                                   valueName: "manifest-section"))
        var section: String = ""

        @Argument(help: ArgumentHelp("Text to find",
                                     valueName: "find-text"))
        var findText: String

        func run() async throws {
            guard let repo = RepoConnection.shared.repo else { return }
            await findTextInManifests(repo: repo, findText: findText, section: section)
        }
    }
}
