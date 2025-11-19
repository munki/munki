//
//  yamlutils.swift
//  munki
//
//  Created by Greg Neagle on 6/20/25.
//
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
import Yams

enum YamlError: Error {
    case readError(description: String)
    case writeError(description: String)
}

extension YamlError: LocalizedError {
    var errorDescription: String? {
        switch self {
        case let .readError(description):
            return description
        case let .writeError(description):
            return description
        }
    }
}

/// Check if a file path has a YAML extension
public func isYamlFile(_ filepath: String) -> Bool {
    let fileExtension = (filepath as NSString).pathExtension.lowercased()
    return fileExtension == "yaml" || fileExtension == "yml"
}

/// Attempt to read YAML from a file
func readYaml(fromFile filepath: String) throws -> Any? {
    do {
        let yamlString = try String(contentsOfFile: filepath, encoding: .utf8)
        let parsed = try Yams.load(yaml: yamlString)
        return normalizeYamlTypes(parsed)
    } catch {
        throw YamlError.readError(description: "Failed to read YAML from \(filepath): \(error)")
    }
}

/// Normalize YAML parsed data to ensure version strings are strings, not floats
/// This prevents the common mistake of writing unquoted version numbers like:
///   minimum_os_version: 10.12  (becomes float 10.12)
/// Instead of:
///   minimum_os_version: '10.12'  (string "10.12")
///
/// Without this normalization, the version check in catalogs.swift would fail:
///   if let minimumOSVersion = item["minimum_os_version"] as? String
/// The cast would return nil for a float, silently bypassing the OS version check.
///
/// This ensures version-related fields are always strings, matching munki's expectations.
func normalizeYamlTypes(_ object: Any?) -> Any? {
    guard let object = object else { return nil }
    
    // Known keys that should always be strings, even if they look like numbers
    let stringKeys: Set<String> = [
        "minimum_os_version",
        "maximum_os_version", 
        "minimum_munki_version",
        "minimum_update_version",
        "version",
        "installer_item_version",
        "installed_version",
        "product_version"
    ]
    
    if let dict = object as? [String: Any] {
        var normalized: [String: Any] = [:]
        for (key, value) in dict {
            // Convert numeric values to strings for version-related keys
            if stringKeys.contains(key) {
                if let floatValue = value as? Double {
                    // Convert float to string, preserving precision
                    // Remove trailing zeros: 14.0 -> "14", 10.12 -> "10.12"
                    let formatted = String(format: "%.10g", floatValue)
                    normalized[key] = formatted
                } else if let intValue = value as? Int {
                    normalized[key] = String(intValue)
                } else if let stringValue = value as? String {
                    normalized[key] = stringValue
                } else {
                    normalized[key] = normalizeYamlTypes(value)
                }
            } else {
                normalized[key] = normalizeYamlTypes(value)
            }
        }
        return normalized
    } else if let array = object as? [Any] {
        return array.map { normalizeYamlTypes($0) }
    } else {
        return object
    }
}


/// Attempt to read YAML from data
func readYaml(fromData data: Data) throws -> Any? {
    do {
        let yamlString = String(data: data, encoding: .utf8) ?? ""
        let parsed = try Yams.load(yaml: yamlString)
        return normalizeYamlTypes(parsed)
    } catch {
        throw YamlError.readError(description: "Failed to parse YAML data: \(error)")
    }
}

/// Attempt to read YAML from a string
func readYaml(fromString string: String) throws -> Any? {
    do {
        let parsed = try Yams.load(yaml: string)
        return normalizeYamlTypes(parsed)
    } catch {
        throw YamlError.readError(description: "Failed to parse YAML string: \(error)")
    }
}

/// Attempt to write YAML to a file
func writeYaml(_ dataObject: Any, toFile filepath: String) throws {
    do {
        let sanitizedData = sanitizeForYaml(dataObject)
        let yamlString = try Yams.dump(object: sanitizedData, 
                                      indent: 2,
                                      width: -1, 
                                      allowUnicode: true)
        try yamlString.write(toFile: filepath, atomically: true, encoding: String.Encoding.utf8)
    } catch {
        throw YamlError.writeError(description: "Failed to write YAML to \(filepath): \(error)")
    }
}

/// Sanitize data object for YAML serialization by converting NSNumber, NSString, etc. to native Swift types
func sanitizeForYaml(_ object: Any) -> Any {
    switch object {
    case let nsNumber as NSNumber:
        // Handle boolean values first
        if nsNumber === kCFBooleanTrue {
            return true
        }
        if nsNumber === kCFBooleanFalse {
            return false
        }
        
        // Get the underlying CFNumber type to determine how to convert
        let objCType = String(cString: nsNumber.objCType)
        
        // Handle different numeric types
        switch objCType {
        case "c", "C":  // char/unsigned char (often used for booleans)
            return nsNumber.intValue != 0
        case "s", "S":  // short/unsigned short
            return nsNumber.intValue
        case "i", "I":  // int/unsigned int
            return nsNumber.intValue
        case "l", "L":  // long/unsigned long
            return nsNumber.intValue
        case "q", "Q":  // long long/unsigned long long
            return nsNumber.intValue
        case "f":       // float
            return nsNumber.floatValue
        case "d":       // double
            return nsNumber.doubleValue
        default:
            // Fallback: try to determine if it's an integer or floating point
            if nsNumber.doubleValue == Double(nsNumber.intValue) {
                return nsNumber.intValue
            } else {
                return nsNumber.doubleValue
            }
        }
    case let nsString as NSString:
        return nsString as String
    case let nsArray as NSArray:
        return nsArray.map { sanitizeForYaml($0) }
    case let nsDictionary as NSDictionary:
        var result: [String: Any] = [:]
        for (key, value) in nsDictionary {
            if let stringKey = key as? String {
                result[stringKey] = sanitizeForYaml(value)
            } else if let stringKey = sanitizeForYaml(key) as? String {
                result[stringKey] = sanitizeForYaml(value)
            }
        }
        return result
    case let nsDate as NSDate:
        // Convert NSDate to ISO 8601 string
        let formatter = ISO8601DateFormatter()
        return formatter.string(from: nsDate as Date)
    case let date as Date:
        // Convert Date to ISO 8601 string
        let formatter = ISO8601DateFormatter()
        return formatter.string(from: date)
    case let nsData as NSData:
        // Convert NSData to base64 string
        return nsData.base64EncodedString()
    case let data as Data:
        // Convert Data to base64 string
        return data.base64EncodedString()
    case let array as [Any]:
        return array.map { sanitizeForYaml($0) }
    case let dictionary as [String: Any]:
        var result: [String: Any] = [:]
        for (key, value) in dictionary {
            result[key] = sanitizeForYaml(value)
        }
        return result
    case let dictionary as [AnyHashable: Any]:
        var result: [String: Any] = [:]
        for (key, value) in dictionary {
            if let stringKey = key as? String {
                result[stringKey] = sanitizeForYaml(value)
            } else if let stringKey = "\(key)" as String? {
                result[stringKey] = sanitizeForYaml(value)
            }
        }
        return result
    case is String, is Int, is Double, is Float, is Bool:
        // Basic Swift types that YAML can handle natively
        return object
    default:
        // Handle any unrecognized object by converting to string representation
        // This catches Core Foundation types, custom objects, etc.
        let objectType = type(of: object)
        let objectString = String(describing: object)
        
        // Enhanced logging for debugging
        print("WARNING: Converting unrecognized object type \(objectType) to string: \(objectString)")
        
        // Check if it's a URL, file path, or other special string-like object
        if let url = object as? URL {
            return url.absoluteString
        } else if let path = object as? NSString {
            return path as String
        } else if objectString.hasPrefix("/") || objectString.contains(".") {
            // Likely a file path or similar string - just return it as a string
            return objectString
        }
        
        // Try to extract useful information from the object
        if let describable = object as? CustomStringConvertible {
            return describable.description
        } else if let debugDescribable = object as? CustomDebugStringConvertible {
            return debugDescribable.debugDescription
        } else {
            return objectString
        }
    }
}

/// Attempt to convert a data object to YAML string
func yamlToString(_ dataObject: Any) throws -> String {
    do {
        let sanitizedData = sanitizeForYaml(dataObject)
        return try Yams.dump(object: sanitizedData, 
                           indent: 2,
                           width: -1, 
                           allowUnicode: true)
    } catch {
        throw YamlError.writeError(description: "Failed to convert to YAML string: \(error)")
    }
}

/// Attempt to convert YAML string to Data
public func yamlToData(_ dataObject: Any) throws -> Data {
    do {
        let yamlString = try yamlToString(dataObject)
        guard let data = yamlString.data(using: .utf8) else {
            throw YamlError.writeError(description: "Failed to convert YAML string to data")
        }
        return data
    } catch {
        throw YamlError.writeError(description: "Failed to convert to YAML data: \(error)")
    }
}

// File Format Detection for Mixed Repositories

/// Attempt to read a file that could be either plist or YAML format
/// Uses dual-parsing approach: tries preferred format first, falls back to other format
public func readMixedFormatFile(fromFile filepath: String, preferYaml: Bool = false) throws -> Any? {
    let data = try Data(contentsOf: URL(fileURLWithPath: filepath))
    return try readData(data, preferYaml: preferYaml, filepath: filepath)
}

/// Attempt to read data that could be either plist or YAML format
/// Uses dual-parsing approach: tries preferred format first, falls back to other format
public func readData(_ data: Data, preferYaml: Bool = false, filepath: String? = nil) throws -> Any? {
    let fileDescription = filepath ?? "data"
    
    if preferYaml {
        // Try YAML first, fallback to plist
        do {
            return try readYaml(fromData: data)
        } catch {
            // YAML failed, try plist
            do {
                return try PropertyListSerialization.propertyList(from: data, options: [], format: nil)
            } catch let plistError {
                throw YamlError.readError(description: "Failed to parse \(fileDescription) as YAML or plist. YAML error: \(error). Plist error: \(plistError)")
            }
        }
    } else {
        // Try plist first, fallback to YAML
        do {
            return try PropertyListSerialization.propertyList(from: data, options: [], format: nil)
        } catch {
            // Plist failed, try YAML
            do {
                return try readYaml(fromData: data)
            } catch let yamlError {
                throw YamlError.readError(description: "Failed to parse \(fileDescription) as plist or YAML. Plist error: \(error). YAML error: \(yamlError)")
            }
        }
    }
}

/// Detect if file content is likely YAML based on content analysis
/// This is a heuristic check that looks for YAML-specific patterns
public func isLikelyYamlContent(_ content: String) -> Bool {
    let trimmed = content.trimmingCharacters(in: .whitespacesAndNewlines)
    
    // Check for YAML document separator
    if trimmed.hasPrefix("---") {
        return true
    }
    
    // Check for XML/plist header
    if trimmed.hasPrefix("<?xml") || trimmed.hasPrefix("<plist") {
        return false
    }
    
    // Look for YAML-style key-value patterns (key: value)
    // This is a simple heuristic - YAML uses colons for key-value separation
    let lines = content.components(separatedBy: .newlines).prefix(10)
    var yamlLikeLines = 0
    var xmlLikeLines = 0
    
    for line in lines {
        let trimmedLine = line.trimmingCharacters(in: .whitespaces)
        if trimmedLine.isEmpty || trimmedLine.hasPrefix("#") {
            continue // Skip empty lines and comments
        }
        
        // YAML patterns
        if trimmedLine.contains(":") && !trimmedLine.hasPrefix("<") {
            yamlLikeLines += 1
        }
        
        // XML/plist patterns
        if trimmedLine.hasPrefix("<") && trimmedLine.hasSuffix(">") {
            xmlLikeLines += 1
        }
    }
    
    // If we see more YAML-like patterns than XML-like, probably YAML
    return yamlLikeLines > xmlLikeLines
}

/// Smart content-based format detection for files without extensions
/// Reads file content and uses heuristics to determine format, then parses accordingly
public func detectFileContent(fromFile filepath: String, preferYaml: Bool = false) throws -> Any? {
    let content = try String(contentsOfFile: filepath, encoding: .utf8)
    let likelyYaml = isLikelyYamlContent(content)
    
    // Use content detection to influence parsing preference
    let shouldTryYamlFirst = preferYaml || likelyYaml
    
    let data = content.data(using: .utf8) ?? Data()
    return try readData(data, preferYaml: shouldTryYamlFirst, filepath: filepath)
}
