//
//  authrestart.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 6/29/18.
//  Copyright © 2018-2026 The Munki Project. All rights reserved.
//

import Foundation

enum AuthRestartClientError: Error {
    case socketError(code: UNIXDomainSocketClientErrorCode, description: String)
    case taskError(description: String)
}

class AuthRestartClient {
    // Handles communication with authrestartd daemon
    
    let AUTHRESTARTD_SOCKET = "/var/run/authrestartd"
    let socket = UNIXDomainSocketClient()
    
    func connect() throws {
        // Connect to authrestartd
        socket.connect(to: AUTHRESTARTD_SOCKET)
        if socket.errCode != .noError {
            throw AuthRestartClientError.socketError(code: socket.errCode,
                                                      description: "Failed to connect to \(AUTHRESTARTD_SOCKET)")
        }
    }
    
    func sendRequest(_ request: [String: String]) throws -> String {
        // Send a request to authrestartd
        let request_str = try writePlistToString(request)
        socket.write(request_str)
        if socket.errCode != .noError {
            throw AuthRestartClientError.socketError(code: socket.errCode,
                                                      description: "Failed to write to \(AUTHRESTARTD_SOCKET)")
        }
        let reply = socket.read(timeout: 1)
        if reply.isEmpty {
            return "ERROR:No reply"
        }
        return reply.trimmingCharacters(in: .whitespacesAndNewlines)
    }
    
    func disconnect() {
        // Disconnect from authrestartd
        socket.close()
    }
    
    func process(_ request: [String: String]) throws -> String {
        // Send a request and return the result
        try connect()
        let result = try sendRequest(request)
        disconnect()
        return result
    }
    
    func fvIsActive() throws -> Bool {
        // Returns a boolean to indicate if FileVault is active
        let request = ["task": "verify_filevault"]
        let result = try process(request)
        return result.hasPrefix("OK")
    }
    
    func verifyUser(_ username: String) throws -> Bool {
        // Returns true if username can unlock the FV volume
        let request = ["task": "verify_user", "username": username]
        let result = try process(request)
        return result.hasPrefix("OK")
    }
    
    func verifyRecoveryKeyPresent() throws -> Bool {
        // Returns true if plist containing a FV recovery key is present
        let request = ["task": "verify_recovery_key_present"]
        let result = try process(request)
        return result.hasPrefix("OK")
    }
    
    func verifyCanAttemptAuthRestart() throws -> Bool {
        // Returns true if we are ready to attempt an auth restart
        let request = ["task": "verify_can_attempt_auth_restart"]
        let result = try process(request)
        return result.hasPrefix("OK")
    }
    
    func storePassword(_ password: String, username: String = "") throws {
        // Stores a FV password with authrestartd
        var request = ["task": "store_password", "password": password]
        if !username.isEmpty {
            request["username"] = username
        }
        let result = try process(request)
        if !result.hasPrefix("OK") {
            throw AuthRestartClientError.taskError(description: result)
        }
    }
    
    func restart() throws {
        // Returns true if restart was successful
        let request = ["task": "restart"]
        let result = try process(request)
        if !result.hasPrefix("OK") {
            throw AuthRestartClientError.taskError(description: result)
        }
    }
}

// Higher-level wrapper functions that swallow AuthRestartClientErrors

func fvIsActive() -> Bool {
    // Returns true if FileVault can be verified to be active,
    // false otherwise
    do {
        return try AuthRestartClient().fvIsActive()
    } catch {
        msc_debug_log("fvIsActive(): Caught \(error)")
        return false
    }
}

func verifyUser(_ username: String) -> Bool {
    // Returns true if user can be verified to be able to perform an
    // authrestart, false otherwise
    do {
        return try AuthRestartClient().verifyUser(username)
    } catch {
        msc_debug_log("verifyUser(): Caught \(error)")
        return false
    }
}

func verifyRecoveryKeyPresent() -> Bool {
    // Returns true if we have a plist with a FileVault recovery key,
    // false otherwise
    do {
        return try AuthRestartClient().verifyRecoveryKeyPresent()
    } catch {
        msc_debug_log("verifyRecoveryKeyPresent(): Caught \(error)")
        return false
    }
}

func verifyCanAttemptAuthRestart() -> Bool {
    // Returns true if we have what we need to attempt an auth restart
    do {
        return try AuthRestartClient().verifyCanAttemptAuthRestart()
    } catch {
        msc_debug_log("verifyCanAttemptAuthRestart(): Caught \(error)")
        return false
    }
}

func storePassword(_ password: String, forUserName username: String = "") -> Bool {
    // Stores a password for later authrestart usage.
    // Returns boolean to indicate success/failure
    do {
        try AuthRestartClient().storePassword(password, username: username)
        return true
    } catch {
        msc_debug_log("storePassword(): Caught \(error)")
        return false
    }
}
