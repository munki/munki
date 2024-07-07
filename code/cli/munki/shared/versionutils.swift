//
//  versionutils.swift
//  munki
//
//  Created by Greg Neagle on 7/2/24.
//  Functions for comparing version strings

import Foundation


struct MunkiVersion: Equatable, Comparable {
    // Class to compare two version strings in a consistent way
    // Originally based on Python's distutils.version.LooseVersion
    // The intention is for version comparisons to be the same as
    // the Python version of Munki
    
    let value: String
    
    init(_ str: String) {
        value = str
    }
    
    static func pad(_ a: String, count: Int) -> String {
        // pads version strings by adding extra ".0"s to one if needed
        var components = a.split(separator: ".", omittingEmptySubsequences: true)
        while components.count < count {
            components.append("0")
        }
        return components.joined(separator: ".")
    }
    
    static func compare(_ lhs: String, _ rhs: String) -> ComparisonResult {
        // compares two version strings and returns a ComparisonResult
        let maxCount = max(lhs.count, rhs.count)
        let a = pad(lhs, count: maxCount)
        let b = pad(rhs, count: maxCount)
        return a.compare(b, options: .numeric)
    }
    
    static func < (lhs: MunkiVersion, rhs: MunkiVersion) -> Bool {
        return compare(lhs.value, rhs.value) == .orderedAscending
    }
    
    static func > (lhs: MunkiVersion, rhs: MunkiVersion) -> Bool {
        return compare(lhs.value, rhs.value) == .orderedDescending
    }
    
    static func == (lhs: MunkiVersion, rhs: MunkiVersion) -> Bool {
        return compare(lhs.value, rhs.value) == .orderedSame
    }
}


func trimVersionString(_ version: String) -> String {
    // Trims all lone trailing zeros in the version string after
    // major/minor.
    //
    // Examples:
    //   10.0.0.0 -> 10.0
    //   10.0.0.1 -> 10.0.0.1
    //   10.0.0-abc1 -> 10.0.0-abc1
    //   10.0.0-abc1.0 -> 10.0.0-abc1
    var parts = version.components(separatedBy: ".")
    while parts.count > 2 && parts.last == "0" {
        parts.removeLast()
    }
    return parts.joined(separator: ".")
}
