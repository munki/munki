//
//  appleupdates.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 4/11/20.
//  Copyright © 2020 The Munki Project. All rights reserved.
//

import AppKit
import Foundation

let INSTALLATSTARTUPFILE = "/Users/Shared/.com.googlecode.munki.installatstartup"

func writeInstallAtStartupFlagFile() {
    // writes out a file to trigger Munki to install Munki updates at next restart
    let plist = ["AppleUpdateAttemptMade": true]
    do {
        try writePlist(plist, toFile: INSTALLATSTARTUPFILE)
    } catch {
        // unfortunate, but not fatal.
        msc_log("MSC", "cant_write_file", msg: "Couldn't write \(INSTALLATSTARTUPFILE) -- \(error)")
    }
}

func killSystemPreferencesApp() {
    let runningApps = NSRunningApplication.runningApplications(withBundleIdentifier: "com.apple.systempreferences")
    for app in runningApps {
        _ = app.forceTerminate()
    }
}

func openSoftwareUpdatePrefsPane() {
    // kill it first in case it is open with a dialog/sheet
    //killSystemPreferencesApp() // nope, it reopens to previous pane
    writeInstallAtStartupFlagFile()
    if let softwareUpdatePrefsPane = URL(string: "x-apple.systempreferences:com.apple.preferences.softwareupdate") {
        NSWorkspace.shared.open(softwareUpdatePrefsPane)
    }
}

