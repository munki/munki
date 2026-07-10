//
//  clientcertsTests.swift
//  munkiCLItesting
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
import X509

struct dnMatchesExpectedIssuersTests {
    private func makeDN(commonName: String, organization: String) throws -> DistinguishedName {
        try DistinguishedName {
            OrganizationName(organization)
            CommonName(commonName)
        }
    }

    /// A DN advertised by the server should match, with no configured issuers
    @Test func matchesServerAdvertisedIssuer() throws {
        let dn = try makeDN(commonName: "Munki Client CA", organization: "SomeOrg")
        #expect(dnMatchesExpectedIssuers(
            dn,
            serverIssuers: [dn],
            configuredTrustedAnchorDNs: []
        ))
    }

    /// A configured issuer string should match when the server sends no CA names
    @Test func matchesConfiguredIssuerWhenServerListEmpty() throws {
        let dn = try makeDN(commonName: "Munki Client CA", organization: "SomeOrg")
        #expect(dnMatchesExpectedIssuers(
            dn,
            serverIssuers: [],
            configuredTrustedAnchorDNs: ["CN=Munki Client CA,O=SomeOrg"]
        ))
    }

    /// A configured issuer string should also match alongside server-advertised names
    @Test func matchesConfiguredIssuerAlongsideServerList() throws {
        let serverDN = try makeDN(commonName: "Other CA", organization: "OtherOrg")
        let dn = try makeDN(commonName: "Munki Client CA", organization: "SomeOrg")
        #expect(dnMatchesExpectedIssuers(
            dn,
            serverIssuers: [serverDN],
            configuredTrustedAnchorDNs: ["CN=Munki Client CA,O=SomeOrg"]
        ))
    }

    /// No match when neither server-advertised nor configured issuers match
    @Test func noMatchWhenNothingMatches() throws {
        let serverDN = try makeDN(commonName: "Other CA", organization: "OtherOrg")
        let dn = try makeDN(commonName: "Munki Client CA", organization: "SomeOrg")
        #expect(!dnMatchesExpectedIssuers(
            dn,
            serverIssuers: [serverDN],
            configuredTrustedAnchorDNs: ["CN=Some Other CA,O=SomeOrg"]
        ))
    }

    /// No match when both lists are empty
    @Test func noMatchWhenBothListsEmpty() throws {
        let dn = try makeDN(commonName: "Munki Client CA", organization: "SomeOrg")
        #expect(!dnMatchesExpectedIssuers(
            dn,
            serverIssuers: [],
            configuredTrustedAnchorDNs: []
        ))
    }

    /// Configured issuer matching is exact — order and spacing matter
    @Test func configuredIssuerMatchIsExact() throws {
        let dn = try makeDN(commonName: "Munki Client CA", organization: "SomeOrg")
        #expect(!dnMatchesExpectedIssuers(
            dn,
            serverIssuers: [],
            configuredTrustedAnchorDNs: ["O=SomeOrg,CN=Munki Client CA"]
        ))
        #expect(!dnMatchesExpectedIssuers(
            dn,
            serverIssuers: [],
            configuredTrustedAnchorDNs: ["CN=Munki Client CA, O=SomeOrg"]
        ))
    }

    /// DNs with escaped characters render and match in RFC 4514-style form
    @Test func matchesIssuerWithEscapedCharacters() throws {
        let dn = try makeDN(commonName: "Munki Client CA", organization: "SomeOrg, Inc.")
        #expect(dnMatchesExpectedIssuers(
            dn,
            serverIssuers: [],
            configuredTrustedAnchorDNs: ["CN=Munki Client CA,O=SomeOrg\\, Inc."]
        ))
    }
}
