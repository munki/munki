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
