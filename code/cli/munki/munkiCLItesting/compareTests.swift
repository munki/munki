//
//  compareTests.swift
//  munkiCLItesting
//
//  Created by Greg Neagle on 5/4/25.
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

struct compareVersionsTests {
    /// Test "obvious" .same, .older, .newer functionality
    @Test func checkSameOlderNewer() async throws {
        #expect(compareVersions("10.15", "10.15.0") == .same)
        #expect(compareVersions("10.15", "10.15.1") == .older)
        #expect(compareVersions("10.15.1", "10.15") == .newer)
    }
}

struct compareUsingVersionScriptTests {
    /// if version_script returns the same version as the item version, compareUsingVersionScript should return .same
    @Test func scriptSameVersionReturnSame() async throws {
        let item: PlistDict = [
            "name": "Foo",
            "version": "1.2.3",
            "version_script": """
            #!/bin/sh
            echo "1.2.3.0"
            """,
        ]
        #expect(await compareUsingVersionScript(item) == .same)
    }

    /// if version_script returns a higher version than the item version, compareUsingVersionScript should return .newer
    @Test func scriptHigherVersionReturnsNewer() async throws {
        let item: PlistDict = [
            "name": "Foo",
            "version": "1.2.3",
            "version_script": """
            #!/bin/sh
            echo "1.2.30"
            """,
        ]
        #expect(await compareUsingVersionScript(item) == .newer)
    }

    /// if version_script returns a lower version than the item version, compareUsingVersionScript should return .older
    @Test func scriptLowerVersionReturnsOlder() async throws {
        let item: PlistDict = [
            "name": "Foo",
            "version": "1.2.3",
            "version_script": """
            #!/bin/sh
            echo "1.2"
            """,
        ]
        #expect(await compareUsingVersionScript(item) == .older)
    }

    /// if version_script returns empty result, compareUsingVersionScript should return .notPresent
    @Test func scriptWithEmptyResultReturnsNotPresent() async throws {
        let item: PlistDict = [
            "name": "Foo",
            "version": "1.2.3",
            "version_script": """
            #!/bin/sh
            echo ""
            """,
        ]
        #expect(await compareUsingVersionScript(item) == .notPresent)
    }

    /// if version_script exits non-zero, compareUsingVersionScript should return .notPresent
    @Test func scriptWithErrorReturnsNotPresent() async throws {
        let item: PlistDict = [
            "name": "Foo",
            "version": "1.2.3",
            "version_script": """
            #!/bin/sh
            exit 1
            """,
        ]
        #expect(await compareUsingVersionScript(item) == .notPresent)
    }
}

struct comparePlistVersionTests {
    var testInfoPath: String

    init() {
        testInfoPath = TestingResource.path(for: "test_info.plist") ?? ""
    }

    @Test func comparePlistVersionWithLowerVersionReturnsNewer() throws {
        try #require(!testInfoPath.isEmpty, "Could not get path for test info plist")
        let item: PlistDict = [
            "path": testInfoPath,
            "CFBundleShortVersionString": "1.0",
        ]
        #expect(try comparePlistVersion(item) == .newer)
    }

    @Test func comparePlistVersionWithHigherVersionReturnsOlder() throws {
        try #require(!testInfoPath.isEmpty, "Could not get path for test info plist")
        let item: PlistDict = [
            "path": testInfoPath,
            "CFBundleShortVersionString": "100.0",
        ]
        #expect(try comparePlistVersion(item) == .older)
    }

    @Test func comparePlistVersionWithSameVersionReturnsSame() throws {
        try #require(!testInfoPath.isEmpty, "Could not get path for test info plist")
        let item: PlistDict = [
            "path": testInfoPath,
            "CFBundleShortVersionString": "7.0.5.5403",
        ]
        #expect(try comparePlistVersion(item) == .same)
    }

    @Test func comparePlistVersionWithAlternateVersionKey() throws {
        try #require(!testInfoPath.isEmpty, "Could not get path for test info plist")
        let item: PlistDict = [
            "path": testInfoPath,
            "CFBundleVersion": "5403",
            "version_comparison_key": "CFBundleVersion",
        ]
        #expect(try comparePlistVersion(item) == .same)
    }
}
