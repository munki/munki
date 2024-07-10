//
//  managedsoftwareupdate.swift
//  munki
//
//  Created by Greg Neagle on 6/24/24.
//
//  Copyright 2024 Greg Neagle.
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

@main
struct ManagedSoftwareUpdate: ParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "managedsoftwareupdate",
        usage: "maangedsoftwareupdate [options]"
    )

    @Flag(name: [.long, .customShort("V")],
          help: "Print the version of the munki tools and exit.")
    var version = false

    @Flag(name: .long,
          help: "Print the current configuration and exit.")
    var showConfig = false

    mutating func run() throws {
        if version {
            print(getVersion())
            return
        }
        if showConfig {
            printConfig()
            return
        }
        print("Nothing much implemented yet!")
    }
}
