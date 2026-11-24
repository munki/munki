//
//  makepkginfolibTests.swift
//  munkiCLItesting
//
//  Created by Greg Neagle on 5/9/25.
//

import Testing

struct pkginfolibTests {
    @Test func getOneMinimumOSVersionFromInstalls() {
        let pkginfo: PlistDict = [
            "installs": [
                ["minosversion": "10.11.0"],
            ],
        ]
        #expect(getMinimumOSVersionFromInstallsApps(pkginfo) == "10.11.0")
    }

    @Test func getHighestMinimumOSVersionFromInstalls() {
        let pkginfo: PlistDict = [
            "installs": [
                ["minosversion": "11.0"],
                ["minosversion": "10.15.0"],
            ],
        ]
        #expect(getMinimumOSVersionFromInstallsApps(pkginfo) == "11.0")
    }

    @Test func getHighestMinimumOSVersionFromInstallsAndPkginfoHigher() {
        let pkginfo: PlistDict = [
            "installs": [
                ["minosversion": "11.0"],
                ["minosversion": "10.15.0"],
            ],
            "minimum_os_version": "12.0",
        ]
        #expect(getMinimumOSVersionFromInstallsApps(pkginfo) == "12.0")
    }

    @Test func getHighestMinimumOSVersionFromInstallsAndPkginfoLower() {
        let pkginfo: PlistDict = [
            "installs": [
                ["minosversion": "11.0"],
                ["minosversion": "10.15.0"],
            ],
            "minimum_os_version": "10.7",
        ]
        #expect(getMinimumOSVersionFromInstallsApps(pkginfo) == "11.0")
    }

    @Test func getHighestMinimumOSVersionFromEmptyInstallsIsNil() {
        let pkginfo: PlistDict = [:]
        #expect(getMinimumOSVersionFromInstallsApps(pkginfo) == nil)
    }

    @Test func getHighestMinimumOSVersionFromStageOsInstallerIsNil() {
        let pkginfo: PlistDict = [
            "installer_type": "stage_os_installer",
            "installs": [
                ["minosversion": "11.0"],
                ["minosversion": "10.15.0"],
            ],
            "minimum_os_version": "10.7",
        ]
        #expect(getMinimumOSVersionFromInstallsApps(pkginfo) == nil)
    }
}

struct forceInstallAfterDateTests {
    /// Clients only honor this key when it is a date, not a string
    @Test func forceInstallAfterDateIsStoredAsDate() throws {
        let options = try PkginfoOptions(
            override: .parse([]),
            script: .parse([]),
            dmg: .parse([]),
            pkg: .parse([]),
            force: .parse(["--force_install_after_date", "2030-01-01T12:00:00Z"]),
            deployment: .parse([]),
            installs: .parse([]),
            type: .parse([]),
            other: .parse([]),
            hidden: .parse([])
        )
        let pkginfo = try makepkginfo(nil, options: options)
        let expected = ISO8601DateFormatter().date(from: "2030-01-01T12:00:00Z")
        #expect(pkginfo["force_install_after_date"] as? Date == expected)
    }
}
