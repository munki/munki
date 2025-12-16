//
//  version.swift
//  munki
//
//  Created by Greg Neagle on 7/15/24.
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

/// one single place to define a version for CLI tools
let CLI_TOOLS_VERSION = "7.0.5"
let BUILD = "<BUILD_GOES_HERE>"

/// Returns version of Munki tools
func getVersion() -> String {
    if Int(BUILD) != nil {
        // BUILD was updated to an integer by the build script
        return "\(CLI_TOOLS_VERSION).\(BUILD)"
    }
    return CLI_TOOLS_VERSION
}
