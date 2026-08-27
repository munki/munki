//
//  downloadTests.swift
//  munkiCLItesting
//
//  Created by Greg Neagle on 1/18/26.
//

import Testing

struct downloadTests {
    @Test func getDownloadCachePathTests() async throws {
        #expect(
            getDownloadCachePath("http://munki.local/repo/pkgs/bar.pkg") == managedInstallsDir(subpath: "Cache/bar.pkg")
        )
    }
}
