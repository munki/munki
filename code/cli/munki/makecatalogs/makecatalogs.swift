//
//  makecatalogs.swift
//  munki
//
//  Created by Greg Neagle on 6/25/24.
//

import Foundation
import ArgumentParser

@main
struct MakeCatalogs: ParsableCommand {
    
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
        if !repo_path.isEmpty && !repoURL.isEmpty {
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

    mutating func run() throws {
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
            var catalogsmaker = try CatalogsMaker(repo: repo, options: options)
            let errors = catalogsmaker.makecatalogs()
            if !errors.isEmpty {
                for error in errors {
                    printStderr(error)
                }
                throw ExitCode(-1)
            }
        } catch RepoError.error(let description) {
            printStderr("Repo error: \(description)")
            throw ExitCode(-1)
        } catch MakeCatalogsError.PkginfoAccessError(let description) {
            printStderr("Pkginfo read error: \(description)")
            throw ExitCode(-1)
        } catch MakeCatalogsError.CatalogWriteError(let description) {
            printStderr("Catalog write error: \(description)")
            throw ExitCode(-1)
        } catch {
            printStderr("Unexpected error: \(error)")
            throw ExitCode(-1)
        }
    }
}
