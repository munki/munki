//
//  GitFileRepo.swift
//  munki
//
//  Created by Greg Neagle on 6/28/24.
//
//  Copyright 2024-2026 The Munki Project.
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

import Foundation

/// A subclass of FileRepo that also does git commits for repo changes
class GitFileRepo: FileRepo {
    // MARK: instance variables

    var cmd: String

    // MARK: override init

    required init(_ url: String) throws {
        // try to get path to git binary from admin prefs or use default path
        cmd = adminPref("GitBinaryPath") as? String ?? "/usr/bin/git"
        // init the rest
        try super.init(url)
    }

    // MARK: git functions

    func runGit(args: [String] = []) -> CLIResults {
        return runCLI(cmd, arguments: args)
    }

    /// Returns True if file referred to by identifier will be ignored by Git
    /// (usually due to being in a .gitignore file)
    func isGitIgnored(_ identifier: String) -> Bool {
        let results = runGit(
            args: ["-C", parentDir(identifier),
                   "check-ignore", fullPath(identifier)]
        )
        return results.exitcode == 0
    }

    /// Returns True if file referred to by identifier is in a Git repo, false otherwise.
    func isInGitRepo(_ identifier: String) -> Bool {
        let results = runGit(
            args: ["-C", parentDir(identifier),
                   "status", "-z", fullPath(identifier)]
        )
        return results.exitcode == 0
    }

    /// Commits the file referred to be identifier. This method will also automatically
    /// generate the commit log appropriate for the status of the file where
    /// status would be 'modified', 'new file', or 'deleted'
    func gitCommit(_ identifier: String) {
        // figure out the name of the tool in use
        let processPath = ProcessInfo.processInfo.arguments[0]
        let toolname = (processPath as NSString).lastPathComponent

        // get the current username
        let username = NSUserName()

        // get the status of file at path
        let statusResults = runGit(
            args: ["-C", parentDir(identifier),
                   "status", "-s", fullPath(identifier)]
        )
        var action = ""
        if statusResults.output.hasPrefix("A") {
            action = "added"
        } else if statusResults.output.hasPrefix("D") {
            action = "deleted"
        } else if statusResults.output.hasPrefix("M") {
            action = "modified"
        } else {
            action = "made unexpected change to"
        }

        // generate the log message
        let logMessage = "\(username) \(action) '\(identifier)' via \(toolname)"
        // do the commit
        print("Doing git commit: \(logMessage)")
        let results = runGit(
            args: ["-C", parentDir(identifier),
                   "commit", "-m", logMessage]
        )
        if results.exitcode != 0 {
            printStderr("Failed to commit changes to \(identifier)")
            printStderr(results.error)
        }
    }

    /// Does a git add or rm of a file at path. "operation" must be either "add" or "rm"
    private func gitAddOrRemove(_ identifier: String, _ operation: String) {
        if isInGitRepo(identifier) {
            if !isGitIgnored(identifier) {
                let results = runGit(
                    args: ["-C", parentDir(identifier),
                           operation, fullPath(identifier)]
                )
                if results.exitcode == 0 {
                    gitCommit(identifier)
                } else {
                    printStderr("git error: \(results.error)")
                }
            }
        } else {
            printStderr("\(identifier) is not in a git repo.")
        }
    }

    /// Adds and commits file at path
    func gitAdd(_ identifier: String) {
        gitAddOrRemove(identifier, "add")
    }

    /// Deletes file at path and commits the result
    func gitDelete(_ identifier: String) {
        gitAddOrRemove(identifier, "rm")
    }

    // MARK: override FileRepo API methods

    override func put(_ identifier: String, content: Data) async throws {
        try await super.put(identifier, content: content)
        gitAdd(identifier)
    }

    override func put(_ identifier: String, fromFile local_path: String) async throws {
        try await super.put(identifier, fromFile: local_path)
        gitAdd(identifier)
    }

    override func delete(_ identifier: String) async throws {
        try await super.delete(identifier)
        gitDelete(identifier)
    }
}
