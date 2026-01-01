//
//  munkiimportOptions.swift
//  munki
//
//  Created by Greg Neagle on 7/12/24.
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

struct MunkiImportOptions: ParsableArguments {
    @Flag(name: .long, help: "Configure munkiimport with details about your Munki repo, preferred editor, and the like. Any other options and arguments are ignored.")
    var configure = false

    @Option(name: .long, help: "When importing an installer item, item will be uploaded to this subdirectory path in the repo pkgs directory, and the pkginfo file will be stored under this subdirectory under the pkgsinfo directory.")
    var subdirectory: String? = nil

    @Flag(name: .shortAndLong, help: "No interactive prompts.")
    var nointeractive = false

    @Option(name: [.long, .customLong("repo_url")],
            help: "Optional repo URL that takes precedence over the default repo_url specified via preferences.")
    var repoURL: String? = nil

    @Option(help: "Optional plugin to connect to repo. If specified, overrides any plugin specified via --configure.")
    var plugin: String? = nil

    @Option(name: [.long, .customLong("icon_path")],
            help: "Path to an icns file for the installer item. Will be converted to PNG and uploaded, and will overwrite any existing PNG.")
    var iconPath: String? = nil

    @Flag(name: [.long, .customLong("extract_icon")],
          help: "Attempt to extract and upload a product icon from the installer item")
    var extractIcon = false

    @Flag(name: [.long, .customShort("V")],
          help: "Print the version of the Munki tools and exit.")
    var version = false

    @Flag(name: .shortAndLong, help: "More detailed output.")
    var verbose = false

    mutating func validate() throws {
        // update plugin (not really a validation, but close enough)
        if plugin == nil {
            plugin = adminPref("plugin") as? String ?? "FileRepo"
        }
        if plugin == "" {
            plugin = "FileRepo"
        }

        // make sure subdirectory does not start with a slash
        if var subdirectory,
           subdirectory.hasPrefix("/")
        {
            self.subdirectory = String(subdirectory.removeFirst())
        }

        // Validate iconPath if set
        if let iconPath {
            if !FileManager.default.fileExists(atPath: iconPath) {
                throw ValidationError("The specified icon '\(iconPath)' does not exist.")
            }
            if (iconPath as NSString).pathExtension != "icns" {
                throw ValidationError("--icon-path must point to an icns file.")
            }
            if extractIcon {
                // can't have both set
                throw ValidationError("Select only one of --icon-path and --extract-icon")
            }
        }
    }
}
