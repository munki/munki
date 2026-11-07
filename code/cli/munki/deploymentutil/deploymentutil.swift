//
//  deploymentutil.swift
//  munki
//
//  Copyright 2026 The Munki Project. All rights reserved.
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
struct DeploymentUtil: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "deploymentutil",
        abstract: "Shows the pkginfo deployments in a Munki repo and where each one is right now.",
        usage: "deploymentutil [options] [<repo_path>]"
    )

    @Flag(name: [.long, .customShort("V")], help: "Print the version of the munki tools and exit.")
    var version = false

    @Option(name: [.customLong("repo-url"), .customLong("repo_url")],
            help: "Optional repo URL that takes precedence over the default repo_url specified via preferences.")
    var repoURL = ""

    @Option(help: "Specify a custom plugin to connect to the Munki repo.")
    var plugin: String? = nil

    @Flag(help: "Also show finished deployments.")
    var all = false

    @Option(help: "Only show pkginfos in this catalog.")
    var catalog: String? = nil

    @Option(help: "Show where the machine with this serial number falls, calculated the same way the client does.")
    var serial: String? = nil

    @Option(help: ArgumentHelp("Print the full schedule for an item: each step's time and its percent.", valueName: "name"))
    var schedule: String? = nil

    @Flag(help: "Print JSON instead of a table.")
    var json = false

    @Argument(help: "Path to Munki repo")
    var repo_path = ""

    var actual_repo_url = ""

    mutating func validate() throws {
        if version {
            // asking for version info; we don't need to validate there's a repo URL
            return
        }
        if !repo_path.isEmpty, !repoURL.isEmpty {
            throw ValidationError("Please specify only one of --repo_url or <repo_path>!")
        }
        if !repo_path.isEmpty {
            actual_repo_url = URL(fileURLWithPath: repo_path).absoluteString
        } else if !repoURL.isEmpty {
            actual_repo_url = repoURL
        } else if let pref_repo_url = adminPref("repo_url") as? String {
            actual_repo_url = pref_repo_url
        }
        if actual_repo_url.isEmpty {
            throw ValidationError("Please specify --repo_url or a repo path.")
        }
        if plugin == nil || plugin == "" {
            plugin = adminPref("plugin") as? String ?? "FileRepo"
        }
    }

    mutating func run() async throws {
        if version {
            print(getVersion())
            return
        }
        do {
            let repo = try repoConnect(url: actual_repo_url, plugin: plugin ?? "FileRepo")
            let (pkginfos, errors) = try await pkginfosFromRepo(repo)
            for error in errors {
                printStderr(error)
            }
            // dates in a deployment mean local time, so show them on this machine's clock
            let now = addTZOffsetToDate(Date())
            let rows = filteredDeploymentRows(
                pkginfos.compactMap { deploymentRow($0, now: now, serial: serial) },
                all: all,
                catalog: catalog,
                name: schedule
            )
            if let schedule, rows.isEmpty {
                printStderr("No deployment found for \(schedule).")
                throw ExitCode.failure
            }
            if json {
                try print(deploymentJSON(rows, includeSchedule: schedule != nil))
            } else if schedule != nil {
                print(deploymentScheduleText(rows))
            } else {
                print(deploymentTable(rows, showMachine: serial != nil))
            }
        } catch let error as MunkiError {
            printStderr("Repo error: \(error.description)")
            throw ExitCode.failure
        } catch is ExitCode {
            throw ExitCode.failure
        } catch {
            printStderr("Unexpected error: \(error)")
            throw ExitCode.failure
        }
    }
}
