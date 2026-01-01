//
//  main.swift
//  repocheck
//
//  Created by Greg Neagle on 9/30/25.
//  Copyright 2025-2026 The Munki Project. All rights reserved.
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

func getPkgsinfoList(repo: Repo) async throws -> [String] {
    do {
        return try await repo.list("pkgsinfo")
    } catch is MunkiError {
        throw MunkiError("Error getting list of pkgsinfo items")
    }
}

func installerTypeIsSupportedInMunki7(_ installerType: String) -> Bool {
    if ["appdmg", "apple_update_metadata", "startosinstall", "profile"].contains(installerType) {
        return false
    }
    if installerType.hasPrefix("Adobe") {
        return false
    }
    return true
}

func uninstallMethodIsSupportedInMunki7(_ uninstallMethod: String) -> Bool {
    return !uninstallMethod.hasPrefix("Adobe")
}

func main() async {
    guard let pref_repo_url = adminPref("repo_url") as? String else {
        print("ERROR: No repo defined")
        exit(-1)
    }
    guard let repo = try? repoConnect(url: pref_repo_url, plugin: "FileRepo") else {
        print("ERROR: Couldn't connect to repo")
        exit(-1)
    }
    guard let pkginfoList = try? await getPkgsinfoList(repo: repo) else {
        print("ERROR: Could not get list of pkginfo items from \(pref_repo_url)")
        exit(-1)
    }
    var pkginfosWithIssuesCount = 0
    for pkginfoName in pkginfoList {
        var errors: [String] = []
        // Try to read the pkginfo file
        var pkginfo = PlistDict()
        let pkginfoIdentifier = "pkgsinfo/" + pkginfoName
        do {
            let data = try await repo.get(pkginfoIdentifier)
            pkginfo = try readPlist(fromData: data) as? PlistDict ?? PlistDict()
            if !(pkginfo.keys.contains("name")) {
                errors.append("Missing name key")
            }
            if let installerType = pkginfo["installer_type"] as? String,
               !installerTypeIsSupportedInMunki7(installerType)
            {
                errors.append("Unsupported installer_type: \(installerType)")
            }
            if let uninstallMethod = pkginfo["uninstall_method"] as? String,
               !uninstallMethodIsSupportedInMunki7(uninstallMethod)
            {
                errors.append("Unsupported uninstall_method: \(uninstallMethod)")
            }
            if pkginfo.keys.contains("suppress_bundle_relocation") {
                errors.append("suppress_bundle_relocation key is no longer supported")
            }
        } catch {
            errors.append("Unexpected read error: \(error)")
        }
        if !errors.isEmpty {
            pkginfosWithIssuesCount += 1
            print("\(pkginfoName):")
            for error in errors {
                print("\t\(error)")
            }
            print()
        }
    }
    print("\(pkginfosWithIssuesCount)/\(pkginfoList.count) pkginfos have issues")
}

await main()
