//
//  MUlistManifests.swift
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

func getManifestNames(repo: Repo) async -> [String]? {
    do {
        let manifestNames = try await repo.list("manifests")
        return manifestNames.sorted()
    } catch {
        printStderr("Could not retrieve manifests: \(error.localizedDescription)")
        return nil
    }
}

extension ManifestUtil {
    struct ListManifests: AsyncParsableCommand {
        static var configuration = CommandConfiguration(
            abstract: "Lists available manifest in Munki repo.")

        @Argument(help: ArgumentHelp(
            "String to match manifest names similar to file name globbing. To avoid the shell expanding wildcards, wrap the string in quotes.",
            valueName: "match-string"
        ))
        var globString: String = ""

        func run() async throws {
            guard let repo = RepoConnection.shared.repo else { return }
            guard let manifestNames = await getManifestNames(repo: repo)
            else {
                return
            }
            if globString.isEmpty {
                print(manifestNames.joined(separator: "\n"))
            } else {
                for name in manifestNames {
                    if fnmatch(globString, name, 0) == 0 {
                        print(name)
                    }
                }
            }
        }
    }
}
