//
//  keychainTests.swift
//  munkiCLItesting
//
//  Created by Greg Neagle on 5/20/25.
//

import Testing

struct keychainTests {
    /// Test we can read/parse a pem file containing a certificate
    @Test func pemCertDataRead() throws {
        let certPath = try #require(TestingResource.path(for: "munki_client.pem"),
                                    "Could not get path for test cert file")
        let certData = try? pemCertData(certPath)
        #expect(certData != nil, "Could not read/parse test cert file")
    }

    @Test func extractCommonName() throws {
        let certPath = try #require(TestingResource.path(for: "munki_client.pem"),
                                    "Could not get path for test cert file")
        let certData = try #require(try? pemCertData(certPath),
                                    "Could not read/parse test cert file")
        #expect(getCommonNameFromCertData(certData) == "munki_client")
    }
}
