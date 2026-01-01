//
//  plistutils.swift
//  munki
//
//  Created by Greg Neagle on 6/27/24.
//  Copyright 2024-2026 The Munki Project.
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

import Foundation

enum PlistError: Error {
    case readError(description: String)
    case writeError(description: String)
}

extension PlistError: LocalizedError {
    var errorDescription: String? {
        switch self {
        case let .readError(description):
            return description
        case let .writeError(description):
            return description
        }
    }
}

/// Attempt to convert data into a PropertyList object
func deserialize(_ data: Data?) throws -> Any? {
    if data != nil {
        do {
            let dataObject = try PropertyListSerialization.propertyList(
                from: data!,
                options: PropertyListSerialization.MutabilityOptions.mutableContainers,
                format: nil
            )
            return dataObject
        } catch {
            throw PlistError.readError(description: "\(error)")
        }
    }
    return nil
}

/// Attempt to read a PropertyList from a file
func readPlist(fromFile filepath: String) throws -> Any? {
    return try deserialize(NSData(contentsOfFile: filepath) as Data?)
}

/// Attempt to read a PropertyList from data
func readPlist(fromData data: Data) throws -> Any? {
    return try deserialize(data)
}

/// Attempt to read a PropertyList from a string
func readPlist(fromString string: String) throws -> Any? {
    return try deserialize(string.data(using: String.Encoding.utf8))
}

/// Attempt to convert a PropertyList object into a data representation
func serialize(_ plist: Any) throws -> Data {
    do {
        let plistData = try PropertyListSerialization.data(
            fromPropertyList: plist,
            format: PropertyListSerialization.PropertyListFormat.xml,
            options: 0
        )
        return plistData
    } catch {
        throw PlistError.writeError(description: "\(error)")
    }
}

/// Attempt to write a PropertyList object to a file
func writePlist(_ dataObject: Any, toFile filepath: String) throws {
    do {
        let data = try serialize(dataObject) as NSData
        if !(data.write(toFile: filepath, atomically: true)) {
            throw PlistError.writeError(description: "write failed")
        }
    } catch {
        throw PlistError.writeError(description: "\(error)")
    }
}

/// Attempt to convert a PropertyList object to a Data object
func plistToData(_ dataObject: Any) throws -> Data {
    return try serialize(dataObject)
}

/// Attempt to convert a PropertyList object to string
func plistToString(_ dataObject: Any) throws -> String {
    do {
        let data = try serialize(dataObject)
        return String(data: data, encoding: String.Encoding.utf8)!
    } catch {
        throw PlistError.writeError(description: "\(error)")
    }
}

/// Parses a string, looking for the first thing that looks like a plist.
/// Returns two strings. The first will be a string representation of a plist (or empty)
/// The second is any characters remaining after the found plist
func parseFirstPlist(fromString str: String) -> (String, String) {
    let header = "<?xml version"
    let footer = "</plist>"
    let headerRange = (str as NSString).range(of: header)
    if headerRange.location == NSNotFound {
        // header not found
        return ("", str)
    }
    let footerSearchIndex = headerRange.location + headerRange.length
    let footerSearchRange = NSRange(
        location: footerSearchIndex,
        length: str.count - footerSearchIndex
    )
    let footerRange = (str as NSString).range(of: footer, range: footerSearchRange)
    if footerRange.location == NSNotFound {
        // footer not found
        return ("", str)
    }
    let plistRange = NSRange(
        location: headerRange.location,
        length: footerRange.location + footerRange.length - headerRange.location
    )
    let plistStr = (str as NSString).substring(with: plistRange)
    let remainderIndex = plistRange.location + plistRange.length
    let remainder = (str as NSString).substring(from: remainderIndex)
    return (plistStr, remainder)
}
