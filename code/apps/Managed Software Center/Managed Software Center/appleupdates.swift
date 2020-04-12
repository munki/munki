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

func openSoftwareUpdatePrefsPane() {
    if let softwareUpdatePrefsPane = URL(string: "x-apple.systempreferences:com.apple.preferences.softwareupdate") {
        writeInstallAtStartupFlagFile()
        NSWorkspace.shared.open(softwareUpdatePrefsPane)
    }
}

