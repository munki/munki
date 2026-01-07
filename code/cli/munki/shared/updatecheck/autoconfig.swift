//
//  autoconfig.swift
//  munki
//
//  Created by Greg Neagle on 8/20/24.
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

import Foundation
import SystemConfiguration

/// Uses SystemConfiguration to get the current DNS search domains
func getSearchDomains() -> [String]? {
    let dnsConfig = SCDynamicStoreCopyValue(nil, "State:/Network/Global/DNS" as CFString)
    return (dnsConfig as? NSDictionary)?["SearchDomains"] as? [String]
}

/// Tries a few default URLs and returns the first one that doesn't fail
/// utterly, or the default
func guessRepoURL() -> String {
    let display = DisplayAndLog.main
    guard let searchDomains = getSearchDomains() else {
        return DEFAULT_INSECURE_REPO_URL
    }

    for domain in searchDomains {
        let possibleURLs = [
            "https://munki." + domain + "/repo",
            "https://munki." + domain + "/munki_repo",
            "http://munki." + domain + "/repo",
            "http://munki." + domain + "/munki_repo",
        ]
        for url in possibleURLs {
            do {
                display.info("Checking for Munki repo at \(url)")
                _ = try getDataFromURL(url + "/catalogs/all")
                // success: just return this url
                return url
            } catch {
                display.info("URL error: \(error.localizedDescription)")
            }
        }
    }
    return DEFAULT_INSECURE_REPO_URL
}

/// If Munki repo URL is not defined, (or is the insecure default) attempt to
/// discover one. If successful, record the discovered URL in Munki's preferences.
func autodetectRepoURLIfNeeded() {
    let display = DisplayAndLog.main
    if let softwareRepoURL = pref("SoftwareRepoURL") as? String,
       !softwareRepoURL.isEmpty,
       softwareRepoURL != DEFAULT_INSECURE_REPO_URL
    {
        // SoftwareRepoURL key is defined.
        return
    }
    var allKeysDefined = true
    // it's OK if SoftwareRepoURL is not defined as long as all of these
    // other keys are defined. I think in the real world we'll never see this.
    for key in ["CatalogURL", "IconURL", "ManifestURL", "PackageURL", "ClientResourceURL"] {
        if pref(key) == nil {
            // not defined!
            allKeysDefined = false
            break
        }
    }

    if allKeysDefined {
        return
    }

    display.info("Looking for local Munki repo server...")
    let detectedURL = guessRepoURL()
    if detectedURL != DEFAULT_INSECURE_REPO_URL {
        display.info("Auto-detected Munki repo at \(detectedURL)")
        // save it to Munki's prefs
        setPref("SoftwareRepoURL", detectedURL)
    } else {
        display.info("Using insecure default URL: \(DEFAULT_INSECURE_REPO_URL)")
    }
}
