//
//  processes.swift
//  munki
//
//  Created by Greg Neagle on 8/5/24.
//

import Foundation

func getRunningProcesses() -> [String] {
    // Returns a list of paths of running processes
    let result = runCLI("/bin/ps", arguments: ["-axo", "comm="])
    if result.exitcode == 0 {
        return result.output.components(separatedBy: .newlines).filter { $0.hasPrefix("/") }
    }
    return [String]()
}

func isAppRunning(_ appName: String) -> Bool {
    // Tries to determine if the application in appname is currently
    // running
    displayDetail("Checking if \(appName) is running...")
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
        displayDebug1("Matching process list: \(matchingItems)")
        displayDebug1("\(appName) is running!")
        return true
    }
    // if we get here, we have no evidence that appname is running
    return false
}

func blockingApplicationsRunning(_ pkginfo: PlistDict) -> Bool {
    // Returns true if any application in the blocking_applications list
    // is running or, if there is no blocking_applications list, if any
    // application in the installs list is running.
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
    displayDebug1("Checking for \(appNames)")
    let runningApps = appNames.filter { isAppRunning($0) }
    if !runningApps.isEmpty {
        let itemName = pkginfo["name"] as? String ?? "<unknown>"
        displayDetail("Blocking apps for \(itemName) are running:")
        displayDetail("    \(runningApps)")
        return true
    }
    return false
}
