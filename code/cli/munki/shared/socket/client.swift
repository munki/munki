//
//  socket/client.swift
//
//  Created by Greg Neagle on 7/23/18.
//  Copyright 2018-2026 The Munki Project. All rights reserved.
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

/// A basic implementation of Unix domain sockets
class UNIXDomainSocketClient {
    private var socket: UNIXDomainSocket?
    private var debug = false

    init(debug: Bool = false) throws {
        self.debug = debug
        socket = try UNIXDomainSocket()
    }

    deinit {
        close()
    }

    /// close the socket if it exists
    func close() {
        socket?.close()
        socket = nil
    }

    /// Attempts to connect to the Unix socket.
    func connect(to socketPath: String) throws {
        log("Attempting to connect to socket path: \(socketPath)")

        guard let socket, socket.fd != -1 else {
            logError("Invalid socket descriptor")
            throw UNIXDomainSocketError.socketError
        }

        var address = sockaddr_un()
        address.sun_family = sa_family_t(AF_UNIX)
        socketPath.withCString { ptr in
            withUnsafeMutablePointer(to: &address.sun_path.0) { dest in
                _ = strcpy(dest, ptr)
            }
        }

        log("File exists: \(FileManager.default.fileExists(atPath: socketPath))")

        if Darwin.connect(socket.fd, withUnsafePointer(to: &address) { $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { $0 } }, socklen_t(MemoryLayout<sockaddr_un>.size)) == -1 {
            logError("Error connecting to socket - \(String(cString: strerror(errno)))")
            throw UNIXDomainSocketError.connectError
        }

        log("Successfully connected to socket")
    }

    /// Reads data from the connected socket.
    func readData(maxsize: Int = 1024, timeout: Int = 10) throws -> Data {
        guard let socket, socket.fd != -1 else {
            logError("Invalid socket descriptor")
            throw UNIXDomainSocketError.socketError
        }
        // read the data
        do {
            let data = try socket.read(maxsize: maxsize, timeout: timeout)
            log("Received: \(data.count) bytes")
            return data
        } catch let e as UNIXDomainSocketError {
            logError("Error reading from socket or connection closed")
            throw e
        }
    }

    func readString(maxsize: Int = 1024, timeout: Int = 10) throws -> String {
        let data = try readData(maxsize: maxsize, timeout: timeout)
        return String(data: data, encoding: .utf8) ?? ""
    }

    /// Sends the provided data to the connected socket.
    /// - Parameter data: The data to send.
    func sendData(_ data: Data) throws {
        guard let socket, socket.fd != -1 else {
            logError("Invalid socket descriptor")
            throw UNIXDomainSocketError.socketError
        }
        log("Sending \(data.count) bytes")
        let bytesWritten = try socket.write(data: data)
        if bytesWritten == -1 {
            logError("Error sending data")
            throw UNIXDomainSocketError.writeError
        }
        log("\(bytesWritten) bytes written")
    }

    /// Logs a message.
    /// - Parameter message: The message to log.
    private func log(_ message: String) {
        if debug {
            print("UNIXDomainSocketClient: \(message)")
        }
    }

    /// Logs an error message.
    /// - Parameter message: The error message to log.
    private func logError(_ message: String) {
        if debug {
            print("UNIXDomainSocketClient: [ERROR] \(message)")
        }
    }
}
