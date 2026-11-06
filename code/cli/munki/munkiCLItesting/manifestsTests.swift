//
//  manifestsTests.swift
//  munkiCLItesting
//
//  Created by Greg Neagle on 12/23/25.
//

import Testing

@Suite(.serialized)
struct manifestsTests {
    @Test func prepareManifestDestinationReplacesCachedManifestFile() throws {
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

        let manifestPath = manifestDirectory + "/child"
        #expect(prepareManifestDestination(manifestPath, cacheRoot: testDirectoryPath))
        #expect(pathIsDirectory(manifestDirectory))
    }

    @Test func prepareManifestDestinationReplacesCachedAncestorManifest() throws {
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

        let manifestPath = manifestDirectory + "/child"
        #expect(prepareManifestDestination(manifestPath, cacheRoot: testDirectoryPath))
        #expect(pathIsDirectory(manifestDirectory))
    }

    @Test func prepareManifestDestinationReplacesParentSymlink() throws {
        let testDirectoryPath = try #require(
            TempDir.shared.path, "Can't get temp directory path"
        )
        let targetPath = testDirectoryPath + "/target-directory-\(UUID().uuidString)"
        let manifestDirectory = testDirectoryPath + "/manifest-link-\(UUID().uuidString)"
        let targetContents = targetPath + "/preserved"
        try FileManager.default.createDirectory(
            atPath: targetPath, withIntermediateDirectories: false
        )
        try #require(
            FileManager.default.createFile(atPath: targetContents, contents: nil),
            "Can't create file in symlink target"
        )
        try FileManager.default.createSymbolicLink(
            atPath: manifestDirectory, withDestinationPath: targetPath
        )

        let manifestPath = manifestDirectory + "/child"
        #expect(prepareManifestDestination(manifestPath, cacheRoot: testDirectoryPath))
        #expect(pathIsDirectory(manifestDirectory))
        #expect(!pathIsSymlink(manifestDirectory))
        #expect(pathIsRegularFile(targetContents))
    }

    @Test func prepareManifestDestinationRemovesCachedDirectory() throws {
        let testDirectoryPath = try #require(
            TempDir.shared.path, "Can't get temp directory path"
        )
        let manifestPath = testDirectoryPath + "/manifest-directory-\(UUID().uuidString)"
        let cachedChildPath = manifestPath + "/cached-child"
        try FileManager.default.createDirectory(
            atPath: manifestPath, withIntermediateDirectories: false
        )
        try #require(
            FileManager.default.createFile(
                atPath: cachedChildPath,
                contents: Data("cached manifest".utf8),
                attributes: nil
            ),
            "Can't create cached child manifest"
        )

        #expect(prepareManifestDestination(manifestPath, cacheRoot: testDirectoryPath))
        #expect(!pathExists(manifestPath))
        #expect(
            FileManager.default.createFile(
                atPath: manifestPath,
                contents: Data("new parent manifest".utf8),
                attributes: nil
            )
        )
        #expect(pathIsRegularFile(manifestPath))
    }

    @Test func prepareManifestDestinationPreservesCachedManifestFile() throws {
        let testDirectoryPath = try #require(
            TempDir.shared.path, "Can't get temp directory path"
        )
        let manifestPath = testDirectoryPath + "/cached-manifest-\(UUID().uuidString)"
        let contents = Data("cached manifest".utf8)
        try #require(
            FileManager.default.createFile(
                atPath: manifestPath, contents: contents, attributes: nil
            ),
            "Can't create cached manifest"
        )

        #expect(prepareManifestDestination(manifestPath, cacheRoot: testDirectoryPath))
        #expect(try Data(contentsOf: URL(fileURLWithPath: manifestPath)) == contents)
    }

    @Test func prepareManifestDestinationReplacesFinalSymlink() throws {
        let testDirectoryPath = try #require(
            TempDir.shared.path, "Can't get temp directory path"
        )
        let targetPath = testDirectoryPath + "/target-file-\(UUID().uuidString)"
        let manifestPath = testDirectoryPath + "/manifest-link-\(UUID().uuidString)"
        try #require(
            FileManager.default.createFile(atPath: targetPath, contents: nil),
            "Can't create symlink target"
        )
        try FileManager.default.createSymbolicLink(
            atPath: manifestPath, withDestinationPath: targetPath
        )

        #expect(prepareManifestDestination(manifestPath, cacheRoot: testDirectoryPath))
        #expect(!pathExists(manifestPath))
        #expect(pathIsRegularFile(targetPath))
    }

    @Test func prepareManifestDestinationReplacesDanglingSymlink() throws {
        let testDirectoryPath = try #require(
            TempDir.shared.path, "Can't get temp directory path"
        )
        let missingTargetPath = testDirectoryPath + "/missing-\(UUID().uuidString)"
        let manifestPath = testDirectoryPath + "/manifest-link-\(UUID().uuidString)"
        try FileManager.default.createSymbolicLink(
            atPath: manifestPath, withDestinationPath: missingTargetPath
        )

        #expect(prepareManifestDestination(manifestPath, cacheRoot: testDirectoryPath))
        #expect(!pathIsSymlink(manifestPath))
        #expect(!pathExists(manifestPath))
        #expect(!pathExists(missingTargetPath))
    }

    @Test func prepareManifestDestinationRejectsCacheRoot() throws {
        let testDirectoryPath = try #require(
            TempDir.shared.path, "Can't get temp directory path"
        )

        #expect(!prepareManifestDestination(testDirectoryPath, cacheRoot: testDirectoryPath))
        #expect(pathIsDirectory(testDirectoryPath))
    }

    @Test func prepareManifestDestinationRejectsPathOutsideCache() throws {
        let testDirectoryPath = try #require(
            TempDir.shared.path, "Can't get temp directory path"
        )
        let cacheRoot = testDirectoryPath + "/cache-\(UUID().uuidString)"
        let outsidePath = testDirectoryPath + "/outside-\(UUID().uuidString)"
        try FileManager.default.createDirectory(
            atPath: cacheRoot, withIntermediateDirectories: false
        )
        try FileManager.default.createDirectory(
            atPath: outsidePath, withIntermediateDirectories: false
        )

        #expect(!prepareManifestDestination(outsidePath, cacheRoot: cacheRoot))
        #expect(pathIsDirectory(outsidePath))
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

    /// Writes manifests to a temp directory and adds them to the Manifests
    /// cache so getManifest() returns them without contacting a server.
    /// Returns a dictionary of manifest names to local paths.
    private func cacheTestManifests(_ manifests: [String: PlistDict]) throws -> [String: String] {
        let testDirectoryPath = try #require(
            TempDir.shared.path, "Can't get temp directory path"
        )
        let manifestDirectory = testDirectoryPath + "/manifests-\(UUID().uuidString)"
        try FileManager.default.createDirectory(
            atPath: manifestDirectory, withIntermediateDirectories: true
        )
        var paths = [String: String]()
        for (name, manifest) in manifests {
            let manifestPath = manifestDirectory + "/" + name
            try writePlist(manifest, toFile: manifestPath)
            Manifests.shared.set(name, path: manifestPath)
            paths[name] = manifestPath
        }
        return paths
    }

    /// Removes test manifests from the Manifests cache
    private func uncacheTestManifests(_ names: [String]) {
        for name in names {
            Manifests.shared.delete(name)
        }
    }

    /// Test that a manifest that includes itself is processed without
    /// recursing forever
    @Test func manifestIncludingItselfIsSkipped() async throws {
        let paths = try cacheTestManifests([
            "circularA": [
                "included_manifests": ["circularA"],
                "featured_items": ["ItemA"],
            ],
        ])
        defer { uncacheTestManifests(Array(paths.keys)) }
        let manifestPath = try #require(paths["circularA"])

        // via a manifest file, as for included manifests
        var installInfo = PlistDict()
        try await processManifest(
            atPath: manifestPath,
            forKey: "featured_items",
            installInfo: &installInfo,
            parentCatalogs: ["testing"]
        )
        #expect(installInfo["featured_items"] as? [String] == ["ItemA"])

        // via manifest data, as for the primary manifest
        let manifestdata = try #require(manifestData(manifestPath))
        installInfo = PlistDict()
        try await processManifest(
            manifestdata,
            forKey: "featured_items",
            installInfo: &installInfo,
            parentCatalogs: ["testing"],
            manifestName: "circularA"
        )
        #expect(installInfo["featured_items"] as? [String] == ["ItemA"])
    }

    /// Test that manifests that include each other are processed without
    /// recursing forever
    @Test func manifestsIncludingEachOtherAreSkipped() async throws {
        let paths = try cacheTestManifests([
            "circularA": [
                "included_manifests": ["circularB"],
                "featured_items": ["ItemA"],
            ],
            "circularB": [
                "included_manifests": ["circularA"],
                "featured_items": ["ItemB"],
            ],
        ])
        defer { uncacheTestManifests(Array(paths.keys)) }
        let manifestPath = try #require(paths["circularA"])

        var installInfo = PlistDict()
        try await processManifest(
            atPath: manifestPath,
            forKey: "featured_items",
            installInfo: &installInfo,
            parentCatalogs: ["testing"]
        )
        let featuredItems = installInfo["featured_items"] as? [String] ?? []
        #expect(Set(featuredItems) == ["ItemA", "ItemB"])
    }

    /// Test that a conditional item that includes the manifest it is in is
    /// processed without recursing forever
    @Test func conditionalItemIncludingItsManifestIsSkipped() async throws {
        let conditionalItem: PlistDict = [
            "condition": "TRUEPREDICATE",
            "included_manifests": ["circularA"],
            "featured_items": ["ConditionalItem"],
        ]
        let paths = try cacheTestManifests([
            "circularA": [
                "conditional_items": [conditionalItem],
                "featured_items": ["ItemA"],
            ],
        ])
        // TRUEPREDICATE doesn't need real machine facts, so provide
        // placeholder info rather than gathering it from this machine
        let savedPredicateInfo = PredicateInfo.shared.info
        PredicateInfo.shared.info = ["os_vers": "test"]
        defer {
            PredicateInfo.shared.info = savedPredicateInfo
            uncacheTestManifests(Array(paths.keys))
        }
        let manifestPath = try #require(paths["circularA"])

        var installInfo = PlistDict()
        try await processManifest(
            atPath: manifestPath,
            forKey: "featured_items",
            installInfo: &installInfo,
            parentCatalogs: ["testing"]
        )
        let featuredItems = installInfo["featured_items"] as? [String] ?? []
        #expect(Set(featuredItems) == ["ItemA", "ConditionalItem"])
    }

    /// Test that nested included manifests are all processed, including a
    /// manifest included from more than one place (not a circular reference)
    @Test func nestedIncludedManifestsAreProcessed() async throws {
        let paths = try cacheTestManifests([
            "top": [
                "included_manifests": ["left", "right"],
            ],
            "left": [
                "included_manifests": ["shared"],
                "featured_items": ["LeftItem"],
            ],
            "right": [
                "included_manifests": ["shared"],
                "featured_items": ["RightItem"],
            ],
            "shared": [
                "featured_items": ["SharedItem"],
            ],
        ])
        defer { uncacheTestManifests(Array(paths.keys)) }
        let manifestPath = try #require(paths["top"])

        var installInfo = PlistDict()
        try await processManifest(
            atPath: manifestPath,
            forKey: "featured_items",
            installInfo: &installInfo,
            parentCatalogs: ["testing"]
        )
        let featuredItems = installInfo["featured_items"] as? [String] ?? []
        #expect(Set(featuredItems) == ["LeftItem", "RightItem", "SharedItem"])
    }
}
