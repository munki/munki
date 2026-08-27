//
//  factsTests.swift
//  munkiCLItesting
//
//  Created by Greg Neagle on 5/4/25.
//
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

struct predicateTests {
    let info: PlistDict = [
        "arch": "arm64",
        "board_id": "<none>",
        "catalogs": ["development", "testing", "production"],
        "date": NSDate(),
        "device_id": "J414sAP",
        "ipv4_address": ["192.168.1.1"],
        "machine_model": "Mac14,9",
        "machine_type": "laptop",
        "munki_version": "7.0.0",
        "os_build_last_component": "263",
        "os_build_number": "24E263",
        "os_vers": "15.4.1",
        "os_vers_major": 15,
        "os_vers_minor": 4,
        "os_vers_patch": 1,
        "physical_or_virtual": "physical",
        "product_name": "MacBook Pro (14-inch, 2023)",
    ]

    @Test func predicateEvaluatesAsTrueTests() async throws {
        #expect(predicateEvaluatesAsTrue(
            "arch == 'arm64'", infoObject: info
        ))
        #expect(predicateEvaluatesAsTrue(
            "ipv4_address CONTAINS '192.168.1.1'", infoObject: info
        ))
        #expect(predicateEvaluatesAsTrue(
            "ANY ipv4_address BEGINSWITH '192.168.1.'", infoObject: info
        ))
        #expect(predicateEvaluatesAsTrue(
            "catalogs CONTAINS 'testing'", infoObject: info
        ))
        #expect(predicateEvaluatesAsTrue(
            "date > CAST('2016-03-02T00:00:00Z', 'NSDate')", infoObject: info
        ))
        #expect(predicateEvaluatesAsTrue(
            "machine_type == 'laptop' AND os_vers_major > 10", infoObject: info
        ))
    }

    @Test func predicateEvaluatesAsFalseTests() async throws {
        #expect(predicateEvaluatesAsTrue(
            "arch == 'x86_64'", infoObject: info
        ) == false)
        #expect(predicateEvaluatesAsTrue(
            "ipv4_address CONTAINS '10.0.0.1'", infoObject: info
        ) == false)
        #expect(predicateEvaluatesAsTrue(
            "ANY ipv4_address BEGINSWITH '10.'", infoObject: info
        ) == false)
        #expect(predicateEvaluatesAsTrue(
            "catalogs CONTAINS 'staging'", infoObject: info
        ) == false)
        #expect(predicateEvaluatesAsTrue(
            "date < CAST('2016-03-02T00:00:00Z', 'NSDate')",
            infoObject: info
        ) == false
        )
        #expect(predicateEvaluatesAsTrue(
            "machine_type == 'laptop' AND os_vers_major < 10",
            infoObject: info
        ) == false
        )
    }

    @Test func predicateEvaluatesAsFalseWithUndefinedValue() async throws {
        #expect(predicateEvaluatesAsTrue(
            "undefined_key == 'Hello'",
            infoObject: info
        ) == false
        )
    }
}

struct applicationDataTesting {
    let applicationData: [PlistDict] = [
        [
            "bundleid": "com.macromates.TextMate",
            "name": "TextMate",
            "path": "/Applications/TextMate.app",
            "version": "2.0.23",
        ],
        [
            "bundleid": "us.zoom.xos",
            "name": "zoom.us",
            "path": "/Applications/zoom.us.app",
            "version": "6.4.6 (53970)",
        ],
        [
            "bundleid": "com.adobe.Photoshop",
            "name": "Photoshop 2025",
            "path": "/Applications/Adobe Photoshop 2025/Adobe Photoshop 2025.app",
            "version": "26.5.0",
        ],
        [
            "bundleid": "com.apple.dt.Xcode",
            "name": "Xcode",
            "path": "/Applications/Xcode.app",
            "version": "16.3",
        ],
        [
            "bundleid": "com.google.Chrome",
            "name": "Chrome",
            "path": "/Applications/Google Chrome.app",
            "version": "136.0.7103.49",
        ],
        [
            "bundleid": "com.microsoft.Word",
            "name": "Word",
            "path": "/Applications/Microsoft Word.app",
            "version": "16.96.2",
        ],
    ]

    @Test func fullPathExists() {
        let info: PlistDict = ["applications": applicationData]
        #expect(predicateEvaluatesAsTrue(
            "ANY applications.path == '/Applications/Microsoft Word.app'",
            infoObject: info
        ))
    }

    @Test func pathEndsWith() {
        let info: PlistDict = ["applications": applicationData]
        #expect(predicateEvaluatesAsTrue(
            "ANY applications.path ENDSWITH '/Microsoft Word.app'",
            infoObject: info
        ))
    }

    @Test func bundleBeginsWith() {
        let info: PlistDict = ["applications": applicationData]
        #expect(predicateEvaluatesAsTrue(
            "ANY applications.bundleid BEGINSWITH 'com.adobe.'",
            infoObject: info
        ))
    }

    @Test func specificAppVersion() {
        let info: PlistDict = ["applications": applicationData]
        #expect(predicateEvaluatesAsTrue(
            "SUBQUERY(applications, $app, $app.bundleid == 'com.microsoft.Word' AND $app.version == '16.96.2').@count > 0",
            infoObject: info
        ))
    }

    @Test func bundleNotPresent() {
        let info: PlistDict = ["applications": applicationData]
        #expect(predicateEvaluatesAsTrue(
            "ANY applications.bundleid == 'DoesNotExist.bundle'",
            infoObject: info
        ) == false)
    }

    /// Make sure an invalid predicate doesn't trigger a crash
    @Test func invalidPredicateDoesntCauseCrash() {
        #expect(predicateEvaluatesAsTrue(
            "FOO bar.baz ^& 'banana'",
            infoObject: PlistDict()
        ) == false)
        // let result = objCpredicateEvaluatesAsTrue(predicateString, ourObject, &err)
    }

    /// Test that an invalid predicate returns the expected error
    @Test func invalidPredicateReturnsObjErr() {
        let predicateString = "FOO bar.baz ^& 'banana'"
        let infoObject = PlistDict()
        var err: NSError?
        let result = objCpredicateEvaluatesAsTrue(predicateString, infoObject, &err)
        #expect(result == -1)
        #expect(err != nil)
    }
}
