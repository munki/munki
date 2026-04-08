//
//  fileUtilsTests.swift
//  munki
//
//  Created by Greg Neagle on 10/22/25.
//
//  Licensed under the Apache License, Version 2.0 (the "License");
//  you may not use this file except in compliance with the License.
//  You may obtain a copy of the License at
//
//       https://www.apache.org/licenses/LICENSE-2.0
//
//  Unless required by applicable law or agreed to in writing, software
//  distributed under the License is distributed on an "AS IS" BASIS,
//  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
//  See the License for the specific language governing permissions and
//  limitations under the License.

import Testing

struct pathExistsTests {
    @Test func nonExistentPathReturnsFalse() {
        #expect(!pathExists("/non/existent/path"))
    }

    @Test func existingPathReturnsTrue() {
        #expect(pathExists("/"))
    }
}

struct fileTypeTests {
    @Test func nonExistentPathReturnsNil() {
        #expect(fileType("/non/existent/path") == nil)
    }

    @Test func directoryReturnsExpected() {
        #expect(fileType("/") == FileAttributeType.typeDirectory.rawValue)
    }

    @Test func regularFileReturnsExpected() {
        #expect(fileType(#file) == FileAttributeType.typeRegular.rawValue)
    }

    @Test func symlinkReturnsExpected() throws {
        let testDirectoryPath = try #require(
            TempDir.shared.path, "Can't get temp directory path"
        )
        try #require(
            try? FileManager.default.createSymbolicLink(
                atPath: testDirectoryPath + "/symlink_test",
                withDestinationPath: testDirectoryPath
            ),
            "Can't create test symlink"
        )
        #expect(
            fileType(testDirectoryPath + "/symlink_test") == FileAttributeType.typeSymbolicLink.rawValue
        )
    }
}

struct pathIsDirectoryTests {
    @Test func directoryReturnsTrue() throws {
        let testDirectoryPath = try #require(
            TempDir.shared.path, "Can't get temp directory path"
        )
        #expect(pathIsDirectory(testDirectoryPath))
    }

    @Test func fileReturnsFalse() throws {
        let testDirectoryPath = try #require(
            TempDir.shared.path, "Can't get temp directory path"
        )
        try #require(
            FileManager.default.createFile(
                atPath: testDirectoryPath + "/test1.txt", contents: nil, attributes: nil
            ) != false,
            "Can't create test file"
        )
        #expect(!pathIsDirectory(testDirectoryPath + "/test1.txt"))
    }

    @Test func absoluteSymlinkToDirectoryTests() throws {
        let testDirectoryPath = try #require(
            TempDir.shared.path, "Can't get temp directory path"
        )
        try #require(
            try? FileManager.default.createSymbolicLink(
                atPath: testDirectoryPath + "/symlink_with_absolute_path",
                withDestinationPath: testDirectoryPath
            ),
            "Can't create test symlink"
        )
        #expect(
            !pathIsDirectory(testDirectoryPath + "/symlink_with_absolute_path")
        )
        #expect(
            pathIsDirectory(
                testDirectoryPath + "/symlink_with_absolute_path",
                followSymlinks: true
            )
        )
    }

    @Test func relativeSymlinkToDirectoryTests() throws {
        let testDirectoryPath = try #require(
            TempDir.shared.path, "Can't get temp directory path"
        )
        try #require(
            try? FileManager.default.createSymbolicLink(
                atPath: testDirectoryPath + "/symlink_with_relative_path",
                withDestinationPath: ".."
            ),
            "Can't create test symlink"
        )
        #expect(
            !pathIsDirectory(testDirectoryPath + "/symlink_with_relative_path")
        )
        #expect(
            pathIsDirectory(
                testDirectoryPath + "/symlink_with_relative_path",
                followSymlinks: true
            )
        )
    }

    @Test func relativeSymlinkToFileReturnsFalse() throws {
        let testDirectoryPath = try #require(
            TempDir.shared.path, "Can't get temp directory path"
        )
        try #require(
            FileManager.default.createFile(
                atPath: testDirectoryPath + "/test2.txt", contents: nil, attributes: nil
            ) != false,
            "Can't create test file"
        )
        try #require(
            try? FileManager.default.createSymbolicLink(
                atPath: testDirectoryPath + "/symlink_with_relative_path_pointing_to_file",
                withDestinationPath: "test2.txt"
            ),
            "Can't create test symlink"
        )
        #expect(
            !pathIsDirectory(
                testDirectoryPath + "/symlink_with_relative_path_pointing_to_file",
                followSymlinks: true
            )
        )
    }

    @Test func nonExistentPathReturnsFalse() {
        #expect(!pathIsDirectory("/this/path/does/not/exist"))
    }

    @Test func symlinkWithNonExistentTargetReturnsFalse() throws {
        let testDirectoryPath = try #require(TempDir.shared.path, "Can't get temp directory path")
        try #require(
            try? FileManager.default.createSymbolicLink(
                atPath: testDirectoryPath + "/symlink_with_non_existent_target",
                withDestinationPath: "./does_not_exist"
            ),
            "Can't create test symlink"
        )
        #expect(
            !pathIsDirectory(
                testDirectoryPath + "/symlink_with_non_existent_target",
                followSymlinks: true
            )
        )
    }
}

struct pathIsRegularFileTests {
    @Test func nonExistantPathReturnsFalse() {
        #expect(!pathIsRegularFile("/this/path/does/not/exist"))
    }

    @Test func directoryReturnsFalse() throws {
        #expect(!pathIsRegularFile("/"))
    }

    @Test func regularFileReturnsTrue() throws {
        let testDirectoryPath = try #require(
            TempDir.shared.path, "Can't get temp directory path"
        )
        try #require(
            FileManager.default.createFile(
                atPath: testDirectoryPath + "/test3.txt", contents: nil, attributes: nil
            ) != false,
            "Can't create test file"
        )
        #expect(pathIsRegularFile(testDirectoryPath + "/test3.txt"))
    }

    @Test func symlinkReturnsFalse() throws {
        let testDirectoryPath = try #require(
            TempDir.shared.path, "Can't get temp directory path"
        )
        try #require(
            FileManager.default.createFile(
                atPath: testDirectoryPath + "/test4.txt", contents: nil, attributes: nil
            ) != false,
            "Can't create test file"
        )
        try #require(
            try? FileManager.default.createSymbolicLink(
                atPath: testDirectoryPath + "/symlink_pointing_to_file",
                withDestinationPath: "test4.txt"
            ),
            "Can't create test symlink"
        )
        #expect(!pathIsRegularFile(testDirectoryPath + "/symlink_pointing_to_file"))
    }
}

struct baseNameTests {
    @Test func absolutePathReturnsExpected() {
        #expect(baseName("/tmp/foo") == "foo")
    }

    @Test func relativePathReturnsExpected() {
        #expect(baseName("tmp/foo") == "foo")
    }

    @Test func urlReturnsExpected() {
        #expect(baseName("https://example.com/bar") == "bar")
    }

    @Test func rootReturnsExpected() {
        #expect(baseName("/") == "/")
    }
}

struct dirNameTests {
    @Test func absolutePathReturnsExpected() {
        #expect(dirName("/tmp/foo") == "/tmp")
    }

    @Test func relativePathReturnsExpected() {
        #expect(dirName("tmp/foo") == "tmp")
    }

    @Test func rootReturnsExpected() {
        #expect(dirName("/") == "/")
    }

    @Test func noDirectoryReturnsEmpty() {
        #expect(dirName("foo") == "")
    }
}

struct verifyPathOwnershipAndPermissionsTests {
    // / is owned by root, has group wheel, and is not world-writable
    @Test func filesystemRootIsTrue() {
        #expect(verifyPathOwnershipAndPermissions("/") == true)
    }

    // /private/tmp is world-writable
    @Test func tmpDirIsFalse() {
        #expect(verifyPathOwnershipAndPermissions("/private/tmp") == false)
    }
}
