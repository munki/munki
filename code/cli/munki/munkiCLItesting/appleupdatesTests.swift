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

    init() {
        updates = []
        let lines = suOutput.components(separatedBy: .newlines)
        var index = 0
        while index < lines.count {
            let currentLine = lines[index]
            index += 1
            if currentLine.hasPrefix("* Label") {
                if index < lines.count {
                    let nextLine = lines[index]
                    index += 1
                    updates.append(parseSULines(currentLine, nextLine))
                }
            }
        }
    }

    @Test func parsingSULinesResultsInExpectedNumberofUpdates() async throws {
        #expect(updates.count == 3)
    }

    @Test func parsingSULinesGetsExpectedLabel() async throws {
        if updates.count > 0 {
            #expect(updates[0]["Label"] == "Safari17.6MontereyAuto-17.6")
        } else {
            #expect(Bool(false))
        }
    }

    @Test func parsingSULinesGetsExpectedTitle() async throws {
        if updates.count > 0 {
            #expect(updates[0]["Title"] == "Safari")
        } else {
            #expect(Bool(false))
        }
    }

    @Test func parsingSULinesGetsExpectedVersion() async throws {
        if updates.count > 1 {
            #expect(updates[1]["Version"] == "12.7.6")
        } else {
            #expect(Bool(false))
        }
    }

    @Test func parsingSULinesGetsExpectedSize() async throws {
        if updates.count > 1 {
            #expect(updates[1]["Size"] == "1765616K")
        } else {
            #expect(Bool(false))
        }
    }

    @Test func parsingSULinesGetsExpectedAction() async throws {
        if updates.count > 2 {
            #expect(updates[2]["Action"] == "restart")
        } else {
            #expect(Bool(false))
        }
    }
}
