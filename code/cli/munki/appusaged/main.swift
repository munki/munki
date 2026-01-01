//
//  main.swift
//  appusaged
//
//  Created by Greg Neagle on 8/3/24.
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

private let DEBUG = false
private let APPNAME = "appusaged"

class AppUsageHandlerError: MunkiError {}

/// Class for working with appusage
class AppUsageHandler {
    var server: AppUsageServer
    var uid: Int
    var request: PlistDict

    init(server: AppUsageServer, uid: Int, request: PlistDict) {
        self.server = server
        self.uid = uid
        self.request = request
    }

    /// Reformats the string representation of a request dict for logging
    func requestDescription() -> String {
        var description = String(describing: request)
        description = description.replacingOccurrences(of: "\n    ", with: " ")
        description = description.replacingOccurrences(of: "\n", with: " ")
        return description
    }

    /// Handle a usage request
    func handle() throws {
        if let event = request["event"] as? String {
            if ["install", "remove"].contains(event) {
                // record App install/removal request
                server.log("App install/removal request from uid \(uid)")
                server.log(requestDescription())
                if let installRequest = request as? [String: String] {
                    ApplicationUsageRecorder().log_install_request(installRequest)
                }
            } else {
                // record app usage event
                server.log("App usage event from uid \(uid)")
                server.log(requestDescription())
                if let appData = request["app_dict"] as? [String: String] {
                    ApplicationUsageRecorder().log_application_usage(event: event, appData: appData)
                }
            }
        } else {
            server.logError("No 'event' in request")
            throw AppUsageHandlerError("No 'event' in request")
        }
    }
}

class AppUsageServerRequestHandler {
    var server: AppUsageServer
    var clientSocket: UNIXDomainSocket

    init(server: AppUsageServer, clientSocket: UNIXDomainSocket) {
        self.server = server
        self.clientSocket = clientSocket
    }

    func handle() async {
        server.debugLog("Handling appusage request")
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
        let handler = AppUsageHandler(server: server, uid: uid, request: request)
        do {
            try handler.handle()
            try? sendString("OK:\n")
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

class AppUsageServer: UNIXDomainSocketServer {
    var logger = MunkiLogger(logname: APPUSAGED_LOGFILENAME)

    /// Handle an incoming appusage event
    override func handleConnection(_ clientSocket: UNIXDomainSocket) async {
        let connectionHandler = AppUsageServerRequestHandler(
            server: self, clientSocket: clientSocket
        )
        await connectionHandler.handle()
        clientSocket.close()
    }

    override func log(_ message: String) {
        logger.notice(message)
    }

    func debugLog(_ message: String) {
        logger.debug(message)
    }

    override func logError(_ message: String) {
        logger.error("ERROR: " + message)
    }

    /// Rotate our log if it's too large
    func rotateServerLog() {
        let logPath = logNamed(APPUSAGED_LOGFILENAME)
        let MAX_LOGFILE_SIZE = 1_000_000
        if pathIsRegularFile(logPath),
           let attributes = try? FileManager.default.attributesOfItem(atPath: logPath)
        {
            let filesize = (attributes as NSDictionary).fileSize()
            if filesize > MAX_LOGFILE_SIZE {
                rotateLog(logPath)
            }
        }
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
        munkiLog("Could not get socket descriptor from launchd", logFile: APPUSAGED_LOGFILENAME)
        usleep(1_000_000 * 10)
        return -1
    }

    /*
     guard let daemon = try? AppUsageServer(socketPath: "/Users/Shared/appusaged.socket", debug: DEBUG)
     else {
          munkiLog("Could not initialize \(APPNAME)", logFile: LOGFILENAME)
          return -1
      }
     */
    let daemon = AppUsageServer(fd: socketFD, debug: DEBUG)
    daemon.rotateServerLog()
    // daemon.log("\(APPNAME) starting")
    do {
        try await daemon.run(withTimeout: 10)
        // try await daemon.run()
    } catch {
        daemon.logError("\(APPNAME) failed: \(error)")
    }
    return 0
}

/// run it!
await exit(main())
