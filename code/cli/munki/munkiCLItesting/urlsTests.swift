//
//  urlsTests.swift
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

struct composedURLWithBaseTests {
    /// Tests URL construction when base URL has trailing slash
    @Test func basicConstructsExpected() async throws {
        let baseURL = "https://munki.example.com/repo/"
        #expect(composedURLWithBase(baseURL, adding: "manifests") == "https://munki.example.com/repo/manifests")
        #expect(composedURLWithBase(baseURL, adding: "catalogs") == "https://munki.example.com/repo/catalogs")
        #expect(composedURLWithBase(baseURL, adding: "pkgs") == "https://munki.example.com/repo/pkgs")
    }

    ///  Tests URL construction when base URL is missing trailing slash
    @Test func baseWithoutTrailingSlashConstructsExpected() async throws {
        let baseURL = "https://munki.example.com/repo"
        #expect(composedURLWithBase(baseURL, adding: "manifests") == "https://munki.example.com/repo/manifests")
        #expect(composedURLWithBase(baseURL, adding: "catalogs") == "https://munki.example.com/repo/catalogs")
        #expect(composedURLWithBase(baseURL, adding: "pkgs") == "https://munki.example.com/repo/pkgs")
    }
}

struct munkiRepoURLTests {
    ///  Tests building URLs to Munki repo directories and resources
    @Test func basicContructsExpected() async throws {
        let munkiBaseURL = "https://munki.example.com/repo"
        #expect(munkiRepoURL(munkiRepoURL: munkiBaseURL) == "https://munki.example.com/repo")
        #expect(munkiRepoURL("manifests", munkiRepoURL: munkiBaseURL) == "https://munki.example.com/repo/manifests/")
        #expect(munkiRepoURL("manifests", resource: "site_default", munkiRepoURL: munkiBaseURL) == "https://munki.example.com/repo/manifests/site_default")
    }

    /// Tests building URLs to Munki repo directories and resources when base URL is a CGI-style URL
    @Test func urlWithCGIContructsExpected() async throws {
        let munkiBaseURL = "https://munki.example.com/cgi?"
        #expect(munkiRepoURL(munkiRepoURL: munkiBaseURL) == "https://munki.example.com/cgi?")
        #expect(munkiRepoURL("manifests", munkiRepoURL: munkiBaseURL) == munkiBaseURL + "manifests/")
        #expect(munkiRepoURL("manifests", resource: "site_default", munkiRepoURL: munkiBaseURL) == "https://munki.example.com/cgi?manifests/site_default")
    }

    /// Tests building URLs to Munki repo resources when base URL iwhen resource name contains a special character
    @Test func urlWithResourceWithSpecialCharacterContructsExpected() async throws {
        let munkiBaseURL = "https://munki.example.com/repo"
        #expect(munkiRepoURL("manifests", resource: "site default", munkiRepoURL: munkiBaseURL) == "https://munki.example.com/repo/manifests/site%20default")
    }
}
