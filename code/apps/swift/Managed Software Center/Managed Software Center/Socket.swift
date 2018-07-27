//
//  UnixDomainSocket.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 7/23/18.
//  Copyright © 2018 The Munki Project. All rights reserved.
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
        // make a CFData reference to the sockaddr struct
        let sockaddr_un_ptr = UnsafeMutableRawPointer(
            &socketAdr).bindMemory(to: UInt8.self,
                                   capacity: MemoryLayout<sockaddr_un>.size)
        return CFDataCreate(kCFAllocatorDefault,
                            sockaddr_un_ptr,
                            MemoryLayout<sockaddr_un>.size)
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
        var readfds = fd_set(fds_bits: (CFSocketGetNative(socket), 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        return select(1, &readfds, nil, nil, &timer) > 0
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
        let buffer = Array<CChar>(repeating: CChar(0), count: maxsize)
        // read from socket
        let msg_len = recv(CFSocketGetNative(socket),
                           UnsafeMutableRawPointer(mutating: buffer),
                           maxsize,
                           0)
        if msg_len > 0 {
            if let text = String(utf8String: buffer) {
                return text
            }
        }
        errCode = .writeError
        return ""
    }
}
