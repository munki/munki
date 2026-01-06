//
//  main.swift
//  installhelper
//
//  Created by Greg Neagle on 4/28/25.
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

// original Python implementation by Ben Toms @ Jamf (dataJAR)

import Foundation
import SystemConfiguration

private let LAUNCHD_PREFIX = "com.googlecode.munki."
private let APPUSAGE_AGENT = LAUNCHD_PREFIX + "app_usage_monitor"
private let APPUSAGE_DAEMON = LAUNCHD_PREFIX + "appusaged"
private let INSTALL_HELPER = LAUNCHD_PREFIX + "installhelper-"
private let PROG_NAME = "managedsoftwareupdate"
private let APP_NAME = "installhelper"
private let APP_VERSION = "0.2"
private let LOGFILENAME = APP_NAME + ".log"

/// Wrapper for logging
private func log(_ message: String) {
    munkiLog(message, logFile: LOGFILENAME)
}

/// Wrapper for our calls to launchctl so we can get more output when testing
private func launchctl(_ args: String...) -> CLIResults {
    #if DEBUG
        log("    Calling /bin/launchctl \(args.joined(separator: " "))")
    #endif
    let result = runCLI("/bin/launchctl", arguments: args)
    #if DEBUG
        if result.exitcode != 0 {
            log("    ERROR: exitcode \(result.exitcode): \(result.error)")
        }
    #endif
    return result
}

/// Returns a list of labels for active loginwindow agents
func getMunkiLoginWindowLaunchdLabels() -> [String] {
    let results = launchctl("print", "loginwindow/")
    // we get an error if we're not at the loginwindow
    if results.exitcode != 0 {
        return []
    }
    var labels: [String] = []
    for line in results.output.split(separator: "\n") {
        let parts = line.split(whereSeparator: { "\t ".contains($0) })
        let lastPart = String(parts.last ?? "")
        if lastPart.hasPrefix(LAUNCHD_PREFIX) {
            labels.append(lastPart)
        }
    }
    return labels
}

/// Takes launchctl list output and returns a list with just the labels of Munki jobs
func getMunkiLaunchdLabels(uid: UInt32 = 0) -> [String] {
    var labels: [String] = []
    var results: CLIResults = if uid == 0 {
        // get root's list (LaunchDaemons)
        launchctl("list")
    } else {
        // get the list for a user (LaunchAgents)
        launchctl("asuser", String(uid), "/bin/launchctl", "list")
    }

    for line in results.output.split(separator: "\n") {
        // Get the launchd label from the output
        let parts = line.split(whereSeparator: { "\t ".contains($0) })
        if parts.count > 2 {
            let lastPart = String(parts.last ?? "")
            if lastPart.hasPrefix(LAUNCHD_PREFIX) {
                labels.append(lastPart)
            }
        }
    }

    if uid == 0 {
        // remove any loginwindow agent labels from the list
        // (we want only labels of _LaunchDaemons_)
        let loginwindowLabels = getMunkiLoginWindowLaunchdLabels()
        labels.removeAll { loginwindowLabels.contains($0) }
    }
    return labels
}

/// Creates and loads the installhelper launch daemon
func createInstallHelperLaunchDaemon(_ group: String) {
    // Set name and path based on the value of launchd_group
    let label = INSTALL_HELPER + group
    let launchDaemonPath = "/Library/LaunchDaemons/\(label).plist"
    log("Creating launch daemon: \(launchDaemonPath)")

    // get running Munki launch daemons
    let launchdLabels = getMunkiLaunchdLabels()

    // Check to see if launch_daemon_name is already loaded, and stop if so
    if launchdLabels.contains(label) {
        // Stop the launch daemon
        _ = launchctl("bootout", "system/\(label)")
    }

    let launchDaemon: [String: Any] = [
        "AssociatedBundleIdentifiers": ["com.googlecode.munki.ManagedSoftwareCenter"],
        "EnvironmentVariables": ["INSTALLHELPER_RUN_TYPE": group],
        "Label": label,
        "ProgramArguments": ["/usr/local/munki/libexec/installhelper"],
        "RunAtLoad": true,
    ]
    // write out launchd plist
    do {
        try writePlist(launchDaemon, toFile: launchDaemonPath)
        // set owner, group and mode to those required
        // by launchd
        try FileManager.default.setAttributes(
            [.ownerAccountID: 0,
             .groupOwnerAccountID: 0,
             .posixPermissions: 0o644],
            ofItemAtPath: launchDaemonPath
        )
    } catch {
        log("ERROR: Could not create plist for launchd job \(label): \(error.localizedDescription)")
    }
    // load the job
    let result = launchctl("bootstrap", "system", launchDaemonPath)
    if result.exitcode != 0 {
        log("ERROR: launchctl bootstrap error for \(label): \(result.exitcode): \(result.error)")
    }
}

/// If managedsoftwareupdate is running, wait until it exits before returning
func waitForManagedSoftwareUpdateToExit() {
    while true {
        if let msuPid = anotherManagedsoftwareupdateInstanceRunning() {
            log(String(repeating: "*", count: 60))
            log("\(PROG_NAME) is running as pid \(msuPid).")
            log("Checking again in 10 seconds...")
            log(String(repeating: "*", count: 60))
            usleep(10_000_000)
        } else {
            break
        }
    }
    log("\(PROG_NAME) is not running, proceeding...")
}

/// get a list of Munki launchd plists (either LaunchAgents or LaunchDaemons)
func getMunkiLaunchdPlists(_ type: String) -> [String] {
    if !["LaunchAgents", "LaunchDaemons"].contains(type) {
        return []
    }
    var launchdItems: [String] = []
    let items = (try? FileManager.default.contentsOfDirectory(atPath: "/Library/\(type)")) ?? []
    for name in items {
        if fnmatch("\(LAUNCHD_PREFIX)*.plist", name, 0) == 0 {
            launchdItems.append("/Library/\(type)/\(name)")
        }
    }
    return launchdItems
}

/// Get and return the "label" from a launchd.plist
func getLaunchdLabel(_ launchAgentPath: String) -> String? {
    guard let agentContent = try? readPlist(fromFile: launchAgentPath) as? PlistDict else {
        return nil
    }
    return agentContent["Label"] as? String
}

/// Used to help us identify loginwindow launchd plists
enum LaunchAgentType {
    case invalid
    case loginwindow
    case user
}

/// This attempts to tell the difference between loginwindow agents and normal user agents
/// agents can actually have multiple types, but Munki itself only has normal user agents ("Aqua") and
/// loginwindow agents, so this implementation is a bit simplistic
func getLaunchAgentType(_ launchAgentPath: String) -> LaunchAgentType {
    guard let agentContent = try? readPlist(fromFile: launchAgentPath) as? PlistDict else {
        return .invalid
    }
    guard agentContent["Label"] is String else {
        return .invalid
    }
    if let sessionType = agentContent["LimitLoadToSessionType"] as? String,
       sessionType == "LoginWindow"
    {
        return .loginwindow
    }
    if let sessionTypes = agentContent["LimitLoadToSessionType"] as? [String],
       sessionTypes.contains("LoginWindow")
    {
        return .loginwindow
    }
    return .user
}

/// Return an array of pathnames for Munki LaunchDaemons
func getMunkiLaunchDaemonPlists() -> [String] {
    return getMunkiLaunchdPlists("LaunchDaemons")
}

/// Return an array of pathnames for Munki user-level LaunchAgents
func getMunkiUserLaunchAgentPlists() -> [String] {
    return getMunkiLaunchdPlists("LaunchAgents").filter {
        getLaunchAgentType($0) == .user
    }
}

/// Return an array of pathnames for Munki loginwindow LaunchAgents
func getMunkiLoginWindowLaunchAgentPlists() -> [String] {
    return getMunkiLaunchdPlists("LaunchAgents").filter {
        getLaunchAgentType($0) == .loginwindow
    }
}

/// Given a uid number, return a username
func userNameFromUID(_ uid: UInt32) -> String {
    if let p = getpwuid(uid) {
        return String(cString: p.pointee.pw_name)
    }
    return "<uid \(uid)>"
}

/// Returns an array of uids of users logged in via the GUI
/// Will be inaccurate if root is allowed a GUI login
func getLoggedInUIDs() -> [UInt32] {
    var uidList: [UInt32] = []
    let procList = UNIXProcessList()
    for proc in procList {
        if proc.command == "loginwindow" {
            if proc.uid != 0 {
                uidList.append(proc.uid)
            }
        }
    }
    return uidList
}

/// Load, or unload and reload Munki launch agents for each logged-in user
func reloadUserLaunchAgents(group: String) {
    let uids = getLoggedInUIDs()
    for uid in uids {
        log("Processing LaunchAgents for \(userNameFromUID(uid))")
        // first, unload active Munki jobs
        var activeAgentLabels = getMunkiLaunchdLabels(uid: uid)
        if group == "appusage" {
            activeAgentLabels = activeAgentLabels.filter { $0 == APPUSAGE_AGENT }
        }
        if group == "launchd" {
            // unload everything but APPUSAGE_AGENT
            activeAgentLabels = activeAgentLabels.filter { $0 != APPUSAGE_AGENT }
        }
        for label in activeAgentLabels {
            log("Stopping agent \(label)")
            _ = launchctl("bootout", "gui/\(String(uid))/\(label)")
        }
        // second, load jobs from the munki launch agent plists
        let APPUSAGE_PLIST = "/Library/LaunchAgents/\(APPUSAGE_AGENT).plist"
        var plists = getMunkiUserLaunchAgentPlists()
        if group == "appusage" {
            // only load APPUSAGE_PLIST
            if plists.contains(APPUSAGE_PLIST) {
                plists = [APPUSAGE_PLIST]
            }
        }
        if group == "launchd" {
            // load all agent plists _except_ APPUSAGE_PLIST
            plists.removeAll { $0 == APPUSAGE_PLIST }
        }
        for plist in plists {
            if let label = getLaunchdLabel(plist) {
                // enable the job
                log("Enabling agent \(label)")
                _ = launchctl("enable", "gui/\(String(uid))/\(label)")
                // load the launch agent
                log("Loading agent \(plist)")
                _ = launchctl("bootstrap", "gui/\(String(uid))", plist)
            }
        }
    }
}

/// Returns console user (the current GUI user)
private func getConsoleUser() -> String {
    return SCDynamicStoreCopyConsoleUser(nil, nil, nil) as? String ?? ""
}

/// Reload Munki loginwindow agents if needed
func reloadMunkiLoginwindowLaunchAgents() {
    if getConsoleUser() != "loginwindow" {
        // we're not at the loginwindow, so nothing to do
        log("Skipping loginwindow launchd reload, we're not at the loginwindow")
        return
    }
    log("Processing Munki loginwindow launchd jobs...")
    // first, unload all active loginwindow jobs
    let activeLoginwindowLabels = getMunkiLoginWindowLaunchdLabels()
    for label in activeLoginwindowLabels {
        log("Stopping loginwindow agent \(label)")
        _ = launchctl("bootout", "loginwindow/\(label)")
    }
    // second, load any loginwindow agent plists
    for plist in getMunkiLoginWindowLaunchAgentPlists() {
        if let label = getLaunchdLabel(plist) {
            // enable the job
            log("Enabling loginwindow agent \(label)")
            _ = launchctl("enable", "loginwindow/\(label)")
            // load the launch agent
            log("Loading loginwindow agent \(plist)")
            _ = launchctl("bootstrap", "loginwindow/", plist)
        }
    }
}

/// Reload Munki launch daemons
func reloadLaunchDaemons(group: String) {
    log("Processing launch daemons")
    // first, unload active Munki jobs
    var activeDaemonLabels = getMunkiLaunchdLabels()
    if group == "appusage" {
        // we should only unload APPUSAGE_DAEMON if if's active
        activeDaemonLabels = activeDaemonLabels.filter { $0 == APPUSAGE_DAEMON }
    }
    if group == "launchd" {
        // unload all Munki jobs _except_ APPUSAGE_DAEMON and our installhelper jobs
        activeDaemonLabels.removeAll {
            $0.hasPrefix(INSTALL_HELPER) || $0 == APPUSAGE_DAEMON
        }
    }
    for label in activeDaemonLabels {
        log("Stopping launch daemon \(label)")
        _ = launchctl("bootout", "system/\(label)")
    }
    // second, load jobs from the munki launch daemon plists
    let APPUSAGE_PLIST = "/Library/LaunchDaemons/\(APPUSAGE_DAEMON).plist"
    var plists = getMunkiLaunchDaemonPlists()
    if group == "appusage" {
        // only load APPUSAGE_PLIST
        if plists.contains(APPUSAGE_PLIST) {
            plists = [APPUSAGE_PLIST]
        }
    }
    if group == "launchd" {
        // load all daemon plists _except_ APPUSAGE_PLIST and our installhelper plists
        plists.removeAll { $0 == APPUSAGE_PLIST || $0.contains(INSTALL_HELPER) }
    }
    for plist in plists {
        if let label = getLaunchdLabel(plist) {
            // enable the job
            log("Enabling daemon \(label)")
            _ = launchctl("enable", "system/\(label)")
            // load the launch agent
            log("Loading daemon \(plist)")
            _ = launchctl("bootstrap", "system/", plist)
        }
    }
}

/// clean up if needed
func cleanUp(group: String) {
    let label = INSTALL_HELPER + group
    let launchDaemonPath = "/Library/LaunchDaemons/\(label).plist"
    if FileManager.default.fileExists(atPath: launchDaemonPath) {
        log("Completed launchd tasks, cleaning up")
        // have to delete the file _before_ we unload the job, or we kill ourselves
        log("Deleting \(launchDaemonPath)")
        try? FileManager.default.removeItem(atPath: launchDaemonPath)
        log("Unloading launch daemon \(label)")
        _ = launchctl("bootout", "system/" + label)
    }
}

/// Load, or unload and reload Munki launchd jobs
func reloadMunkiLaunchdJobs(_ group: String) {
    // Only proceed if managedsoftwareupdate isn't running,
    // looping until it's not running
    waitForManagedSoftwareUpdateToExit()
    reloadUserLaunchAgents(group: group)
    if group == "launchd" {
        reloadMunkiLoginwindowLaunchAgents()
    }
    reloadLaunchDaemons(group: group)
    cleanUp(group: group)
}

/// main function
func main() {
    // check to see if we"re root
    if NSUserName() != "root" {
        printStderr("You must run this as root!")
        exit(-1)
    }

    rotateLog(LOGFILENAME, ifLargerThan: 1_000_000)
    log("Starting \(APP_NAME) \(APP_VERSION)")

    // get our launch group from either the environment or the first argument
    var group = "<none>"
    var manualLaunch = true
    let env = ProcessInfo.processInfo.environment
    if env.keys.contains("INSTALLHELPER_RUN_TYPE") {
        group = (env["INSTALLHELPER_RUN_TYPE"] ?? "<none>").lowercased()
        manualLaunch = false
    } else {
        let args = ProcessInfo.processInfo.arguments
        if args.count > 1 {
            group = args[1].lowercased()
        }
    }
    // validate the group
    let VALID_GROUPS = ["appusage", "launchd"]
    if !VALID_GROUPS.contains(group) {
        log("ERROR: Unknown launchd group: \(group)")
        printStderr("ERROR: Unknown launchd group: \(group)")
        printStderr("Must be one of \(VALID_GROUPS.joined(separator: ", "))")
        exit(-1)
    }

    if manualLaunch {
        log("Launched manually - arg: \(group)")
        createInstallHelperLaunchDaemon(group)
    } else {
        log("Launched via launchd - arg: \(group)")
        reloadMunkiLaunchdJobs(group)
    }
}

main()
