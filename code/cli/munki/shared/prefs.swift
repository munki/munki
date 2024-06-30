//
//  prefs.swift
//  munki
//
//  Created by Greg Neagle on 6/25/24.
//

import Foundation

let DEFAULT_INSECURE_REPO_URL = "http://munki/repo"

// unlike the previous Python implementation, we define default
// preference values only if they are not None/nil
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
    "LogFile": "/Library/Managed Installs/Logs/ManagedSoftwareUpdate.log",
    "LoggingLevel": 1,
    "LogToSyslog": false,
    "ManagedInstallDir": "/Library/Managed Installs",
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

// and since we don't define default values if they are None/nil
// we need a list of keynames we will display for --show-config
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

func reloadPrefs() {
    /* Uses CFPreferencesAppSynchronize(BUNDLE_ID)
     to make sure we have the latest prefs. Call this
     if you have modified /Library/Preferences/ManagedInstalls.plist
     or /var/root/Library/Preferences/ManagedInstalls.plist directly */
    CFPreferencesAppSynchronize(BUNDLE_ID)
}

func setPref(_ prefName: String, _ prefValue: Any) {
    /* Sets a preference, writing it to
     /Library/Preferences/ManagedInstalls.plist.
     This should normally be used only for 'bookkeeping' values;
     values that control the behavior of munki may be overridden
     elsewhere (by MCX, for example) */
    if let key = prefName as CFString? {
        if let value = prefValue as CFPropertyList? {
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

func pref(_ prefName: String) -> Any? {
    /* Return a preference. Since this uses CFPreferencesCopyAppValue,
     Preferences can be defined several places. Precedence is:
     - MCX/configuration profile
     - /var/root/Library/Preferences/ByHost/ManagedInstalls.XXXXXX.plist
     - /var/root/Library/Preferences/ManagedInstalls.plist
     - /Library/Preferences/ManagedInstalls.plist
     - .GlobalPreferences defined at various levels (ByHost, user, system)
     - default_prefs defined here.
     */
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

struct prefsDomain {
    var file: String
    var domain: CFString
    var user: CFString
    var host: CFString
}

func isEqual(_ a: CFPropertyList, _ b: CFPropertyList) -> Bool {
    // attempt to compare two CFPropertyList objects that are actually one of:
    // String, Number, Boolean, Date
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

func getConfigLevel(_ domain: String, _ prefName: String, _ value: Any?) -> String {
    // Returns a string indicating where the given preference is defined
    if value == nil {
        return "[not set]"
    }
    if CFPreferencesAppValueIsForced(prefName as CFString, domain as CFString) {
        return "[MANAGED]"
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
                    return "[\(level.file)]"
                }
            }
        }
    }
    if let value = value as? CFPropertyList, let defaultValue = DEFAULT_PREFS["pref_name"] as? CFPropertyList {
        if isEqual(value, defaultValue) {
            return "[default]"
        }
    }
    return "[unknown]"
}

func printConfig() {
    // Prints the current Munki configuration
    print("Current Munki configuration:")
    let maxPrefNameLen = CONFIG_KEY_NAMES.max(by: { $1.count > $0.count })?.count ?? 0
    let padding = "                                                  "
    for prefName in CONFIG_KEY_NAMES.sorted() {
        let value = pref(prefName)
        let level = getConfigLevel(BUNDLE_ID as String, prefName, value)
        var reprValue = "None"
        // it's hard to distinguish a boolean from a number in a CFPropertyList item, so
        // we look at the type of the default value if defined
        if let numberValue = value as? NSNumber {
            if DEFAULT_PREFS[prefName] is Bool {
                if numberValue != 0 {
                    reprValue = "True"
                } else {
                    reprValue = "False"
                }
            } else {
                reprValue = "\(numberValue)"
            }
        } else if let stringValue = value as? String {
            reprValue = "\"\(stringValue)\""
        } else if let arrayValue = value as? NSArray {
            reprValue = "\(arrayValue)"
        }
        // print(('%' + str(max_pref_name_len) + 's: %5s %s ') % (
        //       pref_name, repr_value, level))
        let paddedPrefName = (padding + prefName).suffix(maxPrefNameLen)
        print("\(paddedPrefName): \(reprValue) \(level)")
    }
}
