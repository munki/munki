//
//  socket/server.swift
//  munkitester
//
//  Created by Greg Neagle on 8/3/24.
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

class UNIXDomainSocketServer {
    var serverSocket: UNIXDomainSocket?
    var debug = false
    var listening: Bool = false

    init(socketPath: String, debug: Bool = false) throws {
        self.debug = debug
        serverSocket = try UNIXDomainSocket()
        try bindSocket(to: socketPath)
    }

    init(fd: Int32, debug: Bool = false) {
        self.debug = debug
        serverSocket = UNIXDomainSocket(fd: fd)
    }

    deinit {
        if listening {
            stop()
        }
    }

    /// Binds the created socket to a specific address.
    private func bindSocket(to socketPath: String) throws {
        guard let socket = serverSocket else {
            throw UNIXDomainSocketError.socketError
        }

        var address = sockaddr_un()
        address.sun_family = sa_family_t(AF_UNIX)
        socketPath.withCString { ptr in
            withUnsafeMutablePointer(to: &address.sun_path.0) { dest in
                _ = strcpy(dest, ptr)
            }
        }

        unlink(socketPath) // Remove any existing socket file

        if Darwin.bind(socket.fd, withUnsafePointer(to: &address) { $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { $0 } }, socklen_t(MemoryLayout<sockaddr_un>.size)) == -1 {
            logError("Error binding socket - \(String(cString: strerror(errno)))")
            throw UNIXDomainSocketError.bindError
        }
        if debug {
            log("Binding to socket path: \(socketPath)")
        }
    }

    /// Listens for connections on the bound socket.
    private func listenOnSocket() throws {
        guard let socket = serverSocket else {
            throw UNIXDomainSocketError.socketError
        }

        if Darwin.listen(socket.fd, 1) == -1 {
            logError("Error listening on socket - \(String(cString: strerror(errno)))")
            throw UNIXDomainSocketError.listenError
        }
        if debug {
            log("Listening for connections...")
        }
    }

    /// Waits for a connection and accepts it when available.
    private func waitForConnection(withTimeout timeout: Int = 0) async throws {
        guard let socket = serverSocket else {
            throw UNIXDomainSocketError.socketError
        }
        if timeout > 0 {
            if !dataAvailable(socket: socket.fd, timeout: timeout) {
                throw UNIXDomainSocketError.timeoutError
            }
        }
        try await acceptConnection()
    }

    /// Accepts a connection request from a client.
    private func acceptConnection() async throws {
        guard let socket = serverSocket else {
            throw UNIXDomainSocketError.socketError
        }

        var clientAddress = sockaddr_un()
        var clientAddressLen = socklen_t(MemoryLayout<sockaddr_un>.size)
        let clientSocketFD = Darwin.accept(socket.fd, withUnsafeMutablePointer(to: &clientAddress) { $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { $0 } }, &clientAddressLen)

        if clientSocketFD == -1 {
            logError("Error accepting connection - \(String(cString: strerror(errno)))")
            throw UNIXDomainSocketError.connectError
        }
        if debug {
            log("Connection accepted!")
        }
        let clientSocket = UNIXDomainSocket(fd: clientSocketFD)
        await handleConnection(clientSocket)
    }

    /// function to be overridden in subclasses
    func handleConnection(_: UNIXDomainSocket) async {
        // override me!
    }

    /// Starts the server and begins listening for connections.
    func run(withTimeout timeout: Int = 0) async throws {
        try listenOnSocket()
        listening = true
        while listening {
            do {
                try await waitForConnection(withTimeout: timeout)
            } catch let e as UNIXDomainSocketError {
                stop()
                switch e {
                case .timeoutError:
                    if debug {
                        log("Timeout waiting for connection")
                    }
                default:
                    logError("\(e)")
                }
            }
        }
    }

    /// Stops the server and closes any open connections.
    func stop() {
        if let socket = serverSocket {
            if debug {
                log("Closing server socket...")
            }
            socket.close()
            serverSocket = nil
        }
        // unlink(socketPath)
        listening = false
        if debug {
            log("Broadcasting stopped.")
        }
    }

    /// Logs a success message.
    /// - Parameter message: The message to log.
    func log(_ message: String) {
        print("UNIXDomainSocketServer: \(message)")
    }

    /// Logs an error message.
    /// - Parameter message: The message to log.
    func logError(_ message: String) {
        print("UNIXDomainSocketServer: [ERROR] \(message)")
    }
}
