//
//  socket/common.swift
//  munki
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

import Darwin
import Foundation

/// Replacement for FD_SET macro
func fdSet(_ fd: Int32, set: inout fd_set) {
    let intOffset = Int(fd / 32)
    let bitOffset = fd % 32
    let mask = Int32(1 << bitOffset)
    switch intOffset {
    case 0: set.fds_bits.0 = set.fds_bits.0 | mask
    case 1: set.fds_bits.1 = set.fds_bits.1 | mask
    case 2: set.fds_bits.2 = set.fds_bits.2 | mask
    case 3: set.fds_bits.3 = set.fds_bits.3 | mask
    case 4: set.fds_bits.4 = set.fds_bits.4 | mask
    case 5: set.fds_bits.5 = set.fds_bits.5 | mask
    case 6: set.fds_bits.6 = set.fds_bits.6 | mask
    case 7: set.fds_bits.7 = set.fds_bits.7 | mask
    case 8: set.fds_bits.8 = set.fds_bits.8 | mask
    case 9: set.fds_bits.9 = set.fds_bits.9 | mask
    case 10: set.fds_bits.10 = set.fds_bits.10 | mask
    case 11: set.fds_bits.11 = set.fds_bits.11 | mask
    case 12: set.fds_bits.12 = set.fds_bits.12 | mask
    case 13: set.fds_bits.13 = set.fds_bits.13 | mask
    case 14: set.fds_bits.14 = set.fds_bits.14 | mask
    case 15: set.fds_bits.15 = set.fds_bits.15 | mask
    case 16: set.fds_bits.16 = set.fds_bits.16 | mask
    case 17: set.fds_bits.17 = set.fds_bits.17 | mask
    case 18: set.fds_bits.18 = set.fds_bits.18 | mask
    case 19: set.fds_bits.19 = set.fds_bits.19 | mask
    case 20: set.fds_bits.20 = set.fds_bits.20 | mask
    case 21: set.fds_bits.21 = set.fds_bits.21 | mask
    case 22: set.fds_bits.22 = set.fds_bits.22 | mask
    case 23: set.fds_bits.23 = set.fds_bits.23 | mask
    case 24: set.fds_bits.24 = set.fds_bits.24 | mask
    case 25: set.fds_bits.25 = set.fds_bits.25 | mask
    case 26: set.fds_bits.26 = set.fds_bits.26 | mask
    case 27: set.fds_bits.27 = set.fds_bits.27 | mask
    case 28: set.fds_bits.28 = set.fds_bits.28 | mask
    case 29: set.fds_bits.29 = set.fds_bits.29 | mask
    case 30: set.fds_bits.30 = set.fds_bits.30 | mask
    case 31: set.fds_bits.31 = set.fds_bits.31 | mask
    default: break
    }
}

/// uses POSIX select() to wait for data to be available on the socket
func dataAvailable(socket: Int32?, timeout: Int = 10) -> Bool {
    // ensure we have a non-nil socketRef
    guard let socket else {
        // print("select error: socket is nil")
        return false
    }
    var timer = timeval()
    timer.tv_sec = timeout
    timer.tv_usec = 0
    var readfds = fd_set(fds_bits: (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))
    fdSet(socket, set: &readfds)
    let result = select(socket + 1, &readfds, nil, nil, &timer)
    // print("select result: \(result) on socket: \(socket)")
    return result > 0
}

enum UNIXDomainSocketError: Error {
    case addressError
    case createError
    case bindError
    case listenError
    case socketError
    case connectError
    case readError
    case writeError
    case timeoutError
}

class UNIXDomainSocket {
    var fd: Int32 = -1

    init(fd: Int32) {
        self.fd = fd
    }

    init() throws {
        fd = Darwin.socket(AF_UNIX, SOCK_STREAM, 0)
        if fd == -1 {
            throw UNIXDomainSocketError.createError
        }
    }

    deinit {
        if fd >= 0 {
            close()
        }
    }

    func close() {
        if fd >= 0 {
            Darwin.shutdown(fd, SHUT_WR)
            Darwin.close(fd)
            fd = -1
        }
    }

    func read(maxsize: Int = 1024, timeout: Int = 0) throws -> Data {
        if fd < 0 {
            throw UNIXDomainSocketError.socketError
        }
        if timeout > 0 {
            if !dataAvailable(socket: fd, timeout: timeout) {
                throw UNIXDomainSocketError.timeoutError
            }
        }
        var buffer = [UInt8](repeating: 0, count: maxsize)
        let bytesRead = Darwin.read(fd, &buffer, buffer.count)
        if bytesRead <= 0 {
            throw UNIXDomainSocketError.readError
        }
        let data = Data(buffer[..<bytesRead])
        return data
    }

    func readString(maxsize: Int = 1024, timeout: Int = 0) throws -> String {
        let data = try read(maxsize: maxsize, timeout: timeout)
        if let str = String(data: data, encoding: .utf8) {
            return str
        }
        throw UNIXDomainSocketError.readError
    }

    func write(data: Data) throws -> Int {
        if fd < 0 {
            throw UNIXDomainSocketError.socketError
        }
        var bytesWritten = 0
        if data.isEmpty {
            return 0
        }
        data.withUnsafeBytes { (bytes: UnsafeRawBufferPointer) in
            let pointer = bytes.bindMemory(to: UInt8.self)
            bytesWritten = Darwin.send(fd, pointer.baseAddress!, data.count, 0)
        }
        if bytesWritten < 0 {
            throw UNIXDomainSocketError.writeError
        }
        return bytesWritten
    }

    func write(string: String) throws -> Int {
        if let data = string.data(using: .utf8) {
            return try write(data: data)
        }
        throw UNIXDomainSocketError.writeError
    }
}
