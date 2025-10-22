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

struct fileUtilsTests {
    @Test func pathIsDirectoryTests() throws {
        // setup
        let testDirectoryPath = try #require(TempDir.shared.path, "Can't get temp directory path")
        try #require(
            FileManager.default.createFile(
                atPath: testDirectoryPath + "/test.txt", contents: nil, attributes: nil
            ) != false,
            "Can't create test file"
        )
        try #require(
            try? FileManager.default.createSymbolicLink(
                atPath: testDirectoryPath + "/symlink",
                withDestinationPath: testDirectoryPath
            ),
            "Can't create test symlink"
        )
        #expect(pathIsDirectory(testDirectoryPath))
        #expect(!pathIsDirectory(testDirectoryPath + "/test.txt"))
        #expect(!pathIsDirectory(testDirectoryPath + "/symlink"))
        #expect(pathIsDirectory(testDirectoryPath + "/symlink", followSymlinks: true))
    }
}
