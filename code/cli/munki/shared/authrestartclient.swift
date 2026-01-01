//
//  authrestartclient.swift
//  munki
//
//  Created by Greg Neagle on 1/4/25.
//  Copyright 2025-2026 The Munki Project.
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

private let AUTHRESTARTD_SOCKET = "/var/run/authrestartd"
private let DEBUG = false

/// Error to throw for errors in AuthRestartClient
class AuthRestartClientError: MunkiError {}

/// Handles communication with authrestartd daemon
class AuthRestartClient {
    var client: UNIXDomainSocketClient?

    /// Connect to appusaged
    func connect() throws {
        client = try UNIXDomainSocketClient(debug: DEBUG)
        try client?.connect(to: AUTHRESTARTD_SOCKET)
    }

    /// Send a request to appusaged
    func sendRequest(_ request: PlistDict) throws -> String {
        guard let client else {
            throw AuthRestartClientError("No valid socket client")
        }
        guard let requestData = try? plistToData(request) else {
            throw AuthRestartClientError("Failed to serialize request")
        }
        try client.sendData(requestData)
        let reply = (try? client.readString(timeout: 10)) ?? ""
        if reply.isEmpty {
            return "ERROR:No reply"
        }
        return reply.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// Disconnect from appusaged
    func disconnect() {
        client?.close()
    }

    /// Send a request and return the result
    func process(_ request: PlistDict) throws -> String {
        try connect()
        let result = try sendRequest(request)
        disconnect()
        return result
    }

    /// Returns a boolean to indicate if FileVault is active
    func fvIsActive() throws -> Bool {
        let result = try process(["task": "verify_filevault"])
        return result.hasPrefix("OK")
    }

    /// Returns true if username can unlock the FV volume
    func verifyUser(_ username: String) throws -> Bool {
        let request = ["task": "verify_user", "username": username]
        let result = try process(request)
        return result.hasPrefix("OK")
    }

    /// Returns true if plist containing a FV recovery key is present
    func verifyRecoveryKeyPresent() throws -> Bool {
        let request = ["task": "verify_recovery_key_present"]
        let result = try process(request)
        return result.hasPrefix("OK")
    }

    /// Returns True if we are ready to attempt an auth restart
    func verifyCanAttemptAuthRestart() throws -> Bool {
        let request = ["task": "verify_can_attempt_auth_restart"]
        let result = try process(request)
        return result.hasPrefix("OK")
    }

    /// Stores a FV password with authrestartd
    func storePassword(_ password: String, username: String = "") throws {
        var request = ["task": "store_password", "password": password]
        if !username.isEmpty {
            request["username"] = username
        }
        let result = try process(request)
        if !result.hasPrefix("OK") {
            throw AuthRestartClientError("Could not store password: \(result)")
        }
    }

    /// Tells authrestartd to perform a restart
    func restart() throws {
        let request = ["task": "restart"]
        let result = try process(request)
        if !result.hasPrefix("OK") {
            throw AuthRestartClientError("Could not restart: \(result)")
        }
    }

    /// Sets up a delayed auth restart
    func setupDelayedAuthRestart(delayMinutes: Int = -1) throws {
        let request = ["task": "delayed_authrestart", "delayminutes": delayMinutes] as PlistDict
        let result = try process(request)
        if !result.hasPrefix("OK") {
            throw AuthRestartClientError("Could not setup delayed auth restart: \(result)")
        }
    }
}

// MARK: Higher-level wrapper functions that swallow AuthRestartClientErrors

/// Returns true if FileVault can be verified to be active, false otherwise
func fvIsActive() -> Bool {
    do {
        return try AuthRestartClient().fvIsActive()
    } catch {
        return false
    }
}

/// Returns true if user can be verified to be able to perform an authrestart, false otherwise
func verifyAuthRestartUser(_ username: String) -> Bool {
    do {
        return try AuthRestartClient().verifyUser(username)
    } catch {
        return false
    }
}

/// Returns true if we have a plist with a FileVault recovery key, false otherwise
func verifyRecoveryKeyPresent() -> Bool {
    do {
        return try AuthRestartClient().verifyRecoveryKeyPresent()
    } catch {
        return false
    }
}

/// Returns True if we have what we need to attempt an auth restart
func verifyCanAttemptAuthRestart() -> Bool {
    do {
        return try AuthRestartClient().verifyCanAttemptAuthRestart()
    } catch {
        return false
    }
}

/// Stores a password for later authrestart usage.
/// Returns boolean to indicate success/failure
func storePassword(_ password: String, username: String = "") -> Bool {
    do {
        try AuthRestartClient().storePassword(password, username: username)
        return true
    } catch {
        return false
    }
}

/// Performs a restart -- authenticated if possible.
/// Returns boolean to indicate success/failure
func performAuthRestart() -> Bool {
    do {
        try AuthRestartClient().restart()
        return true
    } catch {
        return false
    }
}

/// Sets up a delayed authrestart.
/// Returns boolean to indicate success/failure
func setupDelayedAuthRestart() -> Bool {
    do {
        try AuthRestartClient().setupDelayedAuthRestart()
        return true
    } catch {
        return false
    }
}

/// A function for doing some basic testing
func testAuthRestartClientFunctions() {
    print("PerformAuthRestarts preference is: \(pref("PerformAuthRestarts") ?? "<none>")")
    print("FileVault is active: \(fvIsActive())")
    print("Recovery key is present: \(verifyRecoveryKeyPresent())")
    var username = NSUserName()
    if username == "root" {
        print("Enter name of FV-enabled user: ", terminator: "")
        if let input = readLine() {
            username = input
        }
    }
    print("\(username) is FV user: \(verifyAuthRestartUser(username))")
    var password = ""
    if let input = getpass("Enter password: ") {
        password = String(cString: input, encoding: .utf8) ?? ""
    }
    if !password.isEmpty {
        if username == "root" {
            username = ""
        }
        if storePassword(password, username: username) {
            print("store_password was successful")
        }
    }
    print("Can attempt auth restart: \(verifyCanAttemptAuthRestart())")
    print("Test setup of delayed auth restart (y/n)? ", terminator: "")
    if let input = readLine(),
       input.lowercased().hasPrefix("y")
    {
        print("Successfully set up delayed authrestart: \(setupDelayedAuthRestart())")
    }
    print("Test auth restart (y/n)? ", terminator: "")
    if let input = readLine(),
       input.lowercased().hasPrefix("y")
    {
        print("Attempting auth restart...")
        if performAuthRestart() {
            print("restart was successfully triggered")
        } else {
            print("restart failed")
        }
    }
}
