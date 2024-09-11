//
//  socket/common.swift
//  munki
//
//  Created by Greg Neagle on 8/3/24.
//

import Darwin
import Foundation

/// make a sockaddr struct (this is ugly), wrap it in a CFData obj
func addrRefCreate(_ path: String) -> CFData? {
    var socketAdr = sockaddr_un()
    socketAdr.sun_family = sa_family_t(AF_UNIX)
    socketAdr.sun_len = __uint8_t(MemoryLayout<sockaddr_un>.size)
    if var cstring_path = path.cString(using: .utf8) {
        if cstring_path.count > MemoryLayout.size(
            ofValue: socketAdr.sun_path)
        {
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
