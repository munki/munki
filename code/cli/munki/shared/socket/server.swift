//
//  socket/server.swift
//  munkitester
//
//  Created by Greg Neagle on 8/3/24.
//

import Foundation

enum UNIXDomainSocketServerErrorCode: Int {
    case noError = 0, addressError, createError, bindError, listenError, socketError, connectError, readError, writeError, timeoutError
}

class UNIXDomainSocketServer {
    var serverSocket: Int32?
    var clientSocket: Int32?
    var debug = false
    var errCode: UNIXDomainSocketServerErrorCode = .noError

    init(socketPath: String, requestHandler _: @escaping (Int32) -> Void, debug: Bool = false) {
        self.debug = debug
        createSocket()
        bindSocket(to: socketPath)
    }

    init(fd: Int32, requestHandler _: @escaping (Int32) -> Void, debug: Bool = false) {
        self.debug = debug
        serverSocket = fd
    }

    /// Starts the server and begins listening for connections.
    func start() {
        listenOnSocket()
        waitForConnection()
    }

    /// Creates a socket for communication.
    private func createSocket() {
        serverSocket = Darwin.socket(AF_UNIX, SOCK_STREAM, 0)
        guard serverSocket != nil, serverSocket != -1 else {
            logError("Error creating socket")
            errCode = .createError
            return
        }
        log("Socket created successfully")
    }

    /// Binds the created socket to a specific address.
    private func bindSocket(to socketPath: String) {
        guard let socket = serverSocket else { return }

        var address = sockaddr_un()
        address.sun_family = sa_family_t(AF_UNIX)
        socketPath.withCString { ptr in
            withUnsafeMutablePointer(to: &address.sun_path.0) { dest in
                _ = strcpy(dest, ptr)
            }
        }

        unlink(socketPath) // Remove any existing socket file

        if Darwin.bind(socket, withUnsafePointer(to: &address) { $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { $0 } }, socklen_t(MemoryLayout<sockaddr_un>.size)) == -1 {
            logError("Error binding socket - \(String(cString: strerror(errno)))")
            errCode = .bindError
            return
        }
        log("Binding to socket path: \(socketPath)")
    }

    /// Listens for connections on the bound socket.
    private func listenOnSocket() {
        guard let socket = serverSocket else { return }

        if Darwin.listen(socket, 1) == -1 {
            logError("Error listening on socket - \(String(cString: strerror(errno)))")
            errCode = .listenError
            return
        }
        log("Listening for connections...")
    }

    /// Waits for a connection and accepts it when available.
    private func waitForConnection() {
        DispatchQueue.global().async { [weak self] in
            self?.acceptConnection()
        }
    }

    /// function to be overridden in subclasses
    func handleConnection() {
        // override me!
    }

    /// Accepts a connection request from a client.
    private func acceptConnection() {
        guard let socket = serverSocket else { return }

        var clientAddress = sockaddr_un()
        var clientAddressLen = socklen_t(MemoryLayout<sockaddr_un>.size)
        clientSocket = Darwin.accept(socket, withUnsafeMutablePointer(to: &clientAddress) { $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { $0 } }, &clientAddressLen)

        if clientSocket == -1 {
            logError("Error accepting connection - \(String(cString: strerror(errno)))")
            errCode = .connectError
            return
        }
        log("Connection accepted!")
        handleConnection()
    }

    /// Reads data from the connected socket.
    func readData(maxsize: Int = 1024, timeout: Int = 10) -> Data? {
        guard let socketDescriptor = clientSocket else {
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

    /// Sends the provided data to the connected client.
    /// - Parameter data: The data to send
    func sendData(_ data: Data) {
        guard let socketDescriptor = clientSocket else {
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

    /// Stops the server and closes any open connections.
    func stop() {
        if let clientSocket {
            log("Closing client socket...")
            close(clientSocket)
        }
        if let socket = serverSocket {
            log("Closing server socket...")
            close(socket)
        }
        // unlink(socketPath)
        log("Broadcasting stopped.")
    }

    /// Logs a success message.
    /// - Parameter message: The message to log.
    func log(_ message: String) {
        print("ServerUnixSocket: \(message)")
    }

    /// Logs an error message.
    /// - Parameter message: The message to log.
    func logError(_ message: String) {
        print("ServerUnixSocket: [ERROR] \(message)")
    }
}
