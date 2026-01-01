//
//  main.swift
//  authrestartd
//
//  Created by Greg Neagle on 1/4/25.
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

private let DEBUG = false
private let APPNAME = "authrestartd"
private let LOGFILENAME = "authrestartd.log"

class FDEUtilError: MunkiError {}

/// Class for working with fdesetup
class FDEUtil {
    var server: AuthRestartServer
    var uid: Int
    var request: PlistDict

    init(server: AuthRestartServer, uid: Int, request: PlistDict) {
        self.server = server
        self.uid = uid
        self.request = request
    }

    /// Stores a password for later use for authrestart
    func storePassword(_ password: String, username: String = "") {
        server.storedPassword = password
        if !username.isEmpty {
            server.storedUsername = username
        }
    }

    /// Convenience method: logs a message, then returns it so we can throw an error
    /// with the same message
    func logAndReturn(_ message: String) -> String {
        server.log(message)
        return message
    }

    /// Handle our request
    func handle() throws -> String {
        guard let task = request["task"] as? String else {
            throw FDEUtilError("Request missing task")
        }
        if task == "restart" {
            // Attempt to perform an authrestart, falling back to a regular
            // restart
            server.log("Restart request from uid \(uid)")
            if uid == 0 {
                server.log("Stored username for authrestart: \(server.storedUsername ?? "<none>")")
                let password = server.storedPassword ?? ""
                let username = server.storedUsername ?? ""
                doAuthorizedOrNormalRestart(username: username, password: password)
                server.log("Triggered restart")
                return "RESTARTING"
            } else {
                throw FDEUtilError(logAndReturn("Restart request denied: request must come from root"))
            }
        }
        if task == "delayed_authrestart" {
            // set up a delayed authrestart. Defaults to waiting indefinitely,
            // so the next "normal" restart becomes an authrestart.
            server.log("Delayed restart request from uid: \(uid)")
            if uid == 0 {
                server.log("Stored username for delayed authrestart: \(server.storedUsername ?? "<none>")")
                let password = server.storedPassword ?? ""
                let username = server.storedUsername ?? ""
                let delayMinutes = request["delayminutes"] as? Int ?? -1
                if performAuthRestart(username: username, password: password, delayMinutes: delayMinutes) {
                    server.log("Configured delayed auth restart")
                    return "DONE"
                } else {
                    throw FDEUtilError(logAndReturn("Delayed auth restart request failed"))
                }
            } else {
                throw FDEUtilError(logAndReturn("Delayed auth restart request denied: request must come from root"))
            }
        }
        if task == "store_password" {
            // store a password for later fdesetup authrestart
            server.log("Store password request from uid: \(uid)")
            guard let password = request["password"] as? String else {
                throw FDEUtilError(logAndReturn("No password in request"))
            }
            let username = request["username"] as? String ?? ""
            server.log("Username in request: \(username)")
            // don't store the password if the user isn't enabled for FileVault
            if !username.isEmpty,
               !canAttemptAuthRestartFor(username)
            {
                throw FDEUtilError(logAndReturn("User \(username) can't do FileVault auth restart"))
            }
            storePassword(password, username: username)
            server.log("Password stored.")
            return "DONE"
        }

        if task == "verify_can_attempt_auth_restart" {
            // Check if we have all the required bits to attempt
            // an auth restart.
            server.log("Verify ready for auth restart")
            var havePassword = false
            if let password = server.storedPassword,
               !password.isEmpty
            {
                havePassword = true
            }
            if canAttemptAuthRestart(havePassword: havePassword) {
                server.log("Ready for auth restart attempt")
                return "READY"
            } else {
                throw FDEUtilError(logAndReturn("Not ready for FileVault auth restart"))
            }
        }

        if task == "verify_recovery_key_present" {
            // Check if a plist containing a recovery key or password is
            // present.
            server.log("Verify recovery key request")
            if getAuthRestartKey(quiet: true) != nil {
                server.log("Valid recovery key plist found")
                return "PRESENT"
            }
            throw FDEUtilError(logAndReturn("No valid recovery key plist"))
        }

        if task == "verify_user" {
            // Check to see if we can perform an authrestart for this user.
            // FileVault must be active, the hardware must support authrestart,
            // and the user must be enabled for FileVault.
            guard let username = request["username"] as? String else {
                throw FDEUtilError(logAndReturn("Verify user request with no username"))
            }
            server.log("Verify FileVault user request for \(username)")
            if canAttemptAuthRestartFor(username) {
                server.log("User \(username) ok for auth restart")
                return "USER VERIFIED"
            }
            throw FDEUtilError(logAndReturn("User \(username) can't do auth restart"))
        }

        if task == "verify_filevault" {
            // check if FileVault is active
            server.log("Verify FileVault request")
            if filevaultIsActive() {
                server.log("FileVault is active.")
                return "FILEVAULT ON"
            }
            throw FDEUtilError(logAndReturn("FileVault is not active."))
        }

        // the task is not one we know how to handle
        throw FDEUtilError(logAndReturn("Unknown task request: \(task)"))
    }
}

class AuthRestartRequestHandler {
    var server: AuthRestartServer
    var clientSocket: UNIXDomainSocket

    init(server: AuthRestartServer, clientSocket: UNIXDomainSocket) {
        self.server = server
        self.clientSocket = clientSocket
    }

    func handle() async {
        server.debugLog("Handling request")
        let (uid, gid) = getpeerid()
        server.debugLog("Got request from uid \(uid), gid \(gid)")
        // read data
        let requestData = try? readData(timeout: 1)

        // try to parse it
        guard let requestData else {
            server.logError("Request data is nil")
            try? sendString("ERROR:Empty request\n")
            return
        }
        guard let request = try? readPlist(fromData: requestData) as? PlistDict else {
            server.logError("Request is not a plist")
            server.logError(String(decoding: requestData, as: UTF8.self))
            try? sendString("ERROR:Malformed request: not a plist\n")
            return
        }
        server.debugLog("Parsed request plist")
        // verify the plist is in expected format
        let (valid, error) = verifyRequestSyntax(request)
        if !valid {
            server.logError("Plist syntax error: \(error)")
            try? sendString("ERROR:\(error)\n")
            return
        }
        server.debugLog("Dispatching worker to process request for user \(uid)")
        let handler = FDEUtil(server: server, uid: uid, request: request)
        do {
            let result = try handler.handle()
            try? sendString("OK:\(result)\n")
        } catch {
            try? sendString("ERROR:\(error.localizedDescription)\n")
        }
    }

    /// Reads data from the connected socket.
    func readData(maxsize: Int = 1024, timeout: Int = 10) throws -> Data {
        // read the data
        do {
            let data = try clientSocket.read(maxsize: maxsize, timeout: timeout)
            server.debugLog("Received: \(data.count) bytes")
            return data
        } catch let e as UNIXDomainSocketError {
            server.logError("Error reading from socket or connection closed")
            throw e
        }
    }

    /// Sends the provided data to the connected client.
    /// - Parameter data: The data to send
    func sendData(_ data: Data) throws {
        server.debugLog("Writing \(data.count) bytes")
        do {
            let bytesWritten = try clientSocket.write(data: data)
            server.debugLog("\(bytesWritten) bytes written")
        } catch let e as UNIXDomainSocketError {
            server.logError("Error sending data")
            throw e
        }
    }

    func verifyRequestSyntax(_ request: Any) -> (Bool, String) {
        if request is PlistDict {
            return (true, "")
        }
        server.logError(String(describing: request))
        return (false, "Request is not a plist dictionary")
    }

    /// returns uid and gid of peer (client)
    func getpeerid() -> (Int, Int) {
        var credStruct = xucred()
        var credStructSize = socklen_t(MemoryLayout<xucred>.stride)
        let success = getsockopt(clientSocket.fd, 0, LOCAL_PEERCRED, &credStruct, &credStructSize)
        if success != 0 {
            return (-1, -1)
        }
        if credStruct.cr_version != XUCRED_VERSION {
            return (-2, -2)
        }
        let uid = Int(credStruct.cr_uid)
        let gids = credStruct.cr_groups
        return (uid, Int(gids.0))
    }

    func sendString(_ string: String) throws {
        if let data = string.data(using: .utf8) {
            try sendData(data)
        }
    }
}

class AuthRestartServerError: MunkiError {}

class AuthRestartServer: UNIXDomainSocketServer {
    var storedUsername: String?
    var storedPassword: String?

    override func handleConnection(_ clientSocket: UNIXDomainSocket) async {
        let connectionHandler = AuthRestartRequestHandler(
            server: self, clientSocket: clientSocket
        )
        await connectionHandler.handle()
        clientSocket.close()
    }

    override func log(_ message: String) {
        munkiLog(message, logFile: LOGFILENAME)
    }

    func debugLog(_ message: String) {
        if debug {
            log(message)
        }
    }

    override func logError(_ message: String) {
        munkiLog("ERROR: " + message, logFile: LOGFILENAME)
    }

    /// Rotate our log if it's too large
    func rotateServerLog() {
        rotateLog(LOGFILENAME, ifLargerThan: 1_000_000)
    }
}

func main() async -> Int32 {
    // check to see if we're root
    if NSUserName() != "root" {
        printStderr("You must run this as root!")
        usleep(1_000_000 * 10)
        return -1
    }

    if !verifyExecutableOwnershipAndPermissions() {
        usleep(1_000_000 * 10)
        return -1
    }

    // get socket file descriptor from launchd
    guard let socketFD = try? getSocketFd(APPNAME) else {
        munkiLog("Could not get socket descriptor from launchd", logFile: LOGFILENAME)
        usleep(1_000_000 * 10)
        return -1
    }

    let daemon = AuthRestartServer(fd: socketFD, debug: DEBUG)
    daemon.rotateServerLog()
    do {
        try await daemon.run(withTimeout: 10)
    } catch {
        daemon.logError("\(APPNAME) failed: \(error)")
        return -1
    }
    return 0
}

/// run it!
await exit(main())
