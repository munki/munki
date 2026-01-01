//
//  makecatalogs.swift
//  munki
//
//  Created by Greg Neagle on 6/25/24.
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
struct MakeCatalogs: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "makecatalogs",
        abstract: "Builds Munki catalogs from pkginfo files.",
        usage: "makecatalogs [options] [<repo_path>]"
    )

    @Flag(name: [.long, .customShort("V")], help: "Print the version of the munki tools and exit.")
    var version = false

    @Flag(name: .shortAndLong, help: "Disable sanity checks.")
    var force = false

    @Flag(name: .shortAndLong,
          help: "Skip checking of pkg existence. Useful when pkgs aren't on the same server as pkginfo, catalogs and manifests.")
    var skipPkgCheck = false

    @Option(name: [.customLong("repo-url"), .customLong("repo_url")],
            help: "Optional repo URL that takes precedence over the default repo_url specified via preferences.")
    var repoURL = ""

    @Option(help: "Specify a custom plugin to connect to the Munki repo.")
    var plugin = "FileRepo"

    @Argument(help: "Path to Munki repo")
    var repo_path = ""

    var actual_repo_url = ""

    mutating func validate() throws {
        if version {
            // asking for version info; we don't need to validate there's a repo URL
            return
        }
        // figure out what repo we're working with: we can get a repo URL one of three ways:
        //   - as a file path provided at the command line
        //   - as a --repo_url option
        //   - as a preference stored in the com.googlecode.munki.munkiimport domain
        if !repo_path.isEmpty, !repoURL.isEmpty {
            // user has specified _both_ repo_path and repo_url!
            throw ValidationError("Please specify only one of --repo_url or <repo_path>!")
        }
        if !repo_path.isEmpty {
            // convert path to file URL
            if let repo_url_string = NSURL(fileURLWithPath: repo_path).absoluteString {
                actual_repo_url = repo_url_string
            }
        } else if !repoURL.isEmpty {
            actual_repo_url = repoURL
        } else if let pref_repo_url = adminPref("repo_url") as? String {
            actual_repo_url = pref_repo_url
        }

        if actual_repo_url.isEmpty {
            throw ValidationError("Please specify --repo_url or a repo path.")
        }
    }

    mutating func run() async throws {
        if version {
            print(getVersion())
            return
        }

        let options = MakeCatalogOptions(
            skipPkgCheck: skipPkgCheck,
            force: force,
            verbose: true
        )

        do {
            let repo = try repoConnect(url: actual_repo_url, plugin: plugin)
            // TODO: implement repo defining its own makecatalogs method
            // let errors = try repo.makecatalogs(options: options)
            var catalogsmaker = try await CatalogsMaker(repo: repo, options: options)
            await catalogsmaker.makecatalogs()
            for warning in catalogsmaker.warnings {
                printStderr(warning)
            }
            if !catalogsmaker.errors.isEmpty {
                for error in catalogsmaker.errors {
                    printStderr(error)
                }
                throw ExitCode.failure
            }
        } catch let error as MunkiError {
            printStderr("Repo error: \(error.description)")
            throw ExitCode.failure
        } catch let error as MakeCatalogsError {
            switch error {
            case let .CatalogWriteError(description):
                printStderr("Catalog write error: \(description)")
                throw ExitCode.failure
            case let .PkginfoAccessError(description):
                printStderr("Pkginfo read error: \(description)")
                throw ExitCode.failure
            }
        } catch {
            if error is ExitCode {
                throw error
            }
            printStderr("Unexpected error: \(error)")
            throw ExitCode.failure
        }
    }
}
