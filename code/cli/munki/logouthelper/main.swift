//
//  main.swift
//  logouthelper
//
//  Created by Greg Neagle on 1/6/25.
//
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

/// A helper tool for forced logouts to allow munki to force install items by a certain deadline.

import AppKit
import Foundation

private let NOTIFICATION_MINS = [240, 180, 120, 90, 60, 45, 30, 15, 10, 5]
private let MANDATORY_NOTIFICATIONS = [60, 30, 10, 5]
private let PROCESS_ID = "com.googlecode.munki.logouthelper"
private let LOGINWINDOW_PATH = "/System/Library/CoreServices/loginwindow.app/Contents/MacOS/loginwindow"

/// Logs messages from this tool with an identifier
func log(_ message: String) {
    munkiLog("\(PROCESS_ID): \(message)")
}

/// Check installable packages for force_install_after_dates
/// Returns nil or earliest force_install_after_date converted to local time
func earliestForceInstallDate() -> Date? {
    var earliestDate: Date?
    let installinfoTypes = [
        "InstallInfo.plist": "managed_installs",
        "AppleUpdates.plist": "AppleUpdates",
    ]
    let installinfopath = managedInstallsDir(subpath: "InstallInfo.plist")
    guard let installInfo = try? readPlist(fromFile: installinfopath) else {
        return nil
    }

    for (plistName, keyToCheck) in installinfoTypes {
        let plistPath = managedInstallsDir(subpath: plistName)
        guard let installInfo = try? readPlist(fromFile: installinfopath) as? PlistDict else {
            continue
        }
        guard let installItems = installInfo[keyToCheck] as? [PlistDict] else {
            continue
        }
        for install in installItems {
            if var forceInstallDate = install["force_install_after_date"] as? Date {
                forceInstallDate = subtractTZOffsetFromDate(forceInstallDate)
                if earliestDate == nil || forceInstallDate < earliestDate! {
                    earliestDate = forceInstallDate
                }
            }
        }
    }
    return earliestDate
}

func createEmptyFile(_ path: String) {
    let fileManager = FileManager.default
    _ = fileManager.createFile(atPath: path, contents: Data())
}

///  Triggers a LaunchAgent to launch Managed Software Center for us in the user's context
func launchOrActivateManagedSoftwareCenter() {
    createEmptyFile(MSCLAUNCHFILE)
    usleep(5_000_000)
    if pathExists(MSCLAUNCHFILE) {
        try? FileManager.default.removeItem(atPath: MSCLAUNCHFILE)
    }
}

/// Force the logout of interactive GUI users and cause Munki to install at logout
func forceLogoutNow() {
    // cause Munki to install at logout
    createEmptyFile(INSTALLATLOGOUTFLAG)
    // kill loginwindows to cause logout of current users, whether
    // active or switched away via fast user switching.
    let loginwindowProcesses = UNIXProcessListWithPaths().filter {
        $0.path == LOGINWINDOW_PATH
    }
    for process in loginwindowProcesses {
        if process.uid != 0 {
            _ = kill(process.pid, SIGKILL)
        }
    }
}

/// Uses Managed Software Center.app to notify the user of an upcoming forced logout.
func alertUserOfForcedLogout(_ infoDict: PlistDict? = nil) {
    launchOrActivateManagedSoftwareCenter()
    let dnc = DistributedNotificationCenter.default()
    dnc.postNotificationName(
        NSNotification.Name(rawValue: "com.googlecode.munki.ManagedSoftwareUpdate.logoutwarn"),
        object: nil,
        userInfo: infoDict,
        options: [.deliverImmediately, .postToAllSessions]
    )
    // make sure flag is in place to cause Munki to install at logout
    createEmptyFile(INSTALLATLOGOUTFLAG)
}

/// Check for logged-in users and upcoming forced installs;
/// notify the user if needed; sleep a minute and do it again.
func main() -> Int32 {
    // if prefs.pref('LogToSyslog'):
    //     munkilog.configure_syslog()

    log("launched")
    var sentNotifications = [Int]()
    var logoutTimeOverride: Date?
    var logoutTime = Date.distantFuture

    // minimum notification of 60 minutes + 3 seconds
    let minimumNotificationMinutes = Double(MANDATORY_NOTIFICATIONS.max() ?? 60)
    let minimumNotificationsLogoutTime = Date().addingTimeInterval(60 * minimumNotificationMinutes + 30)

    while true {
        if currentGUIUsers().isEmpty {
            // no-one is logged in, so bail
            log("no-one logged in")
            usleep(10_000_000) // Makes launchd happier
            log("exited")
            return 0
        }

        // we check each time because items might have been added or removed
        // from the list; or their install date may have been changed.
        guard let nextLogoutTime = earliestForceInstallDate() else {
            // no forced logout needed, so bail
            log("no forced installs found")
            usleep(10_000_000) // makes launchd happier
            log("exited")
            return 0
        }

        if logoutTimeOverride == nil {
            log("set logout time to \(logoutTime)")
            logoutTime = nextLogoutTime
        } else {
            // allow the new nextLogoutTime from InstallInfo to be used
            // if it has changed to a later time since when we decided to
            // override it.
            if nextLogoutTime > logoutTimeOverride! {
                logoutTime = nextLogoutTime
                log("reset logout time to \(logoutTime)")
                logoutTimeOverride = nil
                // reset sent notifications
                sentNotifications = [Int]()
            }
        }

        // always give at least MANDATORY_NOTIFICATIONS warnings
        if logoutTime < minimumNotificationsLogoutTime {
            for notification in MANDATORY_NOTIFICATIONS {
                if !sentNotifications.contains(notification) {
                    log("\(notification) minute notification not sent.")
                    logoutTime = Date().addingTimeInterval(60 * TimeInterval(notification) + 30)
                    log("reset logout time to \(logoutTime)")
                    logoutTimeOverride = logoutTime
                    break
                }
            }
        }

        // do we need to notify?
        let minutesUntilLogout = Int(logoutTime.timeIntervalSinceNow / 60)
        let infoDict = ["logout_time": logoutTime]
        if NOTIFICATION_MINS.contains(minutesUntilLogout) {
            sentNotifications.append(minutesUntilLogout)
            log("Warning user of \(minutesUntilLogout) minutes until forced logout")
            alertUserOfForcedLogout(infoDict)
        } else if minutesUntilLogout < 1 {
            log("Forced logout in 60 seconds")
            alertUserOfForcedLogout(infoDict)
        }

        usleep(60_000_000)
        if minutesUntilLogout < 1 {
            break
        }
    }

    // exited loop, now time to force a logout
    if !currentGUIUsers().isEmpty, earliestForceInstallDate() != nil {
        log("Beginning forced logout")
        forceLogoutNow()
    }
    log("exited")
    return 0
}

/// run it!
exit(main())
