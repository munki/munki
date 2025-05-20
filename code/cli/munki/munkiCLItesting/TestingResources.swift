//
//  TestingResources.swift
//  GCSMiddlewareTests
//
//  Created by Greg Neagle on 5/20/25.
//

import Foundation

/// We use this to find bundled testing resources (files used as fixtures)
class TestingResource {
    /// Return a file URL for a bundled test file
    static func url(for resource: String) -> URL? {
        let name = (resource as NSString).deletingPathExtension
        let ext = (resource as NSString).pathExtension
        return Bundle(for: self).url(forResource: name, withExtension: ext)
    }

    /// Return a path for a bundled test file
    static func path(for resource: String) -> String? {
        let name = (resource as NSString).deletingPathExtension
        let ext = (resource as NSString).pathExtension
        return Bundle(for: self).path(forResource: name, ofType: ext)
    }
}
