//
//  plistutilsTests.swift
//  munkiCLItesting
//
//  Created by Greg Neagle on 12/24/25.
//
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

private let PLIST_STRING_WITH_TABS = """
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
\t<key>catalogs</key>
\t<array>
\t\t<string>production</string>
\t</array>
\t<key>included_manifests</key>
\t<array/>
\t<key>managed_installs</key>
\t<array>
\t\t<string>Firefox</string>
\t</array>
\t<key>managed_uninstalls</key>
\t<array>
\t\t<string>GoogleChrome</string>
\t</array>
</dict>
</plist>
"""

private let PLIST_DICT: PlistDict = [
    "catalogs": ["production"],
    "included_manifests": [],
    "managed_installs": ["Firefox"],
    "managed_uninstalls": ["GoogleChrome"],
]

struct readPlistTests {
    /// Test that we can read a known plist from a file
    @Test func readPlistFromFileReturnsExpected() async throws {
        let manifestPath = try #require(
            TestingResource.path(for: "test_manifest.plist"),
            "Could not get path for test manifest"
        )
        let plist = try #require(
            readPlist(fromFile: manifestPath) as? PlistDict,
            "Could not read test manifest"
        )
        #expect(!plist.isEmpty)
        #expect(plist["catalogs"] as? [String] == ["testing", "production"])
        #expect(plist["managed_installs"] as? [String] == ["Firefox", "GoogleChrome"])
        #expect(plist["managed_uninstalls"] as? [String] == nil)
    }

    /// Test that we parse a plist from a string with expected results
    @Test func readPlistFromStringReturnsExpected() async throws {
        let plist = try #require(
            readPlist(fromString: PLIST_STRING_WITH_TABS) as? PlistDict,
            "Could not parse test manifest string"
        )
        #expect(!plist.isEmpty)
        #expect(plist["catalogs"] as? [String] == ["production"])
        #expect(plist["included_manifests"] as? [String] == [])
        #expect(plist["managed_installs"] as? [String] == ["Firefox"])
        #expect(plist["managed_uninstalls"] as? [String] == ["GoogleChrome"])
    }
}

struct writePlistTests {
    /// Test that we can correctly write plist data to a file
    @Test func writePlistCreatesExpectedFile() async throws {
        let filepath = tempFile()
        let unwrappedFilepath = try #require(filepath, "Can't create temporary filepath")
        try #require(
            try? writePlist(PLIST_DICT, toFile: unwrappedFilepath),
            "Failed to write plist to file"
        )
        #expect(FileManager.default.fileExists(atPath: unwrappedFilepath))
        let plist = try #require(
            readPlist(fromFile: unwrappedFilepath) as? PlistDict,
            "Could not read test manifest"
        )
        #expect(!plist.isEmpty)
        #expect(plist["catalogs"] as? [String] == ["production"])
        #expect(plist["included_manifests"] as? [String] == [])
        #expect(plist["managed_installs"] as? [String] == ["Firefox"])
        #expect(plist["managed_uninstalls"] as? [String] == ["GoogleChrome"])
    }
}

struct plistToStringTests {
    /// Test that converting a PlistDict to a string produces the expected result
    @Test func returnsExpected() async throws {
        let convertedPlist = try #require(
            try? plistToString(PLIST_DICT),
            "Failed to convert plist data to string format"
        )
        #expect(convertedPlist.trailingNewlineTrimmed == PLIST_STRING_WITH_TABS.trailingNewlineTrimmed)
    }
}

struct parseFirstPlistTests {
    /// Test that we can find the first plist in a string that also contains non-plist lines
    @Test func returnsExpected() async throws {
        let notPlistText = "This is not a plist.\n"
        let testText = notPlistText + PLIST_STRING_WITH_TABS + notPlistText
        let (parsed, remainingText) = parseFirstPlist(fromString: testText)
        #expect(parsed.trailingNewlineTrimmed == PLIST_STRING_WITH_TABS.trailingNewlineTrimmed)
        #expect(remainingText == notPlistText)
    }
}
