//
//  managedsoftwareupdate.swift
//  munki
//
//  Created by Greg Neagle on 6/24/24.
//
//  Copyright 2024 Greg Neagle.
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
        doCleanupTasks(runType: runtype)
        initializeReport()
        // TODO: support logging to syslog and unified logging

        munkiLog("### Starting managedsoftwareupdate run: \(runtype) ###")
        if DisplayOptions.shared.verbose > 0 {
            print("Managed Software Update Tool")
            print("Version \(getVersion())")
            print("Copyright 2010-2024 The Munki Project")
            print("https://github.com/munki/munki\n")
        }
        displayMajorStatus("Starting...")
        sendStartNotification()
        try await runPreflight()

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

        if appleupdatesonly, DisplayOptions.shared.verbose > 0 {
            print("NOTE: managedsoftwareupdate is configured to process Apple Software Updates only.")
        }

        var updateCheckResult: UpdateCheckResult? = nil
        if !skipMunkiCheck {
            do {
                try await updateCheckResult = checkForUpdates(
                    clientID: configOptions.id
                )
            } catch {
                displayError("Error during updatecheck: \(error.localizedDescription)")
                Report.shared.save()
                throw ExitCode(-1) // TODO: better exit code
            }
        }
        if let updateCheckResult {
            recordUpdateCheckResult(updateCheckResult)
        }

        let updatesAvailable = munkiUpdatesAvailable()
        var appleUpdatesAvailable = 0
    }

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

    private func exitIfAnotherManagedSoftwareUpdateIsRunning() throws {
        if let otherPid = anotherManagedsoftwareupdateInstanceRunning() {
            let ourName = ProcessInfo().processName
            let ourPid = ProcessInfo().processIdentifier
            munkiLog(String(repeating: "*", count: 60))
            munkiLog("\(ourName) launched as pid \(ourPid)")
            munkiLog("Another instance of \(ourName) is running as pid \(otherPid).")
            munkiLog("This process (pid \(ourPid)) exiting.")
            munkiLog(String(repeating: "*", count: 60))
            printStderr("Another instance of \(ourName) is running. Exiting.")
            throw ExitCode(0)
        }
    }

    private mutating func processLaunchdOptions() throws {
        if otherOptions.auto {
            // typically invoked by a launch daemon periodically.
            // munkistatusoutput is false for checking, but true for installing
            runtype = "auto"
            otherOptions.munkistatusoutput = false
            otherOptions.quiet = false
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
                        displayMinorStatus("Waiting for network...")
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

    private func ensureMunkiDirsExist() throws {
        if !initMunkiDirs() {
            throw ExitCode(EXIT_STATUS_MUNKI_DIRS_FAILURE)
        }
    }

    private func configureDisplayOptions() {
        // sets our display options
        DisplayOptions.shared.munkistatusoutput = otherOptions.munkistatusoutput
        if otherOptions.quiet {
            DisplayOptions.shared.verbose = 0
        } else {
            DisplayOptions.shared.verbose = commonOptions.verbose + 1
        }
        // TODO: support setting MUNKI_VERBOSITY_LEVEL env variable
    }

    private func initializeReport() {
        if commonOptions.installOnly {
            // we're only installing, not checking, so we should copy
            // some report values from the prior run
            Report.shared.read()
        }
        Report.shared.record(Date(), to: "StartTime")
        Report.shared.record(runtype, to: "RunType")
    }

    private func runPreflight() async throws {
        // tries to run a Munki preflight. If it exists and exits non-zero
        // abort execution of the managedsoftwareupdate run
        let result = await runPreOrPostScript(name: "preflight", runType: runtype)
        if result == 0 {
            // Force a prefs refresh, in case preflight modified the prefs file.
            reloadPrefs()
            return
        }
        displayInfo("managedsoftwareupdate run aborted by preflight script: \(result)")
        // record the check result for use by Managed Software Center.app
        // right now, we'll return the same code as if the munki server
        // was unavailable. We need to revisit this and define additional
        // update check results.
        recordUpdateCheckResult(.checkDidntStart)
        // tell status app we're done sending status
        munkiStatusQuit()
        throw ExitCode(EXIT_STATUS_PREFLIGHT_FAILURE)
    }
}
