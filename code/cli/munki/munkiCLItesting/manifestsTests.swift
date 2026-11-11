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

    /// Test that a primary manifest that includes itself is skipped
    /// without being processed again. The primary manifest is processed
    /// from its data under its own name, as checkForUpdates does, and is
    /// deliberately not in the Manifests cache: re-entering it would mean
    /// fetching it, which would throw here.
    @Test func primaryManifestIncludingItselfIsSkipped() async throws {
        let primary: PlistDict = [
            "included_manifests": ["selfIncludingPrimary"],
            "featured_items": ["PrimaryItem"],
        ]
        var installInfo = PlistDict()
        try await processManifest(
            primary,
            forKey: "featured_items",
            installInfo: &installInfo,
            parentCatalogs: ["testing"],
            manifestName: "selfIncludingPrimary"
        )
        #expect(installInfo["featured_items"] as? [String] == ["PrimaryItem"])
    }

    /// Test that an included manifest that includes itself is processed
    /// without recursing forever. The manifest is in the cache, so without
    /// the guard this would never return; the time limit turns that into
    /// a failure.
    @Test(.timeLimit(.minutes(1)))
    func includedManifestIncludingItselfIsSkipped() async throws {
        let paths = try cacheTestManifests([
            "selfIncluding": [
                "included_manifests": ["selfIncluding"],
                "featured_items": ["IncludedItem"],
            ],
        ])
        defer { uncacheTestManifests(Array(paths.keys)) }

        let primary: PlistDict = [
            "included_manifests": ["selfIncluding"],
            "featured_items": ["PrimaryItem"],
        ]
        var installInfo = PlistDict()
        try await processManifest(
            primary,
            forKey: "featured_items",
            installInfo: &installInfo,
            parentCatalogs: ["testing"],
            manifestName: "selfIncludingParent"
        )
        let featuredItems = installInfo["featured_items"] as? [String] ?? []
        #expect(Set(featuredItems) == ["PrimaryItem", "IncludedItem"])
    }

    /// Test that two cached manifests that include each other are each
    /// processed once. As above, a regression here would recurse forever,
    /// so the test has a time limit.
    @Test(.timeLimit(.minutes(1)))
    func cachedManifestsIncludingEachOtherAreSkipped() async throws {
        let paths = try cacheTestManifests([
            "cycleB": [
                "included_manifests": ["cycleC"],
                "featured_items": ["ItemB"],
            ],
            "cycleC": [
                "included_manifests": ["cycleB"],
                "featured_items": ["ItemC"],
            ],
        ])
        defer { uncacheTestManifests(Array(paths.keys)) }

        let primary: PlistDict = [
            "included_manifests": ["cycleB"],
            "featured_items": ["TopItem"],
        ]
        var installInfo = PlistDict()
        try await processManifest(
            primary,
            forKey: "featured_items",
            installInfo: &installInfo,
            parentCatalogs: ["testing"],
            manifestName: "top"
        )
        let featuredItems = installInfo["featured_items"] as? [String] ?? []
        #expect(Set(featuredItems) == ["TopItem", "ItemB", "ItemC"])
    }

    /// Test that a manifest that includes the primary manifest is caught
    /// on the first hop, without fetching the primary manifest again
    @Test func manifestIncludingPrimaryManifestIsSkipped() async throws {
        let paths = try cacheTestManifests([
            "mutualB": [
                "included_manifests": ["mutualA"],
                "featured_items": ["ItemB"],
            ],
        ])
        defer { uncacheTestManifests(Array(paths.keys)) }

        // mutualA is the primary manifest and is not in the cache
        let primary: PlistDict = [
            "included_manifests": ["mutualB"],
            "featured_items": ["ItemA"],
        ]
        var installInfo = PlistDict()
        try await processManifest(
            primary,
            forKey: "featured_items",
            installInfo: &installInfo,
            parentCatalogs: ["testing"],
            manifestName: "mutualA"
        )
        let featuredItems = installInfo["featured_items"] as? [String] ?? []
        #expect(Set(featuredItems) == ["ItemA", "ItemB"])
    }

    /// Test that a conditional item that includes the primary manifest is
    /// skipped without fetching the primary manifest again
    @Test func conditionalItemIncludingPrimaryManifestIsSkipped() async throws {
        let conditionalItem: PlistDict = [
            "condition": "TRUEPREDICATE",
            "included_manifests": ["conditionalPrimary"],
            "featured_items": ["ConditionalItem"],
        ]
        let primary: PlistDict = [
            "conditional_items": [conditionalItem],
            "featured_items": ["PrimaryItem"],
        ]
        // TRUEPREDICATE doesn't need real machine facts, so provide
        // placeholder info rather than gathering it from this machine.
        // This suite is serialized and is the only one using PredicateInfo.
        let savedPredicateInfo = PredicateInfo.shared.info
        PredicateInfo.shared.info = ["os_vers": "test"]
        defer { PredicateInfo.shared.info = savedPredicateInfo }

        var installInfo = PlistDict()
        try await processManifest(
            primary,
            forKey: "featured_items",
            installInfo: &installInfo,
            parentCatalogs: ["testing"],
            manifestName: "conditionalPrimary"
        )
        let featuredItems = installInfo["featured_items"] as? [String] ?? []
        #expect(Set(featuredItems) == ["PrimaryItem", "ConditionalItem"])
    }

    /// Test that nested included manifests are all processed, and that a
    /// manifest included from more than one place isn't treated as a
    /// circular reference
    @Test func nestedIncludedManifestsAreProcessed() async throws {
        let paths = try cacheTestManifests([
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

        let primary: PlistDict = [
            "included_manifests": ["left", "right"],
        ]
        var installInfo = PlistDict()
        try await processManifest(
            primary,
            forKey: "featured_items",
            installInfo: &installInfo,
            parentCatalogs: ["testing"],
            manifestName: "top"
        )
        let featuredItems = installInfo["featured_items"] as? [String] ?? []
        #expect(Set(featuredItems) == ["LeftItem", "RightItem", "SharedItem"])
    }
}
