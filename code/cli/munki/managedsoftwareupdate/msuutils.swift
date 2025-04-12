//
//  msuutils.swift
//  munki
//
//  Created by Greg Neagle on 8/27/24.
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

/// Clear the last date the user was notified of updates.
func clearLastNotifiedDate() {
    setPref("LastNotifiedDate", nil)
}

/// Attempts to create any missing directories needed by managedsoftwareupdate
/// Returns a boolean to indicate success
func initMunkiDirs() -> Bool {
    var dirlist = [managedInstallsDir()]
    for subdir in [
        "Archives",
        "Cache",
        "Logs",
        "catalogs",
        "client_resources",
        "icons",
        "manifests",
    ] {
        dirlist.append(managedInstallsDir(subpath: subdir))
    }
    var success = true
    for dir in dirlist {
        if !pathExists(dir) {
            do {
                try FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: false)
            } catch {
                displayError("Could not create missing directory \(dir): \(error.localizedDescription)")
                success = false
            }
        }
    }
    return success
}

/// Run an external script. Do not run if the permissions on the external
/// script file are weaker than the current executable.
func runMunkiDirScript(_ scriptPath: String, taskName: String, runType: String) async -> Int {
    if !pathExists(scriptPath) {
        return 0
    }
    displayMinorStatus("Performing \(taskName) tasks...")
    do {
        let result = try await runExternalScript(
            scriptPath, arguments: [runType]
        )
        if result.exitcode != 0 {
            displayInfo("\(scriptPath) return code: \(result.exitcode)")
        }
        if !result.output.isEmpty {
            displayInfo("\(scriptPath) stdout: \(result.output)")
        }
        if !result.error.isEmpty {
            displayInfo("\(scriptPath) stderr: \(result.error)")
        }
        return result.exitcode
    } catch ExternalScriptError.notFound {
        // not required, so pass
    } catch {
        displayWarning("Unexpected error when attempting to run \(scriptPath): \(error.localizedDescription)")
    }
    return 0
}

/// Helper to specifically run Munki preflight or postflight scripts
func runPreOrPostScript(name: String, runType: String) async -> Int {
    // first check the same directory where managedsoftwareupdate lives
    var scriptPath = currentExecutableDir(appendingPathComponent: name)
    if !pathIsExecutableFile(scriptPath) {
        return 0
    }
    return await runMunkiDirScript(scriptPath, taskName: name, runType: runType)
}

/// If there are executables inside the cleanup directory,
/// run them and remove them if successful
/// NOTE: historically, this has been used to clean up the Python framework when updating
/// Python versions. This may no longer be needed.
func doCleanupTasks(runType: String) async {
    let cleanupdir = currentExecutableDir(appendingPathComponent: "cleanup")
    if !pathIsDirectory(cleanupdir) {
        return
    }
    if let dirContents = try? FileManager.default.contentsOfDirectory(atPath: cleanupdir) {
        for itemName in dirContents {
            let fullPath = (cleanupdir as NSString).appendingPathComponent(itemName)
            if pathIsExecutableFile(fullPath) {
                let result = await runMunkiDirScript(fullPath, taskName: "cleanup", runType: runType)
                if result == 0 {
                    try? FileManager.default.removeItem(atPath: fullPath)
                }
            }
        }
    }
}

/// Return count of available updates.
func munkiUpdatesAvailable() -> Int {
    if let plist = getInstallInfo() {
        var updatesAvailable = 0
        if let removals = plist["removals"] as? [PlistDict] {
            updatesAvailable += removals.count
        }
        if let installs = plist["managed_installs"] as? [PlistDict] {
            updatesAvailable += installs.count
        }
        return updatesAvailable
    }
    return 0
}

/// Return true if there is an item with this installerType in the list of updates
func munkiUpdatesContainItemWithInstallerType(_ installerType: String) -> Bool {
    if let plist = getInstallInfo(),
       let managedInstalls = plist["managed_installs"] as? [PlistDict]
    {
        for item in managedInstalls {
            if let type = item["installer_type"] as? String,
               type == installerType
            {
                return true
            }
        }
    }
    return false
}

/// Return True if there are any Apple items in the list of updates
func munkiUpdatesContainAppleItems() -> Bool {
    if let plist = getInstallInfo() {
        for key in ["managed_installs", "removals"] {
            if let items = plist[key] as? [PlistDict] {
                for item in items {
                    if let appleItem = item["apple_item"] as? Bool,
                       appleItem == true
                    {
                        return true
                    }
                }
            }
        }
    }
    return false
}

/// Record last check date and result
func recordUpdateCheckResult(_ result: UpdateCheckResult) {
    let now = Date()
    setPref("LastCheckDate", now)
    setPref("LastCheckResult", result.rawValue)
}

/// Detect if there is an app actively making an idle sleep assertion, e.g.
/// Keynote, PowerPoint, Zoom, Webex, etc
/// See: https://developer.apple.com/documentation/iokit/iopmlib_h/iopmassertiontypes
/// Intent is to avoid user notifications when a user is presenting or in a virtual meeting
/// Idea borrowed from Installomator
func activeDisplaySleepAssertion() -> Bool {
    let assertions = getPMAssertions()
    for processName in assertions.keys {
        if processName == "coreaudiod" {
            continue
        }
        if let assertionTypes = assertions[processName],
           assertionTypes.contains("NoDisplaySleepAssertion") ||
           assertionTypes.contains("PreventUserIdleDisplaySleep")
        {
            munkiLog("\(processName) has an active display sleep assertion")
            return true
        }
    }
    return false
}

/// Notify the logged-in user of available updates.
///
/// Args:
///     force: bool, default false, forcefully notify user regardless
///     of LastNotifiedDate.
func notifyUserOfUpdates(force: Bool = false) {
    if getConsoleUser() == "loginwindow" {
        // someone is logged in, but we're sitting at the loginwindow
        // due to to fast user switching so do nothing
        munkiLog("Skipping user notification because we are at the loginwindow.")
        return
    } else if boolPref("SuppressUserNotification") ?? false {
        munkiLog("Skipping user notification because SuppressUserNotification is true.")
        return
    }
    let lastNotifiedDate = datePref("LastNotifiedDate") ?? Date.distantPast
    if !(pref("DaysBetweenNotifications") is Int) {
        displayWarning("Preference DaysBetweenNotifications is not an integer; using a value of 1")
    }
    let daysBetweenNotifications = intPref("DaysBetweenNotifications") ?? 1
    let now = Date()
    // calculate interval in seconds
    let interval = if daysBetweenNotifications > 0 {
        // we make this adjustment so a 'daily' notification
        // doesn't require exactly 24 hours to elapse
        // subtract 6 hours
        // IOW, if we notify today at 4pm, we don't really want to wait
        // until after 4pm tomorrow to notifiy again.
        Double((daysBetweenNotifications * 24 * 60 * 60) - (6 * 60 * 60))
    } else {
        0.0
    }
    if force || now.timeIntervalSince(lastNotifiedDate) >= interval {
        if !force, activeDisplaySleepAssertion() {
            // user may be in a virtual meeting or presenting.
            // Skip the notification; hopefully we'll be able to notify later.
            munkiLog("Skipping user notification.")
            return
        }
        // record current notification date
        setPref("LastNotifiedDate", now)
        munkiLog("Notifying user of available updates.")
        munkiLog("LastNotifiedDate was \(lastNotifiedDate)")
        // trigger LaunchAgent to launch munki-notifier.app in the right context
        let launchfile = "/var/run/com.googlecode.munki.munki-notifier"
        FileManager.default.createFile(atPath: launchfile, contents: nil)
        usleep(1_000_000)
        // clear the trigger file. We have to do it because we're root,
        // and the munki-notifier process is running as the user
        try? FileManager.default.removeItem(atPath: launchfile)
    }
}

/// Munki defaults to using http://munki/repo as the base URL.
/// This is useful as a bootstrapping default, but is insecure.
/// Warn the admin if Munki is using an insecure default.
func warnIfServerIsDefault() {
    var server = stringPref("ManifestURL") ?? stringPref("SoftwareRepoURL") ?? DEFAULT_INSECURE_REPO_URL
    if server.last == "/" {
        server = String(server.dropLast())
    }
    if [DEFAULT_INSECURE_REPO_URL, DEFAULT_INSECURE_REPO_URL + "/manifests"].contains(server) {
        displayWarning("Client is configured to use the default repo (\(DEFAULT_INSECURE_REPO_URL)), which is insecure. Client could be trivially compromised when off your organization's network. Consider using a non-default URL, and preferably an https:// URL.")
    }
}

/// Removes the jobs that launch MunkiStatus and managedsoftwareupdate at
/// the loginwindow. We do this if we decide it's not applicable to run right
/// now so we don't get relaunched repeatedly, but don't want to remove the
/// trigger file because we do want to run again at the next logout/reboot.
/// These jobs will be reloaded the next time we're in the loginwindow context.
func removeLaunchdLogoutJobs() {
    munkiStatusQuit()
    _ = runCLI("/bin/launchctl", arguments: ["remove", "com.googlecode.munki.MunkiStatus"])
    _ = runCLI("/bin/launchctl", arguments: ["remove", "com.googlecode.munki.managedsoftwareupdate-loginwindow"])
}

/// Handle the need for a restart or a possible shutdown.
func doRestart(shutdown: Bool = false) {
    let message = if shutdown {
        "Software installed or removed requires a shut down."
    } else {
        "Software installed or removed requires a restart."
    }
    if DisplayOptions.munkistatusoutput {
        munkiStatusHideStopButton()
        munkiStatusMessage(message)
        munkiStatusDetail("")
        munkiStatusPercent(-1)
        munkiLog(message)
    } else {
        displayInfo(message)
    }

    // check current console user
    let consoleUser = getConsoleUser()
    if consoleUser.isEmpty || consoleUser == "loginwindow" {
        // no-one is logged in or we're at the loginwindow
        usleep(5_000_000)
        if shutdown {
            doAuthorizedOrNormalRestart(shutdown: shutdown)
        } else if !performAuthRestart() {
            doAuthorizedOrNormalRestart()
        }
    } else {
        if DisplayOptions.munkistatusoutput {
            // someone is logged in and we're using Managed Software Center.
            // We need to notify the active user that a restart is required.
            // We actually should almost never get here; generally Munki knows
            // a restart is needed before even starting the updates and forces
            // a logout before applying the updates
            displayInfo("Notifying currently logged-in user to restart.")
            munkiStatusActivate()
            munkiStatusRestartAlert()
        } else {
            print("Please restart immediately.")
        }
    }
}

/// Perform our installation/removal tasks.
///
/// Args:
///    doAppleUpdates: Bool. If true, install Apple updates
///    onlyUnattended:  Bool. If true, only do unattended_(un)install items.
///
/// Returns:
///    PostAction - one of .none, .logout, .restart, .shutdown
func doInstallTasks(doAppleUpdates: Bool = false, onlyUnattended: Bool = false) async -> PostAction {
    if !onlyUnattended {
        // first, clear the last notified date so we can get notified of new
        // changes after this round of installs
        clearLastNotifiedDate()
    }

    var munkiItemsRestartAction = PostAction.none
    var appleItemsRestartAction = PostAction.none

    if munkiUpdatesAvailable() > 0 {
        // install Munki updates
        munkiItemsRestartAction = await doInstallsAndRemovals(onlyUnattended: onlyUnattended)
        if !onlyUnattended {
            if munkiUpdatesContainItemWithInstallerType("startosinstall") {
                Report.shared.save()
                // install macOS
                // TODO: implement this (install macOS via startOSInstall)
            }
        }
    }
    if doAppleUpdates {
        // install Apple updates
        // TODO: implement? appleItemsRestartAction = installAppleUpdates(onlyUnattended: onlyUnattended)
        // We're probably never going to implement this...
    }

    Report.shared.save()

    return max(appleItemsRestartAction, munkiItemsRestartAction)
}

/// Handle the need for a forced logout. Start our logouthelper
func startLogoutHelper() {
    let result = runCLI("/bin/launchctl",
                        arguments: ["start", "com.googlecode.munki.logouthelper"])
    if result.exitcode != 0 {
        displayError("Could not start com.googlecode.munki.logouthelper")
    }
}

/// A collection of tasks to do as we finish up
func doFinishingTasks(runtype: String = "") async {
    // finish our report
    Report.shared.record(Date(), to: "EndTime")
    Report.shared.record(getVersion(), to: "ManagedInstallVersion")
    Report.shared.record(availableDiskSpace(), to: "AvailableDiskSpace")
    var consoleUser = getConsoleUser()
    if consoleUser.isEmpty {
        consoleUser = "<None>"
    }
    Report.shared.record(consoleUser, to: "ConsoleUser")
    Report.shared.save()

    // store the current pending update count and other data for munki-notifier
    savePendingUpdateTimes()
    let updateInfo = getPendingUpdateInfo()
    setPref("PendingUpdateCount", updateInfo.pendingUpdateCount)
    setPref("OldestUpdateDays", updateInfo.oldestUpdateDays)
    setPref("ForcedUpdateDueDate", updateInfo.forcedUpdateDueDate)

    // save application inventory data
    saveAppData()

    // run the Munki postflight script if it exists
    // if runtype is not defined -- we're being called by osinstall
    let postflightRuntype: String = if !runtype.isEmpty {
        runtype
    } else {
        "osinstall"
    }
    _ = await runPreOrPostScript(name: "postflight", runType: postflightRuntype)
}
