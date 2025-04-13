//
//  main.swift
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

@main
struct ManifestUtil: AsyncParsableCommand {
    static var configuration = CommandConfiguration(
            abstract: "A utility for working with Munki manifests.",
            subcommands: [
                //AddPkg.self,
                //AddCatalog.self,
                //AddIncludedManifest.self,
                //RemovePkg.self,
                //MoveInstallToUninstall.self,
                //RemoveCatalog.self,
                //RemoveIncludedManifest.self,
                //ListCatalogs.self,
                //ListCatalogItems.self,
                //DisplayManifest.self,
                //ExpandIncludedManifests.self,
                //Find.self,
                //NewManifest.self,
                //CopyManifest.self,
                //RenameManifest.self,
                //DeleteManifest.self,
                //RefreshCache.self,
                Exit.self,
                Help.self,
                Configure.self,
                Version.self],
            defaultSubcommand: RunInteractive.self)
}

extension ManifestUtil {
    struct Exit: ParsableCommand {
        static var configuration = CommandConfiguration(
            abstract: "Exits this utility when in interactive mode.")
        
        func run() throws {
            throw ExitCode(0)
        }
    }
}

extension ManifestUtil {
    struct Help: ParsableCommand {
        static var configuration = CommandConfiguration(abstract: "Show this help message.")
        
        func run() throws {
            print(ManifestUtil.helpMessage())
        }
    }
}

extension ManifestUtil {
    struct Configure: ParsableCommand {
        static var configuration = CommandConfiguration(
            abstract: "Show and edit configuration for this tool.")
        
        func run() throws {
            let promptList = [
                ("repo_url", "Repo URL (example: afp://munki.example.com/repo)"),
                ("plugin", "Munki repo plugin (defaults to FileRepo)")
            ]
            configure(promptList: promptList)
        }
    }
}

extension ManifestUtil {
    struct Version: ParsableCommand {
        static var configuration = CommandConfiguration(abstract: "Print version information.")
        
        func run() throws {
            print(CLI_TOOLS_VERSION)
        }
    }
}

extension ManifestUtil {
    struct RunInteractive: ParsableCommand {
        static var configuration = CommandConfiguration(
            abstract: "Runs this utility in interactive mode.")
        
        func run() throws {
    
        }
    }
}
