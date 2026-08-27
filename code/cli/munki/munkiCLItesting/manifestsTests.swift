//
//  manifestsTests.swift
//  munkiCLItesting
//
//  Created by Greg Neagle on 12/23/25.
//

import Testing

@Suite(.serialized)
struct manifestsTests {
    @Test func prepareManifestDirectoryReplacesCachedManifestFile() throws {
        let testDirectoryPath = try #require(
            TempDir.shared.path, "Can't get temp directory path"
        )
        let manifestDirectory = testDirectoryPath + "/manifest-file-\(UUID().uuidString)"
        try #require(
            FileManager.default.createFile(
                atPath: manifestDirectory,
                contents: Data("cached manifest".utf8),
                attributes: nil
            ),
            "Can't create cached manifest file"
        )

        #expect(prepareManifestDirectory(manifestDirectory, cacheRoot: testDirectoryPath))
        #expect(pathIsDirectory(manifestDirectory))
    }

    @Test func prepareManifestDirectoryReplacesCachedAncestorManifest() throws {
        let testDirectoryPath = try #require(
            TempDir.shared.path, "Can't get temp directory path"
        )
        let ancestorPath = testDirectoryPath + "/ancestor-file-\(UUID().uuidString)"
        let manifestDirectory = ancestorPath + "/nested/manifest"
        try #require(
            FileManager.default.createFile(
                atPath: ancestorPath,
                contents: Data("cached manifest".utf8),
                attributes: nil
            ),
            "Can't create cached ancestor manifest"
        )

        #expect(prepareManifestDirectory(manifestDirectory, cacheRoot: testDirectoryPath))
        #expect(pathIsDirectory(manifestDirectory))
    }

    @Test func prepareManifestDirectoryDoesNotRemoveSymlink() throws {
        let testDirectoryPath = try #require(
            TempDir.shared.path, "Can't get temp directory path"
        )
        let targetPath = testDirectoryPath + "/target-file-\(UUID().uuidString)"
        let manifestDirectory = testDirectoryPath + "/manifest-link-\(UUID().uuidString)"
        try #require(
            FileManager.default.createFile(
                atPath: targetPath, contents: nil, attributes: nil
            ),
            "Can't create symlink target"
        )
        try FileManager.default.createSymbolicLink(
            atPath: manifestDirectory, withDestinationPath: targetPath
        )

        #expect(!prepareManifestDirectory(manifestDirectory, cacheRoot: testDirectoryPath))
        #expect(pathIsSymlink(manifestDirectory))
    }

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
