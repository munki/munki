//
//  installationstate.swift
//  munki
//
//  Created by Greg Neagle on 8/19/24.
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

private let display = DisplayAndLog.main

enum InstallationState: Int {
    case thisVersionNotInstalled = 0
    case thisVersionInstalled = 1
    case newerVersionInstalled = 2
}

/// Checks to see if the item described by pkginfo (or a newer version) is
/// currently installed
///
/// All tests must pass to be considered installed.
/// Returns InstallationState
func installedState(_ pkginfo: PlistDict) async -> InstallationState {
    var foundNewer = false
    if pkginfo["OnDemand"] as? Bool ?? false {
        // we always need to install these items
        display.debug1("This is an OnDemand item. Must install.")
        return .thisVersionNotInstalled
    }
    if pkginfo["installcheck_script"] is String {
        let retcode = await runEmbeddedScript(
            name: "installcheck_script",
            pkginfo: pkginfo,
            suppressError: true
        )
        display.debug1("installcheck_script returned \(retcode)")
        // retcode 0 means install IS needed
        if retcode == 0 {
            return .thisVersionNotInstalled
        }
        // non-zero could be an error or successfully indicating
        // that an install is not needed. We hope it's the latter.
        // return .thisVersionInstalled so we're marked as not needing to be installed
        return .thisVersionInstalled
    }
    if pkginfo["version_script"] is String {
        // if a version_script is defined, use that to determine installedState
        let compareResult = await compareUsingVersionScript(pkginfo)
        if compareResult == .notPresent || compareResult == .older {
            return .thisVersionNotInstalled
        }
        if compareResult == .newer {
            return .newerVersionInstalled
        }
        if compareResult == .same {
            return .thisVersionInstalled
        }
    }
    let installerType = pkginfo["installer_type"] as? String ?? ""
    if installerType == "startosinstall",
       var installerItemVersion = pkginfo["version"] as? String
    {
        let currentOSVersion = getOSVersion() // just gets major.minor
        let installerVersionParts = installerItemVersion.components(separatedBy: ".")
        if (Int(installerVersionParts[0]) ?? 0) > 10 {
            // if we're running Big Sur+, we just want the major (11, 12, etc)
            installerItemVersion = installerVersionParts[0]
        } else {
            // need just major.minor part of the version -- 10.12 and not 10.12.4
            installerItemVersion = installerVersionParts[0] + "." + installerVersionParts[1]
        }
        let compareResult = compareVersions(currentOSVersion, installerItemVersion)
        if compareResult == .older {
            return .thisVersionNotInstalled
        }
        if compareResult == .newer {
            return .newerVersionInstalled
        }
        return .thisVersionInstalled
    }
    if installerType == "stage_os_installer",
       var installerItemVersion = pkginfo["version"] as? String
    {
        // we return .newerVersionInstalled if the installed macOS is the same version
        // or higher than the version of this item
        // we return .thisVersionInstalled if the OS installer has already been staged
        // otherwise return .thisVersionNotInstalled
        let currentOSVersion = getOSVersion() // just gets major.minor
        let installerVersionParts = installerItemVersion.components(separatedBy: ".")
        if (Int(installerVersionParts[0]) ?? 0) > 10 {
            // if we're running Big Sur+, we just want the major (11, 12, etc)
            installerItemVersion = installerVersionParts[0]
        } else {
            // need just major.minor part of the version -- 10.12 and not 10.12.4
            installerItemVersion = installerVersionParts[0] + "." + installerVersionParts[1]
        }
        let compareResult = compareVersions(currentOSVersion, installerItemVersion)
        if compareResult == .same || compareResult == .newer {
            return .newerVersionInstalled
        }
        // installed OS version is lower; check to see if we've staged the os installer
        for item in pkginfo["installs"] as? [PlistDict] ?? [] {
            do {
                let compareResult = try compareItem(item)
                if compareResult != .same {
                    return .thisVersionNotInstalled
                }
            } catch {
                display.error(error.localizedDescription)
                // return .thisVersionInstalled so we don't attempt an install
                return .thisVersionInstalled
            }
        }
        // all items are present and same version
        return .thisVersionInstalled
    }
    // do we have installs items?
    if let installItems = pkginfo["installs"] as? [PlistDict],
       !installItems.isEmpty
    {
        for item in installItems {
            do {
                let compareResult = try compareItem(item)
                if compareResult == .older || compareResult == .notPresent {
                    return .thisVersionNotInstalled
                }
                if compareResult == .newer {
                    foundNewer = true
                }
            } catch {
                display.error(error.localizedDescription)
                // return .thisVersionInstalled so we don't attempt an install
                return .thisVersionInstalled
            }
        }
    } else if let receipts = pkginfo["receipts"] as? [PlistDict] {
        // if there are no 'installs' items, then we'll use receipt info
        // to determine install status.
        for item in receipts {
            do {
                let compareResult = try await compareReceipt(item)
                if compareResult == .older || compareResult == .notPresent {
                    return .thisVersionNotInstalled
                }
                if compareResult == .newer {
                    foundNewer = true
                }

            } catch {
                display.error(error.localizedDescription)
                // return .thisVersionInstalled so we don't attempt an install
                return .thisVersionInstalled
            }
        }
    }
    // if we got this far, we passed all the tests, so the item
    // must be installed (or we don't have enough info...)
    if foundNewer {
        return .newerVersionInstalled
    }
    return .thisVersionInstalled
}

/// Checks to see if some version of a pkgitem is installed.
func someVersionInstalled(_ pkginfo: PlistDict) async -> Bool {
    if pkginfo["OnDemand"] as? Bool ?? false {
        // These should never be counted as installed
        display.debug1("This is an OnDemand item.")
        return false
    }
    if pkginfo["installcheck_script"] is String {
        // installcheck_script can really only tell us that an item needs
        // to be installed, or it doesn't.
        // it can't tell us that an older version of the item is installed
        let retcode = await runEmbeddedScript(
            name: "installcheck_script",
            pkginfo: pkginfo,
            suppressError: true
        )
        display.debug1("installcheck_script returned \(retcode)")
        // retcode 0 means install is needed
        // (ie, item is not installed)
        // non-zero could be an error or successfully indicating
        // that an install is not needed. We hope it's the latter.
        return retcode != 0
    }
    if pkginfo["version_script"] is String {
        // if there's a version_script, let's use that to determine
        // if some version installed
        let comparisonResult = await compareUsingVersionScript(pkginfo)
        if comparisonResult == .notPresent {
            return false
        }
        return true
    }
    if let installerType = pkginfo["installer_type"] as? String,
       installerType == "startosinstall" || installerType == "stage_os_installer"
    {
        // Some version of macOS is always installed!
        return true
    }
    // do we have installs items?
    if let installItems = pkginfo["installs"] as? [PlistDict],
       !installItems.isEmpty
    {
        for item in installItems {
            do {
                let compareResult = try compareItem(item)
                if compareResult == .notPresent {
                    return false
                }
            } catch {
                display.error(error.localizedDescription)
                return false
            }
        }
    } else if let receipts = pkginfo["receipts"] as? [PlistDict] {
        for item in receipts {
            do {
                let compareResult = try await compareReceipt(item)
                if compareResult == .notPresent {
                    return false
                }

            } catch {
                display.error(error.localizedDescription)
                // return .thisVersionInstalled so we don't attempt an install
                return false
            }
        }
    }
    // if we got this far, we passed all the tests, so the item
    // must be installed (or we don't have enough info...)
    return true
}

/// Checks to see if there is any evidence that the item described
/// by pkginfo (any version) is currently installed.
/// If any tests pass, the item might be installed.
/// This is used when determining if we can remove the item, thus
/// the attention given to the uninstall method.
func evidenceThisIsInstalled(_ pkginfo: PlistDict) async -> Bool {
    if pkginfo["OnDemand"] as? Bool ?? false {
        // These should never be counted as installed
        display.debug1("This is an OnDemand item.")
        return false
    }
    if pkginfo["uninstallcheck_script"] is String {
        // installcheck_script can really only tell us that an item needs
        // to be installed, or it doesn't.
        // it can't tell us that an older version of the item is installed
        let retcode = await runEmbeddedScript(
            name: "uninstallcheck_script",
            pkginfo: pkginfo,
            suppressError: true
        )
        display.debug1("uninstallcheck_script returned \(retcode)")
        // retcode 0 means uninstall is needed
        // (ie, item is installed)
        // non-zero could be an error or successfully indicating
        // that an uninstall is not needed.
        return retcode == 0
    }
    if pkginfo["installcheck_script"] is String {
        // installcheck_script can really only tell us that an item needs
        // to be installed, or it doesn't.
        // it can't tell us that an older version of the item is installed
        let retcode = await runEmbeddedScript(
            name: "installcheck_script",
            pkginfo: pkginfo,
            suppressError: true
        )
        display.debug1("installcheck_script returned \(retcode)")
        // retcode 0 means install is needed
        // (ie, item is not installed)
        // non-zero could be an error or successfully indicating
        // that an install is not needed. We hope it's the latter.
        return retcode != 0
    }
    if pkginfo["version_script"] is String {
        // if a comparison using a version_script returns anything
        // other than .notPresent that's evidence the item is installed
        let comparisonResult = await compareUsingVersionScript(pkginfo)
        if comparisonResult != .notPresent {
            return true
        }
    }
    if let installerType = pkginfo["installer_type"] as? String,
       installerType == "startosinstall" || installerType == "stage_os_installer"
    {
        // Some version of macOS is always installed!
        return true
    }
    var foundAllInstallItems = false
    if let installItems = pkginfo["installs"] as? [PlistDict],
       !installItems.isEmpty,
       (pkginfo["uninstall_method"] as? String ?? "") != "removepackages"
    {
        display.debug2("Checking 'installs' items...")
        foundAllInstallItems = true
        for item in installItems {
            if let path = item["path"] as? String, !pathExists(path) {
                // this item isn't present
                display.debug2("\(path) not found on disk.")
                foundAllInstallItems = false
            }
        }
        if foundAllInstallItems {
            display.debug2("Found all installs items")
            return true
        }
    }
    if let itemName = pkginfo["name"] as? String,
       let receipts = pkginfo["receipts"] as? [PlistDict],
       !receipts.isEmpty
    {
        display.debug2("Checking receipts...")
        let pkgdata = await analyzeInstalledPkgs()

        if let installedNames = pkgdata["installed_names"] as? [String],
           installedNames.contains(itemName)
        {
            display.debug2("Found matching receipts")
            return true
        }
        display.debug2("Installed receipts don't match for \(itemName)")
    }
    // if we got this far, we failed all the tests, so the item
    // must not be installed (or we don't have the right info...)
    return false
}
