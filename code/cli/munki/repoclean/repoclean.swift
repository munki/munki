//
//  repoclean.swift
//  repoclean
//
//  Created by Greg Neagle on 11/18/24.
//

import ArgumentParser
import Foundation

@main
struct RepoClean: ParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "repoclean",
        abstract: "Cleans up older packages and pkginfos from a repo"
    )

    @Flag(name: [.long, .customShort("V")],
          help: "Print the version of the munki tools and exit.")
    var version = false

    @Option(name: .shortAndLong,
            help: "Keep this many versions of a specific variation.")
    var keep = 2

    @Flag(name: .long,
          help: "Show all items even if none will be deleted.")
    var showAll = false

    @Option(name: [.customLong("repo-url"), .customLong("repo_url")],
            help: "Optional repo URL. Supply this or a repo_path as an argument.")
    var repoURL = ""

    @Option(name: .long,
            help: "Specify a custom plugin to connect to the Munki repo.")
    var plugin = "FileRepo"

    @Flag(name: .shortAndLong,
          help: "Do not prompt for confirmation before deleting repo items. Use with caution.")
    var auto = false

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
            /* } else if let pref_repo_url = adminPref("repo_url") as? String {
             actual_repo_url = pref_repo_url */
        }

        if actual_repo_url.isEmpty {
            throw ValidationError("Please specify --repo_url or a repo path.")
        }
    }

    mutating func run() throws {
        if version {
            print(getVersion())
            return
        }

        do {
            let repo = try repoConnect(url: actual_repo_url, plugin: plugin)
            // TODO: the actual cleaning!
        } catch let error as MunkiError {
            printStderr("Repo error: \(error.description)")
            throw ExitCode(-1)
        } catch {
            printStderr("Unexpected error: \(error)")
            throw ExitCode(-1)
        }
    }
}
