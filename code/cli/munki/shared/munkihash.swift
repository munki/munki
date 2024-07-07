//
//  munkihash.swift
//  munki
//
//  Created by Greg Neagle on 7/6/24.
//

import CryptoKit
import Foundation

// put all the hashing functions here

func sha256hash(data: Data) -> String {
    let hashed = SHA256.hash(data: data)
    return hashed.compactMap { String(format: "%02x", $0) }.joined()
}

func sha256hash(file: String) -> String {
    if let data = NSData(contentsOfFile: file) {
        let hashed = SHA256.hash(data: data)
        return hashed.compactMap { String(format: "%02x", $0) }.joined()
    }
    return "N/A"
}

func md5hash(file: String) -> String {
    if let data = NSData(contentsOfFile: file) {
        let hashed = Insecure.MD5.hash(data: data)
        return hashed.compactMap { String(format: "%02x", $0) }.joined()
    }
    return ""
}
