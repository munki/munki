//
//  appleupdates.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 4/11/20.
//  Copyright © 2020-2026 The Munki Project. All rights reserved.
//

import AppKit
import Foundation
import OpenDirectory


let INSTALLATSTARTUPFILE = "/Users/Shared/.com.googlecode.munki.installatstartup"
let CHECKANDINSTALLATSTARTUPFILE = "/Users/Shared/.com.googlecode.munki.checkandinstallatstartup"

func writeInstallAtStartupFlagFile(skipAppleUpdates: Bool = true) {
    // writes out a file to trigger Munki to install Munki updates at next restart or logout
    let plist = ["SkipAppleUpdates": skipAppleUpdates]
    do {
        try writePlist(plist, toFile: INSTALLATSTARTUPFILE)
    } catch {
        // unfortunate, but not fatal.
        msc_log("MSC", "cant_write_file", msg: "Couldn't write \(INSTALLATSTARTUPFILE) -- \(error)")
    }
}

func clearLogoutAndStartupFlagFiles() {
    // Remove the all logout/startup flag files if they exist so we don't try to install at logout
    // while Apple Software Update is doing its thing
    for fileName in [INSTALLATLOGOUTFILE, INSTALLATSTARTUPFILE, CHECKANDINSTALLATSTARTUPFILE] {
        if FileManager.default.isDeletableFile(atPath: fileName) {
            do {
                try FileManager.default.removeItem(atPath: fileName)
            } catch {
                // unfortunate, but not much we can do about it!
                msc_log("MSC", "cant_delete_file", msg: "Couldn't delete \(fileName) -- \(error)")
            }
        }
    }
}

func killSystemPreferencesApp() {
    // force quits System Preferences if it's open
    let runningApps = NSRunningApplication.runningApplications(withBundleIdentifier: "com.apple.systempreferences")
    for app in runningApps {
        _ = app.forceTerminate()
    }
}

func openSoftwareUpdatePrefsPane() {
    // kill it first in case it is open with a dialog/sheet
    //killSystemPreferencesApp() // nope, it reopens to previous pane
    clearLogoutAndStartupFlagFiles()
    if #available(macOS 13, *) {
        // open System Settings > General > Software Updates"
        if let softwareUpdatePrefsPane = URL(string: "x-apple.systempreferences:com.apple.Software-Update-Settings.extension") {
            NSWorkspace.shared.open(softwareUpdatePrefsPane)
        }
    } else {
        // open System Preferences > Software Update pane
        if let softwareUpdatePrefsPane = URL(string: "x-apple.systempreferences:com.apple.preferences.softwareupdate") {
            NSWorkspace.shared.open(softwareUpdatePrefsPane)
        }
    }
}

func userMustBeAdminToInstallAppleUpdates() -> Bool {
    // returns a boolean telling if the user must be an admin to install Apple Updates
    let suMustBeAdmin = CFPreferencesCopyAppValue(
        "restrict-software-update-require-admin-to-install" as CFString,
        "com.apple.SoftwareUpdate" as CFString) as? Bool ?? false
    let suMustBeAdminIsForced = CFPreferencesAppValueIsForced(
        "restrict-software-update-require-admin-to-install" as CFString,
        "com.apple.SoftwareUpdate" as CFString)
    let appStoreMustBeAdmin = CFPreferencesCopyAppValue(
        "restrict-store-require-admin-to-install" as CFString,
        "com.apple.appstore" as CFString ) as? Bool ?? false
    let appStoreMustBeAdminIsForced = CFPreferencesAppValueIsForced(
        "restrict-store-require-admin-to-install" as CFString,
        "com.apple.appstore" as CFString)
    return (suMustBeAdmin && suMustBeAdminIsForced) || (appStoreMustBeAdmin && appStoreMustBeAdminIsForced)
}

func findODgroupRecords(groupname: String, nodename: String = "/Search") throws -> [ODRecord] {
    // Uses OpenDirectory methods to find user records for username
    let searchNode = try ODNode(session: ODSession.default(), name: nodename)
    let query = try ODQuery(node: searchNode,
                            forRecordTypes: kODRecordTypeGroups,
                            attribute: kODAttributeTypeRecordName,
                            matchType: ODMatchType(kODMatchEqualTo),
                            queryValues: groupname,
                            returnAttributes: kODAttributeTypeAllAttributes,
                            maximumResults: 0)
    return (try query.resultsAllowingPartial(false) as! [ODRecord])
}

func findODgroupRecord(groupname: String, nodename: String = "/Search") -> ODRecord? {
    // Returns first record found for groupname, or nil if not found
    do {
        let records = try findODgroupRecords(groupname: groupname)
        if records.isEmpty {
            return nil
        }
        return records[0]
    } catch {
        return nil
    }
}

func userIsAdmin() -> Bool {
    let username = NSUserName()
    if let userRecord = findODuserRecord(username: username) {
        if let adminGroupRecord = findODgroupRecord(groupname: "admin", nodename: "/Local/Default") {
            do {
                try adminGroupRecord.isMemberRecord(userRecord)
                return true
            } catch {
                return false
            }
        }
    }
    return false
}

func su_pref(_ prefName: String) -> Any? {
    // Return a com.apple.SoftwareUpdate preference.
    return CFPreferencesCopyValue(prefName as CFString,
                                  "com.apple.SoftwareUpdate" as CFString,
                                  kCFPreferencesAnyUser,
                                  kCFPreferencesCurrentHost)
}

func suRecommendedUpdateIDs() -> [String] {
    // returns a list of productids for the SoftwareUpdate recommended ids
    var ids = [String]()
    if let recommendedUpdates = su_pref("RecommendedUpdates") as? [[String: Any]] {
        for update in recommendedUpdates {
            if let productKey = update["Product Key"] as? String {
                ids.append(productKey)
            }
        }
    }
    return ids
}
