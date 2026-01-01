//
//  launchd.swift
//  munki
//
//  Created by Greg Neagle on 12/22/24.
//
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

import Darwin.C
import Foundation

/// Retrieve named socket file descriptor from launchd.
func getSocketFd(_ socketName: String) throws -> Int32 {
    var fdsCount = 0
    var fds = UnsafeMutablePointer<CInt>.allocate(capacity: 0)
    let originalFds = fds
    let err = launch_activate_socket(
        socketName,
        &fds,
        &fdsCount
    )
    if err != 0 {
        originalFds.deallocate()
        var errorDescription = ""
        switch err {
        case ENOENT:
            errorDescription = "The socket name specified does not exist in the caller's launchd.plist"
        case ESRCH:
            errorDescription = "The calling process is not managed by launchd"
        case EALREADY:
            errorDescription = "The specified socket has already been activated"
        default:
            let errStr = String(cString: strerror(err))
            errorDescription = "Error \(errStr)"
        }
        throw MunkiError("Failed to retrieve sockets from launchd: \(errorDescription)")
    }
    // make sure we clean up these allocations
    defer { fds.deallocate() }
    defer { originalFds.deallocate() }
    // fds is now a pointer to a list of filedescriptors. Transform into Swift array
    let outputFds = UnsafeMutableBufferPointer<CInt>(
        start: fds,
        count: Int(fdsCount)
    )
    if [CInt](outputFds).isEmpty {
        throw MunkiError("Failed to retrieve sockets from launchd: Empty socket list")
    }
    // for our needs we only need the first file descriptor
    return [CInt](outputFds)[0] as Int32
}
