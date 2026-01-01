//
//  BlockingApplications.swift
//  munki
//
//  Created by Greg Neagle on 4/29/25.
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

/// Tries to determine if the application in appname is currently running
func isAppRunning(_ appName: String) -> Bool {
    let display = DisplayAndLog.main
    display.detail("Checking if \(appName) is running...")
    let procList = getRunningProcesses()
    var matchingItems = [String]()
    if appName.hasPrefix("/") {
        // search by exact path
        matchingItems = procList.filter { $0 == appName }
    } else if appName.hasSuffix(".app") {
        // search by filename
        let searchName = "/" + appName + "/Contents/MacOS/"
        matchingItems = procList.filter { $0.contains(searchName) }
    } else {
        // check executable name
        matchingItems = procList.filter { $0.hasSuffix("/" + appName) }
    }
    if matchingItems.isEmpty {
        // try adding '.app' to the name and check again
        let searchName = "/" + appName + ".app/Contents/MacOS/"
        matchingItems = procList.filter { $0.contains(searchName) }
    }
    if !matchingItems.isEmpty {
        // it's running!
        display.debug1("Matching process list: \(matchingItems)")
        display.debug1("\(appName) is running!")
        return true
    }
    // if we get here, we have no evidence that appname is running
    return false
}

/// Returns true if any application in the blocking_applications list is running
/// or, if there is no blocking_applications list, true if any application in the installs list is running.
func blockingApplicationsRunning(_ pkginfo: PlistDict) -> Bool {
    let display = DisplayAndLog.main
    var appNames = [String]()
    if let blockingApplications = pkginfo["blocking_applications"] as? [String] {
        appNames = blockingApplications
    } else {
        // if no blocking_applications specified, get appnames
        // from 'installs' list if it exists
        if let installs = pkginfo["installs"] as? [PlistDict] {
            let apps = installs.filter {
                $0["type"] as? String ?? "" == "application"
            }
            appNames = apps.map {
                ($0["path"] as? NSString)?.lastPathComponent ?? ""
            }.filter { !$0.isEmpty }
        }
    }
    display.debug1("Checking for \(appNames)")
    let runningApps = appNames.filter { isAppRunning($0) }
    if !runningApps.isEmpty {
        let itemName = pkginfo["name"] as? String ?? "<unknown>"
        display.detail("Blocking apps for \(itemName) are running:")
        display.detail("    \(runningApps)")
        return true
    }
    return false
}
