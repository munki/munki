//
//  xattr.swift
//  munki
//
//  Created by Greg Neagle on 8/4/24.
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

import Darwin
import Foundation

/// List extended attributes for path
/// A simple implementation sufficient for Munki's needs
/// Inspired by https://github.com/okla/swift-xattr/blob/master/xattr.swift
func listXattrs(atPath path: String) throws -> [String] {
    let bufLength = listxattr(path, nil, 0, XATTR_NOFOLLOW)

    guard bufLength != -1 else {
        let errString = String(utf8String: strerror(errno)) ?? String(errno)
        throw MunkiError("Could not get buffer length for xattrs for \(path): \(errString)")
    }

    let buf = UnsafeMutablePointer<Int8>.allocate(capacity: bufLength)
    guard listxattr(path, buf, bufLength, 0) != -1 else {
        let errString = String(utf8String: strerror(errno)) ?? String(errno)
        throw MunkiError("Could not get list of xattrs for \(path): \(errString)")
    }

    let names = NSString(bytes: buf, length: bufLength, encoding: String.Encoding.utf8.rawValue)?.components(separatedBy: "\0").filter { !$0.isEmpty }
    return names ?? [String]()
}

/// Remove an extended attribute for path
/// A simple implementation sufficient for Munki's needs
/// Inspired by https://github.com/okla/swift-xattr/blob/master/xattr.swift
func removeXattr(_ name: String, atPath path: String) throws {
    if removexattr(path, name, XATTR_NOFOLLOW) == -1 {
        let errString = String(utf8String: strerror(errno)) ?? String(errno)
        throw MunkiError("Failed to remove xattr \(name) from \(path): \(errString)")
    }
}

/// Set an extended attribute for path
/// A simple implementation sufficient for Munki's needs
/// Inspired by https://github.com/okla/swift-xattr/blob/master/xattr.swift
func setXattr(named name: String, data: Data, atPath path: String) throws {
    if setxattr(path, name, (data as NSData).bytes, data.count, 0, 0) == -1 {
        let errString = String(utf8String: strerror(errno)) ?? String(errno)
        throw MunkiError("Failed to set xattr \(name) at \(path): \(errString)")
    }
}

/// Get an extended attribute for path
/// A simple implementation sufficient for Munki's needs
/// Inspired by https://github.com/okla/swift-xattr/blob/master/xattr.swift
func getXattr(named name: String, atPath path: String) throws -> Data {
    let bufLength = getxattr(path, name, nil, 0, 0, 0)

    guard bufLength != -1, let buf = malloc(bufLength), getxattr(path, name, buf, bufLength, 0, 0) != -1 else {
        let errString = String(utf8String: strerror(errno)) ?? String(errno)
        throw MunkiError("Failed to get xattr \(name) at \(path): \(errString)")
    }
    return Data(bytes: buf, count: bufLength)
}

/// Removes com.apple.quarantine xattr from a path
func removeQuarantineXattrFromItem(_ path: String) throws {
    let xattrs = try listXattrs(atPath: path)
    if xattrs.contains("com.apple.quarantine") {
        try removeXattr("com.apple.quarantine", atPath: path)
    }
}

/// Removes com.apple.quarantine xattr from a path, recursively if needed
func removeQuarantineXattrsRecursively(_ path: String) throws {
    try removeQuarantineXattrFromItem(path)
    if pathIsDirectory(path) {
        let dirEnum = FileManager.default.enumerator(atPath: path)
        while let item = dirEnum?.nextObject() as? String {
            let itempath = (path as NSString).appendingPathComponent(item)
            try removeQuarantineXattrFromItem(itempath)
        }
    }
}
