//
//  osinstaller.swift
//  munki
//
//  Created by Greg Neagle on 7/9/24.
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

import Foundation

private let display = DisplayAndLog.main

// TODO: implement setup_authrestart_if_applicable() (not needed unless we implement support for StartOSInstall)

// TODO: implement StartOSInstallRunner and related functions

/// Attempts to trigger a "verification" process against the staged macOS
/// installer. This improves the launch time.
func verifyStagedOSInstaller(_ appPath: String) {
    display.minorStatus("Verifying macOS installer...")
    displayPercentDone(current: -1, maximum: 100)
    let startOSInstallPath = (appPath as NSString).appendingPathComponent("Contents/Resources/startosinstall")
    let result = runCLI(startOSInstallPath, arguments: ["--usage"])
    if result.exitcode != 0 {
        display.warning("Error verifying macOS installer: \(result.error)")
    }
}

/// Records info on a staged macOS installer. This includes info for managedsoftwareupdate and
/// Managed Software Center to display, and the path to the staged installer.
func recordStagedOSInstaller(_ iteminfo: PlistDict) {
    let infoPath = stagedOSInstallerInfoPath()
    guard let stagedOSInstallerInfo = createOSInstallerInfo(iteminfo) else {
        display.error("Error recording staged macOS installer: could not get os installer path")
        return
    }
    do {
        try writePlist(stagedOSInstallerInfo, toFile: infoPath)
    } catch {
        display.error("Error recording staged macOS installer: \(error.localizedDescription)")
    }
    // finally, trigger a verification
    if let osInstallerPath = stagedOSInstallerInfo["osinstaller_path"] as? String {
        verifyStagedOSInstaller(osInstallerPath)
    }
}

/// Returns info we may have on a staged OS installer
func getStagedOSInstallerInfo() -> PlistDict? {
    let infoPath = stagedOSInstallerInfoPath()
    if !pathExists(infoPath) {
        return nil
    }
    do {
        guard let osInstallerInfo = try readPlist(fromFile: infoPath) as? PlistDict else {
            display.error("Error reading \(infoPath): wrong format")
            return nil
        }
        let appPath = osInstallerInfo["osinstaller_path"] as? String ?? ""
        if appPath.isEmpty || !pathExists(appPath) {
            try? FileManager.default.removeItem(atPath: infoPath)
            return nil
        }
        return osInstallerInfo
    } catch {
        display.error("Error reading \(infoPath): \(error.localizedDescription)")
        return nil
    }
}

/// Removes any staged OS installer we may have
func removeStagedOSInstallerInfo() {
    let infoPath = stagedOSInstallerInfoPath()
    try? FileManager.default.removeItem(atPath: infoPath)
}

/// Prints staged macOS installer info (if any) and updates ManagedInstallReport.
func displayStagedOSInstallerInfo(info: PlistDict? = nil) {
    guard let item = info else { return }
    Report.shared.record(item, to: "StagedOSInstaller")
    display.info("")
    display.info("The following macOS upgrade is available to install:")
    let name = item["display_name"] as? String ?? item["name"] as? String ?? ""
    let version = item["version_to_install"] as? String ?? ""
    display.info("    + \(name)-\(version)")
    display.info("       *Must be manually installed")
}

// MARK: functions for determining if a user is a volume owner

/// Returns a list of UUIDs of accounts that are volume owners for /
func volumeOwnerUUIDs() -> [String] {
    var cryptoUsers = PlistDict()
    do {
        let result = runCLI(
            "/usr/sbin/diskutil",
            arguments: ["apfs", "listUsers", "/", "-plist"]
        )
        cryptoUsers = try readPlist(fromString: result.output) as? PlistDict ?? [:]
    } catch {
        // do nothing
    }
    let users = cryptoUsers["Users"] as? [PlistDict] ?? []
    return users.filter {
        $0["APFSCryptoUserUUID"] != nil &&
            $0["VolumeOwner"] as? Bool ?? false &&
            $0["APFSCryptoUserType"] as? String ?? "" == "LocalOpenDirectory"
    }.compactMap {
        $0["APFSCryptoUserUUID"] as? String
    }
}

/// Returns a boolean to indicate if the user is a volume owner of /
func userIsVolumeOwner(_ username: String) -> Bool {
    return volumeOwnerUUIDs().contains(getGeneratedUID(username))
}

// MARK: functions for launching staged macOS installer

/// Writes our adminopen script to a temp file. Returns the path.
func getAdminOpenPath() -> String? {
    let scriptText = """
    #!/bin/bash

    # This script is designed to be run as root.
    # It takes one argument, a path to an app to be launched.
    #
    # If the current console user is not a member of the admin group, the user will
    # be added to to the group.
    # The app will then be launched in the console user's context.
    # When the app exits (or this script is killed via SIGINT or SIGTERM),
    # if we had promoted the user to admin, we demote that user once again.

    export PATH=/usr/bin:/bin:/usr/sbin:/sbin

    function fail {
        echo "$@" 1>&2
        exit 1
    }

    function demote_user {
        # demote CONSOLEUSER from admin
        dseditgroup -o edit -d ${CONSOLEUSER} -t user admin
    }

    if [ $EUID -ne 0 ]; then
       fail "This script must be run as root."
    fi


    CONSOLEUSER=$(stat -f %Su /dev/console)
    if [ "${CONSOLEUSER}" == "root" ] ; then
        fail "The console user may not be root!"
    fi

    USER_UID=$(id -u ${CONSOLEUSER})
    if [ $? -ne 0 ] ; then
        # failed to get UID, bail
        fail "Could not get UID for ${CONSOLEUSER}"
    fi

    APP=$1
    if [ "${APP}" == "" ] ; then
        # no application specified
        fail "Need to specify an application!"
    fi

    # check if CONSOLEUSER is admin
    dseditgroup -o checkmember -m ${CONSOLEUSER} admin > /dev/null
    if [ $? -ne 0 ] ; then
        # not currently admin, so promote to admin
        dseditgroup -o edit -a ${CONSOLEUSER} -t user admin
        # make sure we demote the user at the end or if we are interrupted
        trap demote_user EXIT SIGINT SIGTERM
    fi

    # launch $APP as $USER_UID and wait until it exits
    launchctl asuser ${USER_UID} open -W "${APP}"

    """
    guard let tempdir = TempDir.shared.path else {
        display.error("Could not get temp directory for adminopen tool")
        return nil
    }
    let scriptPath = (tempdir as NSString).appendingPathComponent("adminopen")
    guard createExecutableFile(
        atPath: scriptPath,
        withStringContents: scriptText,
        posixPermissions: 0o744
    )
    else {
        display.error("Could not get temp directory for adminopen tool")
        return nil
    }
    return scriptPath
}

/// Runs our adminopen tool to launch the Install macOS app. adminopen is run
/// via launchd so we can exit after the app is launched (and the user may or
/// may not actually complete running it.) Returns true if we run adminopen,
/// false otherwise (some reasons: can't find Install app, no GUI user)
func launchInstallerApp(_ appPath: String) -> Bool {
    // do we have a GUI user?
    let username = getConsoleUser()
    if username.isEmpty || username == "loginwindow" {
        // we're at the loginwindow. Bail.
        display.error("Could not launch macOS installer application: No current GUI user.")
        return false
    }

    // if we're on Apple silicon -- is the user a volume owner?
    if isAppleSilicon(), !userIsVolumeOwner(username) {
        display.error("Could not launch macOS installer application: Current GUI user \(username) is not a volume owner.")
        return false
    }

    // create the adminopen tool and get its path
    guard let adminOpenPath = getAdminOpenPath() else {
        display.error("Error launching macOS installer: Can't create adminopen tool.")
        return false
    }

    // make sure the Install macOS app is present
    if !pathExists(appPath) {
        display.error("Error launching macOS installer: \(appPath) doesn't exist.")
        return false
    }

    // OK, all preconditions are met, let's go!
    display.majorStatus("Launching macOS installer...")
    let cmd = [adminOpenPath, appPath]
    do {
        let job = try LaunchdJob(cmd: cmd, cleanUpAtExit: false)
        try job.start()
        // sleep a bit, then check to see if our launchd job has exited with an error
        usleep(1_000_000)
        if let exitcode = job.exitcode(), exitcode != 0 {
            var errorMsg = ""
            if let stderr = job.stderr {
                errorMsg = String(data: stderr.readDataToEndOfFile(), encoding: .utf8) ?? ""
            }
            throw MunkiError("(\(exitcode)) \(errorMsg)")
        }
    } catch {
        display.error("Failed to launch macOS installer due to launchd error.")
        display.error(error.localizedDescription)
        return false
    }

    // set Munki to run at boot after the OS upgrade is complete
    do {
        try setBootstrapMode()
    } catch {
        display.warning("Could not set up Munki to run at boot after OS upgrade is complete: \(error.localizedDescription)")
    }
    // return true to indicate we launched the Install macOS app
    return true
}

/// Attempt to launch a staged OS installer
func launchStagedOSInstaller() -> Bool {
    guard let osInstallerInfo = getStagedOSInstallerInfo(),
          let osInstallerPath = osInstallerInfo["osinstaller_path"] as? String
    else {
        display.error("Could not get path to staged OS installer.")
        return false
    }
    if boolPref("SuppressStopButtonOnInstall") ?? false {
        munkiStatusHideStopButton()
    }
    munkiLog("### Beginning GUI launch of macOS installer ###")
    return launchInstallerApp(osInstallerPath)
}
