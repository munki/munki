//
//  manifestutil.swift
//  manifestutil
//
//  Created by Greg Neagle on 4/13/25.
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

func connectToRepo() throws -> Repo {
    guard let repoURL = adminPref("repo_url") as? String else {
        printStderr("No repo URL defined. Run manifestutil config to define one.")
        throw ExitCode(-1)
    }
    var plugin = adminPref("plugin") as? String ?? "FileRepo"
    if plugin.isEmpty {
        plugin = "FileRepo"
    }
    // connect to the repo
    var repo: Repo
    do {
        repo = try repoConnect(url: repoURL, plugin: plugin)
    } catch let error as MunkiError {
        printStderr("Repo connection error: \(error.description)")
        throw ExitCode(-1)
    }
    return repo
}

/// A singleton class for our repo connection
class RepoConnection {
    static var shared = RepoConnection()

    var repo: Repo?

    private init() {
        repo = try? connectToRepo()
    }
}

@main
struct ManifestUtil: AsyncParsableCommand {
    static var configuration = CommandConfiguration(
        commandName: "manifestutil",
        abstract: "A utility for working with Munki manifests.",
        subcommands: [
            AddPkg.self,
            RemovePkg.self,
            MoveInstallToUninstall.self,
            AddCatalog.self,
            RemoveCatalog.self,
            AddIncludedManifest.self,
            RemoveIncludedManifest.self,
            ListCatalogs.self,
            ListCatalogItems.self,
            ListManifests.self,
            DisplayManifest.self,
            ExpandIncludedManifests.self,
            Find.self,
            NewManifest.self,
            CopyManifest.self,
            RenameManifest.self,
            DeleteManifest.self,
            Configure.self,
            Version.self,
            RunInteractive.self,
            // RefreshCache.self,
            Exit.self,
        ],
        defaultSubcommand: RunInteractive.self
    )
}

extension ManifestUtil {
    struct Exit: AsyncParsableCommand {
        static var configuration = CommandConfiguration(
            abstract: "Exits this utility when in interactive mode.",
            shouldDisplay: false
        )

        func run() throws {
            Exit.exit()
        }
    }
}

extension ManifestUtil {
    struct Configure: AsyncParsableCommand {
        static var configuration = CommandConfiguration(
            abstract: "Show and edit configuration for this tool.")

        func run() throws {
            let promptList = [
                ("repo_url", "Repo URL (example: afp://munki.example.com/repo)"),
                ("plugin", "Munki repo plugin (defaults to FileRepo)"),
            ]
            configure(promptList: promptList)
        }
    }
}

extension ManifestUtil {
    struct Version: AsyncParsableCommand {
        static var configuration = CommandConfiguration(abstract: "Print version information.")

        func run() throws {
            print(getVersion())
        }
    }
}
