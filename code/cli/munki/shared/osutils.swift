//
//  osutils.swift
//  munki
//
//  Created by Greg Neagle on 7/2/24.
//

import Foundation

func getOSVersion(onlyMajorMinor: Bool = true) -> String {
    let version = ProcessInfo().operatingSystemVersion
    if onlyMajorMinor {
        return "\(version.majorVersion).\(version.minorVersion)"
    } else {
        return "\(version.majorVersion).\(version.minorVersion).\(version.patchVersion)"
    }
}
