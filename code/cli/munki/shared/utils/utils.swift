//
//  utils.swift
//  managedsoftwareupdate
//
//  Created by Greg Neagle on 6/25/24.
//
//  Copyright 2024 Greg Neagle.
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

/// Returns version of Munki tools
func getVersion() -> String {
    return CLI_TOOLS_VERSION
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
