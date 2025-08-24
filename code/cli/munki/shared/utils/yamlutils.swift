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
func isYamlFile(_ filepath: String) -> Bool {
    let fileExtension = (filepath as NSString).pathExtension.lowercased()
    return fileExtension == "yaml" || fileExtension == "yml"
}

/// Attempt to read YAML from a file
func readYaml(fromFile filepath: String) throws -> Any? {
    do {
        let yamlString = try String(contentsOfFile: filepath, encoding: .utf8)
        return try Yams.load(yaml: yamlString)
    } catch {
        throw YamlError.readError(description: "Failed to read YAML from \(filepath): \(error)")
    }
}

/// Attempt to read YAML from data
func readYaml(fromData data: Data) throws -> Any? {
    do {
        let yamlString = String(data: data, encoding: .utf8) ?? ""
        return try Yams.load(yaml: yamlString)
    } catch {
        throw YamlError.readError(description: "Failed to parse YAML data: \(error)")
    }
}

/// Attempt to read YAML from a string
func readYaml(fromString string: String) throws -> Any? {
    do {
        return try Yams.load(yaml: string)
    } catch {
        throw YamlError.readError(description: "Failed to parse YAML string: \(error)")
    }
}

/// Attempt to write YAML to a file
func writeYaml(_ dataObject: Any, toFile filepath: String) throws {
    do {
        let yamlString = try Yams.dump(object: dataObject, 
                                      indent: 2,
                                      width: -1, 
                                      allowUnicode: true)
        try yamlString.write(toFile: filepath, atomically: true, encoding: String.Encoding.utf8)
    } catch {
        throw YamlError.writeError(description: "Failed to write YAML to \(filepath): \(error)")
    }
}

/// Attempt to convert a data object to YAML string
func yamlToString(_ dataObject: Any) throws -> String {
    do {
        return try Yams.dump(object: dataObject, 
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
