//
//  fetchTests.swift
//  munkiCLItesting
//
//  Created by Greg Neagle on 12/23/25.
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

struct headerDictFromListTests {
    /// Test basic splitting a string into header name and value
    @Test func parsesAuthHeader() async throws {
        let headers = ["Authorization: Basic foobarbaz"]
        let headerDict = headerDictFromList(headers)
        #expect(headerDict["Authorization"] == "Basic foobarbaz")
    }

    /// Test string with no colon seperator
    @Test func ignoresBadlyFormattedString() async throws {
        let headers = ["Authorization Basic foobarbaz"]
        let headerDict = headerDictFromList(headers)
        // headerDict should contain only a value for User-Agent and nothing else
        #expect(headerDict == ["User-Agent": DEFAULT_USER_AGENT])
    }

    /// Ensure extra spaces after the colon are trimmed
    @Test func parsesAuthHeaderWithExtraWhitespace() async throws {
        let headers = ["Authorization:    Basic foobarbaz"]
        let headerDict = headerDictFromList(headers)
        #expect(headerDict["Authorization"] == "Basic foobarbaz")
    }

    /// Tests for issue in https://github.com/munki/munki/issues/1296/
    @Test func parsesValueContainingColon() async throws {
        let headers = ["Referer: https://foo.com"]
        let headerDict = headerDictFromList(headers)
        #expect(headerDict["Referer"] == "https://foo.com")
    }
}
