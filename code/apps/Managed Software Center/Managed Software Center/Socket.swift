//
//  Socket.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 7/23/18.
//  Copyright © 2018-2026 The Munki Project. All rights reserved.
//

import Darwin
import Foundation
import CoreFoundation

enum UNIXDomainSocketClientErrorCode: Int {
    case noError = 0, addressError, createError, socketError, connectError, readError, writeError, timeoutError
}

class UNIXDomainSocketClient {
    // A basic implementation of Unix domain sockets for MSC
    // We use CFSocket calls when we can, and fallback to Darwin (BSD/C) API
    // when we must.
    
    var socketRef: CFSocket? = nil
    var errCode: UNIXDomainSocketClientErrorCode = .noError
    
    func close() {
        // close the socket if it exists
        if let socket = socketRef {
            CFSocketInvalidate(socket)
            socketRef = nil
        }
    }
    
    private func addrRefCreate(_ path: String) -> CFData? {
        // make a sockaddr struct (this is ugly), wrap it in a CFData obj
        var socketAdr = sockaddr_un()
        socketAdr.sun_family = sa_family_t(AF_UNIX)
        socketAdr.sun_len = __uint8_t(MemoryLayout<sockaddr_un>.size)
        if var cstring_path = path.cString(using: .utf8) {
            if cstring_path.count > MemoryLayout.size(
                ofValue: socketAdr.sun_path) {
                // path is too long for this 1970s era struct
                return nil
            }
            memcpy(&socketAdr.sun_path, &cstring_path, cstring_path.count)
        } else {
            return nil
        }
        return NSData(bytes: &socketAdr,
                      length: MemoryLayout.size(ofValue: socketAdr)) as CFData
    }

    func connect(to path: String) {
        // Create a UNIX domain socket object and connect
        //
        // get a CFData reference to our socket path
        guard let adrDataRef = addrRefCreate(path) else {
            errCode = .addressError
            return
        }
        // create a CFSocket object
        guard let socket = CFSocketCreate(kCFAllocatorDefault,
                                          PF_UNIX,
                                          SOCK_STREAM,
                                          0,
                                          0,
                                          nil,
                                          nil) else {
                                            errCode = .createError
                                            return
        }
        // connect
        guard CFSocketConnectToAddress(socket,
                                       adrDataRef,
                                       1) == .success else {
                                        errCode = .connectError
                                        return
        }
        // save the socket obj for later use
        socketRef = socket
    }
    
    func write(_ text: String) {
        // send text data to our socket
        //
        // ensure we have a non-nil socketRef
        guard let socket = socketRef else {
            errCode = .socketError
            return
        }
        if text.count == 0 || errCode != .noError {
            return
        }
        // make a CFData reference from our text data
        guard let data = text.data(using: .utf8) as CFData? else {
            errCode = .writeError
            return
        }
        errCode = .noError
        guard CFSocketSendData(socket, nil, data, 30) == .success else {
            errCode = .writeError
            return
        }
    }
    
    private func fdSet(_ fd: Int32, set: inout fd_set) {
        // Replacement for FD_SET macro
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
    
    private func dataAvailable(timeout: Int = 10) -> Bool {
        // uses POSIX select() to wait for data to be available on the socket
        //
        // ensure we have a non-nil socketRef
        guard let socket = socketRef else {
            errCode = .socketError
            return false
        }
        var timer = timeval()
        timer.tv_sec = timeout
        timer.tv_usec = 0
        let socket_fd = CFSocketGetNative(socket)
        var readfds = fd_set(fds_bits: (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        fdSet(socket_fd, set: &readfds)
        let result = select(socket_fd + 1, &readfds, nil, nil, &timer)
        return result > 0
    }

    func read(maxsize: Int = 1024, timeout: Int = 10) -> String {
        // read a message from our socket
        // there's no CFSocketRead method, use BSD socket recv method instead
        //
        // ensure we have a non-nil socketRef
        guard let socket = socketRef else {
            errCode = .socketError
            return ""
        }
        // wait up until timeout seconds for data to become available
        if !dataAvailable(timeout: timeout) {
            errCode = .timeoutError
            return ""
        }
        // allocate some space for the return message.
        let buffer = UnsafeMutablePointer<UInt8>.allocate(capacity: maxsize)
        defer { buffer.deallocate() }
        // read from socket
        let msg_len = recv(CFSocketGetNative(socket), buffer, maxsize, 0)
        if let msg = NSString(bytes: buffer,
                              length: msg_len,
                              encoding: String.Encoding.utf8.rawValue) as String? {
            return msg
        }
        errCode = .readError
        return ""
    }
}
