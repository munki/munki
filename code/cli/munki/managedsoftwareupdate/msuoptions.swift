//
//  msuoptions.swift
//  munki
//
//  Created by Greg Neagle on 9/2/24.
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

struct MSUCommonOptions: ParsableArguments {
    @Flag(name: .shortAndLong,
          help: "More verbose output. May be specified multiple times.")
    var verbose: Int

    @Flag(name: .customLong("checkonly"),
          help: "Check for updates, but don't install them. This is the default behavior when no other options are specified.")
    var checkOnly = false

    @Flag(name: .customLong("installonly"),
          help: "Skip checking and install all pending updates. No safety checks.")
    var installOnly = false

    @Flag(name: .customLong("applesuspkgsonly"),
          help: "Only check/install Apple SUS packages, skip Munki packages.")
    var appleSUSPkgsOnly = false

    @Flag(name: .customLong("munkipkgsonly"),
          help: "Only check/install Munki packages, skip Apple SUS.")
    var munkiPkgsOnly = false
}

struct MSUConfigOptions {
    @Flag(name: .long,
          help: "Print the current configuration and exit.")
    var showConfig = false

    @Flag(name: .long,
          help: "Print the current configuration in XML plist format and exit.")
    var showConfigPlist = false

    @Option(name: .long,
            help: "String to use as ClientIdentifier for this run only.")
    var id: String

    @Flag(name: .long,
          help: "Set up 'bootstrapping' mode for managedsoftwareupdate and exit. See the Munki wiki for details on 'bootstrapping'  mode.")
    var setBootstrapMode = false
}
