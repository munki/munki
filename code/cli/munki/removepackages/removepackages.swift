//
//  removepackages.swift
//  removepackages
//
//  Created by Greg Neagle on 8/1/24.
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

@main
struct RemovePackages: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "removepackages",
        abstract: "Removes files installed by one or more package identifiers",
        usage: "removepackages [options] package_id ..."
    )

    @Flag(name: [.short, .customLong("forcedeletebundles")],
          help: "Delete bundles even if they aren't empty.")
    var forceDeleteBundles = false

    @Flag(name: [.short, .customLong("listfiles")],
          help: "List the filesystem objects to be removed, but do not actually remove them.")
    var listFiles = false

    @Flag(name: [.customLong("rebuildpkgdb")],
          help: "Force a rebuild of the internal package database.")
    var rebuildPkgDB = false

    @Flag(name: [.customLong("noremovereceipts")],
          help: "Do not remove receipts from internal package database or Apple's package database.")
    var noRemoveReceipts = false

    @Flag(name: [.customLong("noupdateapplepkgdb")],
          help: "Do not update Apple's package database. If --noremovereceipts is also given, this is implied")
    var noUpdateApplePkgDB = false

    @Flag(name: [.short, .customLong("munkistatusoutput")],
          help: "Output is formatted for use with MunkiStatus/Managed Software Center.")
    var munkiStatusOutput = false

    @Flag(name: .shortAndLong,
          help: "More verbose output. May be specified multiple times.")
    var verbose: Int

    @Argument
    var pkgids: [String]

    mutating func validate() throws {}

    mutating func run() async throws {
        // make sure we're running as root or via sudo (unless --listfiles is given)
        if !listFiles, NSUserName() != "root" {
            printStderr("ERROR: This tool must be run as the root user or via sudo!")
            throw ExitCode(-1)
        }

        DisplayOptions.munkistatusoutput = munkiStatusOutput
        DisplayOptions.verbose = verbose + 1

        let returnCode = await removePackages(
            pkgids,
            forceDeleteBundles: forceDeleteBundles,
            listFiles: listFiles,
            rebuildPkgDB: rebuildPkgDB,
            noRemoveReceipts: noRemoveReceipts,
            noUpdateApplePkgDB: noUpdateApplePkgDB
        )
        if returnCode != 0 {
            throw ExitCode(Int32(returnCode))
        }
    }
}
