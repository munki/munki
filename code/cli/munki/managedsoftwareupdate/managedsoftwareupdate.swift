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
struct ManagedSoftwareUpdate: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "managedsoftwareupdate",
        usage: "mangedsoftwareupdate [options]"
    )

    @Flag(name: [.long, .customShort("V")],
          help: "Print the version of the munki tools and exit.")
    var version = false

    @OptionGroup(title: "Commonly used options")
    var commonOptions: MSUCommonOptions

    @OptionGroup(title: "Configuration options")
    var configOptions: MSUConfigOptions

    @OptionGroup(title: "Other options")
    var otherOptions: MSUOtherOptions

    mutating func run() throws {
        if version {
            print(getVersion())
            return
        }
        // check to see if we're root
        if NSUserName() != "root" {
            printStderr("You must run this as root!")
            throw ExitCode(EXIT_STATUS_ROOT_REQUIRED)
        }
        try handleConfigOptions(configOptions)

        print("Nothing much implemented yet!")
    }
}

func handleConfigOptions(_ options: MSUConfigOptions) throws {
    if options.showConfig {
        printConfig()
        throw ExitCode(0)
    }
    if options.showConfigPlist {
        printConfigPlist()
        throw ExitCode(0)
    }
    if options.setBootstrapMode {
        do {
            try setBootstrapMode()
        } catch {
            printStderr(error.localizedDescription)
            throw ExitCode(-1)
        }
        print("Bootstrap mode is set.")
        throw ExitCode(0)
    }
    if options.clearBootstrapMode {
        do {
            try clearBootstrapMode()
        } catch {
            printStderr(error.localizedDescription)
            throw ExitCode(-1)
        }
        print("Bootstrap mode cleared.")
        throw ExitCode(0)
    }
}
