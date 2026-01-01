//
//  versionutils.swift
//  munki
//
//  Created by Greg Neagle on 7/2/24.
//  Functions for comparing version strings
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

import Foundation

/// Class to compare two version strings in a consistent way
/// Originally based on Python's distutils.version.LooseVersion
/// The intention is for version comparisons to be the same as
/// the Python version of Munki
struct MunkiVersion: Equatable, Comparable {
    let value: String

    init(_ str: String) {
        value = str
    }

    /// pads version strings by adding extra ".0"s to one if needed
    static func pad(_ a: String, count: Int) -> String {
        var components = a.split(separator: ".", omittingEmptySubsequences: true)
        while components.count < count {
            components.append("0")
        }
        return components.joined(separator: ".")
    }

    /// compares two version strings and returns a ComparisonResult
    static func compare(_ lhs: String, _ rhs: String) -> ComparisonResult {
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

/// Trims all lone trailing zeros in the version string after
/// major/minor.
///
/// Examples:
///   10.0.0.0 -> 10.0
///   10.0.0.1 -> 10.0.0.1
///   10.0.0-abc1 -> 10.0.0-abc1
///   10.0.0-abc1.0 -> 10.0.0-abc1
func trimVersionString(_ version: String) -> String {
    var parts = version.components(separatedBy: ".")
    while parts.count > 2, parts.last == "0" {
        parts.removeLast()
    }
    return parts.joined(separator: ".")
}
