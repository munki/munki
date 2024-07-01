//
//  utils.swift
//  managedsoftwareupdate
//
//  Created by Greg Neagle on 6/25/24.
//

import Foundation

func getVersion() -> String {
    // TODO: actually read this from a file
    // or figure out a way to update this at build time
    return "0.0.1"
}

func parseFirstPlist(fromString str: String) -> (String, String) {
    // Parses a string, looking for the first thing that looks like a plist.
    // Returns two strings. The first will be a string representaion of a plist (or empty)
    // The second is any characters remaining after the found plist
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
    return(plistStr, remainder)
}

