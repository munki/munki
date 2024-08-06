//
//  xattr.swift
//  munki
//
//  Created by Greg Neagle on 8/4/24.
//

import Darwin
import Foundation

func listXattrs(atPath path: String) throws -> [String] {
    // A simple implementation sufficient for Munki's needs
    // Inspired by https://github.com/okla/swift-xattr/blob/master/xattr.swift
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

    var names = NSString(bytes: buf, length: bufLength, encoding: String.Encoding.utf8.rawValue)?.components(separatedBy: "\0").filter { !$0.isEmpty }
    return names ?? [String]()
}

func removeXattr(_ name: String, atPath path: String) throws {
    // A simple implementation sufficient for Munki's needs
    // Inspired by https://github.com/okla/swift-xattr/blob/master/xattr.swift
    if removexattr(path, name, XATTR_NOFOLLOW) == -1 {
        let errString = String(utf8String: strerror(errno)) ?? String(errno)
        throw MunkiError("Failed to remove xattr \(name) from \(path): \(errString)")
    }
}
