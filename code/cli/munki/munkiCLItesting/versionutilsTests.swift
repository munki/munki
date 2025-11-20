//
//  versionutilsTests.swift
//  munki
//
//  Created by Greg Neagle on 5/3/25.
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

struct MunkiVersionTests {
    /// Two versions, differing only by the number of appended ".0"s should compare as equal
    @Test func versionsCompareEqual() async throws {
        let version1 = MunkiVersion("1.0")
        let version2 = MunkiVersion("1.0.0.0")
        #expect(version1 == version2)
    }

    /// Test that less-than comparison is numeric and not alpha
    @Test func versionsCompareFoo() async throws {
        let version1 = MunkiVersion("1.2")
        let version2 = MunkiVersion("1.10")
        #expect(version1 < version2)
    }
}

struct trimVersionStringTests {
    /// trimVersionString:
    /// Trims all lone trailing zeros in the version string after
    /// major/minor.
    ///
    /// Examples:
    ///   10.0.0.0 -> 10.0
    ///   10.0.0.1 -> 10.0.0.1
    ///   10.0.0-abc1 -> 10.0.0-abc1
    ///   10.0.0-abc1.0 -> 10.0.0-abc1
    @Test func removesExtraZeros() async throws {
        #expect(trimVersionString("10.0.0.0") == "10.0")
        #expect(trimVersionString("10.0.0.1") == "10.0.0.1")
        #expect(trimVersionString("10.0.0-abc1") == "10.0.0-abc1")
        #expect(trimVersionString("10.0.0-abc1.0") == "10.0.0-abc1")
    }
}
