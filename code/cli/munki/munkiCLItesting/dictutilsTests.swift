//
//  dictutilsTests.swift
//  munkiCLItesting
//
//  Created by Greg Neagle on 6/11/26.
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

struct stringValueTests {
    let info: [String: Any] = [
        "name": "TestName",
        "display_name": "",
        "integer": 6,
    ]

    @Test func stringValueStringItemReturnsExpectedString() {
        #expect(stringValue(from: info, for: "name", fallback: "bar") == "TestName")
    }

    @Test func stringValueUndefinedItemReturnsEmptyString() async throws {
        #expect(stringValue(from: info, for: "nonexistent_key") == "")
    }

    @Test func stringValueUndefinedItemReturnsFallback() async throws {
        #expect(stringValue(from: info, for: "nonexistent_key", fallback: "TestName") == "TestName")
    }

    @Test func stringValueEmptyItemReturnsFallback() async throws {
        #expect(stringValue(from: info, for: "display_name", fallback: "TestName") == "TestName")
    }

    @Test func stringValueIntegerItemReturnsEmptyString() async throws {
        #expect(stringValue(from: info, for: "integer") == "")
    }
}

struct getStringExtensionTests {
    let info: [String: Any] = [
        "name": "TestName",
        "display_name": "",
        "integer": 6,
    ]

    @Test func getStringReturnsExpectedString() {
        #expect(info.getString(for: "name", fallback: "bar") == "TestName")
    }

    @Test func getStringUndefinedItemReturnsEmptyString() async throws {
        #expect(info.getString(for: "nonexistent_key") == "")
    }

    @Test func getStringUndefinedItemReturnsFallback() async throws {
        #expect(info.getString(for: "nonexistent_key", fallback: "TestName") == "TestName")
    }

    @Test func getStringEmptyItemReturnsFallback() async throws {
        #expect(info.getString(for: "display_name", fallback: "TestName") == "TestName")
    }

    @Test func getStringIntegerItemReturnsEmptyString() async throws {
        #expect(info.getString(for: "integer") == "")
    }
}
