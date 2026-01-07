//
//  FoundationPlist.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 5/27/18.
//  Copyright © 2018-2026 The Munki Project. All rights reserved.
//

import Foundation

enum FoundationPlistError: Error {
    case readError(description: String)
    case writeError(description: String)
}

func deserialize(_ data: Data?) throws -> Any? {
    if data != nil {
        do {
            let dataObject = try PropertyListSerialization.propertyList(
                from: data!,
                options: PropertyListSerialization.MutabilityOptions.mutableContainers,
                format: nil)
            return dataObject
        } catch {
            throw FoundationPlistError.readError(description: "\(error)")
        }
    }
    return nil
}

func readPlist(_ filepath: String) throws -> Any? {
    return try deserialize(NSData(contentsOfFile: filepath) as Data?)
}

func readPlistFromString(_ stringData: String) throws -> Any? {
    return try deserialize(stringData.data(using: String.Encoding.utf8))
}

func serialize(_ plist: Any) throws -> Data {
    do {
        let plistData = try PropertyListSerialization.data(
            fromPropertyList: plist,
            format: PropertyListSerialization.PropertyListFormat.xml,
            options: 0)
        return plistData
    } catch {
        throw FoundationPlistError.writeError(description: "\(error)")
    }
}

func writePlist(_ dataObject: Any, toFile filepath: String) throws {
    do {
        let data = try serialize(dataObject) as NSData
        if !(data.write(toFile: filepath, atomically: true)) {
            throw FoundationPlistError.writeError(description: "write failed")
        }
    } catch {
        throw FoundationPlistError.writeError(description: "\(error)")
    }
}

func writePlistToString(_ dataObject: Any) throws -> String {
    do {
        let data = try serialize(dataObject)
        return String(data: data, encoding: String.Encoding.utf8)!
    } catch {
        throw FoundationPlistError.writeError(description: "\(error)")
    }
}
