//
//  analyzeTests.swift
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

struct itemInInstallInfoTests {
    let installInfo: [PlistDict] = [
        ["name": "Firefox",
         "installed": true,
         "installed_version": "100.0"],
        ["name": "GoogleChrome",
         "version_to_install": "200.0"],
    ]

    /// Tests that given item is *not* in the list as expected
    @Test func itemIsNotInInstallInfo() async throws {
        let item: PlistDict = ["name": "NotAnApp"]
        #expect(itemInInstallInfo(item, theList: installInfo) == false)
    }

    /// Tests that given item *is*  in the list as expected
    @Test func itemIsInInstallInfo() async throws {
        let item: PlistDict = ["name": "Firefox"]
        #expect(itemInInstallInfo(item, theList: installInfo) == true)
    }

    /// Tests that the given item is in the list as the same version or higher as expected
    @Test func itemInInstallInfoIsSameOrNewer() async throws {
        let testVersion = "98.0"
        let item: PlistDict = ["name": "Firefox", "version": testVersion]
        #expect(itemInInstallInfo(item, theList: installInfo, version: testVersion) == true)
    }

    /// Tests that the given item is in the list but is a lower version as expected
    @Test func itemInInstallInfoIsNotSameOrNewer() async throws {
        let testVersion = "101.0"
        let item: PlistDict = ["name": "Firefox", "version": testVersion]
        #expect(itemInInstallInfo(item, theList: installInfo, version: testVersion) == false)
    }

    /// Tests that the given item is in the list (as not yet installed) as the same version or higher as expected
    @Test func notInstalledItemInInstallInfoIsSameOrNewer() async throws {
        let testVersion = "199.0"
        let item: PlistDict = ["name": "GoogleChrome", "version": testVersion]
        #expect(itemInInstallInfo(item, theList: installInfo, version: testVersion) == true)
    }

    /// Tests that the given item is in the list (as not yet installed) but is a lower version as expected
    @Test func notInstalledItemInInstallInfoIsNotSameOrNewer() async throws {
        let testVersion = "201.0"
        let item: PlistDict = ["name": "GoogleChrome", "version": testVersion]
        #expect(itemInInstallInfo(item, theList: installInfo, version: testVersion) == false)
    }
}

struct isAppleItemTests {
    /// startosinstall items should return true
    @Test func startOSinstallItemReturnsTrue() async throws {
        let item: PlistDict = [
            "name": "Foo",
            "version": "1.2.3",
            "installer_type": "startosinstall",
        ]
        #expect(isAppleItem(item) == true)
    }

    /// non startosinstall items should return false
    @Test func nonStartOSinstallItemReturnsFalse() async throws {
        let item: PlistDict = [
            "name": "Foo",
            "version": "1.2.3",
            "installer_type": "",
            "installs": [
                ["CFBundleIdentifier": "com.foo.bar"],
            ],
            "receipts": [
                ["packageid": "com.foo.bar"],
            ],
        ]
        #expect(isAppleItem(item) == false)
    }

    /// Item with an apple pkg receipt should return true
    @Test func appleReceiptReturnsTrue() async throws {
        let item: PlistDict = [
            "name": "Foo",
            "version": "1.2.3",
            "receipts": [
                ["packageid": "com.apple.foo"],
            ],
        ]
        #expect(isAppleItem(item) == true)
    }

    /// Item with an installs item containing an Apple bundle identifier should return true
    @Test func appleInstallsItemReturnsTrue() async throws {
        let item: PlistDict = [
            "name": "Foo",
            "version": "1.2.3",
            "installs": [
                ["CFBundleIdentifier": "com.apple.bar"],
            ],
            "receipts": [
                ["packageid": "com.foo.bar"],
            ],
        ]
        #expect(isAppleItem(item) == true)
    }
}

struct alreadyProcessedTests {
    let installInfo: PlistDict = [
        "managed_installs": [
            ["name": "Firefox",
             "installed": true,
             "installed_version": "100.0"],
            ["name": "GoogleChrome",
             "version_to_install": "200.0"],
        ],
        "optional_installs": ["Slack", "Zoom"],
    ]

    /// Tests that alreadyProcessed() returns expected results
    @Test func itemInInstallInfoAsExepcted() async throws {
        #expect(alreadyProcessed("Firefox", installInfo: installInfo, sections: ["managed_installs", "optional_installs"]) == true)
        #expect(alreadyProcessed("Firefox", installInfo: installInfo, sections: ["managed_installs"]) == true)
        #expect(alreadyProcessed("GoogleChrome", installInfo: installInfo, sections: ["managed_installs"]) == true)
        #expect(alreadyProcessed("Slack", installInfo: installInfo, sections: ["managed_installs"]) == false)
        #expect(alreadyProcessed("Firefox", installInfo: installInfo, sections: ["optional_installs"]) == false)
        #expect(alreadyProcessed("Slack", installInfo: installInfo, sections: ["optional_installs"]) == true)
        #expect(alreadyProcessed("Zoom", installInfo: installInfo, sections: ["optional_installs"]) == true)
        #expect(alreadyProcessed("Zoom", installInfo: installInfo, sections: ["managed_uninstalls"]) == false)
    }
}
