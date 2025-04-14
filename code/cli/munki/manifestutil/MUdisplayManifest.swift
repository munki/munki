//
//  MUdisplayManifest.swift
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

func getManifest(repo: Repo, name: String) -> PlistDict? {
    do {
        let data = try repo.get("manifests/\(name)")
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

/// Prints contents of a given manifest
extension ManifestUtil {
    struct DisplayManifest: ParsableCommand {
        static var configuration = CommandConfiguration(
            abstract: "Displays a manifest.")
        
        @Flag(name: [.long, .customShort("X")],
              help: "Display manifest in XML format.")
        var xml: Bool = false
        
        @Argument(help: ArgumentHelp(
            "Prints the contents of the specified manifest",
            valueName: "manifest-name"
        ))
        var manifestName: String
        
        func run() throws {
            let repo = try connectToRepo()
            if let manifest = getManifest(repo: repo, name: manifestName) {
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
