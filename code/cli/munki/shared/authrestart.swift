//
//  authrestart.swift
//  munki
//
//  Created by Greg Neagle on 1/3/25.
//  Copyright 2025-2026 The Munki Project. All rights reserved.
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

/// a Singleton struct to hold shared config values
struct Authrestart {
    static var logger = MunkiLogger(logname: "authrestartd")
    private init() {} // prevents assigning an instance to another variable
}

/// Check if FileVault is enabled; returns true or false accordingly.
func filevaultIsActive() -> Bool {
    Authrestart.logger.debug1("Checking if FileVault is enabled...")
    let result = runCLI("/usr/bin/fdesetup", arguments: ["isactive"])
    if result.exitcode != 0 {
        if result.output.contains("false") {
            Authrestart.logger.debug1("FileVault appears to be disabled...")
        } else {
            Authrestart.logger.warning("Error running fdsetup: \(result.output) \(result.error)")
        }
        return false
    }
    if result.output.contains("true") {
        Authrestart.logger.debug1("FileVault appears to be enabled...")
        return true
    }
    Authrestart.logger.debug1("Could not confirm FileVault is enabled...")
    return false
}

/// Checks if an Authorized Restart is supported; returns true or false accordingly.
func supportsAuthRestart() -> Bool {
    Authrestart.logger.debug1("Checking if FileVault can perform an AuthRestart...")
    let result = runCLI("/usr/bin/fdesetup", arguments: ["supportsauthrestart"])
    if result.exitcode != 0 {
        Authrestart.logger.warning("Error running fdsetup: \(result.output) \(result.error)")
        return false
    }
    if result.output.contains("true") {
        Authrestart.logger.debug1("FileVault supports AuthRestart...")
        return true
    }
    Authrestart.logger.debug1("FileVault AuthRestart is not supported...")
    return false
}

/// Returns a boolean indicating if username is in the list of FileVault authorized users
func isFilevaultUser(_ username: String) -> Bool {
    let result = runCLI("/usr/bin/fdesetup", arguments: ["list"])
    if result.exitcode != 0 {
        Authrestart.logger.warning("Error running fdsetup: \(result.output) \(result.error)")
        return false
    }
    // output is in the format
    // jsmith,911D2742-7983-436D-9FA3-3F6B7421684B
    // tstark,5B0EBEE6-0917-47B2-BFF3-78A9DE437D65
    for line in result.output.split(separator: "\n") {
        let parts = line.split(separator: ",")
        if parts.count == 2, parts[0] == username {
            Authrestart.logger.debug1("Found \(username) in FileVault authorized users...")
            return true
        }
    }
    Authrestart.logger.debug1("Did not find \(username) in FileVault authorized users...")
    return false
}

/// Returns a boolean to indicate if all the needed conditions are present
/// for us to attempt an authrestart with username's password
func canAttemptAuthRestartFor(_ username: String) -> Bool {
    let performAuthRestarts = boolPref("PerformAuthRestarts") ?? false
    return performAuthRestarts && filevaultIsActive() && supportsAuthRestart() && isFilevaultUser(username)
}

/// Returns recovery key as a string. If we fail to get the proper information, returns nil.
/// If quiet is set, fail silently
func getAuthRestartKey(quiet: Bool = false) -> String? {
    // check to see if recovery key preference is set
    guard let recoveryKeyPlist = pref("RecoveryKeyFile") as? String else {
        if !quiet {
            Authrestart.logger.debug1("RecoveryKeyFile preference is not set")
        }
        return nil
    }
    if !quiet {
        Authrestart.logger.debug1("RecoveryKeyFile preference is set to \(recoveryKeyPlist)")
    }
    // try to get the recovery key from the defined location
    guard let recoveryKeyDict = try? readPlist(fromFile: recoveryKeyPlist) as? PlistDict,
          let recoveryKey = recoveryKeyDict["RecoveryKey"] as? String
    else {
        if !quiet {
            Authrestart.logger.error("Could not retrieve recovery key from \(recoveryKeyPlist).")
        }
        return nil
    }
    return recoveryKey
}

/// Returns a boolean to indicate if all the needed conditions are present for us to attempt an authrestart
func canAttemptAuthRestart(havePassword: Bool = false) -> Bool {
    let performAuthRestarts = boolPref("PerformAuthRestarts") ?? false
    return performAuthRestarts && filevaultIsActive() && supportsAuthRestart() && (havePassword || getAuthRestartKey(quiet: true) != nil)
}

/// When called this will perform an authorized restart. Before trying
/// to perform an authorized restart it checks to see if the machine supports
/// the feature. If supported it will look for the defined plist containing
/// a key called RecoveryKey. If this doesn't exist, it will use a password
/// (or recovery key) passed into the function. It will use that value to
/// perform the restart.
func performAuthRestart(
    username: String = "",
    password: String = "",
    delayMinutes: Int = 0
) -> Bool {
    Authrestart.logger.debug1("Checking if performing an Auth Restart is fully supported...")
    if !supportsAuthRestart() {
        Authrestart.logger.debug1("Machine doesn't support Authorized Restarts...")
        return false
    }
    Authrestart.logger.debug1("Machine supports Authorized Restarts...")
    let fvPassword = (getAuthRestartKey() ?? password)
    if fvPassword.isEmpty {
        Authrestart.logger.debug1("No password or recovery key provided...")
        return false
    }
    var keys = [String: String]()
    keys["Password"] = fvPassword
    if !username.isEmpty {
        keys["Username"] = username
    }
    guard let inputPlist = try? plistToString(keys) else {
        Authrestart.logger.error("Could not create auth plist for fdesetup")
        return false
    }
    if delayMinutes == 0 {
        Authrestart.logger.info("Attempting an Authorized Restart now...")
    } else {
        Authrestart.logger.info("Configuring a delayed Authorized Restart...")
    }
    let result = runCLI("/usr/bin/fdesetup", arguments: ["authrestart", "-delayminutes", String(delayMinutes), "-inputplist"], stdIn: inputPlist)
    if result.exitcode == 0 {
        // fdesetup reports success
        return true
    }
    if result.error.contains("System is being restarted") {
        return true
    }
    Authrestart.logger.error(result.error)
    return false
}

/// Do a shutdown if needed, or an authrestart if allowed/possible, else do a normal restart.
/// This is called by both authrestartd and managedsoftwareupdate
func doAuthorizedOrNormalRestart(
    username: String = "",
    password: String = "",
    shutdown: Bool = false
) {
    if shutdown {
        // we need a shutdown here instead of any type of restart
        Authrestart.logger.info("Shutting down now.")
        Authrestart.logger.debug1("Performing a regular shutdown...")
        _ = runCLI("/sbin/shutdown", arguments: ["-h", "-o", "now"])
        return
    }
    Authrestart.logger.info("Restarting now.")
    let performAuthRestarts = boolPref("PerformAuthRestarts") ?? false
    let haveRecoveryKeyFile = !(stringPref("RecoveryKeyFile") ?? "").isEmpty
    if filevaultIsActive(),
       performAuthRestarts,
       haveRecoveryKeyFile || !password.isEmpty
    {
        Authrestart.logger.debug1("Configured to perform AuthRestarts...")
        // try to perform an auth restart
        if !performAuthRestart(username: username, password: password) {
            // if we got to here then the auth restart failed
            // notify that it did then perform a normal restart
            Authrestart.logger.warning("Authorized Restart failed. Performing normal restart...")
        } else {
            // we successfully triggered an authrestart
            return
        }
    }
    // fall back to normal restart
    Authrestart.logger.debug1("Performing a regular restart...")
    _ = runCLI("/sbin/shutdown", arguments: ["-r", "now"])
}
