//
//  socket/common.swift
//  munki
//
//  Created by Greg Neagle on 8/3/24.
//

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
        return false
    }
    var timer = timeval()
    timer.tv_sec = timeout
    timer.tv_usec = 0
    var readfds = fd_set(fds_bits: (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))
    fdSet(socket, set: &readfds)
    let result = select(socket + 1, &readfds, nil, nil, &timer)
    return result > 0
}

/// Reads data from a socket.
func socket_read(socket: Int32, maxsize: Int = 1024) -> Data? {
    var buffer = [UInt8](repeating: 0, count: maxsize)
    let bytesRead = read(socket, &buffer, buffer.count)
    if bytesRead <= 0 {
        return nil
    }
    let data = Data(buffer[..<bytesRead])
    return data
}

/// Sends the provided data to the socket.
/// - Parameters
///  - socket: the socket
///  - data: The data to send.
///  Returns number of bytes written; -1 means an error occurred
func socket_write(socket: Int32, data: Data) -> Int {
    var bytesWritten = 0
    if data.isEmpty {
        return 0
    }
    data.withUnsafeBytes { (bytes: UnsafeRawBufferPointer) in
        let pointer = bytes.bindMemory(to: UInt8.self)
        bytesWritten = Darwin.send(socket, pointer.baseAddress!, data.count, 0)
    }
    return bytesWritten
}
