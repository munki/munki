//
//  pkginfolib.swift
//  munki
//
//  Created by Greg Neagle on 7/2/24.
//  functions used by makepkginfo to create pkginfo files

import Foundation

func pkginfoMetadata() -> PlistDict {
    // Helps us record  information about the environment in which the pkginfo was
    // created so we have a bit of an audit trail. Returns a dictionary.
    var metadata = PlistDict()
    metadata["created_by"] = NSUserName()
    metadata["creation_date"] = Date()
    metadata["munki_version"] = getVersion()
    metadata["os_version"] = getOSVersion(onlyMajorMinor: false)
    return metadata
}
