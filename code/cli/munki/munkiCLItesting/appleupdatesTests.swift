//
//  appleupdatesTests.swift
//  munkiCLItesting
//
//  Created by Greg Neagle on 5/4/25.
//

import Testing

struct appleupdatesTests {
    let suOutput = """
    Software Update Tool

    Finding available software
    2024-09-09 11:07:46.969 softwareupdate[25532:32872565] XType: com.apple.fonts is not accessible.
    2024-09-09 11:07:46.969 softwareupdate[25532:32872565] XType: XTFontStaticRegistry is enabled.
    Software Update found the following new or updated software:
    * Label: Safari17.6MontereyAuto-17.6
        Title: Safari, Version: 17.6, Size: 152370KiB, Recommended: YES, 
    * Label: macOS Monterey 12.7.6-21H1320
        Title: macOS Monterey 12.7.6, Version: 12.7.6, Size: 1765616K, Recommended: YES, Action: restart, 
    * Label: macOS Sonoma 14.6.1-23G93
        Title: macOS Sonoma 14.6.1, Version: 14.6.1, Size: 6327722K, Recommended: YES, Action: restart, 
    """
    var updates: [[String: String]]

    let recommendedUpdates: [PlistDict] = [
        [
            "Display Name": "Safari",
            "Display Version": "17.6",
            "Identifier": "Safari17.6MontereyAuto",
            "Product Key": "062-47822",
        ],
        [
            "Display Name": "macOS Sonoma 14.6.1",
            "Display Version": "14.6.1",
            "Identifier": "MSU_UPDATE_23G93_patch_14.6.1",
            "MobileSoftwareUpdate": 1,
            "Product Key": "MSU_UPDATE_23G93_patch_14.6.1",
        ],
        [
            "Display Name": "macOS Monterey 12.7.6",
            "Display Version": "12.7.6",
            "Identifier": "MSU_UPDATE_21H1320_patch_12.7.6",
            "MobileSoftwareUpdate": 1,
            "Product Key": "MSU_UPDATE_21H1320_patch_12.7.6",
        ],
    ]

    init() {
        updates = []
        let lines = suOutput.components(separatedBy: .newlines)
        var index = 0
        while index < lines.count {
            let currentLine = lines[index]
            index += 1
            if currentLine.hasPrefix("* Label"), index < lines.count {
                let nextLine = lines[index]
                index += 1
                updates.append(parseSULines(currentLine, nextLine))
            }
        }
    }

    @Test func parsingSULinesResultsInExpectedNumberofUpdates() {
        #expect(updates.count == 3)
    }

    @Test func parsingSULinesGetsExpectedLabel() throws {
        try #require(updates.count > 0, "Did not parse any updates")
        #expect(updates[0]["Label"] == "Safari17.6MontereyAuto-17.6")
    }

    @Test func parsingSULinesGetsExpectedTitle() throws {
        try #require(updates.count > 0, "Did not parse any updates")
        #expect(updates[0]["Title"] == "Safari")
    }

    @Test func parsingSULinesGetsExpectedVersion() throws {
        try #require(updates.count > 1, "Did not parse at least two updates")
        #expect(updates[1]["Version"] == "12.7.6")
    }

    @Test func parsingSULinesGetsExpectedSize() throws {
        try #require(updates.count > 1, "Did not parse at least two updates")
        #expect(updates[1]["Size"] == "1765616K")
    }

    @Test func parsingSULinesGetsExpectedAction() throws {
        try #require(updates.count > 2, "Did not parse at least three updates")
        #expect(updates[2]["Action"] == "restart")
    }

    @Test func productKeyIsExpected() throws {
        try #require(updates.count > 0, "Did not parse any updates")
        let name = try #require(updates[0]["Title"], "Update did not have Title")
        let version = try #require(updates[0]["Version"], "Update did not have Title")
        let item: PlistDict = [
            "name": name,
            "version_to_install": version,
        ]
        #expect(getProductKey(for: item, recommendedUpdates: recommendedUpdates) == "062-47822")
    }

    @Test func productKeyIsNil() {
        let item: PlistDict = [
            "name": "Foo",
            "version_to_install": "1.0",
        ]
        #expect(getProductKey(for: item, recommendedUpdates: recommendedUpdates) == nil)
    }
}
