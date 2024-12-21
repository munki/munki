//
//  socket/client.swift
//
//  Created by Greg Neagle on 7/23/18.
//  Copyright © 2018-2024 The Munki Project. All rights reserved.
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

import Darwin
import Foundation

enum UNIXDomainSocketClientErrorCode: Int {
    case noError = 0, addressError, createError, socketError, connectError, readError, writeError, timeoutError
}

/// A basic implementation of Unix domain sockets
class UNIXDomainSocketClient {
    private var socketDescriptor: Int32?
    var errCode: UNIXDomainSocketClientErrorCode = .noError
    private var debug = false

    init(debug: Bool = false) {
        self.debug = debug
    }

    /// close the socket if it exists
    func close() {
        if let socket = socketDescriptor {
            Darwin.close(socket)
            socketDescriptor = nil
        }
    }

    /// Attempts to connect to the Unix socket.
    func connect(to socketPath: String) {
        log("Attempting to connect to socket path: \(socketPath)")

        socketDescriptor = Darwin.socket(AF_UNIX, SOCK_STREAM, 0)
        guard let socketDescriptor, socketDescriptor != -1 else {
            logError("Error creating socket")
            errCode = .createError
            return
        }

        var address = sockaddr_un()
        address.sun_family = sa_family_t(AF_UNIX)
        socketPath.withCString { ptr in
            withUnsafeMutablePointer(to: &address.sun_path.0) { dest in
                _ = strcpy(dest, ptr)
            }
        }

        log("File exists: \(FileManager.default.fileExists(atPath: socketPath))")

        if Darwin.connect(socketDescriptor, withUnsafePointer(to: &address) { $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { $0 } }, socklen_t(MemoryLayout<sockaddr_un>.size)) == -1 {
            logError("Error connecting to socket - \(String(cString: strerror(errno)))")
            errCode = .connectError
            return
        }

        log("Successfully connected to socket")
    }

    /// Reads data from the connected socket.
    func readData(maxsize: Int = 1024, timeout: Int = 10) -> Data? {
        guard let socketDescriptor else {
            logError("Socket descriptor is nil")
            errCode = .socketError
            return nil
        }
        // wait up until timeout seconds for data to become available
        if !dataAvailable(socket: socketDescriptor, timeout: timeout) {
            errCode = .timeoutError
            return nil
        }
        // read the data
        let data = socket_read(socket: socketDescriptor, maxsize: maxsize)
        if let data {
            log("Received: \(data.count) bytes")
            return data
        } else {
            logError("Error reading from socket or connection closed")
            errCode = .readError
            return nil
        }
    }

    func readString(maxsize: Int = 1024, timeout: Int = 10) -> String {
        let data = readData(maxsize: maxsize, timeout: timeout)
        if let data, let str = String(data: data, encoding: .utf8) {
            return str
        }
        return ""
    }

    /// Sends the provided data to the connected socket.
    /// - Parameter data: The data to send.
    func sendData(_ data: Data) {
        guard let socketDescriptor else {
            logError("Socket descriptor is nil")
            errCode = .socketError
            return
        }
        let bytesWritten = socket_write(socket: socketDescriptor, data: data)
        if bytesWritten == -1 {
            logError("Error sending data")
            errCode = .writeError
            return
        }
        log("\(bytesWritten) bytes written")
    }

    /// Logs a message.
    /// - Parameter message: The message to log.
    private func log(_ message: String) {
        if debug {
            print("ClientUnixSocket: \(message)")
        }
    }

    /// Logs an error message.
    /// - Parameter message: The error message to log.
    private func logError(_ message: String) {
        if debug {
            print("ClientUnixSocket: [ERROR] \(message)")
        }
    }
}
