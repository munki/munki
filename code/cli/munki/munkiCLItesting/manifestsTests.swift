//
//  manifestsTests.swift
//  munkiCLItesting
//
//  Created by Greg Neagle on 12/23/25.
//

import Testing

struct manifestsTests {
    /// Test that we can read a (plist) manifest file
    @Test func manifestDataReturnsExpectedDict() async throws {
        let manifestPath = try #require(
            TestingResource.path(for: "test_manifest.plist"),
            "Could not get path for test manifest"
        )
        let manifest = manifestData(manifestPath)
        #expect(manifest != nil)
        #expect(manifest!.isEmpty == false)
        #expect(manifest!["catalogs"] as? [String] == ["testing", "production"])
        #expect(manifest!["managed_installs"] as? [String] == ["Firefox", "GoogleChrome"])
    }
    
    /// Test that getManifestValue gets the expected values from a manifest file
    @Test func getManifestValueReturnsExpectedValue() async throws {
        let manifestPath = try #require(
            TestingResource.path(for: "test_manifest.plist"),
            "Could not get path for test manifest"
        )
        #expect(getManifestValue(manifestPath, forKey: "catalogs") as? [String] == ["testing", "production"])
        #expect(getManifestValue(manifestPath, forKey: "managed_installs") as? [String] == ["Firefox", "GoogleChrome"])
        #expect(getManifestValue(manifestPath, forKey: "managed_uninstalls") as? [String] == nil)
    }
}
