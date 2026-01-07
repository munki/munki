//
//  MunkiURL.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 7/12/25.
//  Copyright © 2025-2026 The Munki Project. All rights reserved.
//

import Foundation

/// Defines some constants for the standard Munki URLs for the default sidebar items and pages
enum MunkiURL: String {
    case software = "munki://category-all"
    case categories = "munki://categories"
    case myItems = "munki://myitems"
    case updates = "munki://updates"
}

/// "Normalizes" several string formats into a standard munki:// URL
func munkiURL(from urlString: String) -> String {
    let basename = (urlString as NSString).lastPathComponent
    return "munki://" + ((basename as NSString).deletingPathExtension)
}

/// Returns true if string appears to be a MunkiURL
func isMunkiURL(_ str: String) -> Bool {
    return str.hasPrefix("munki://")
}

/// Returns the page name given a munki:// URL
func pageNameFromMunkiURL(_ url: String) -> String? {
    if !isMunkiURL(url) {
        return nil
    }
    let munkiURL = munkiURL(from: url)
    let basename = (munkiURL as NSString).lastPathComponent
    if basename.isEmpty {
        return nil
    }
    return basename + ".html"
}
