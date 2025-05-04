//
//  pkgutilsTests.swift
//  munkiCLItesting
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

struct nameAndVersionTests {
    /// general tests that nameAndVersion splits strings as expected
    @Test func splitsAsExpected() throws {
        #expect(nameAndVersion("foo-1.2.3") == ("foo", "1.2.3"))
        #expect(nameAndVersion("foo--1.2.3") == ("foo", "1.2.3"))
        #expect(nameAndVersion("foo-1.2.3-1") == ("foo-1.2.3", "1"))
        #expect(nameAndVersion("foo--1.2.3-1") == ("foo", "1.2.3-1"))

        #expect(nameAndVersion("foov1.2.3", onlySplitOnHyphens: false) == ("foo", "1.2.3"))
        #expect(nameAndVersion("foo 1.2.3", onlySplitOnHyphens: false) == ("foo", "1.2.3"))
        #expect(nameAndVersion("foo_1.2.3", onlySplitOnHyphens: false) == ("foo", "1.2.3"))
        #expect(nameAndVersion("foo.1.2.3", onlySplitOnHyphens: false) == ("foo", "1.2.3"))
        #expect(nameAndVersion("foo 1.2.3b1", onlySplitOnHyphens: false) == ("foo", "1.2.3b1"))
        #expect(nameAndVersion("foo 1.0b1", onlySplitOnHyphens: false) == ("foo", "1.0b1"))
        #expect(nameAndVersion("foo 1.2.3.4b1", onlySplitOnHyphens: false) == ("foo", "1.2.3.4b1"))

        #expect(nameAndVersion("MSWord2021", onlySplitOnHyphens: false) == ("MSWord2021", ""))
    }
}

struct hadValidExtensionTests {
    /// Test that valid package extensions are correctly detected
    @Test func validPackageExtensions() throws {
        #expect(hasValidPackageExt("foo.pkg") == true)
        #expect(hasValidPackageExt("foo.PKG") == true)
        #expect(hasValidPackageExt("foo.mpkg") == true)
        #expect(hasValidPackageExt("foo.MPKG") == true)
        #expect(hasValidPackageExt("foo.bar.pkg") == true)
        #expect(hasValidPackageExt("foo.bar.mpkg") == true)
    }

    /// Test that invalid package extensions are correctly detected
    @Test func invalidPackageExtensions() throws {
        #expect(hasValidPackageExt("foo.bar") == false)
        #expect(hasValidPackageExt("foo.pkg.bar") == false)
        #expect(hasValidPackageExt("foo.mpkg.bar") == false)
        #expect(hasValidPackageExt("foo.somepkg") == false)
        #expect(hasValidPackageExt("foo.somempkg") == false)
    }

    /// Test that valid disk image extensions are correctly detected
    @Test func validDiskImageExtensions() throws {
        #expect(hasValidDiskImageExt("foo.dmg") == true)
        #expect(hasValidDiskImageExt("foo.DMG") == true)
        #expect(hasValidDiskImageExt("foo.iso") == true)
        #expect(hasValidDiskImageExt("foo.ISO") == true)
        #expect(hasValidDiskImageExt("foo.bar.dmg") == true)
        #expect(hasValidDiskImageExt("foo.bar.iso") == true)
    }

    /// Test that invalid disk image extensions are correctly detected
    @Test func invalidDiskImageExtensions() throws {
        #expect(hasValidDiskImageExt("foo.pkg") == false)
        #expect(hasValidDiskImageExt("foo.mpkg") == false)
        #expect(hasValidDiskImageExt("foo.dmg.pkg") == false)
        #expect(hasValidDiskImageExt("foo.iso.pkg") == false)
        #expect(hasValidDiskImageExt("foo.somedmg") == false)
        #expect(hasValidDiskImageExt("foo.someiso") == false)
    }
}

struct partialFileURLToRelativePathTests {
    /// Test that we get expected path
    @Test func expectedResultsWithHash() {
        #expect(partialFileURLToRelativePath("#foo/bar/baz") == "foo/bar/baz")
        #expect(partialFileURLToRelativePath("#foo%20bar/baz") == "foo bar/baz")
    }

    /// Test that we get expected path (need to find some examples in actual packages)
    @Test func expectedResultsWithFileURL() {
        #expect(partialFileURLToRelativePath("file:///foo/bar/baz") == "/foo/bar/baz")
        #expect(partialFileURLToRelativePath("file:///foo%20bar/baz") == "/foo bar/baz")
    }
}

struct DistFileTests {
    let distribution = """
    <?xml version="1.0" encoding="utf-8" standalone="yes"?>
    <installer-script minSpecVersion="2">
        <title>Munki - Software Management for macOS</title>
        <volume-check>
            <allowed-os-versions>
                <os-version min="10.15"/>
            </allowed-os-versions>
        </volume-check>
        <options hostArchitectures="x86_64,arm64" customize="allow" allow-external-scripts="no"/>
        <domains enable_anywhere="true"/>
        <choices-outline>
            <line choice="core"/>
            <line choice="admin"/>
            <line choice="app"/>
            <line choice="app_usage"/>
            <line choice="launchd"/>
            <line choice="pythonlibs"/>
        </choices-outline>
        <choice id="core" title="Munki core tools" description="Core command-line tools used by Munki.">
            <pkg-ref id="com.googlecode.munki.core"/>
        </choice>
        <choice id="admin" title="Munki admin tools" description="Command-line munki admin tools.">
            <pkg-ref id="com.googlecode.munki.admin"/>
        </choice>
        <choice id="app" title="Managed Software Center" description="Managed Software Center application.">
            <pkg-ref id="com.googlecode.munki.app"/>
        </choice>
        <choice id="app_usage" title="Munki app usage monitoring tool" description="Munki app usage monitoring tool and launchdaemon. Optional install; if installed Munki can use data collected by this tool to automatically remove unused software.">
            <pkg-ref id="com.googlecode.munki.app_usage"/>
        </choice>
        <choice id="python" title="Munki embedded Python" description="Embedded Python 3 framework for Munki.">
            <pkg-ref id="com.googlecode.munki.python"/>
        </choice>
        <choice id="launchd" title="Munki launchd files" description="Core Munki launch daemons and launch agents.">
            <pkg-ref id="com.googlecode.munki.launchd"/>
        </choice>
        <choice id="pythonlibs" title="Munki Python libraries" description="Python libraries for Munki.">
            <pkg-ref id="com.googlecode.munki.pythonlibs"/>
        </choice>
        <pkg-ref id="com.googlecode.munki.core" auth="Root" version="7.0.0.5096" installKBytes="39393" updateKBytes="0">#munkitools_core.pkg</pkg-ref>
        <pkg-ref id="com.googlecode.munki.admin" auth="Root" version="7.0.0.5096" installKBytes="20832" updateKBytes="0">#munkitools_admin.pkg</pkg-ref>
        <pkg-ref id="com.googlecode.munki.app" auth="Root" version="6.6.3.4707" installKBytes="29260" updateKBytes="0">#munkitools_app.pkg</pkg-ref>
        <pkg-ref id="com.googlecode.munki.app_usage" auth="Root" version="7.0.0.5096" installKBytes="1254" updateKBytes="0">#munkitools_app_usage.pkg</pkg-ref>
        <pkg-ref id="com.googlecode.munki.launchd" auth="Root" version="6.6.0.4656" installKBytes="455" updateKBytes="0">#munkitools_launchd.pkg</pkg-ref>
        <pkg-ref id="com.googlecode.munki.pythonlibs" auth="Root" version="6.6.5.5096" installKBytes="975" updateKBytes="0">#munkitools_pythonlibs.pkg</pkg-ref>
        <product id="com.googlecode.munki" version="7.0.0.5096"/>
        <pkg-ref id="com.googlecode.munki.core">
            <bundle-version/>
        </pkg-ref>
        <pkg-ref id="com.googlecode.munki.admin">
            <bundle-version/>
        </pkg-ref>
        <pkg-ref id="com.googlecode.munki.app">
            <bundle-version>
                <bundle CFBundleShortVersionString="6.6.3.4707" CFBundleVersion="4707" id="com.googlecode.munki.MunkiStatus" path="Applications/Managed Software Center.app/Contents/Helpers/MunkiStatus.app"/>
                <bundle CFBundleShortVersionString="6.6.0.4707" CFBundleVersion="4707" id="com.googlecode.munki.munki-notifier" path="Applications/Managed Software Center.app/Contents/Helpers/munki-notifier.app"/>
                <bundle CFBundleShortVersionString="1.0" CFBundleVersion="1" id="com.googlecode.munki.MSCDockTilePlugin" path="Applications/Managed Software Center.app/Contents/PlugIns/MSCDockTilePlugin.docktileplugin"/>
                <bundle CFBundleShortVersionString="6.6.3.4707" CFBundleVersion="4707" id="com.googlecode.munki.ManagedSoftwareCenter" path="Applications/Managed Software Center.app"/>
            </bundle-version>
        </pkg-ref>
        <pkg-ref id="com.googlecode.munki.app_usage">
            <bundle-version/>
        </pkg-ref>
        <pkg-ref id="com.googlecode.munki.launchd">
            <bundle-version/>
        </pkg-ref>
        <pkg-ref id="com.googlecode.munki.pythonlibs">
            <bundle-version/>
        </pkg-ref>
    </installer-script>
    """
    var distPath: String?
    init() throws {
        if let filepath = tempFile() {
            let data = distribution.data(using: .utf8)
            if FileManager.default.createFile(atPath: filepath, contents: data) {
                distPath = filepath
            }
        }
    }

    /// Ensure we get expected value for product version
    @Test func getProductVersionFromDistIsExpected() async throws {
        if let distPath {
            #expect(getProductVersionFromDist(distPath) == "7.0.0.5096")
        } else {
            #expect(Bool(false))
        }
    }

    /// Ensure we get expected value for minimum OS version
    @Test func getMinOSVersFromDistIsExpected() async throws {
        if let distPath {
            #expect(getMinOSVersFromDist(distPath) == "10.15")
        } else {
            #expect(Bool(false))
        }
    }

    /// Ensure we get the expected receipts from the sample distribution
    @Test func receiptsFromDistFileExpectedCount() async throws {
        if let distPath {
            let receipts = receiptsFromDistFile(distPath)
            let pkgids = receipts.compactMap { $0["packageid"] as? String }
            #expect(receipts.count == 6)
            #expect(pkgids.contains("com.googlecode.munki.core"))
            #expect(pkgids.contains("com.googlecode.munki.admin"))
            #expect(pkgids.contains("com.googlecode.munki.app"))
            #expect(pkgids.contains("com.googlecode.munki.launchd"))
            #expect(pkgids.contains("com.googlecode.munki.app_usage"))
            #expect(pkgids.contains("com.googlecode.munki.pythonlibs"))
        } else {
            #expect(Bool(false))
        }
    }
}

struct PackageInfoFileTests {
    let pkginfo = """
    <?xml version="1.0"?>
    <pkg-info format-version="2" install-location="/" identifier="com.googlecode.munki.core" version="7.0.0.5096" generator-version="InstallCmds-860 (24E263)" auth="root">
        <payload numberOfFiles="39" installKBytes="39393"/>
        <bundle-version/>
        <upgrade-bundle/>
        <update-bundle/>
        <atomic-update-bundle/>
        <strict-identifier/>
        <relocate/>
    </pkg-info>
    """
    var pkginfoPath: String?
    init() throws {
        if let filepath = tempFile() {
            let data = pkginfo.data(using: .utf8)
            if FileManager.default.createFile(atPath: filepath, contents: data) {
                pkginfoPath = filepath
            }
        }
    }

    @Test func receiptFromPackageInfoFileGetsExpectedPackageID() throws {
        if let pkginfoPath {
            let receipt = receiptFromPackageInfoFile(pkginfoPath)
            #expect((receipt["packageid"] as? String ?? "") == "com.googlecode.munki.core")
        } else {
            #expect(Bool(false))
        }
    }

    @Test func receiptFromPackageInfoFileGetsExpectedVersion() throws {
        if let pkginfoPath {
            let receipt = receiptFromPackageInfoFile(pkginfoPath)
            #expect((receipt["version"] as? String ?? "") == "7.0.0.5096")
        } else {
            #expect(Bool(false))
        }
    }

    @Test func receiptFromPackageInfoFileGetsExpectedSize() throws {
        if let pkginfoPath {
            let receipt = receiptFromPackageInfoFile(pkginfoPath)
            #expect((receipt["installed_size"] as? Int ?? 0) == 39393)
        } else {
            #expect(Bool(false))
        }
    }
}

struct getVersionStringTests {
    let plist1: PlistDict = [
        "CFBundleShortVersionString": "1.2.3",
        "CFBundleVersion": "456",
        "CFBundleIdentifier": "com.example.otherpkg",
        "RandomVersionKey": "7.8.9",
    ]

    let plist2: PlistDict = [
        "CFBundleVersion": "456",
        "CFBundleIdentifier": "com.example.otherpkg",
        "RandomVersionKey": "7.8.9",
    ]

    /// Ensure getVersionString returns the CFBundleShortVersionString value
    @Test func getVersionStringReturnsCFBundleShortVersionString() async throws {
        #expect(getVersionString(plist: plist1) == "1.2.3")
    }

    /// Ensure getVersionString returns the CFBundleVersion if CFBundleShortVersionString is not defined
    @Test func getVersionStringReturnsCFBundleVersion() async throws {
        #expect(getVersionString(plist: plist2) == "456")
    }

    /// Ensure getVersionString returns the value for specific key
    @Test func getVersionStringReturnsValueForCustomKey() async throws {
        #expect(getVersionString(plist: plist1, key: "RandomVersionKey") == "7.8.9")
    }
}
