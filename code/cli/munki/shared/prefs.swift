//
//  prefs.swift
//  munki
//
//  Created by Greg Neagle on 6/25/24.
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

let DEFAULT_INSECURE_REPO_URL = "http://munki/repo"

/// Unlike the previous Python implementation, we define default
/// preference values only if they are not None/nil
let DEFAULT_PREFS: [String: Any] = [
    // "AdditionalHttpHeaders": None,
    "AggressiveUpdateNotificationDays": 14,
    "AppleSoftwareUpdatesIncludeMajorOSUpdates": false,
    "AppleSoftwareUpdatesOnly": false,
    // "CatalogURL": None,
    // "ClientCertificatePath": None,
    "ClientIdentifier": "",
    // "ClientKeyPath": None,
    // "ClientResourcesFilename": None,
    // "ClientResourceURL": None,
    "DaysBetweenNotifications": 1,
    "EmulateProfileSupport": false,
    "FollowHTTPRedirects": "none",
    // "HelpURL": None,
    // "IconURL": None,
    "IgnoreMiddleware": false,
    "IgnoreSystemProxies": false,
    "InstallRequiresLogout": false,
    "InstallAppleSoftwareUpdates": false,
    "LastNotifiedDate": NSDate(timeIntervalSince1970: 0),
    // "LocalOnlyManifest": None,
    "LogFile": "\(DEFAULT_MANAGED_INSTALLS_DIR)/Logs/ManagedSoftwareUpdate.log",
    "LoggingLevel": 1,
    "LogToSyslog": false,
    "ManagedInstallDir": DEFAULT_MANAGED_INSTALLS_DIR,
    // "ManifestURL": None,
    // "PackageURL": None,
    "PackageVerificationMode": "hash",
    "PerformAuthRestarts": false,
    // "RecoveryKeyFile": None,
    "ShowOptionalInstallsForHigherOSVersions": false,
    // "SoftwareRepoCACertificate": None,
    // "SoftwareRepoCAPath": None,
    "SoftwareRepoURL": DEFAULT_INSECURE_REPO_URL,
    // "SoftwareUpdateServerURL": None,
    "SuppressAutoInstall": false,
    "SuppressLoginwindowInstall": false,
    "SuppressStopButtonOnInstall": false,
    "SuppressUserNotification": false,
    "UnattendedAppleUpdates": false,
    "UseClientCertificate": false,
    "UseClientCertificateCNAsClientIdentifier": false,
    "UseNotificationCenterDays": 3,
]

/// Since we don't define default values if they are None/nil
/// we need a list of keynames we will display for --show-config
let CONFIG_KEY_NAMES = [
    "AdditionalHttpHeaders",
    "AggressiveUpdateNotificationDays",
    "AppleSoftwareUpdatesIncludeMajorOSUpdates",
    "AppleSoftwareUpdatesOnly",
    "CatalogURL",
    "ClientCertificatePath",
    "ClientIdentifier",
    "ClientKeyPath",
    "ClientResourcesFilename",
    "ClientResourceURL",
    "DaysBetweenNotifications",
    "EmulateProfileSupport",
    "FollowHTTPRedirects",
    "HelpURL",
    "IconURL",
    "IgnoreMiddleware",
    "IgnoreSystemProxies",
    "InstallRequiresLogout",
    "InstallAppleSoftwareUpdates",
    "LocalOnlyManifest",
    "LogFile",
    "LoggingLevel",
    "LogToSyslog",
    "ManagedInstallDir",
    "ManifestURL",
    "PackageURL",
    "PackageVerificationMode",
    "PerformAuthRestarts",
    "RecoveryKeyFile",
    "ShowOptionalInstallsForHigherOSVersions",
    "SoftwareRepoCACertificate",
    "SoftwareRepoCAPath",
    "SoftwareRepoURL",
    "SoftwareUpdateServerURL",
    "SuppressAutoInstall",
    "SuppressLoginwindowInstall",
    "SuppressStopButtonOnInstall",
    "SuppressUserNotification",
    "UnattendedAppleUpdates",
    "UseClientCertificate",
    "UseClientCertificateCNAsClientIdentifier",
    "UseNotificationCenterDays",
]

/// Uses CFPreferencesAppSynchronize(BUNDLE_ID) to make sure
/// we have the latest prefs. Call this if you have modified
/// /Library/Preferences/ManagedInstalls.plist
/// or /var/root/Library/Preferences/ManagedInstalls.plist directly
func reloadPrefs() {
    CFPreferencesAppSynchronize(BUNDLE_ID)
}

/// Sets a preference, writing it to /Library/Preferences/ManagedInstalls.plist.
/// This should normally be used only for 'bookkeeping' values;
/// values that control the behavior of munki may be overridden
/// elsewhere (by config profiles, for example)
func setPref(_ prefName: String, _ prefValue: Any?) {
    if let key = prefName as CFString? {
        if prefValue == nil {
            CFPreferencesSetValue(
                key, nil, BUNDLE_ID,
                kCFPreferencesAnyUser, kCFPreferencesCurrentHost
            )
            CFPreferencesAppSynchronize(BUNDLE_ID)
        } else if let value = prefValue as CFPropertyList? {
            CFPreferencesSetValue(
                key, value, BUNDLE_ID,
                kCFPreferencesAnyUser, kCFPreferencesCurrentHost
            )
            CFPreferencesAppSynchronize(BUNDLE_ID)
        } else {
            // raise error about illegal value?
        }
    } else {
        // raise error about illegal key?
    }
}

/// Return a preference. Since this uses CFPreferencesCopyAppValue,
/// Preferences can be defined several places. Precedence is:
/// - MCX/configuration profile
/// - /var/root/Library/Preferences/ByHost/ManagedInstalls.XXXXXX.plist
/// - /var/root/Library/Preferences/ManagedInstalls.plist
/// - /Library/Preferences/ManagedInstalls.plist
/// - .GlobalPreferences defined at various levels (ByHost, user, system)
/// - default_prefs defined here.
func pref(_ prefName: String) -> Any? {
    var prefValue: Any?
    prefValue = CFPreferencesCopyAppValue(prefName as CFString, BUNDLE_ID)
    if prefValue == nil {
        if let defaultValue = DEFAULT_PREFS[prefName] {
            prefValue = defaultValue
            // we're using a default value. We'll write it out to
            // /Library/Preferences/<BUNDLE_ID>.plist for admin discoverability
            setPref(prefName, defaultValue)
        }
    }
    // prior Python implementation converted dates to strings; we won't do that
    /* if isinstance(pref_value, NSDate):
     # convert NSDate/CFDates to strings
     pref_value = str(pref_value) */
    return prefValue
}

/// Returns preference as a String if possible
func stringPref(_ prefName: String) -> String? {
    return pref(prefName) as? String
}

/// Returns preference as a Bool if possible
func boolPref(_ prefName: String) -> Bool? {
    return pref(prefName) as? Bool
}

/// Returns preference as an Int if possible
func intPref(_ prefName: String) -> Int? {
    return pref(prefName) as? Int
}

/// Returns preference as a Date if possible
func datePref(_ prefName: String) -> Date? {
    if let date = pref(prefName) as? Date {
        return date
    }
    if let str = pref(prefName) as? String {
        let dateFormatter = ISO8601DateFormatter()
        if let date = dateFormatter.date(from: str) {
            return date
        }
    }
    return nil
}

/// Convenience function to return the path to the Managed Installs dir
/// or a subpath of that directory
func managedInstallsDir(subpath: String? = nil) -> String {
    let managedInstallsDir = pref("ManagedInstallDir") as? String ?? DEFAULT_MANAGED_INSTALLS_DIR
    if let subpath {
        return (managedInstallsDir as NSString).appendingPathComponent(subpath)
    }
    return managedInstallsDir
}

struct prefsDomain {
    var file: String
    var domain: CFString
    var user: CFString
    var host: CFString
}

/// Attempt to compare two CFPropertyList objects that are actually one of:
/// String, Number, Boolean, Date
func isEqual(_ a: CFPropertyList, _ b: CFPropertyList) -> Bool {
    if let aString = a as? String, let bString = b as? String {
        return aString == bString
    }
    if let aNumber = a as? NSNumber, let bNumber = b as? NSNumber {
        return aNumber == bNumber
    }
    if let aDate = a as? NSDate, let bDate = b as? NSDate {
        return aDate == bDate
    }
    return false
}

/// Returns a string indicating where the given preference is defined
func getConfigLevel(_ domain: String, _ prefName: String, _ value: Any?) -> String {
    if value == nil {
        return "not set"
    }
    if CFPreferencesAppValueIsForced(prefName as CFString, domain as CFString) {
        return "MANAGED"
    }
    // define all the places we need to search, in priority order
    let levels: [prefsDomain] = [
        prefsDomain(
            file: "/var/root/Library/Preferences/ByHost/\(domain).xxxx.plist",
            domain: domain as CFString,
            user: kCFPreferencesCurrentUser,
            host: kCFPreferencesCurrentHost
        ),
        prefsDomain(
            file: "/var/root/Library/Preferences/\(domain).plist",
            domain: domain as CFString,
            user: kCFPreferencesCurrentUser,
            host: kCFPreferencesAnyHost
        ),
        prefsDomain(
            file: "/var/root/Library/Preferences/ByHost/.GlobalPreferences.xxxx.plist",
            domain: ".GlobalPreferences" as CFString,
            user: kCFPreferencesCurrentUser,
            host: kCFPreferencesCurrentHost
        ),
        prefsDomain(
            file: "/var/root/Library/Preferences/.GlobalPreferences.plist",
            domain: ".GlobalPreferences" as CFString,
            user: kCFPreferencesCurrentUser,
            host: kCFPreferencesAnyHost
        ),
        prefsDomain(
            file: "/Library/Preferences/\(domain).plist",
            domain: domain as CFString,
            user: kCFPreferencesAnyUser,
            host: kCFPreferencesCurrentHost
        ),
        prefsDomain(
            file: "/Library/Preferences/.GlobalPreferences.plist",
            domain: ".GlobalPreferences" as CFString,
            user: kCFPreferencesAnyUser,
            host: kCFPreferencesCurrentHost
        ),
    ]
    for level in levels {
        if let levelValue = CFPreferencesCopyValue(
            prefName as CFString,
            level.domain,
            level.user,
            level.host
        ) {
            if let ourValue = value as? CFPropertyList {
                if isEqual(ourValue, levelValue) {
                    return level.file
                }
            }
        }
    }
    if let value = value as? CFPropertyList, let defaultValue = DEFAULT_PREFS["pref_name"] as? CFPropertyList {
        if isEqual(value, defaultValue) {
            return "default"
        }
    }
    return "unknown"
}
