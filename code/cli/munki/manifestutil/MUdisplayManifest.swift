//
//  MUdisplayManifest.swift
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

func getManifest(repo: Repo, name: String) async -> PlistDict? {
    do {
        let data = try await repo.get("manifests/\(name)")
        return try readPlist(fromData: data) as? PlistDict
    } catch {
        printStderr("Could not retrieve manifest: \(error.localizedDescription)")
        return nil
    }
}

/// Prints a plist item in an 'attractive' way
func printPlistItem(_ label: String, _ value: Any?, indent: Int = 0) {
    let INDENTSPACE = String(repeating: " ", count: indent * 4)
    if let value {
        if let array = value as? [Any] {
            if !label.isEmpty {
                print("\(INDENTSPACE)\(label):")
            }
            for item in array {
                printPlistItem("", item, indent: indent + 1)
            }
        } else if let dict = value as? PlistDict {
            if !label.isEmpty {
                print("\(INDENTSPACE)\(label):")
            }
            for subkey in dict.keys.sorted() {
                printPlistItem(subkey, dict[subkey], indent: indent + 1)
            }
        } else {
            if !label.isEmpty {
                print("\(INDENTSPACE)\(label): \(value)")
            } else {
                print("\(INDENTSPACE)\(value)")
            }
        }
    }
}

/// Prints plist dictionary in a pretty(?) way
func printPlist(_ plist: PlistDict) {
    for key in plist.keys.sorted() {
        printPlistItem(key, plist[key])
    }
}

/// Recursive expansion of included manifests.
/// Input: a "normal" manifest
/// Output: a manifest with the included\_manifest names replaced with dictionaries containing
///       the actual content of the included manifestd
func expandIncludedManifests(repo: Repo, manifest: PlistDict) async -> PlistDict {
    // No infinite loop checking! Be wary!
    var expandedManifest = manifest
    if let includedManifests = manifest["included_manifests"] as? [String] {
        var expandedIncludedManifests = [PlistDict]()
        for name in includedManifests {
            if var includedManifest = await getManifest(repo: repo, name: name) {
                includedManifest = await expandIncludedManifests(repo: repo, manifest: includedManifest)
                expandedIncludedManifests.append([name: includedManifest])
            }
        }
        expandedManifest["included_manifests"] = expandedIncludedManifests
    }
    return expandedManifest
}

/// Prints contents of a given manifest
extension ManifestUtil {
    struct DisplayManifest: AsyncParsableCommand {
        static var configuration = CommandConfiguration(
            abstract: "Displays a manifest.")

        @Flag(name: .shortAndLong,
              help: "Expand included manifests.")
        var expand: Bool = false

        @Flag(name: .shortAndLong,
              help: "Display manifest in XML format.")
        var xml: Bool = false

        @Argument(help: ArgumentHelp(
            "Prints the contents of the specified manifest",
            valueName: "manifest-name"
        ))
        var manifestName: String

        func run() async throws {
            guard let repo = RepoConnection.shared.repo else { return }
            if var manifest = await getManifest(repo: repo, name: manifestName) {
                if expand {
                    manifest = await expandIncludedManifests(repo: repo, manifest: manifest)
                }
                if xml {
                    print((try? plistToString(manifest)) ?? "")
                } else {
                    printPlist(manifest)
                }
            } else {
                printStderr("Manifest data was malformed or not found.")
            }
        }
    }
}

/// Prints contents of a given manifest, expanding included manifests
extension ManifestUtil {
    struct ExpandIncludedManifests: AsyncParsableCommand {
        static var configuration = CommandConfiguration(
            abstract: "Displays a manifest, expanding included manifests.")

        @Flag(name: .shortAndLong,
              help: "Display manifest in XML format.")
        var xml: Bool = false

        @Argument(help: ArgumentHelp(
            "Prints the contents of the specified manifest",
            valueName: "manifest-name"
        ))
        var manifestName: String

        func run() async throws {
            guard let repo = RepoConnection.shared.repo else { return }
            if var manifest = await getManifest(repo: repo, name: manifestName) {
                manifest = await expandIncludedManifests(repo: repo, manifest: manifest)
                if xml {
                    print((try? plistToString(manifest)) ?? "")
                } else {
                    printPlist(manifest)
                }
            } else {
                printStderr("Manifest data was malformed or not found.")
            }
        }
    }
}
