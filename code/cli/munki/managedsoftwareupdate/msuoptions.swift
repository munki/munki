//
//  msuoptions.swift
//  munki
//
//  Created by Greg Neagle on 9/2/24.
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
          help: "Only check for Apple software updates, skip Munki packages.")
    var appleSUSPkgsOnly = false

    @Flag(name: .customLong("munkipkgsonly"),
          help: "Only check/install Munki packages, skip Apple software updates.")
    var munkiPkgsOnly = false
}

struct MSUConfigOptions: ParsableArguments {
    @Option(name: .long,
            help: "String to use as ClientIdentifier for this run only.")
    var id: String = ""

    @Flag(name: .long,
          help: "Print the current configuration and exit.")
    var showConfig = false

    @Flag(name: .long,
          help: "Print the current configuration in XML plist format and exit.")
    var showConfigPlist = false

    @Flag(name: .long,
          help: "Set up 'bootstrapping' mode for managedsoftwareupdate and exit. See the Munki wiki for details on 'bootstrapping'  mode.")
    var setBootstrapMode = false

    @Flag(name: .long,
          help: "Clear 'bootstrapping' mode for managedsoftwareupdate and exit.")
    var clearBootstrapMode = false
}

struct MSUOtherOptions: ParsableArguments {
    @Flag(name: .shortAndLong,
          help: "Triggers an updatecheck, followed by an install/removal of items that can be done without user interaction. Used by launchd LaunchDaemon for scheduled/background runs. Not tested or supported with any other option. This is a safer option to use than --installonly when using managedsoftwareupdate to install pending updates, since only unattended updates are installed if there is an active user.")
    var auto = false

    @Flag(name: .shortAndLong,
          help: "Used by launchd LaunchAgent when running at the loginwindow. Not for general use.")
    var logoutinstall = false

    @Flag(name: .long,
          help: "Used by Managed Software Center.app when user triggers an install without logging out. Not for general use.")
    var installwithnologout = false

    @Flag(name: .long, help: "Used internally. Not for general use.")
    var launchosinstaller = false

    @Flag(name: .long,
          help: "Used by launchd LaunchAgent when checking manually. Not for general use.")
    var manualcheck = false

    @Flag(name: .shortAndLong,
          help: "Uses MunkiStatus.app for progress feedback when installing. Not for general use.")
    var munkistatusoutput = false

    @Flag(name: .shortAndLong,
          help: "Quiet mode. Logs messages, but nothing to stdout. --verbose is ignored if --quiet is used.")
    var quiet = false
}
