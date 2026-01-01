//
//  managedsoftwareupdate.swift
//  munki
//
//  Created by Greg Neagle on 6/24/24.
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

import ArgumentParser
import Foundation

private let display = DisplayAndLog.main

@main
struct ManagedSoftwareUpdate: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "managedsoftwareupdate",
        usage: "mangedsoftwareupdate [options]"
    )

    @Flag(name: [.long, .customShort("V")],
          help: "Print the version of the munki tools and exit.")
    var version = false

    @OptionGroup(title: "Commonly used options")
    var commonOptions: MSUCommonOptions

    @OptionGroup(title: "Configuration options")
    var configOptions: MSUConfigOptions

    @OptionGroup(title: "Other options")
    var otherOptions: MSUOtherOptions

    // runtype is used for pre and postflight scripts
    var runtype = "custom"
    var munkiUpdateCount = 0
    var appleUpdateCount = 0
    var restartAction: PostAction = .none
    var forcedSoon = false
    var mustLogout = false
    var shouldNotifyUser = false

    private func handleConfigOptions() throws {
        if configOptions.showConfig {
            printConfig()
            throw ExitCode(0)
        }
        if configOptions.showConfigPlist {
            printConfigPlist()
            throw ExitCode(0)
        }
        if configOptions.setBootstrapMode {
            do {
                try setBootstrapMode()
            } catch {
                printStderr(error.localizedDescription)
                throw ExitCode(-1)
            }
            print("Bootstrap mode is set.")
            throw ExitCode(0)
        }
        if configOptions.clearBootstrapMode {
            do {
                try clearBootstrapMode()
            } catch {
                printStderr(error.localizedDescription)
                throw ExitCode(-1)
            }
            print("Bootstrap mode cleared.")
            throw ExitCode(0)
        }
    }

    /// Triggers an exit if another instance of managedsoftwareupdate is running
    private func exitIfAnotherManagedSoftwareUpdateIsRunning() throws {
        while let proc = anotherManagedsoftwareupdateInstanceRunning() {
            // find out how long it's been running
            let runtime = Int(Date().timeIntervalSince1970) - proc.starttime
            if runtime > MSU_MAX_RUNTIME_SECS {
                // other managedsoftwareupdate has been running too long. kill it
                munkiLog("Another managedsoftwareupdate has been running for \(runtime) seconds, which is more than the allowed \(MSU_MAX_RUNTIME_SECS) seconds. Killing it.")
                munkiLog("Sending SIGKILL to \(proc.path) (pid \(proc.pid))")
                Darwin.kill(proc.pid, SIGKILL)
                // sleep a bit and then check if the pid is gone
                usleep(1_000_000)
                if let anotherProc = anotherManagedsoftwareupdateInstanceRunning(),
                   anotherProc.pid == proc.pid
                {
                    // same pid as before!
                    munkiLog("ERROR: \(proc.path) (pid \(proc.pid)) won't die. We should not continue.")
                    throw ExitCode(0)
                }
            } else {
                // another managedsoftwareupdate process is running. We should exit so
                // we don't conflict with what it is doing
                let ourName = ProcessInfo().processName
                let ourPid = ProcessInfo().processIdentifier
                munkiLog(String(repeating: "*", count: 60))
                munkiLog("\(ourName) launched as pid \(ourPid)")
                munkiLog("Another instance of \(ourName) is running as pid \(proc.pid) from \(proc.path)")
                munkiLog("This process (pid \(ourPid)) exiting.")
                munkiLog(String(repeating: "*", count: 60))
                printStderr("Another instance of \(ourName) is running. Exiting.")
                throw ExitCode(0)
            }
        }
    }

    /// Process the options needed when we're triggered vi launchd
    private mutating func processLaunchdOptions() throws {
        if otherOptions.auto {
            // typically invoked by a launch daemon periodically.
            // munkistatusoutput is false for checking, but true for installing
            runtype = "auto"
            otherOptions.munkistatusoutput = false
            // otherOptions.quiet = true  // behavior change here; we're going to print output unless --quiet is explicitly given
            commonOptions.checkOnly = false
            commonOptions.installOnly = false
        }
        if otherOptions.logoutinstall {
            // typically invoked by launchd agent running in the LoginWindow context
            runtype = "logoutinstall"
            otherOptions.munkistatusoutput = true
            otherOptions.quiet = true
            commonOptions.checkOnly = false
            commonOptions.installOnly = true
            // if we're running at the loginwindow, let's make sure the user
            // triggered the update before logging out, or we triggered it before
            // restarting.
            var userTriggered = false
            let flagfiles = [
                CHECKANDINSTALLATSTARTUPFLAG,
                INSTALLATSTARTUPFLAG,
                INSTALLATLOGOUTFLAG,
            ]
            for filename in flagfiles {
                if !pathExists(filename) {
                    continue
                }
                munkiLog("managedsoftwareupdate run triggered by \(filename)")
                userTriggered = true
                if filename == CHECKANDINSTALLATSTARTUPFLAG {
                    runtype = "checkandinstallatstartup"
                    commonOptions.installOnly = false
                    otherOptions.auto = true
                    // this often runs at boot -
                    // attempt to ensure we have network before continuing
                    detectNetworkHardware()
                    for _ in 0 ... 60 {
                        if networkUp() { break }
                        display.minorStatus("Waiting for network...")
                        usleep(1_000_000)
                    }
                    break
                }
                if filename == INSTALLATSTARTUPFLAG {
                    runtype = "installatstartup"
                    break
                }
            }
            // delete any triggerfile that isn't checkandinstallatstartup
            // so it's not hanging around at the next logout or restart
            for triggerfile in [INSTALLATSTARTUPFLAG, INSTALLATLOGOUTFLAG] {
                if pathExists(triggerfile) {
                    try? FileManager.default.removeItem(atPath: triggerfile)
                }
            }

            if !userTriggered {
                // no trigger file was found; let's just exit
                throw ExitCode(0)
            }
        }
        if otherOptions.installwithnologout {
            // typically invoked by Managed Software Center.app
            // for installs that do not require a logout
            let launchdtriggerfile = "/private/tmp/.com.googlecode.munki.managedinstall.launchd"
            if pathExists(launchdtriggerfile) {
                munkiLog("managedsoftwareupdate run triggered by \(launchdtriggerfile)")
                if let launchOptions = (try? readPlist(fromFile: launchdtriggerfile)) as? PlistDict,
                   let launchOSInstaller = launchOptions["LaunchStagedOSInstaller"] as? Bool
                {
                    otherOptions.launchosinstaller = launchOSInstaller
                }
                // remove it so we aren't automatically relaunched
                try? FileManager.default.removeItem(atPath: launchdtriggerfile)
            }
            runtype = "installwithnologout"
            otherOptions.munkistatusoutput = true
            otherOptions.quiet = true
            commonOptions.checkOnly = false
            commonOptions.installOnly = true
        }
        if otherOptions.manualcheck {
            // update check triggered by Managed Software Center.app
            let launchdtriggerfile = "/private/tmp/.com.googlecode.munki.updatecheck.launchd"
            if pathExists(launchdtriggerfile) {
                munkiLog("managedsoftwareupdate run triggered by \(launchdtriggerfile)")
                if let launchOptions = (try? readPlist(fromFile: launchdtriggerfile)) as? PlistDict,
                   let suppressAppleCheck = launchOptions["SuppressAppleUpdateCheck"] as? Bool
                {
                    commonOptions.munkiPkgsOnly = suppressAppleCheck
                }
                // remove it so we aren't automatically relaunched
                try? FileManager.default.removeItem(atPath: launchdtriggerfile)
            }
            runtype = "manualcheck"
            otherOptions.munkistatusoutput = true
            otherOptions.quiet = true
            commonOptions.checkOnly = true
            commonOptions.installOnly = false
        }
    }

    /// Make sure our needed directories exist or exit
    private func ensureMunkiDirsExist() throws {
        if !initMunkiDirs() {
            throw ExitCode(EXIT_STATUS_MUNKI_DIRS_FAILURE)
        }
    }

    /// Sets our display options
    private func configureDisplayOptions() {
        DisplayOptions.munkistatusoutput = otherOptions.munkistatusoutput
        if otherOptions.quiet {
            DisplayOptions.verbose = 0
        } else {
            DisplayOptions.verbose = commonOptions.verbose + 1
        }
        // TODO: support setting MUNKI_VERBOSITY_LEVEL env variable
    }

    /// Start a report for this run
    private func initializeReport() {
        if commonOptions.installOnly {
            // we're only installing, not checking, so we should copy
            // some report values from the prior run
            Report.shared.read()
        }
        Report.shared.record(Date(), to: "StartTime")
        Report.shared.record(runtype, to: "RunType")
    }

    /// Tries to run a Munki preflight. If it exists and exits non-zero
    /// abort execution of the managedsoftwareupdate run
    private func runPreflight() async throws {
        let result = await runPreOrPostScript(name: "preflight", runType: runtype)
        if result == 0 {
            // Force a prefs refresh, in case preflight modified the prefs file.
            reloadPrefs()
            return
        }
        display.info("managedsoftwareupdate run aborted by preflight script: \(result)")
        // record the check result for use by Managed Software Center.app
        // right now, we'll return the same code as if the munki server
        // was unavailable. We need to revisit this and define additional
        // update check results.
        recordUpdateCheckResult(.checkDidntStart)
        // tell status app we're done sending status
        munkiStatusQuit()
        throw ExitCode(EXIT_STATUS_PREFLIGHT_FAILURE)
    }

    /// Do our update check against the Munki repo
    private func doMunkiUpdateCheck(skipCheck: Bool) async throws -> UpdateCheckResult? {
        if !skipCheck {
            do {
                let updateCheckResult = try await checkForUpdates(
                    clientID: configOptions.id
                )
                recordUpdateCheckResult(updateCheckResult)
                return updateCheckResult
            } catch {
                display.error("Error during updatecheck: \(error.localizedDescription)")
                Report.shared.save()
                throw ExitCode(-1) // TODO: better exit code
            }
        }
        return nil
    }

    /// Should we look for Apple updates this run?
    private func shouldDoAppleUpdates(appleUpdatesOnly: Bool) -> Bool {
        if appleUpdatesOnly {
            // admin told us to do them
            return true
        } else if commonOptions.munkiPkgsOnly {
            // admin told us not to do apple updates
            return false
        } else if munkiUpdatesContainAppleItems() {
            // shouldn't do apple updates
            munkiLog("Skipping Apple Software Updates because items to be installed from the Munki repo contain Apple items.")
            // if there are force_install_after_date items in a pre-existing
            // AppleUpdates.plist this means we are blocking those updates.
            // we need to delete AppleUpdates.plist so that other code doesn't
            // mistakenly alert for forced installs it isn't actually going to
            // install.
            clearAppleUpdateInfo()
            return false
        }
        // check the normal preferences
        return boolPref("InstallAppleSoftwareUpdates") ?? false
    }

    /// Does an Apple update check if appropriate
    private func doAppleUpdateCheckIfAppropriate(appleUpdatesOnly: Bool) -> Int {
        if shouldDoAppleUpdates(appleUpdatesOnly: appleUpdatesOnly) {
            return findAndRecordAvailableAppleUpdates()
        }
        //
        return 0
    }

    /// Once a check is done, some options may need to be adjusted for the install phase
    private mutating func reconfigureOptionsForInstall() {
        if runtype == "installatstartup" {
            // turn off options.installonly; we need options.auto behavior from here
            // on out because if FileVault is active we may actually be logged in
            // at this point!
            commonOptions.installOnly = false
            otherOptions.auto = true
        }
        if runtype == "checkandinstallatstartup",
           munkiUpdateCount == 0
        {
            // we're in bootstrap mode and
            // there are no updates we can do.
            // Clear bootstrapping mode so we don't loop endlessly
            do {
                try clearBootstrapMode()
            } catch {
                display.error(error.localizedDescription)
            }
        }
        if otherOptions.launchosinstaller {
            // user chose to update from Managed Software Center and there is
            // a cached macOS installer. We'll do that _only_.
            munkiUpdateCount = 0
            appleUpdateCount = 0
            if getStagedOSInstallerInfo() != nil {
                _ = launchStagedOSInstaller()
            } else {
                // staged OS installer is missing
                display.error("Requested to launch staged OS installer, but no info on a staged OS installer was found.")
            }
        }
    }

    // Do our actual install/removal tasks
    private mutating func handleInstallTasks() async {
        // Complex logic here to handle lots of install scenarios
        // and options
        if munkiUpdateCount == 0, appleUpdateCount == 0 {
            // no updates available
            if commonOptions.installOnly, !otherOptions.quiet {
                print("Nothing to install or remove.")
            }
            if runtype == "checkandinstallatstartup" {
                // we have nothing to do, clear the bootstrapping mode
                // so we'll stop running at startup/logout
                do {
                    try clearBootstrapMode()
                } catch {
                    display.error(error.localizedDescription)
                }
            }
            return
        }
        if commonOptions.installOnly || otherOptions.logoutinstall {
            // admin has triggered install or MSC has triggered install,
            // so just install everything
            restartAction = await doInstallTasks(
                doAppleUpdates: appleUpdateCount > 0)
            // reset our count of available updates (it might not actually
            // be zero, but we want to clear the badge on the Dock icon;
            // it can be updated to the "real" count on the next Munki run)
            munkiUpdateCount = 0
            appleUpdateCount = 0
            // send a notification event so MSU can update its display
            // if needed
            sendUpdateNotification()
            return
        } else if otherOptions.auto {
            // admin has specified --auto, or launch daemon background run
            await handleAutoInstallTasks()
            return
        } else if !otherOptions.quiet {
            // this is a checkonly run
            print("\nRun managedsoftwareupdate --installonly to install the downloaded updates.")
            return
        }
    }

    /// Do the automatic (background) install tasks
    private mutating func handleAutoInstallTasks() async {
        if currentGUIUsers().isEmpty {
            // we're at the loginwindow
            if boolPref("SuppressAutoInstall") ?? false {
                munkiLog("Skipping auto install because SuppressAutoInstall is true.")
                return
            }
            if boolPref("SuppressLoginwindowInstall") ?? false {
                // admin says we can't install pkgs at loginwindow
                // unless they don't require a logout or restart
                // (and are marked with unattended_install = True)
                //
                // check for packages that need to be force installed
                // soon and convert them to unattended_installs if they
                // don't require a logout
                _ = forceInstallPackageCheck() // this might mark some more items as unattended
                // now install anything that can be done unattended
                munkiLog("Installing only items marked unattended because SuppressLoginwindowInstall is true.")
                _ = await doInstallTasks(onlyUnattended: true)
                return
            }
            if getIdleSeconds() < 10 {
                // user may be attempting to login
                munkiLog("Skipping auto install at loginwindow because system is not idle (keyboard or mouse activity).")
                return
            }
            // at loginwindow, system is idle, so we can install
            // but first, enable status output over login window
            DisplayOptions.munkistatusoutput = true
            munkiLog("No GUI users, installing at login window.")
            munkiStatusLaunch()
            restartAction = await doInstallTasks(
                doAppleUpdates: appleUpdateCount > 0
            )
            // reset our count of available updates
            munkiUpdateCount = 0
            appleUpdateCount = 0
            return
                // end at loginwindow
        } else {
            // there are GUI users
            if boolPref("SuppressAutoInstall") ?? false {
                munkiLog("Skipping unattended installs because SuppressAutoInstall is true.")
                return
            }
            // check for packages that need to be force installed
            // soon and convert them to unattended_installs if they
            // don't require a logout
            _ = forceInstallPackageCheck()
            // install anything that can be done unattended
            _ = await doInstallTasks(
                doAppleUpdates: appleUpdateCount > 0,
                onlyUnattended: true
            )
            // send a notification event so MSC can update its display
            // if needed
            sendUpdateNotification()

            let forceAction = forceInstallPackageCheck()
            // if any installs are still requiring force actions, just
            // initiate a logout to get started.  blocking apps might
            // have stopped even non-logout/reboot installs from
            // occurring.
            forcedSoon = forceAction != .none
            let mustLogoutActions: [ForceInstallStatus] = [.now, .logout, .restart]
            if mustLogoutActions.contains(forceAction) {
                mustLogout = true
            }

            // recount available Munki updates
            munkiUpdateCount = munkiUpdatesAvailable()
            if munkiUpdateCount > 0 || appleUpdateCount > 0 {
                // set a flag to notify the user of available updates
                // after we conclude this run.
                shouldNotifyUser = true
            }
        }
    }

    /// Possibly clear bootstrapping mode
    private func clearBootstrapModeIfAppropriate() {
        // TODO: rethink all this
        if runtype == "checkandinstallatstatup",
           restartAction == .none,
           pathExists(CHECKANDINSTALLATSTARTUPFLAG),
           currentGUIUsers().isEmpty
        {
            if getIdleSeconds() < 10 {
                // system is not idle, but check again in case someone has
                // simply briefly touched the mouse to see progress.
                usleep(10_500_000)
            }
            if getIdleSeconds() < 10 {
                // we're still not idle.
                // if the trigger file is present when we exit, we'll
                // be relaunched by launchd, so we need to remove it
                // to prevent automatic relaunch.
                munkiLog("System not idle -- clearing bootstrap mode to prevent relaunch")
                do {
                    try clearBootstrapMode()
                } catch {
                    display.error(error.localizedDescription)
                }
            }
        }
    }

    // MARK: main run function

    mutating func run() async throws {
        if version {
            print(getVersion())
            return
        }
        // check to see if we're root
        if NSUserName() != "root" {
            printStderr("You must run this as root!")
            throw ExitCode(EXIT_STATUS_ROOT_REQUIRED)
        }

        try handleConfigOptions()
        try exitIfAnotherManagedSoftwareUpdateIsRunning()
        try processLaunchdOptions()
        try ensureMunkiDirsExist()
        configureDisplayOptions()
        await doCleanupTasks(runType: runtype)
        initializeReport()

        // install handlers for SIGINT and SIGTERM
        let sigintSrc = installSignalHandler(SIGINT, logger: MunkiLogger.standard)
        sigintSrc.activate()
        let sigtermSrc = installSignalHandler(SIGTERM, logger: MunkiLogger.standard)
        sigtermSrc.activate()

        munkiLog("### Starting managedsoftwareupdate run: \(runtype) ###")
        if DisplayOptions.verbose > 0 {
            print("Managed Software Update Tool")
            print("Version \(getVersion())")
            print("Copyright 2010-2025 The Munki Project")
            print("https://github.com/munki/munki\n")
        }
        display.majorStatus("Starting...")
        sendStartNotification()
        try await runPreflight() // can exit early

        let appleupdatesonly = (boolPref("AppleSoftwareUpdatesOnly") ?? false) || commonOptions.appleSUSPkgsOnly
        let skipMunkiCheck = commonOptions.installOnly || appleupdatesonly
        if !skipMunkiCheck {
            warnIfServerIsDefault()
        }
        // reset our errors and warnings files, rotate main log if needed
        munkiLogResetErrors()
        munkiLogResetWarnings()
        munkiLogRotateMainLog()
        // archive the previous session's report
        Report.shared.archiveReport()

        if appleupdatesonly, DisplayOptions.verbose > 0 {
            print("NOTE: managedsoftwareupdate is configured to process Apple Software Updates only.")
        }

        let updateCheckResult = try await doMunkiUpdateCheck(skipCheck: skipMunkiCheck)
        appleUpdateCount = doAppleUpdateCheckIfAppropriate(
            appleUpdatesOnly: appleupdatesonly)

        // display any available update info
        if updateCheckResult == .updatesAvailable {
            displayUpdateInfo()
        }
        if let stagedOSInstallerInfo = getStagedOSInstallerInfo() {
            displayStagedOSInstallerInfo(info: stagedOSInstallerInfo)
        } else if appleUpdateCount > 0 {
            displayAppleUpdateInfo()
        }

        // send a notification event so MSC can update its display if needed
        sendUpdateNotification()

        // this will get us a count of available Munki updates even if
        // we did not check this time (one of the installonly modes)
        munkiUpdateCount = munkiUpdatesAvailable()

        reconfigureOptionsForInstall()
        await handleInstallTasks()

        display.majorStatus("Finishing...")
        await doFinishingTasks(runtype: runtype)
        sendDockUpdateNotification()
        sendEndedNotification()

        munkiLog("### Ending managedsoftwareupdate run ###")
        if !otherOptions.quiet {
            print("Done.")
        }
        TempDir.shared.cleanUp()

        if mustLogout {
            // not handling this currently
        }
        if restartAction == .shutdown {
            doRestart(shutdown: true)
        } else if restartAction == .restart {
            doRestart()
        } else {
            // tell MunkiStatus/MSC we're done sending status info
            munkiStatusQuit()
            if shouldNotifyUser {
                // it may have been more than a minute since we ran our original
                // updatecheck so tickle the updatecheck time so MSC.app knows to
                // display results immediately
                recordUpdateCheckResult(.updatesAvailable)
                notifyUserOfUpdates(force: forcedSoon)
                if forcedSoon {
                    usleep(2_000_000)
                    startLogoutHelper()
                }
            }
        }
        clearBootstrapModeIfAppropriate()
    }
}
