//
//  yamlutils.swift
//  munki
//
//  Created by Rod Christiansen on 10/5/25.
//
//  Copyright 2025 The Munki Project
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

// MARK: - Type-Flexible String Extraction

/// Extract a string value from a dictionary, handling multiple YAML types.
/// This allows clean YAML files without quote requirements for version-like values.
///
/// YAML parsers may interpret unquoted values differently:
///   - `version: 10.13` → Double (10.13)
///   - `version: 2025.12.25.1308` → String (multiple dots)
///   - `version: '10.13'` → String
///   - `version: 14` → Int
///
/// This function handles all cases by trying String first, then converting
/// numeric types to strings with appropriate formatting.
///
/// Usage:
///   ```swift
///   // Instead of: item["minimum_os_version"] as? String
///   // Use: getString(from: item, forKey: "minimum_os_version")
///   ```
func getString(from dict: [String: Any], forKey key: String) -> String? {
    guard let value = dict[key] else { return nil }
    
    // Try String first (most common case)
    if let stringValue = value as? String {
        return stringValue.isEmpty ? nil : stringValue
    }
    
    // Handle Double (e.g., 10.13 parsed as float)
    if let doubleValue = value as? Double {
        // Format to remove trailing zeros: 14.0 -> "14", 10.12 -> "10.12"
        return String(format: "%.10g", doubleValue)
    }
    
    // Handle Int (e.g., version: 14)
    if let intValue = value as? Int {
        return String(intValue)
    }
    
    // Handle Bool (unlikely for versions but be safe)
    if let boolValue = value as? Bool {
        return String(boolValue)
    }
    
    // Fallback: try to convert using String(describing:)
    let described = String(describing: value)
    return described.isEmpty ? nil : described
}

/// Convenience extension on Dictionary for cleaner syntax
extension Dictionary where Key == String, Value == Any {
    /// Get a string value, automatically converting numeric types to strings.
    /// This allows YAML files to omit quotes on version-like values.
    func stringValue(forKey key: String) -> String? {
        return getString(from: self, forKey: key)
    }
}

enum YamlError: Error {
    case readError(description: String)
    case writeError(description: String)
}

// MARK: - Custom Key Ordering for pkginfo YAML output

/// Keys that should appear first in pkginfo YAML output, in this order
private let priorityKeys = ["name", "display_name", "version"]

/// Keys that should appear last in pkginfo YAML output
private let lastKeys = ["_metadata"]

/// Keys that indicate a receipt entry dictionary
private let receiptKeys: Set<String> = ["packageid", "installed_size", "version", "filename", "name", "optional"]

/// Preferred key order for receipt entries - packageid first for readability
private let receiptKeyOrder = ["packageid", "name", "filename", "installed_size", "version", "optional"]

/// Keys that indicate an installs item dictionary
private let installsKeys: Set<String> = ["path", "type", "CFBundleIdentifier", "CFBundleShortVersionString", "CFBundleVersion", "md5checksum"]

/// Preferred key order for installs items - path first for readability
private let installsKeyOrder = ["path", "type", "CFBundleIdentifier", "CFBundleName", "CFBundleShortVersionString", "CFBundleVersion", "md5checksum", "minosversion"]

/// Keys that indicate a conditional_items entry dictionary
private let conditionalItemKeys: Set<String> = ["condition", "managed_installs", "managed_uninstalls", "managed_updates", "optional_installs", "included_manifests", "conditional_items"]

/// Preferred key order for conditional_items - condition MUST be first for readability
private let conditionalItemKeyOrder = ["condition", "managed_installs", "managed_uninstalls", "managed_updates", "optional_installs", "default_installs", "featured_items", "included_manifests", "conditional_items"]

/// Check if a dictionary looks like a receipt entry
private func isReceiptDict(_ dict: [String: Any]) -> Bool {
    // A receipt must have packageid and typically has version
    return dict.keys.contains("packageid")
}

/// Check if a dictionary looks like an installs item
private func isInstallsDict(_ dict: [String: Any]) -> Bool {
    // An installs item must have path and type
    return dict.keys.contains("path") && dict.keys.contains("type")
}

/// Check if a dictionary looks like a conditional_items entry (manifest conditional block)
private func isConditionalItemDict(_ dict: [String: Any]) -> Bool {
    // A conditional item typically has "condition" key, or has manifest list keys without name/version
    // Check for condition key first (most reliable indicator)
    if dict.keys.contains("condition") {
        return true
    }
    // Also detect conditional items without explicit condition (unconditional blocks in conditional_items array)
    // These have manifest keys but no pkginfo keys like name, version, display_name
    let hasManifestKeys = dict.keys.contains { conditionalItemKeys.contains($0) }
    let hasPkginfoKeys = dict.keys.contains("name") || dict.keys.contains("version") || dict.keys.contains("installer_item_location")
    return hasManifestKeys && !hasPkginfoKeys
}

/// Sort conditional_items dictionary keys with condition first
private func sortConditionalItemKeys(_ keys: [String]) -> [String] {
    var orderedKeys: [String] = []
    var otherKeys: [String] = []
    
    for key in keys {
        if conditionalItemKeyOrder.contains(key) {
            orderedKeys.append(key)
        } else {
            otherKeys.append(key)
        }
    }
    
    // Sort ordered keys by their position in conditionalItemKeyOrder array
    orderedKeys.sort { 
        (conditionalItemKeyOrder.firstIndex(of: $0) ?? 999) < (conditionalItemKeyOrder.firstIndex(of: $1) ?? 999)
    }
    
    // Sort other keys alphabetically
    otherKeys.sort()
    
    return orderedKeys + otherKeys
}

/// Sort receipt dictionary keys with packageid first
private func sortReceiptKeys(_ keys: [String]) -> [String] {
    var orderedKeys: [String] = []
    var otherKeys: [String] = []
    
    for key in keys {
        if receiptKeyOrder.contains(key) {
            orderedKeys.append(key)
        } else {
            otherKeys.append(key)
        }
    }
    
    // Sort ordered keys by their position in receiptKeyOrder array
    orderedKeys.sort { 
        (receiptKeyOrder.firstIndex(of: $0) ?? 999) < (receiptKeyOrder.firstIndex(of: $1) ?? 999)
    }
    
    // Sort other keys alphabetically
    otherKeys.sort()
    
    return orderedKeys + otherKeys
}

/// Sort installs item dictionary keys with path first
private func sortInstallsKeys(_ keys: [String]) -> [String] {
    var orderedKeys: [String] = []
    var otherKeys: [String] = []
    
    for key in keys {
        if installsKeyOrder.contains(key) {
            orderedKeys.append(key)
        } else {
            otherKeys.append(key)
        }
    }
    
    // Sort ordered keys by their position in installsKeyOrder array
    orderedKeys.sort { 
        (installsKeyOrder.firstIndex(of: $0) ?? 999) < (installsKeyOrder.firstIndex(of: $1) ?? 999)
    }
    
    // Sort other keys alphabetically
    otherKeys.sort()
    
    return orderedKeys + otherKeys
}

/// Sort pkginfo dictionary keys with custom ordering:
/// - name, display_name, version appear first (in that order)
/// - _metadata appears last
/// - All other keys appear alphabetically in between
func sortPkginfoKeys(_ keys: [String]) -> [String] {
    var firstKeys: [String] = []
    var middleKeys: [String] = []
    var endKeys: [String] = []
    
    for key in keys {
        if priorityKeys.contains(key) {
            firstKeys.append(key)
        } else if lastKeys.contains(key) {
            endKeys.append(key)
        } else {
            middleKeys.append(key)
        }
    }
    
    // Sort first keys by their position in priorityKeys array
    firstKeys.sort { priorityKeys.firstIndex(of: $0)! < priorityKeys.firstIndex(of: $1)! }
    
    // Sort middle keys alphabetically
    middleKeys.sort()
    
    // Sort end keys alphabetically (in case we add more lastKeys in the future)
    endKeys.sort()
    
    return firstKeys + middleKeys + endKeys
}

/// Sort dictionary keys based on the dictionary's apparent type
private func sortKeysForDict(_ dict: [String: Any]) -> [String] {
    if isReceiptDict(dict) {
        return sortReceiptKeys(Array(dict.keys))
    } else if isInstallsDict(dict) {
        return sortInstallsKeys(Array(dict.keys))
    } else if isConditionalItemDict(dict) {
        return sortConditionalItemKeys(Array(dict.keys))
    } else {
        return sortPkginfoKeys(Array(dict.keys))
    }
}

/// Convert a value to a Yams Node, recursively handling dictionaries with custom key ordering
private func toNode(_ value: Any) -> Node {
    switch value {
    case is NSNull:
        // Return an empty/null node - this shouldn't normally happen if we filter properly
        return Node("")
    case let string as String:
        // Check for null sentinel first
        if string == "__YAML_NULL_SENTINEL__" {
            return Node("")
        }
        return Node(string)
    case let dict as [String: Any]:
        // Sort keys using context-aware ordering (receipts, installs, or pkginfo)
        let sortedKeys = sortKeysForDict(dict)
        var pairs: [(Node, Node)] = []
        for dictKey in sortedKeys {
            if let val = dict[dictKey] {
                // Skip NSNull values and null sentinels - don't include them in YAML output
                if val is NSNull {
                    continue
                }
                if let str = val as? String, str == "__YAML_NULL_SENTINEL__" {
                    continue
                }
                pairs.append((Node(dictKey), toNode(val)))
            }
        }
        return Node(pairs, .implicit, .block)
    case let array as [Any]:
        // Filter out null sentinels
        let filtered = array.filter { item in
            if item is NSNull { return false }
            if let str = item as? String, str == "__YAML_NULL_SENTINEL__" { return false }
            return true
        }
        let nodes = filtered.map { toNode($0) }
        return Node(nodes, .implicit, .block)
    case let int as Int:
        return Node(String(int), .implicit, .any)
    case let double as Double:
        return Node(String(double), .implicit, .any)
    case let bool as Bool:
        return Node(bool ? "true" : "false", .implicit, .any)
    case let date as Date:
        let formatter = ISO8601DateFormatter()
        return Node(formatter.string(from: date))
    case let data as Data:
        return Node(data.base64EncodedString())
    default:
        let desc = String(describing: value)
        // Last check for null-like values
        if desc == "<null>" || desc == "nil" || desc == "null" {
            return Node("")
        }
        return Node(desc)
    }
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
func isYamlFile(_ filepath: String) -> Bool {
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

/// Attempt to write YAML to a file with custom key ordering for pkginfo
func writeYaml(_ dataObject: Any, toFile filepath: String) throws {
    do {
        let sanitizedData = sanitizeForYaml(dataObject)
        let node = toNode(sanitizedData)
        let yamlString = try Yams.serialize(node: node, 
                                           indent: 2,
                                           width: -1, 
                                           allowUnicode: true)
        try yamlString.write(toFile: filepath, atomically: true, encoding: String.Encoding.utf8)
    } catch {
        throw YamlError.writeError(description: "Failed to write YAML to \(filepath): \(error)")
    }
}

/// Check if a value represents null (NSNull or nil-equivalent)
private func isNullValue(_ value: Any) -> Bool {
    if value is NSNull {
        return true
    }
    // Check for other null representations
    let mirror = Mirror(reflecting: value)
    if mirror.displayStyle == .optional && mirror.children.isEmpty {
        return true
    }
    // Check string representation as last resort
    let desc = String(describing: value)
    if desc == "<null>" || desc == "nil" {
        return true
    }
    return false
}

/// Clean floating-point numbers that are very close to simpler decimal representations
/// This prevents values like 26.2 from being serialized as 26.199999999999999
private func cleanFloatingPoint(_ value: Double) -> Any {
    // If it's actually an integer, return as Int
    if value == Double(Int(value)) {
        return Int(value)
    }
    
    // Try rounding to 1-4 decimal places and see if we're very close
    for decimals in 1...4 {
        let multiplier = pow(10.0, Double(decimals))
        let rounded = round(value * multiplier) / multiplier
        let epsilon = pow(10.0, Double(-(decimals + 6))) // Very small tolerance
        
        if abs(value - rounded) < epsilon {
            return rounded
        }
    }
    
    // If no clean representation found, return the original value
    return value
}

/// Sanitize data object for YAML serialization by converting NSNumber, NSString, etc. to native Swift types
func sanitizeForYaml(_ object: Any) -> Any {
    // First check for null values using our comprehensive check
    if isNullValue(object) {
        // Return a sentinel that we filter out - but this should rarely happen
        // as we filter nulls at the dictionary/array level
        return "__YAML_NULL_SENTINEL__"
    }
    
    switch object {
    case is NSNull:
        // NSNull represents a null value - return sentinel to filter out
        return "__YAML_NULL_SENTINEL__"
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
            return cleanFloatingPoint(Double(nsNumber.floatValue))
        case "d":       // double
            return cleanFloatingPoint(nsNumber.doubleValue)
        default:
            // Fallback: try to determine if it's an integer or floating point
            if nsNumber.doubleValue == Double(nsNumber.intValue) {
                return nsNumber.intValue
            } else {
                return cleanFloatingPoint(nsNumber.doubleValue)
            }
        }
    case let nsString as NSString:
        return nsString as String
    case let nsArray as NSArray:
        // Filter out NSNull values and sentinels from arrays
        return nsArray.compactMap { item -> Any? in
            if isNullValue(item) { return nil }
            let sanitized = sanitizeForYaml(item)
            if let str = sanitized as? String, str == "__YAML_NULL_SENTINEL__" { return nil }
            return sanitized
        }
    case let nsDictionary as NSDictionary:
        var result: [String: Any] = [:]
        for (key, value) in nsDictionary {
            // Skip NSNull values and null-like values - don't include them in output
            if isNullValue(value) { continue }
            let sanitizedValue = sanitizeForYaml(value)
            // Also skip if sanitization returned the null sentinel
            if let str = sanitizedValue as? String, str == "__YAML_NULL_SENTINEL__" { continue }
            // Skip empty strings - they serialize ambiguously in YAML and get interpreted as null
            if let str = sanitizedValue as? String, str.isEmpty { continue }
            if let stringKey = key as? String {
                result[stringKey] = sanitizedValue
            } else if let stringKey = sanitizeForYaml(key) as? String {
                result[stringKey] = sanitizedValue
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
        // Filter out NSNull values and sentinels from arrays
        return array.compactMap { item -> Any? in
            if isNullValue(item) { return nil }
            let sanitized = sanitizeForYaml(item)
            if let str = sanitized as? String, str == "__YAML_NULL_SENTINEL__" { return nil }
            return sanitized
        }
    case let dictionary as [String: Any]:
        var result: [String: Any] = [:]
        for (key, value) in dictionary {
            // Skip NSNull values and null-like values
            if isNullValue(value) { continue }
            let sanitizedValue = sanitizeForYaml(value)
            if let str = sanitizedValue as? String, str == "__YAML_NULL_SENTINEL__" { continue }
            // Skip empty strings - they serialize ambiguously in YAML and get interpreted as null
            if let str = sanitizedValue as? String, str.isEmpty { continue }
            result[key] = sanitizedValue
        }
        return result
    case let dictionary as [AnyHashable: Any]:
        var result: [String: Any] = [:]
        for (key, value) in dictionary {
            // Skip NSNull values and null-like values
            if isNullValue(value) { continue }
            let sanitizedValue = sanitizeForYaml(value)
            if let str = sanitizedValue as? String, str == "__YAML_NULL_SENTINEL__" { continue }
            // Skip empty strings - they serialize ambiguously in YAML and get interpreted as null
            if let str = sanitizedValue as? String, str.isEmpty { continue }
            if let stringKey = key as? String {
                result[stringKey] = sanitizedValue
            } else if let stringKey = "\(key)" as String? {
                result[stringKey] = sanitizedValue
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
        
        // Check for null-like values one more time (in case our isNullValue check missed something)
        if objectString == "<null>" || objectString == "nil" || objectString == "null" {
            return "__YAML_NULL_SENTINEL__"
        }
        
        // Only log warning for truly unexpected types (not null-related)
        let typeString = String(describing: objectType)
        if !typeString.contains("Null") && !typeString.contains("null") {
            print("WARNING: Converting unrecognized object type \(objectType) to string: \(objectString)")
        }
        
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

/// Attempt to convert a data object to YAML string with custom key ordering for pkginfo
func yamlToString(_ dataObject: Any) throws -> String {
    do {
        let sanitizedData = sanitizeForYaml(dataObject)
        let node = toNode(sanitizedData)
        return try Yams.serialize(node: node, 
                                 indent: 2,
                                 width: -1, 
                                 allowUnicode: true)
    } catch {
        throw YamlError.writeError(description: "Failed to convert to YAML string: \(error)")
    }
}

/// Attempt to convert YAML string to Data
func yamlToData(_ dataObject: Any) throws -> Data {
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
func readMixedFormatFile(fromFile filepath: String, preferYaml: Bool = false) throws -> Any? {
    let data = try Data(contentsOf: URL(fileURLWithPath: filepath))
    return try readData(data, preferYaml: preferYaml, filepath: filepath)
}

/// Attempt to read data that could be either plist or YAML format
/// Uses dual-parsing approach: tries preferred format first, falls back to other format
func readData(_ data: Data, preferYaml: Bool = false, filepath: String? = nil) throws -> Any? {
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
func isLikelyYamlContent(_ content: String) -> Bool {
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
func detectFileContent(fromFile filepath: String, preferYaml: Bool = false) throws -> Any? {
    let content = try String(contentsOfFile: filepath, encoding: .utf8)
    let likelyYaml = isLikelyYamlContent(content)
    
    // Use content detection to influence parsing preference
    let shouldTryYamlFirst = preferYaml || likelyYaml
    
    let data = content.data(using: .utf8) ?? Data()
    return try readData(data, preferYaml: shouldTryYamlFirst, filepath: filepath)
}
