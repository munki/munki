//
//  urls.swift
//  munki
//
//  Created by Greg Neagle on 8/15/24.
//

import Foundation

/// Uses URL to compose a url string from base url and additional relative path
func composedURLWithBase(_ baseURLString: String, adding path: String) -> String {
    let baseURL = URL(string: baseURLString)
    let composedURL = URL(string: path, relativeTo: baseURL)
    return composedURL?.absoluteString ?? ""
}

/// Returns a URL to something in a Munki repo.
/// If type is empty, returns the base URL for the Munki repo.
/// If type is one of the supported types, returns the type-specific URL.
/// If type is specified and resource is also specified, a full URL to the resource is
/// constructed and returned
func munkiRepoURL(_ type: String = "", resource: String = "") -> String? {
    // we could use composedURLWithBase, but that doesn't handle
    // URLs in the format of CGI invocations correctly, and would not
    // be consistent with the behavior of the Python version of Munki
    // So instead we'll do simple string concatenation
    // (with percent-encoding of the resource path)
    let munkiBaseURL = pref("SoftwareRepoURL") as? String ?? ""
    if type.isEmpty {
        return munkiBaseURL
    }
    let map = [
        "catalogs": "CatalogURL",
        "client_resources": "ClientResourceURL",
        "icons": "IconURL",
        "manifests": "ManifestURL",
        "pkgs": "PackageURL",
    ]
    guard let encodedType = (type as NSString).addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) else {
        // encoding failed
        return nil
    }
    // we're not actually handling errors in percent-encoding
    var typeURL = munkiBaseURL + "/" + encodedType + "/"
    // if a more specific URL has been defined in preferences, use that
    if let key = map[type] {
        if let testURL = pref(key) as? String,
           !testURL.isEmpty
        {
            // add a trailing slash if needed
            if testURL.hasSuffix("/") || testURL.hasSuffix("?") {
                typeURL = testURL
            } else {
                typeURL = testURL + "/"
            }
        }
    }
    if resource.isEmpty {
        return typeURL
    }
    if let encodedResource = (resource as NSString).addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) {
        return typeURL + encodedResource
    }
    // encoding failed
    return nil
}
