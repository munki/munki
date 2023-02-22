//
//  Utils.swift
//  MunkiStatus
//
//  Created by Greg Neagle on 5/19/18.
//  Copyright © 2018-2023 The Munki Project. All rights reserved.
//

import Foundation
import AppKit
import SystemConfiguration

func logFilePref() -> String {
    /* Returns Munki's LogFile preference. Since this uses CFPreferencesCopyAppValue,
       preferences can be defined several places. Precedence is:
        - MCX/configuration profile
        - ~/Library/Preferences/ManagedInstalls.plist
        - /Library/Preferences/ManagedInstalls.plist
        - default_pref defined here.
    */
    let value = CFPreferencesCopyAppValue("LogFile" as CFString, "ManagedInstalls" as CFString)
    if value == nil {
        return "/Library/Managed Installs/Logs/ManagedSoftwareUpdate.log"
    }
    return value! as! String
}

func getconsoleuser() -> String? {
    return SCDynamicStoreCopyConsoleUser(nil, nil, nil) as String?
}

func atLoginWindow() -> Bool {
    let consoleuser = getconsoleuser()
    if consoleuser == nil {
        return true
    }
    return (consoleuser! == "loginwindow")
}

func exec(_ command: String, args: [String]?) -> String {
    // runs a UNIX command and returns stdout as a string
    let proc = Process()
    proc.launchPath = command
    proc.arguments = args
    let pipe = Pipe()
    proc.standardOutput = pipe
    proc.launch()
    let data = pipe.fileHandleForReading.readDataToEndOfFile()
    return String(data: data, encoding: String.Encoding.utf8)!
}

func pythonScriptRunning(_ scriptName: String) -> Bool {
    let output = exec("/bin/ps", args: ["-eo", "command="])
    let lines = output.components(separatedBy: "\n")
    for line in lines {
        let part = line.components(separatedBy: " ")
        if (part[0].contains("/MacOS/Python") || part[0].contains("python")) {
            if part.count > 1 {
                if part[1].contains(scriptName) {
                    print(line)
                    return true
                }
            }
        }
    }
    return false
}

func checkForElCapPolicyBanner() -> Bool {
    // Returns True if we are running El Cap or later and there is
    // a loginwindow PolicyBanner in place
    if #available(OSX 10.10, *) {
        let os_vers = OperatingSystemVersion(majorVersion: 10, minorVersion: 10, patchVersion: 0)
        if ProcessInfo().isOperatingSystemAtLeast(os_vers) {
            let testfiles = ["/Library/Security/PolicyBanner.txt",
                             "/Library/Security/PolicyBanner.rtf",
                             "/Library/Security/PolicyBanner.rtfd"]
            let fm = FileManager.default
            for testfile in testfiles {
                if fm.fileExists(atPath: testfile) {
                    print("haveElCapPolicyBanner == true")
                    return true
                }
            }
        }
    }
    print("haveElCapPolicyBanner == false")
    return false
}

let haveElCapPolicyBanner = checkForElCapPolicyBanner()
let backdropWindowLevel = haveElCapPolicyBanner ? NSWindow.Level.screenSaver : NSWindow.Level(998)
let statusWindowLevel = haveElCapPolicyBanner ? NSWindow.Level.screenSaver : NSWindow.Level(999)



