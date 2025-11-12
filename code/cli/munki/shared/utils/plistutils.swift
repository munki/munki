//
//  plistutils.swift
//  munki
//
//  Created by Greg Neagle on 6/27/24.
//  Copyright 2024-2025 Greg Neagle.
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
/// Now supports both plist and YAML files based on file extension
func readPlist(fromFile filepath: String) throws -> Any? {
    if isYamlFile(filepath) {
        return try readYaml(fromFile: filepath)
    }
    return try deserialize(NSData(contentsOfFile: filepath) as Data?)
}

/// Attempt to read a PropertyList from data
/// Tries plist first, then YAML if that fails
func readPlist(fromData data: Data) throws -> Any? {
    // Try plist first
    do {
        return try deserialize(data)
    } catch {
        // Try YAML as fallback
        do {
            return try readYaml(fromData: data)
        } catch {
            // Throw the original plist error if both fail
            throw PlistError.readError(description: "Failed to parse as plist or YAML: \(error)")
        }
    }
}

/// Attempt to read a PropertyList from a string
/// Tries plist first, then YAML if that fails
func readPlist(fromString string: String) throws -> Any? {
    // Try plist first
    do {
        return try deserialize(string.data(using: String.Encoding.utf8))
    } catch {
        // Try YAML as fallback
        do {
            return try readYaml(fromString: string)
        } catch {
            // Throw the original plist error if both fail
            throw PlistError.readError(description: "Failed to parse as plist or YAML: \(error)")
        }
    }
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
/// Writes YAML if filepath has .yaml/.yml extension, otherwise writes plist
func writePlist(_ dataObject: Any, toFile filepath: String) throws {
    if isYamlFile(filepath) {
        try writeYaml(dataObject, toFile: filepath)
        return
    }
    
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
public func plistToData(_ dataObject: Any) throws -> Data {
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

/// Attempt to convert a PropertyList object to string
/// If yamlOutput is true, returns YAML format; otherwise returns plist format
public func plistToString(_ dataObject: Any, yamlOutput: Bool = false) throws -> String {
    if yamlOutput {
        return try yamlToString(dataObject)
    } else {
        return try plistToString(dataObject)
    }
}

/// Parses a string, looking for the first thing that looks like a plist.
/// Returns two strings. The first will be a string representaion of a plist (or empty)
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
