//
//  munkihash.swift
//  munki
//
//  Created by Greg Neagle on 7/6/24.
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

#if canImport(CryptoKit)
    import CryptoKit
#else
    import Crypto
#endif
import Foundation

#if !canImport(ObjectiveC)
    // Linux has no Obj-C runtime; autoreleasepool is a no-op shim
    @inline(__always)
    func autoreleasepool<T>(_ body: () -> T) -> T { body() }
#endif

// put all the hashing functions here

func sha256hash(data: Data) -> String {
    let hashed = SHA256.hash(data: data)
    return hashed.compactMap { String(format: "%02x", $0) }.joined()
}

func sha256hash(file: String) -> String {
    guard let handle = FileHandle(forReadingAtPath: file) else {
        return "N/A"
    }
    defer { handle.closeFile() }
    var hasher = SHA256()
    let chunkSize = 1024 * 1024 // 1 MB
    var done = false
    while !done {
        // autoreleasepool drains NSData-backed chunks each iteration,
        // preventing all chunks from accumulating until the pool drains
        autoreleasepool {
            let chunk = handle.readData(ofLength: chunkSize)
            if chunk.isEmpty {
                done = true
            } else {
                hasher.update(data: chunk)
            }
        }
    }
    let digest = hasher.finalize()
    return digest.compactMap { String(format: "%02x", $0) }.joined()
}

func md5hash(file: String) -> String {
    guard let handle = FileHandle(forReadingAtPath: file) else {
        return ""
    }
    defer { handle.closeFile() }
    var hasher = Insecure.MD5()
    let chunkSize = 1024 * 1024 // 1 MB
    var done = false
    while !done {
        autoreleasepool {
            let chunk = handle.readData(ofLength: chunkSize)
            if chunk.isEmpty {
                done = true
            } else {
                hasher.update(data: chunk)
            }
        }
    }
    let digest = hasher.finalize()
    return digest.compactMap { String(format: "%02x", $0) }.joined()
}
