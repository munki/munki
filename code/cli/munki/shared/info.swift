//
//  info.swift
//  munki
//
//  Created by Greg Neagle on 8/7/24.
//

import Foundation

func platform() -> String {
    // returns platform ("x86_64", "arm64")
    var systemInfo = utsname()
    uname(&systemInfo)
    let size = Int(_SYS_NAMELEN) // is 32, but posix AND its init is 256....

    let s = withUnsafeMutablePointer(to: &systemInfo.machine) { p in
        p.withMemoryRebound(to: CChar.self, capacity: size) { p2 in
            return String(cString: p2)
        }
    }
    return s
}

func isAppleSilicon() -> Bool {
    // Returns true if we're running on Apple silicon"
    return platform() == "arm64"
}
