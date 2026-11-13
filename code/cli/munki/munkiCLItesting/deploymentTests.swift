//
//  deploymentTests.swift
//  munkiCLItesting
//
//  Copyright 2026 The Munki Project. All rights reserved.
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

import Foundation
import Testing

/// "2026-10-20 09:00" as a UTC date, the frame pkginfo dates are compared in.
/// 2026-10-12 is a Monday, and 2026-10-17 and 18 are a weekend.
private func date(_ text: String) -> Date {
    let formatter = ISO8601DateFormatter()
    return formatter.date(from: text.replacingOccurrences(of: " ", with: "T") + ":00Z")!
}

private func deployment(_ dict: [String: Any]) throws -> Deployment {
    return try Deployment(dict)
}

private func percent(_ deployment: Deployment, _ text: String) -> Int {
    return deployment.state(at: date(text)).currentPercent
}

struct DeploymentStrategyTests {
    @Test func twoWeekRollout() throws {
        let rollout = try deployment(["start": date("2026-10-12 00:00"), "end": date("2026-10-24 00:00")])

        let state = rollout.state(at: date("2026-10-14 09:30"))
        #expect(state.status == .inProgress)
        #expect(state.step == 58)
        #expect(state.totalSteps == 241)
        #expect(state.currentPercent == 25)
        #expect(state.nextStepDate == date("2026-10-14 10:00"))
        // steps 59 and 60 also round up to 25, so the percent next rises at step 61
        #expect(state.nextIncreaseDate == date("2026-10-14 12:00"))

        #expect(percent(rollout, "2026-10-11 23:59") == 0)
        #expect(percent(rollout, "2026-10-12 00:00") == 1)
        // rounding up would give 100 from 22:00, but only the last step reaches it
        #expect(percent(rollout, "2026-10-23 21:59") == 99)
        #expect(percent(rollout, "2026-10-23 22:00") == 99)
        #expect(percent(rollout, "2026-10-23 23:59") == 99)
        #expect(percent(rollout, "2026-10-24 00:00") == 100)
    }

    @Test func fastRoll() throws {
        let rollout = try deployment(["start": date("2026-10-20 09:00"), "end": date("2026-10-20 17:00")])
        let expected = [12, 23, 34, 45, 56, 67, 78, 89, 100]
        for (index, value) in expected.enumerated() {
            #expect(percent(rollout, String(format: "2026-10-20 %02d:00", 9 + index)) == value)
        }
        #expect(percent(rollout, "2026-10-20 08:59") == 0)
        #expect(percent(rollout, "2026-10-20 16:59") == 89)
        #expect(rollout.state(at: date("2026-10-20 12:00")).totalSteps == 9)
    }

    @Test func overnight() throws {
        let rollout = try deployment(["start": date("2026-10-20 18:00"), "end": date("2026-10-21 06:00")])
        #expect(rollout.state(at: date("2026-10-20 18:00")).totalSteps == 13)
        #expect(percent(rollout, "2026-10-20 18:00") == 8)
        #expect(percent(rollout, "2026-10-20 19:00") == 16)
        #expect(percent(rollout, "2026-10-21 05:59") == 93)
        #expect(percent(rollout, "2026-10-21 06:00") == 100)
    }

    @Test func hourlyRate() throws {
        let rollout = try deployment(["start": date("2026-10-20 09:00"), "percent_per_hour": 10])
        for index in 0 ..< 10 {
            #expect(percent(rollout, String(format: "2026-10-20 %02d:00", 9 + index)) == (index + 1) * 10)
        }
        #expect(percent(rollout, "2026-10-20 17:59") == 90)
        #expect(rollout.state(at: date("2026-10-20 18:00")).status == .complete)
    }

    @Test func dailyBatches() throws {
        let rollout = try deployment([
            "start": date("2026-10-12 00:00"), "percent_per_step": 10, "step_hours": 24,
        ])
        #expect(percent(rollout, "2026-10-12 00:00") == 10)
        #expect(percent(rollout, "2026-10-12 23:59") == 10)
        #expect(percent(rollout, "2026-10-16 00:00") == 50)
        #expect(percent(rollout, "2026-10-17 12:00") == 50)
        #expect(percent(rollout, "2026-10-19 00:00") == 60)
        #expect(percent(rollout, "2026-10-22 23:59") == 90)
        #expect(percent(rollout, "2026-10-23 00:00") == 100)
        #expect(rollout.state(at: date("2026-10-16 12:00")).nextStepDate == date("2026-10-19 00:00"))
    }

    @Test func dailyRate() throws {
        let rollout = try deployment(["start": date("2026-10-12 00:00"), "percent_per_day": 20])
        #expect(percent(rollout, "2026-10-12 00:00") == 1)
        #expect(percent(rollout, "2026-10-16 21:59") == 99)
        // the design's "rounding up gets there an hour early"
        #expect(percent(rollout, "2026-10-16 22:00") == 100)
        #expect(rollout.state(at: date("2026-10-12 00:00")).totalSteps == 119)
    }

    @Test func staticPercent() throws {
        let canary = try deployment(["percent": 5])
        let state = canary.state(at: date("2026-10-20 09:00"))
        #expect(state.status == .fixed)
        #expect(state.currentPercent == 5)
        #expect(state.step == nil)
        #expect(state.totalSteps == nil)
        #expect(state.nextStepDate == nil)
        #expect(state.nextIncreaseDate == nil)

        #expect(try deployment(["percent": 100]).state(at: date("2026-10-20 09:00")).status == .complete)
    }

    @Test func staticPercentWithStart() throws {
        let canary = try deployment(["start": date("2026-11-05 00:00"), "percent": 5])

        let before = canary.state(at: date("2026-11-04 23:59"))
        #expect(before.status == .scheduled)
        #expect(before.currentPercent == 0)
        #expect(before.step == nil)
        #expect(before.nextStepDate == date("2026-11-05 00:00"))
        #expect(before.nextIncreaseDate == date("2026-11-05 00:00"))

        let after = canary.state(at: date("2026-11-05 00:00"))
        #expect(after.status == .fixed)
        #expect(after.currentPercent == 5)
        #expect(after.nextStepDate == nil)
        #expect(after.nextIncreaseDate == nil)
    }

    @Test func staticPercentWithWeekendStartBehavesLikeMonday() throws {
        let canary = try deployment(["start": date("2026-10-17 10:00"), "percent": 5])
        #expect(percent(canary, "2026-10-18 23:59") == 0)
        #expect(canary.state(at: date("2026-10-18 23:59")).nextStepDate == date("2026-10-19 00:00"))
        #expect(percent(canary, "2026-10-19 00:00") == 5)
    }

    @Test func staticHundredWithStartIsScheduledThenComplete() throws {
        let rollout = try deployment(["start": date("2026-11-05 00:00"), "percent": 100])
        #expect(rollout.state(at: date("2026-11-04 12:00")).status == .scheduled)
        #expect(rollout.state(at: date("2026-11-05 00:00")).status == .complete)
    }

    @Test func staticPercentIgnoresStepHours() throws {
        #expect(percent(try deployment(["percent": 5, "step_hours": 24]), "2026-10-20 09:00") == 5)
        #expect(percent(try deployment(["percent": 5, "step_hours": "bad"]), "2026-10-20 09:00") == 5)
    }
}

struct DeploymentStepTests {
    @Test func partialStartHour() throws {
        let rollout = try deployment(["start": date("2026-10-20 08:30"), "end": date("2026-10-20 17:00")])
        #expect(rollout.state(at: date("2026-10-20 08:30")).totalSteps == 10)
        #expect(percent(rollout, "2026-10-20 08:29") == 0)
        #expect(percent(rollout, "2026-10-20 08:30") == 10)
        #expect(percent(rollout, "2026-10-20 08:59") == 10)
        #expect(percent(rollout, "2026-10-20 09:00") == 20)
        #expect(percent(rollout, "2026-10-20 17:00") == 100)
    }

    @Test func partialStartHourWithStepHours() throws {
        let rollout = try deployment([
            "start": date("2026-10-20 08:30"), "end": date("2026-10-20 17:00"), "step_hours": 2,
        ])
        #expect(rollout.state(at: date("2026-10-20 08:30")).totalSteps == 6)
        #expect(rollout.state(at: date("2026-10-20 08:30")).nextStepDate == date("2026-10-20 10:00"))
        #expect(percent(rollout, "2026-10-20 09:59") == 17)
        #expect(percent(rollout, "2026-10-20 10:00") == 34)
    }

    @Test func partialEndHour() throws {
        let rollout = try deployment(["start": date("2026-10-20 09:00"), "end": date("2026-10-20 11:30")])
        #expect(rollout.state(at: date("2026-10-20 09:00")).totalSteps == 4)
        #expect(percent(rollout, "2026-10-20 11:00") == 75)
        #expect(rollout.state(at: date("2026-10-20 11:00")).nextStepDate == date("2026-10-20 11:30"))
        #expect(percent(rollout, "2026-10-20 11:30") == 100)
    }

    @Test func stepHoursLastStepCanBeShort() throws {
        let rollout = try deployment([
            "start": date("2026-10-20 08:00"), "end": date("2026-10-20 17:00"), "step_hours": 2,
        ])
        let expected = [("08:00", 17), ("10:00", 34), ("12:00", 50), ("14:00", 67), ("16:00", 84), ("17:00", 100)]
        for (time, value) in expected {
            #expect(percent(rollout, "2026-10-20 \(time)") == value)
        }
        #expect(percent(rollout, "2026-10-20 15:59") == 67)
    }

    @Test func endLandingOnAStepIsNotCountedTwice() throws {
        let rollout = try deployment([
            "start": date("2026-10-20 08:00"), "end": date("2026-10-20 18:00"), "step_hours": 2,
        ])
        #expect(rollout.state(at: date("2026-10-20 08:00")).totalSteps == 6)
    }

    @Test func roundingUpSeventeenSteps() throws {
        let rollout = try deployment(["start": date("2026-10-12 00:00"), "end": date("2026-10-12 16:00")])
        #expect(rollout.state(at: date("2026-10-12 00:00")).totalSteps == 17)
        #expect(percent(rollout, "2026-10-12 00:00") == 6)
        #expect(percent(rollout, "2026-10-12 01:00") == 12)
        #expect(percent(rollout, "2026-10-12 02:00") == 18)
        #expect(percent(rollout, "2026-10-12 15:00") == 95)
        #expect(percent(rollout, "2026-10-12 16:00") == 100)
    }

    @Test func rateWithAPartialStartHourContinuesOnTheHour() throws {
        let rollout = try deployment(["start": date("2026-10-20 08:30"), "percent_per_hour": 10])
        #expect(percent(rollout, "2026-10-20 08:30") == 10)
        #expect(percent(rollout, "2026-10-20 08:59") == 10)
        #expect(percent(rollout, "2026-10-20 09:00") == 20)
        #expect(rollout.state(at: date("2026-10-20 08:30")).nextStepDate == date("2026-10-20 09:00"))
    }

    @Test func staysAtOneHundred() throws {
        let rollout = try deployment(["start": date("2026-10-20 09:00"), "percent_per_hour": 50])
        let state = rollout.state(at: date("2030-06-05 12:00"))
        #expect(state.currentPercent == 100)
        #expect(state.status == .complete)
        #expect(state.nextStepDate == nil)
        #expect(state.nextIncreaseDate == nil)
    }

    @Test func beforeStart() throws {
        let rollout = try deployment(["start": date("2026-10-20 09:00"), "end": date("2026-10-20 17:00")])
        let state = rollout.state(at: date("2026-10-19 09:00"))
        #expect(state.status == .scheduled)
        #expect(state.currentPercent == 0)
        #expect(state.step == 0)
        #expect(state.nextStepDate == date("2026-10-20 09:00"))
        #expect(state.nextIncreaseDate == date("2026-10-20 09:00"))
    }
}

struct DeploymentWeekendTests {
    private let acrossWeekend: [String: Any] = [
        "start": date("2026-10-16 20:00"), "end": date("2026-10-19 02:00"),
    ]

    @Test func weekendHoursAreNotCounted() throws {
        let rollout = try deployment(acrossWeekend)
        #expect(rollout.state(at: date("2026-10-16 20:00")).totalSteps == 7)
        #expect(percent(rollout, "2026-10-16 23:00") == 58)
        #expect(percent(rollout, "2026-10-17 00:00") == 58)
        #expect(percent(rollout, "2026-10-18 23:59") == 58)
        #expect(percent(rollout, "2026-10-19 00:00") == 72)
        #expect(rollout.state(at: date("2026-10-17 12:00")).nextStepDate == date("2026-10-19 00:00"))
    }

    @Test func weekendStartBehavesLikeMonday() throws {
        let rollout = try deployment(["start": date("2026-10-17 10:00"), "end": date("2026-10-19 02:00")])
        #expect(rollout.state(at: date("2026-10-18 12:00")).status == .scheduled)
        #expect(rollout.state(at: date("2026-10-18 12:00")).nextStepDate == date("2026-10-19 00:00"))
        #expect(rollout.state(at: date("2026-10-19 00:00")).totalSteps == 3)
        #expect(percent(rollout, "2026-10-18 23:59") == 0)
        #expect(percent(rollout, "2026-10-19 00:00") == 34)
        #expect(percent(rollout, "2026-10-19 02:00") == 100)
    }

    @Test func weekendEndMovesBackToSaturdayMidnight() throws {
        for end in ["2026-10-17 00:00", "2026-10-17 12:00", "2026-10-18 15:00"] {
            let rollout = try deployment(["start": date("2026-10-16 20:00"), "end": date(end)])
            #expect(rollout.state(at: date("2026-10-16 20:00")).totalSteps == 5)
            #expect(percent(rollout, "2026-10-16 23:59") == 80)
            #expect(rollout.state(at: date("2026-10-16 23:30")).nextStepDate == date("2026-10-17 00:00"))
            #expect(percent(rollout, "2026-10-17 00:00") == 100)
            #expect(percent(rollout, "2026-10-18 12:00") == 100)
        }
    }

    @Test func mondayMidnightEndDoesNotFinishOverTheWeekend() throws {
        let rollout = try deployment(["start": date("2026-10-16 20:00"), "end": date("2026-10-19 00:00")])
        #expect(percent(rollout, "2026-10-18 12:00") == 80)
        #expect(percent(rollout, "2026-10-19 00:00") == 100)
    }

    @Test func startAndEndWithNoWeekdayBetweenAreInvalid() {
        let cases = [
            ("2026-10-17 10:00", "2026-10-18 10:00"),
            ("2026-10-17 10:00", "2026-10-17 11:00"),
            ("2026-10-17 10:00", "2026-10-19 00:00"),
        ]
        for (start, end) in cases {
            #expect(throws: MunkiError.self) {
                try deployment(["start": date(start), "end": date(end)])
            }
        }
    }

    @Test func rateModesPauseOverTheWeekend() throws {
        let rollout = try deployment(["start": date("2026-10-16 20:00"), "percent_per_hour": 10])
        #expect(percent(rollout, "2026-10-16 23:00") == 40)
        #expect(percent(rollout, "2026-10-17 12:00") == 40)
        #expect(percent(rollout, "2026-10-19 00:00") == 50)
    }

    @Test func dailyStepsCarryTheirHourAcrossTheWeekend() throws {
        let rollout = try deployment([
            "start": date("2026-10-16 09:00"), "percent_per_step": 20, "step_hours": 24,
        ])
        #expect(percent(rollout, "2026-10-16 09:00") == 20)
        #expect(percent(rollout, "2026-10-19 08:59") == 20)
        #expect(percent(rollout, "2026-10-19 09:00") == 40)
    }
}

struct DeploymentLocalTimeTests {
    /// Converts the way subtractTZOffsetFromDate does, for a named time zone.
    private func toRealDate(in zone: String) -> (Date) -> Date {
        let timeZone = TimeZone(identifier: zone)!
        return { $0.addingTimeInterval(-Double(timeZone.secondsFromGMT(for: $0))) }
    }

    /// 09:00Z in the pkginfo means 09:00 local on each machine.
    @Test func stepsOpenAtLocalTime() throws {
        let rollout = try deployment(["start": date("2026-10-20 09:00"), "end": date("2026-10-20 17:00")])
        let losAngeles = toRealDate(in: "America/Los_Angeles") // UTC-7 in October
        #expect(rollout.state(at: date("2026-10-20 15:59"), toRealDate: losAngeles).currentPercent == 0)
        #expect(rollout.state(at: date("2026-10-20 16:00"), toRealDate: losAngeles).currentPercent == 12)

        let tokyo = toRealDate(in: "Asia/Tokyo") // UTC+9
        #expect(rollout.state(at: date("2026-10-19 23:59"), toRealDate: tokyo).currentPercent == 0)
        #expect(rollout.state(at: date("2026-10-20 00:00"), toRealDate: tokyo).currentPercent == 12)
    }

    /// Each step converts on its own date, so a clock change moves the steps after it. Clocks
    /// change on a Sunday in the US, so this one changes on a Monday, as they do elsewhere.
    @Test func aClockChangeMovesTheStepsAfterIt() throws {
        let change = date("2026-10-20 00:00")
        let toRealDate: (Date) -> Date = { $0.addingTimeInterval($0 < change ? 8 * 3600 : 7 * 3600) }
        let rollout = try deployment(["start": date("2026-10-19 22:00"), "percent_per_hour": 10])
        // 23:00 before the change is 07:00 UTC
        #expect(rollout.state(at: date("2026-10-20 06:59"), toRealDate: toRealDate).currentPercent == 10)
        #expect(rollout.state(at: date("2026-10-20 07:00"), toRealDate: toRealDate).currentPercent == 30)
        // 01:00 after it is 08:00 UTC
        #expect(rollout.state(at: date("2026-10-20 07:59"), toRealDate: toRealDate).currentPercent == 30)
        #expect(rollout.state(at: date("2026-10-20 08:00"), toRealDate: toRealDate).currentPercent == 40)
    }

    @Test func staticStartDateIsConverted() throws {
        let canary = try deployment(["start": date("2026-11-05 00:00"), "percent": 5])
        let state = canary.state(at: date("2026-11-01 00:00"), toRealDate: toRealDate(in: "Asia/Tokyo"))
        #expect(state.nextStepDate == date("2026-11-04 15:00"))
    }

    @Test func returnedDatesAreConverted() throws {
        let rollout = try deployment(["start": date("2026-10-20 09:00"), "end": date("2026-10-20 17:00")])
        let state = rollout.state(at: date("2026-10-20 12:00"), toRealDate: toRealDate(in: "America/Los_Angeles"))
        #expect(state.nextStepDate == date("2026-10-20 16:00"))
        #expect(state.nextIncreaseDate == date("2026-10-20 16:00"))
    }

    @Test func staticStartUsesLocalTime() throws {
        let canary = try deployment(["start": date("2026-11-05 00:00"), "percent": 5])
        let tokyo = toRealDate(in: "Asia/Tokyo")
        #expect(canary.state(at: date("2026-11-04 14:59"), toRealDate: tokyo).currentPercent == 0)
        #expect(canary.state(at: date("2026-11-04 15:00"), toRealDate: tokyo).currentPercent == 5)
    }
}

struct DeploymentPropertyTests {
    /// Walks each schedule in half hours and checks what should hold for any deployment.
    @Test func schedulesBehaveAtEveryPoint() throws {
        let start = date("2026-10-12 00:00")
        let schedules: [[String: Any]] = [
            ["start": start, "end": date("2026-10-24 00:00")],
            ["start": date("2026-10-14 08:30"), "end": date("2026-10-27 16:45")],
            ["start": date("2026-10-14 08:30"), "end": date("2026-10-18 12:00"), "step_hours": 5],
            ["start": date("2026-10-17 08:30"), "end": date("2026-10-26 12:00"), "step_hours": 24],
            ["start": date("2026-10-16 20:15"), "percent_per_hour": 7],
            ["start": date("2026-10-16 20:15"), "percent_per_step": 3, "step_hours": 7],
            ["start": start, "percent_per_day": 7],
            ["start": date("2026-10-15 13:00"), "percent_per_step": 13, "step_hours": 24],
        ]
        for dict in schedules {
            let rollout = try deployment(dict)
            var previous = 0
            for halfHour in 0 ..< (2 * 24 * 7 * 8) {
                let now = start.addingTimeInterval(Double(halfHour) * 1800)
                let state = rollout.state(at: now)
                #expect(state.currentPercent >= previous)
                #expect((0 ... 100).contains(state.currentPercent))
                #expect((state.currentPercent == 100) == (state.status == .complete))

                if state.currentPercent != 100 {
                    let nextStep = try #require(state.nextStepDate)
                    let nextIncrease = try #require(state.nextIncreaseDate)
                    #expect(nextStep > now)
                    #expect(nextIncrease >= nextStep)
                    #expect(rollout.state(at: nextStep).step == (state.step ?? 0) + 1)
                    #expect(rollout.state(at: nextIncrease).currentPercent > state.currentPercent)
                    #expect(rollout.state(at: nextIncrease.addingTimeInterval(-1)).currentPercent == state.currentPercent)
                }
                previous = state.currentPercent
            }
            #expect(previous == 100)
        }
    }

    /// A step only opens on a weekend when it's the end of a start/end deployment.
    @Test func noStepOpensOnAWeekend() throws {
        let rollout = try deployment(["start": date("2026-10-16 20:00"), "percent_per_hour": 1])
        var now = date("2026-10-17 00:00")
        let friday = rollout.state(at: date("2026-10-16 23:59")).currentPercent
        #expect(friday == 4)
        while now < date("2026-10-19 00:00") {
            #expect(rollout.state(at: now).currentPercent == friday)
            now.addTimeInterval(1800)
        }
        #expect(percent(rollout, "2026-10-19 00:00") == 5)
    }
}

struct DeploymentValidationTests {
    private let start = date("2026-10-20 09:00")
    private let end = date("2026-10-20 17:00")

    private func expectInvalid(_ value: Any?, sourceLocation: SourceLocation = #_sourceLocation) {
        #expect(throws: MunkiError.self, sourceLocation: sourceLocation) {
            try Deployment(value)
        }
    }

    @Test func notADictionary() {
        expectInvalid(nil)
        expectInvalid("deployment")
        expectInvalid(["percent"])
    }

    @Test func noMode() {
        expectInvalid([String: Any]())
        expectInvalid(["start": start])
        expectInvalid(["start": start, "step_hours": 2])
    }

    @Test func moreThanOneMode() {
        expectInvalid(["start": start, "end": end, "percent_per_hour": 10])
        expectInvalid(["start": start, "end": end, "percent_per_day": 10])
        expectInvalid(["start": start, "end": end, "percent": 10])
        expectInvalid(["start": start, "percent_per_hour": 10, "percent_per_day": 10])
        expectInvalid(["start": start, "percent_per_hour": 10, "percent": 10])
        expectInvalid(["percent_per_day": 10, "percent": 10])
        expectInvalid(["start": start, "end": end, "percent_per_step": 10, "step_hours": 2])
        expectInvalid(["start": start, "percent_per_hour": 10, "percent_per_step": 10, "step_hours": 2])
        expectInvalid(["start": start, "percent_per_day": 10, "percent_per_step": 10, "step_hours": 2])
        expectInvalid(["percent": 10, "percent_per_step": 10, "step_hours": 2])
    }

    @Test func datedModeWithoutStart() {
        expectInvalid(["end": end])
        expectInvalid(["percent_per_hour": 10])
        expectInvalid(["percent_per_day": 10])
        expectInvalid(["percent_per_step": 10, "step_hours": 2])
    }

    /// Any step_hours is invalid on these, even 1, so the rule stays simple.
    @Test func hourAndDayRatesRejectStepHours() {
        for stepHours in [1, 2, 24] {
            expectInvalid(["start": start, "percent_per_hour": 10, "step_hours": stepHours])
            expectInvalid(["start": start, "percent_per_day": 10, "step_hours": stepHours])
        }
    }

    @Test func percentPerStepRequiresStepHours() {
        expectInvalid(["start": start, "percent_per_step": 10])
    }

    /// The first step is the number the admin wrote, so 100 is clear and valid.
    @Test func percentPerStepOfOneHundredIsEveryoneAtStart() throws {
        let rollout = try deployment(["start": start, "percent_per_step": 100, "step_hours": 24])
        #expect(rollout.state(at: start).currentPercent == 100)
        #expect(rollout.state(at: start).totalSteps == 1)
    }

    @Test func staticWithBadStartIsInvalid() {
        expectInvalid(["start": "2026-11-05T00:00:00Z", "percent": 5])
        expectInvalid(["start": Date(timeIntervalSince1970: 1e30), "percent": 5])
    }

    @Test func endAtOrBeforeStart() {
        expectInvalid(["start": end, "end": end])
        expectInvalid(["start": end, "end": start])
    }

    @Test func badDates() {
        expectInvalid(["start": "2026-10-20T09:00:00Z", "end": end])
        expectInvalid(["start": start, "end": "2026-10-20T17:00:00Z"])
        expectInvalid(["start": 12345, "percent_per_hour": 10])
        // these would trap converting to Int if they weren't rejected
        expectInvalid(["start": Date(timeIntervalSince1970: 1e30), "percent_per_hour": 10])
        expectInvalid(["start": Date(timeIntervalSince1970: -1e30), "percent_per_hour": 10])
        expectInvalid(["start": Date(timeIntervalSince1970: .infinity), "percent_per_hour": 10])
        expectInvalid(["start": Date(timeIntervalSince1970: .nan), "percent_per_hour": 10])
        expectInvalid(["start": start, "end": Date(timeIntervalSince1970: 1e30)])
    }

    @Test func percentAndRatesOutOfRangeOrWrongType() {
        let badValues: [Any] = [0, -1, 101, 5.5, 5.0, true, "5"]
        for value in badValues {
            expectInvalid(["percent": value])
            expectInvalid(["start": start, "percent_per_hour": value])
            expectInvalid(["start": start, "percent_per_day": value])
            expectInvalid(["start": start, "percent_per_step": value, "step_hours": 2])
        }
    }

    @Test func percentAndRateBoundsAreValid() throws {
        for value in [1, 100] {
            _ = try deployment(["percent": value])
            _ = try deployment(["start": start, "percent_per_hour": value])
            _ = try deployment(["start": start, "percent_per_day": value])
            _ = try deployment(["start": start, "percent_per_step": value, "step_hours": 2])
        }
    }

    @Test func badStepHours() {
        let badValues: [Any] = [0, -1, 1.5, 2.0, true, "2"]
        for value in badValues {
            expectInvalid(["start": start, "end": end, "step_hours": value])
            expectInvalid(["start": start, "percent_per_step": 10, "step_hours": value])
        }
    }

    @Test func hugeStepHoursDoesNotOverflow() throws {
        let startEnd = try deployment(["start": start, "end": end, "step_hours": Int.max])
        #expect(startEnd.state(at: start).totalSteps == 2)
        #expect(percent(startEnd, "2026-10-20 17:00") == 100)

        let perStep = try deployment(["start": start, "percent_per_step": 1, "step_hours": Int.max])
        #expect(perStep.state(at: start).currentPercent == 1)
        #expect(perStep.state(at: start).totalSteps == 100)
    }

    @Test func farOffDatesStayFast() throws {
        // over 12 million steps, so counting conversions catches a linear search
        let rollout = try deployment(["start": start, "end": date("4000-12-31 00:00")])
        var conversions = 0
        let state = rollout.state(at: date("3000-06-05 12:00")) { date in
            conversions += 1
            return date
        }
        #expect(state.status == .inProgress)
        #expect(conversions < 64)
    }

    @Test func plistRoundTrip() throws {
        let xml = """
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0"><dict>
            <key>valid</key><dict>
                <key>start</key><date>2026-10-12T00:00:00Z</date>
                <key>percent_per_step</key><integer>10</integer>
                <key>step_hours</key><integer>24</integer>
            </dict>
            <key>boolean</key><dict><key>percent</key><true/></dict>
            <key>real</key><dict><key>percent</key><real>5</real></dict>
            <key>stepBoolean</key><dict>
                <key>start</key><date>2026-10-12T00:00:00Z</date>
                <key>percent_per_step</key><integer>10</integer>
                <key>step_hours</key><true/>
            </dict>
            <key>stepReal</key><dict>
                <key>start</key><date>2026-10-12T00:00:00Z</date>
                <key>percent_per_step</key><integer>10</integer>
                <key>step_hours</key><real>2</real>
            </dict>
            <key>stringDate</key><dict>
                <key>start</key><string>2026-10-12T00:00:00Z</string>
                <key>percent_per_day</key><integer>10</integer>
            </dict>
        </dict></plist>
        """
        let plist = try #require(
            PropertyListSerialization.propertyList(from: Data(xml.utf8), format: nil) as? [String: Any]
        )
        #expect(percent(try Deployment(plist["valid"]), "2026-10-13 00:00") == 20)
        expectInvalid(plist["boolean"])
        expectInvalid(plist["real"])
        expectInvalid(plist["stringDate"])
        expectInvalid(plist["stepBoolean"])
        expectInvalid(plist["stepReal"])
    }

    @Test func reasonsNameTheProblem() {
        let missingStart = #expect(throws: MunkiError.self) {
            try Deployment(["percent_per_day": 10])
        }
        #expect(missingStart?.description == "deployment percent_per_day requires start")
        let twoModes = #expect(throws: MunkiError.self) {
            try Deployment(["start": start, "end": end, "percent": 10])
        }
        #expect(twoModes?.description == "deployment has more than one mode: end, percent")
    }
}

struct DeployPercentHashTests {
    /// These values were calculated separately, with Python's hashlib. They must never change:
    /// if they do, machines move to different groups in every running deployment.
    @Test func hashIsStable() {
        #expect(machineDeployPercent(identifier: "C02ABC123DEF") == 89)
        #expect(machineDeployPercent(identifier: "VM0000000001") == 72)
        #expect(machineDeployPercent(identifier: "564D1234-ABCD-4EF0-9123-456789ABCDEF") == 92)
        #expect(packageDeployPercent(identifier: "C02ABC123DEF", itemName: "Firefox") == 36)
        #expect(packageDeployPercent(identifier: "C02ABC123DEF", itemName: "Zoom") == 73)
        #expect(packageDeployPercent(identifier: "VM0000000001", itemName: "Firefox") == 96)
        #expect(packageDeployPercent(identifier: "Ünï", itemName: "Fïrefox") == 75)
    }

    @Test func noIdentifierIsTheLastGroup() {
        #expect(machineDeployPercent(identifier: nil) == 100)
        #expect(packageDeployPercent(identifier: nil, itemName: "Firefox") == 100)
    }

    @Test func identifierPrefersSerial() {
        #expect(deployPercentIdentifier(serial: "ABC", hardwareUUID: "UUID") == "ABC")
        #expect(deployPercentIdentifier(serial: nil, hardwareUUID: "UUID") == "UUID")
        #expect(deployPercentIdentifier(serial: "", hardwareUUID: "UUID") == "UUID")
        #expect(deployPercentIdentifier(serial: "UNKNOWN", hardwareUUID: "UUID") == "UUID")
        #expect(deployPercentIdentifier(serial: "UNKNOWN", hardwareUUID: "") == nil)
        #expect(deployPercentIdentifier(serial: nil, hardwareUUID: nil) == nil)
    }

    /// The groups need to be about even, or a "10%" step won't reach about 10% of machines.
    /// The input is fixed, so this can't be flaky.
    @Test func valuesAreSpreadEvenly() {
        var counts = [Int: Int]()
        var saltedCounts = [Int: Int]()
        for index in 0 ..< 100_000 {
            let identifier = "SERIAL\(index)"
            counts[machineDeployPercent(identifier: identifier), default: 0] += 1
            saltedCounts[packageDeployPercent(identifier: identifier, itemName: "Firefox"), default: 0] += 1
        }
        for buckets in [counts, saltedCounts] {
            #expect(buckets.count == 100)
            #expect(buckets.keys.min() == 1)
            #expect(buckets.keys.max() == 100)
            #expect(buckets.values.allSatisfy { (850 ... 1150).contains($0) })
        }
    }
}

/// C02ABC123DEF's package_deploy_percent is 36 for Firefox and 73 for Zoom.
private let testSerial = "C02ABC123DEF"
private let testCatalogs = ["deployment_tests"]
private let notStarted: [String: Any] = ["start": date("2099-01-05 00:00"), "percent": 100]
private let installedPath = "/bin/ls"
private let missingPath = "/private/tmp/munki-deployment-tests-does-not-exist"
/// Some version is on disk, but not this one: the file exists with a different checksum.
private let otherVersionInstalled: PlistDict = [
    "installs": [["type": "file", "path": installedPath, "md5checksum": "00000000000000000000000000000000"]],
]

private func seedCatalog(_ items: [PlistDict], serial: String? = testSerial, uuid: String? = nil) {
    var facts: PlistDict = ["os_vers": "15.0", "arch": "arm64", "munki_version": "7.5.0"]
    facts["serial_number"] = serial
    facts["hardware_uuid"] = uuid
    MachineFacts.shared.facts = facts
    Catalogs.shared.set(testCatalogs[0], to: makeCatalogDB(items))
    DeploymentRecords.shared.reset()
}

/// A nopkg item, so nothing downloads. It's "installed" if its path exists.
private func item(
    _ name: String,
    _ version: String,
    percent: Int? = nil,
    deployment: [String: Any]? = nil,
    path: String = missingPath,
    extra: PlistDict = [:]
) -> PlistDict {
    var pkginfo: PlistDict = [
        "name": name,
        "version": version,
        "installer_type": "nopkg",
        "installs": [["type": "file", "path": path]],
    ]
    if let percent {
        pkginfo["deployment"] = ["percent": percent]
    }
    if let deployment {
        pkginfo["deployment"] = deployment
    }
    return pkginfo.merging(extra) { _, new in new }
}

private func lookup(
    _ name: String,
    skipMinimumOSCheck: Bool = false
) async -> String? {
    let pkginfo = await getItemDetail(
        name,
        catalogList: testCatalogs,
        skipMinimumOSCheck: skipMinimumOSCheck,
        suppressWarnings: true
    )
    return pkginfo?["version"] as? String
}

private func entry(_ installInfo: PlistDict, _ name: String) -> PlistDict? {
    let entries = (installInfo["managed_installs"] as? [PlistDict] ?? []).filter { $0["name"] as? String == name }
    #expect(entries.count <= 1)
    return entries.first
}

/// All of these share singletons, so they can't run at the same time. Some also write errors and
/// warnings to Report.shared, which isn't thread-safe and which manifestsTests writes to as well,
/// so they're nested in that serialized suite rather than changing Report for the sake of tests.
extension manifestsTests {
    @Suite(.disabled(if: intPref("DeployPercentOverride") != nil, "a DeployPercentOverride preference on this machine changes the results"))
    struct DeploymentClientTests {
        // MARK: catalog lookup

        @Test func eligibleAtOrBelowTheCurrentPercent() async {
            seedCatalog([item("Firefox", "2.0", percent: 36), item("Firefox", "1.0")])
            #expect(await lookup("Firefox") == "2.0")

            seedCatalog([item("Firefox", "2.0", percent: 35), item("Firefox", "1.0")])
            #expect(await lookup("Firefox") == "1.0")
        }

        @Test func fallsBackToNextHighestEligibleVersion() async {
            seedCatalog([item("Firefox", "3.0", percent: 1), item("Firefox", "2.0", percent: 50), item("Firefox", "1.0")])
            #expect(await lookup("Firefox") == "2.0")
        }

        @Test func noEligibleVersionFindsNothing() async {
            seedCatalog([item("Firefox", "2.0", percent: 1)])
            #expect(await lookup("Firefox") == nil)
        }

        @Test func aSpecificVersionHasNoFallback() async {
            seedCatalog([item("Firefox", "2.0", percent: 1), item("Firefox", "1.0")])
            #expect(await lookup("Firefox--2.0") == nil)
        }

        @Test func noMachineIsEligibleBeforeStart() async {
            seedCatalog([item("Firefox", "2.0", deployment: notStarted)])
            #expect(await lookup("Firefox") == nil)
        }

        @Test func invalidDeploymentFailsClosed() async {
            seedCatalog([item("Firefox", "2.0", deployment: ["percent": 0]), item("Firefox", "1.0")])
            #expect(await lookup("Firefox") == "1.0")
            seedCatalog([item("Firefox", "2.0", deployment: ["percent": 0])])
            #expect(await lookup("Firefox") == nil)
        }

        @Test func otherChecksComeFirst() async {
            seedCatalog([
                item("Firefox", "3.0", percent: 1, extra: ["minimum_os_version": "99.0"]),
                item("Firefox", "2.0", percent: 1, extra: ["supported_architectures": ["x86_64"]]),
                item("Firefox", "1.5", percent: 1, extra: ["minimum_munki_version": "99.0"]),
                item("Firefox", "1.0"),
            ])
            #expect(await lookup("Firefox") == "1.0")
            #expect(deploymentReportEntries().isEmpty)
        }

        @Test func anotherRejectionStillCountsAsAProblem() async {
            seedCatalog([
                item("Firefox", "2.0", percent: 1),
                item("Firefox", "1.0", extra: ["minimum_os_version": "99.0"]),
            ])
            #expect(await lookup("Firefox") == nil)
        }

        /// The "Requires macOS X" lookup: a machine the deployment doesn't include doesn't see the version.
        @Test func skippingMinimumOSDoesNotSkipTheDeployment() async {
            seedCatalog([item("Firefox", "2.0", percent: 1, extra: ["minimum_os_version": "99.0"])])
            #expect(await lookup("Firefox", skipMinimumOSCheck: true) == nil)

            seedCatalog([item("Firefox", "2.0", percent: 36, extra: ["minimum_os_version": "99.0"])])
            #expect(await lookup("Firefox", skipMinimumOSCheck: true) == "2.0")
        }

        @Test func noIdentifierIsTheLastGroup() async {
            seedCatalog([item("Firefox", "2.0", percent: 99), item("Firefox", "1.0")], serial: "UNKNOWN", uuid: "")
            #expect(await lookup("Firefox") == "1.0")

            seedCatalog([item("Firefox", "2.0", percent: 100), item("Firefox", "1.0")], serial: "UNKNOWN", uuid: "")
            #expect(await lookup("Firefox") == "2.0")
        }

        @Test func fallsBackToHardwareUUID() async {
            let uuid = "564D1234-ABCD-4EF0-9123-456789ABCDEF"
            let percent = packageDeployPercent(identifier: uuid, itemName: "Firefox")
            seedCatalog([item("Firefox", "2.0", percent: percent), item("Firefox", "1.0")], serial: "UNKNOWN", uuid: uuid)
            #expect(await lookup("Firefox") == "2.0")
        }

        // MARK: overrides

        @Test func overridePrecedence() {
            #expect(deployPercentOverride(commandLine: nil, preference: nil) == nil)
            #expect(deployPercentOverride(commandLine: nil, preference: 5)?.value == 5)
            #expect(deployPercentOverride(commandLine: nil, preference: 5)?.source == "preference")
            #expect(deployPercentOverride(commandLine: 9, preference: 5)?.value == 9)
            #expect(deployPercentOverride(commandLine: 9, preference: 5)?.source == "command_line")
        }

        @Test func preferenceOutOfRangeIsIgnored() {
            for preference in [0, -1, 101] {
                #expect(deployPercentOverride(commandLine: nil, preference: preference) == nil)
            }
            #expect(deployPercentOverride(commandLine: nil, preference: 1)?.value == 1)
            #expect(deployPercentOverride(commandLine: nil, preference: 100)?.value == 100)
        }

        @Test func overrideOneGetsEveryStartedDeployment() async {
            seedCatalog([item("Firefox", "2.0", percent: 1), item("Firefox", "1.0")])
            DeploymentRecords.shared.commandLineDeployPercent = 1
            #expect(await lookup("Firefox") == "2.0")
        }

        @Test func overrideOneHundredSkipsAnythingBelowOneHundred() async {
            seedCatalog([item("Firefox", "2.0", percent: 99), item("Firefox", "1.0")])
            DeploymentRecords.shared.commandLineDeployPercent = 100
            #expect(await lookup("Firefox") == "1.0")

            seedCatalog([item("Firefox", "2.0", percent: 100), item("Firefox", "1.0")])
            DeploymentRecords.shared.commandLineDeployPercent = 100
            #expect(await lookup("Firefox") == "2.0")
        }

        @Test func overrideDoesNotInstallBeforeStart() async {
            seedCatalog([item("Firefox", "2.0", deployment: notStarted), item("Firefox", "1.0")])
            DeploymentRecords.shared.commandLineDeployPercent = 1
            #expect(await lookup("Firefox") == "1.0")
        }

        @Test func overrideDoesNotUseTheHash() async {
            // Firefox hashes to 36 and Zoom to 73 on this machine, but the override applies to both
            seedCatalog([item("Firefox", "2.0", percent: 50), item("Zoom", "2.0", percent: 50)])
            DeploymentRecords.shared.commandLineDeployPercent = 50
            #expect(await lookup("Firefox") == "2.0")
            #expect(await lookup("Zoom") == "2.0")
        }

        // MARK: deploy_percent fact

        @Test func factIsTheUnsaltedValue() {
            DeploymentRecords.shared.reset()
            #expect(deployPercentFact(machine: ["serial_number": testSerial]) == 89)
        }

        @Test func factWithNoIdentifierIsTheLastGroup() {
            DeploymentRecords.shared.reset()
            #expect(deployPercentFact(machine: ["serial_number": "UNKNOWN", "hardware_uuid": ""]) == 100)
        }

        /// The real fact, in the real predicate info, usable from a condition.
        @Test func aConditionCanUseTheFact() async {
            seedCatalog([])
            let info = await generatePredicateInfo()
            #expect(info["deploy_percent"] as? Int == 89)
            #expect(predicateEvaluatesAsTrue("deploy_percent == 89", infoObject: info))
            #expect(!predicateEvaluatesAsTrue("deploy_percent < 89", infoObject: info))
        }

        @Test func factUsesTheOverride() {
            DeploymentRecords.shared.reset()
            DeploymentRecords.shared.commandLineDeployPercent = 7
            #expect(deployPercentFact(machine: ["serial_number": testSerial]) == 7)
            DeploymentRecords.shared.reset()
        }

        @Test func predicateInfoIncludesTheFact() async {
            seedCatalog([])
            DeploymentRecords.shared.commandLineDeployPercent = 7
            defer { DeploymentRecords.shared.reset() }
            #expect(await generatePredicateInfo()["deploy_percent"] as? Int == 7)
        }

        // MARK: report entries

        private func reportEntry(_ name: String, _ version: String) -> PlistDict? {
            return deploymentReportEntries().first {
                $0["name"] as? String == name && $0["version"] as? String == version
            }
        }

        @Test func reportEntryForAVersionNotEligibleFor() async throws {
            seedCatalog([
                item("Firefox", "2.0", deployment: ["start": date("2099-01-05 00:00"), "percent_per_hour": 10]),
                item("Firefox", "1.0"),
            ])
            _ = await lookup("Firefox")
            let found = try #require(reportEntry("Firefox", "2.0"))
            #expect(found["package_deploy_percent"] as? Int == 36)
            #expect(found["current_deploy_percent"] as? Int == 0)
            #expect(found["eligible"] as? Bool == false)
            #expect(found["next_step_date"] is Date)
        }

        @Test func reportEntryForAnEligibleVersion() async throws {
            seedCatalog([item("Firefox", "2.0", percent: 50)])
            _ = await lookup("Firefox")
            let found = try #require(reportEntry("Firefox", "2.0"))
            #expect(found["current_deploy_percent"] as? Int == 50)
            #expect(found["eligible"] as? Bool == true)
            // a static deployment has no next step
            #expect(found["next_step_date"] == nil)
        }

        /// With over 100 steps a step can leave the percent unchanged. This is when it next rises.
        @Test func reportNextStepDateIsWhenThePercentNextRises() async throws {
            seedCatalog([item("Firefox", "2.0", deployment: ["start": date("2026-10-12 00:00"), "end": date("2026-10-24 00:00")])])
            DeploymentRecords.shared.now = subtractTZOffsetFromDate(date("2026-10-14 09:30"))
            _ = await lookup("Firefox")
            let found = try #require(reportEntry("Firefox", "2.0"))
            #expect(found["current_deploy_percent"] as? Int == 25)
            #expect(found["next_step_date"] as? Date == subtractTZOffsetFromDate(date("2026-10-14 12:00")))
        }

        @Test func noReportEntryWhenInstallableConditionFailsFirst() async {
            defer { PredicateInfo.shared.info = PlistDict() }
            PredicateInfo.shared.info = ["deploy_percent": 50]
            seedCatalog([item("Firefox", "2.0", percent: 1, extra: ["installable_condition": "deploy_percent <= 10"])])
            _ = await lookup("Firefox")
            #expect(deploymentReportEntries().isEmpty)
        }

        @Test func reportHasOneEntryPerVersion() async {
            seedCatalog([item("Firefox", "2.0", percent: 1), item("Firefox", "1.0", percent: 50), item("Firefox", "0.9")])
            _ = await lookup("Firefox")
            _ = await lookup("Firefox")
            #expect(deploymentReportEntries().map { $0["version"] as? String } == ["1.0", "2.0"])
        }

        @Test func noReportEntryForAVersionWithoutADeployment() async {
            seedCatalog([item("Firefox", "2.0"), item("Firefox", "1.0", percent: 50)])
            #expect(await lookup("Firefox") == "2.0")
            #expect(deploymentReportEntries().isEmpty)
        }

        @Test func reportEntryUsesTheOverride() async throws {
            seedCatalog([item("Firefox", "2.0", percent: 50)])
            DeploymentRecords.shared.commandLineDeployPercent = 7
            _ = await lookup("Firefox")
            #expect(try #require(reportEntry("Firefox", "2.0"))["package_deploy_percent"] as? Int == 7)
        }

        @Test func noReportEntryWhenAnotherCheckFailsFirst() async {
            seedCatalog([item("Firefox", "2.0", percent: 1, extra: ["minimum_os_version": "99.0"])])
            _ = await lookup("Firefox")
            #expect(deploymentReportEntries().isEmpty)
        }

        @Test func noReportEntryForAnInvalidDeployment() async {
            seedCatalog([item("Firefox", "2.0", deployment: ["percent": 0])])
            _ = await lookup("Firefox")
            #expect(deploymentReportEntries().isEmpty)
        }

        /// The report is saved as a plist, and one bad value stops it saving.
        @Test func reportEntriesCanBeSavedAsAPlist() async throws {
            seedCatalog([
                item("Firefox", "2.0", deployment: ["start": date("2099-01-05 00:00"), "percent_per_hour": 10]),
                item("Firefox", "1.0"),
            ])
            _ = await lookup("Firefox")
            #expect(!deploymentReportEntries().isEmpty)
            let plist: PlistDict = ["Deployments": deploymentReportEntries()]
            _ = try PropertyListSerialization.data(fromPropertyList: plist, format: .xml, options: 0)
        }

        // MARK: logging

        private func reported(_ key: String, containing text: String) -> [String] {
            return (Report.shared.retrieve(key: key) as? [String] ?? []).filter { $0.contains(text) }
        }

        /// The same two warnings as a failed installable_condition, and no error.
        @Test func noEligibleVersionWarnsLikeAFailedCondition() async {
            seedCatalog([item("LogNoFallback", "2.0", percent: 1)])
            _ = await install("LogNoFallback")
            #expect(reported("Warnings", containing: "Rejected item LogNoFallback, version 2.0 with deployment").count == 1)
            #expect(reported("Warnings", containing: "Could not process item LogNoFallback").count == 1)
            #expect(reported("Errors", containing: "LogNoFallback").isEmpty)

            seedCatalog([item("LogNoFallback2", "2.0", extra: ["installable_condition": "FALSEPREDICATE"])])
            _ = await install("LogNoFallback2")
            #expect(reported("Warnings", containing: "Rejected item LogNoFallback2, version 2.0 with installable_condition").count == 1)
            #expect(reported("Warnings", containing: "Could not process item LogNoFallback2").count == 1)
        }

        /// A rejection isn't logged at all if another version is used, as with installable_condition.
        @Test func aFallbackIsNotAWarning() async {
            seedCatalog([item("LogFallback", "2.0", percent: 1), item("LogFallback", "1.0")])
            _ = await install("LogFallback")
            #expect(reported("Warnings", containing: "LogFallback").isEmpty)
        }

        @Test func anItemThatDoesNotExistStillWarns() async {
            seedCatalog([])
            _ = await install("LogDoesNotExist")
            #expect(reported("Warnings", containing: "LogDoesNotExist").count == 1)
        }

        @Test func anotherRejectionStillWarns() async {
            seedCatalog([
                item("LogOtherReason", "2.0", percent: 1),
                item("LogOtherReason", "1.0", extra: ["minimum_os_version": "99.0"]),
            ])
            _ = await install("LogOtherReason")
            #expect(reported("Warnings", containing: "Could not process item LogOtherReason").count == 1)
            #expect(reported("Warnings", containing: "Rejected item LogOtherReason, version 2.0 with deployment").count == 1)
            #expect(reported("Warnings", containing: "Rejected item LogOtherReason, version 1.0").count == 1)
        }

        /// Like a predicate that raises an exception: an error, then the same warnings as any rejection.
        @Test func invalidIsAnErrorAndARejection() async {
            seedCatalog([item("LogInvalid", "2.0", deployment: ["percent": 0])])
            _ = await install("LogInvalid")
            #expect(reported("Errors", containing: "LogInvalid 2.0 has an invalid deployment").count == 1)
            #expect(reported("Warnings", containing: "Rejected item LogInvalid, version 2.0 with an invalid deployment").count == 1)
            #expect(reported("Warnings", containing: "Could not process item LogInvalid").count == 1)
        }

        @Test func unavailableRequirementWarnsLikeAFailedCondition() async {
            seedCatalog([
                item("LogWaitingTop", "1.0", extra: ["requires": ["LogWaitingBase"]]),
                item("LogWaitingBase", "2.0", percent: 1),
            ])
            _ = await install("LogWaitingTop")
            #expect(!reported("Warnings", containing: "Didn't attempt to install LogWaitingTop").isEmpty)
        }

        @Test func unavailableRequirementWhenAlreadyInstalledWarnsLikeAFailedCondition() async {
            seedCatalog([
                item("LogInstalledTop", "1.0", path: installedPath, extra: ["requires": ["LogInstalledBase"]]),
                item("LogInstalledBase", "2.0", percent: 1),
            ])
            _ = await install("LogInstalledTop")
            #expect(!reported("Warnings", containing: "Could not resolve all dependencies for LogInstalledTop").isEmpty)
        }

        // MARK: autoremove

        /// autoremove works by item name and doesn't check availability, the same as for
        /// installable_condition, so a deployment doesn't change it.
        @Test func autoremoveIgnoresDeployments() {
            seedCatalog([item("Firefox", "2.0", percent: 1, extra: ["autoremove": true]), item("Firefox", "1.0")])
            #expect(getAutoRemovalItems(installInfo: PlistDict(), catalogList: testCatalogs) == ["Firefox"])
        }

        @Test func autoremoveCountsAnItemWithNoEligibleVersion() async {
            seedCatalog([item("Firefox", "2.0", percent: 1, extra: ["autoremove": true])])
            var installInfo = PlistDict()
            _ = await processInstall("Firefox", catalogList: testCatalogs, installInfo: &installInfo)
            #expect(getAutoRemovalItems(installInfo: installInfo, catalogList: testCatalogs) == ["Firefox"])
        }

        @Test func autoremoveCountsAPinnedVersionNotEligibleFor() async {
            seedCatalog([item("Firefox", "2.0", percent: 1), item("Firefox", "1.0", extra: ["autoremove": true])])
            var installInfo = PlistDict()
            _ = await processInstall("Firefox--2.0", catalogList: testCatalogs, installInfo: &installInfo)
            #expect(getAutoRemovalItems(installInfo: installInfo, catalogList: testCatalogs) == ["Firefox"])
        }

        /// An item with an unavailable requirement goes in managed_installs with a note, which
        /// keeps it from being auto-removed.
        @Test func autoremoveSkipsAnItemWithAnUnavailableRequirement() async {
            seedCatalog([
                item("Firefox", "2.0", extra: ["requires": ["Zoom"], "autoremove": true]),
                item("Zoom", "2.0", deployment: notStarted),
            ])
            var installInfo = PlistDict()
            _ = await processInstall("Firefox", catalogList: testCatalogs, installInfo: &installInfo)
            #expect(getAutoRemovalItems(installInfo: installInfo, catalogList: testCatalogs) == [])
        }

        // MARK: installs

        private func install(_ name: String) async -> (Bool, PlistDict) {
            var installInfo = PlistDict()
            let result = await processInstall(name, catalogList: testCatalogs, installInfo: &installInfo)
            return (result, installInfo)
        }

        @Test func eligibleInstallsNewestDirectly() async {
            seedCatalog([item("Firefox", "2.0", percent: 36), item("Firefox", "1.0")])
            let (result, installInfo) = await install("Firefox")
            #expect(result)
            #expect(entry(installInfo, "Firefox")?["version_to_install"] as? String == "2.0")
        }

        @Test func notEligibleInstallsTheOlderVersion() async {
            seedCatalog([item("Firefox", "2.0", percent: 1), item("Firefox", "1.0")])
            let (result, installInfo) = await install("Firefox")
            #expect(result)
            #expect(entry(installInfo, "Firefox")?["version_to_install"] as? String == "1.0")
        }

        /// 1.0 is on disk, and 1.1 is the newest version with no deployment.
        @Test func aVersionWithoutADeploymentUpdatesNow() async {
            seedCatalog([
                item("Firefox", "1.2", percent: 1, extra: otherVersionInstalled),
                item("Firefox", "1.1", extra: otherVersionInstalled),
                item("Firefox", "1.0", path: installedPath),
            ])
            let (_, installInfo) = await install("Firefox")
            #expect(entry(installInfo, "Firefox")?["version_to_install"] as? String == "1.1")
        }

        /// 2.0 is on disk at the same path as 1.0, and the machine isn't eligible for 2.0 any more.
        /// Munki's normal version check sees something newer, so nothing is queued.
        @Test func aNewerVersionAtTheSamePathIsLeftAlone() async throws {
            let bundle = FileManager.default.temporaryDirectory.appendingPathComponent("deployment-\(UUID().uuidString).bundle")
            let contents = bundle.appendingPathComponent("Contents")
            try FileManager.default.createDirectory(at: contents, withIntermediateDirectories: true)
            defer { try? FileManager.default.removeItem(at: bundle) }
            let info = try PropertyListSerialization.data(
                fromPropertyList: ["CFBundleIdentifier": "com.example.t", "CFBundleShortVersionString": "2.0"],
                format: .xml,
                options: 0
            )
            try info.write(to: contents.appendingPathComponent("Info.plist"))
            func installs(_ version: String) -> PlistDict {
                return ["installs": [["type": "bundle", "path": bundle.path, "CFBundleShortVersionString": version]]]
            }
            seedCatalog([item("Firefox", "2.0", percent: 1, extra: installs("2.0")), item("Firefox", "1.0", extra: installs("1.0"))])
            let (result, installInfo) = await install("Firefox")
            #expect(result)
            #expect(entry(installInfo, "Firefox")?["installed"] as? Bool == true)
            #expect(entry(installInfo, "Firefox")?["version_to_install"] == nil)
        }

        /// A version-pinned requirement fails the same way, and hyphens stay part of the name.
        @Test func pinnedRequirementIsAProblemItem() async {
            seedCatalog([item("Firefox", "2.0", extra: ["requires": ["Zoom--3.0"]]), item("Zoom", "3.0", deployment: notStarted)])
            let (result, installInfo) = await install("Firefox")
            #expect(!result)
            #expect(entry(installInfo, "Firefox")?["note"] != nil)
        }

        @Test func noEligibleVersionInstallsNothing() async {
            seedCatalog([item("Firefox", "2.0", percent: 1)])
            let (result, installInfo) = await install("Firefox")
            #expect(!result)
            #expect(entry(installInfo, "Firefox") == nil)
        }

        @Test func forceInstallDateOnlyAppliesOnceEligible() async {
            let forced: PlistDict = ["force_install_after_date": date("2020-01-06 00:00")]
            seedCatalog([item("Firefox", "2.0", percent: 1, extra: forced), item("Firefox", "1.0")])
            let (_, before) = await install("Firefox")
            #expect(entry(before, "Firefox")?["force_install_after_date"] == nil)

            seedCatalog([item("Firefox", "2.0", percent: 36, extra: forced), item("Firefox", "1.0")])
            let (_, after) = await install("Firefox")
            #expect(entry(after, "Firefox")?["force_install_after_date"] != nil)
        }

        // MARK: required packages

        /// A deployment only makes a version available or not, so what's required follows its own.
        @Test func aRequirementFollowsItsOwnDeployment() async {
            seedCatalog([
                item("Firefox", "2.0", percent: 36, extra: ["requires": ["Zoom"]]),
                item("Zoom", "2.0", percent: 1),
                item("Zoom", "1.0"),
            ])
            let (result, installInfo) = await install("Firefox")
            #expect(result)
            #expect(entry(installInfo, "Zoom")?["version_to_install"] as? String == "1.0")
            #expect(entry(installInfo, "Firefox")?["version_to_install"] as? String == "2.0")
        }

        @Test func notEligibleRequirementOfAnUngatedItemIsAProblemItem() async {
            seedCatalog([item("Firefox", "2.0", extra: ["requires": ["Zoom"]]), item("Zoom", "2.0", percent: 1)])
            let (result, installInfo) = await install("Firefox")
            #expect(!result)
            #expect(entry(installInfo, "Firefox")?["note"] != nil)
        }

        @Test func updateForDoesNotFollow() async {
            seedCatalog([
                item("Firefox", "2.0", percent: 36),
                item("Zoom", "2.0", percent: 1, extra: ["update_for": ["Firefox"]]),
                item("Zoom", "1.0", extra: ["update_for": ["Firefox"]]),
            ])
            let (_, installInfo) = await install("Firefox")
            #expect(entry(installInfo, "Zoom")?["version_to_install"] as? String == "1.0")
        }

        @Test func notStartedRequirementOfAnUngatedItemIsAProblemItem() async {
            seedCatalog([item("Firefox", "2.0", extra: ["requires": ["Zoom"]]), item("Zoom", "2.0", deployment: notStarted)])
            let (result, installInfo) = await install("Firefox")
            #expect(!result)
            #expect(entry(installInfo, "Firefox")?["note"] != nil)
        }

        @Test func aProblemCarriesUpAChain() async {
            seedCatalog([
                item("Top", "1.0", extra: ["requires": ["Firefox"]]),
                item("Firefox", "2.0", extra: ["requires": ["Zoom"]]),
                item("Zoom", "2.0", deployment: notStarted),
            ])
            let (result, installInfo) = await install("Top")
            #expect(!result)
            #expect(entry(installInfo, "Top")?["note"] != nil)
        }

        // MARK: requirements of an item with a deployment

        /// A's deployment doesn't change B's, and B has no other version available.
        @Test func aRequirementTheDeploymentDoesNotIncludeIsAProblemItem() async {
            for (requirement, zoom1) in [("Zoom", nil), ("apps/Zoom", nil), ("Zoom--2.0", item("Zoom", "1.0"))] as [(String, PlistDict?)] {
                seedCatalog([
                    item("Firefox", "2.0", percent: 36, extra: ["requires": [requirement]]),
                    item("Zoom", "2.0", percent: 1),
                ] + (zoom1.map { [$0] } ?? []))
                let (result, installInfo) = await install("Firefox")
                #expect(!result)
                #expect(entry(installInfo, "Zoom") == nil)
                #expect(entry(installInfo, "Firefox")?["note"] != nil)
            }
        }

        /// The whole chain stops at the requirement with no available version.
        @Test func aProblemCarriesUpAChainOfDeployments() async {
            seedCatalog([
                item("Firefox", "2.0", percent: 36, extra: ["requires": ["Zoom"]]),
                item("Zoom", "2.0", percent: 100, extra: ["requires": ["Chrome"]]),
                item("Chrome", "2.0", deployment: notStarted),
            ])
            let (result, installInfo) = await install("Firefox")
            #expect(!result)
            #expect(entry(installInfo, "Chrome") == nil)
            #expect(entry(installInfo, "Zoom")?["note"] != nil)
            #expect(entry(installInfo, "Firefox")?["note"] != nil)
        }

        /// Machines keep the installed version of A, and A is still reported as a problem.
        @Test func anInstalledVersionStaysWhenTheNewOnesRequirementIsUnavailable() async {
            seedCatalog([
                item("Firefox", "2.0", percent: 36, extra: otherVersionInstalled.merging(["requires": ["Zoom"]]) { _, new in new }),
                item("Firefox", "1.0", path: installedPath),
                item("Zoom", "2.0", percent: 1),
            ])
            let (result, installInfo) = await install("Firefox")
            #expect(!result)
            #expect(entry(installInfo, "Firefox")?["note"] != nil)
        }

        @Test func aRejectedVersionsRequirementsAreNotProcessed() async {
            seedCatalog([
                item("Firefox", "2.0", percent: 1, extra: ["requires": ["Zoom"]]),
                item("Firefox", "1.0"),
                item("Zoom", "2.0", percent: 1),
            ])
            let (_, installInfo) = await install("Firefox")
            #expect(entry(installInfo, "Zoom") == nil)
            #expect(entry(installInfo, "Firefox")?["version_to_install"] as? String == "1.0")
        }

        @Test func updateForWithNoAvailableVersionIsSkipped() async {
            seedCatalog([
                item("Firefox", "2.0", percent: 36),
                item("Zoom", "2.0", percent: 1, extra: ["update_for": ["Firefox"]]),
            ])
            let (_, installInfo) = await install("Firefox")
            #expect(entry(installInfo, "Zoom") == nil)
        }

        @Test func invalidRequirementIsAProblemItem() async {
            seedCatalog([item("Firefox", "2.0", percent: 36, extra: ["requires": ["Zoom"]]), item("Zoom", "2.0", deployment: ["percent": 0])])
            let (result, installInfo) = await install("Firefox")
            #expect(!result)
            #expect(entry(installInfo, "Firefox")?["note"] != nil)
        }

        @Test func requirementWithAPathIsAProblemItem() async {
            seedCatalog([item("Firefox", "2.0", extra: ["requires": ["apps/Zoom"]]), item("Zoom", "2.0", deployment: notStarted)])
            let (result, installInfo) = await install("Firefox")
            #expect(!result)
            #expect(entry(installInfo, "Firefox")?["note"] != nil)
        }

        @Test func aRealDependencyProblemIsStillAProblem() async {
            seedCatalog([item("Firefox", "2.0", percent: 36, extra: ["requires": ["DoesNotExist"]])])
            let (result, installInfo) = await install("Firefox")
            #expect(!result)
            #expect(entry(installInfo, "Firefox")?["note"] != nil)
        }

        /// An admin may want Zoom 2.0 and 3.0 both installed at different paths. Pinning 2.0 means
        /// 2.0, as it always has, whatever else is installed and whatever was looked up first.
        @Test func aPinnedVersionInstallsAlongsideANewerOne() async {
            let items = [
                item("Zoom", "3.0", deployment: notStarted, path: installedPath),
                item("Zoom", "2.0", path: missingPath),
            ]
            seedCatalog(items)
            let (result, installInfo) = await install("Zoom--2.0")
            #expect(result)
            #expect(entry(installInfo, "Zoom")?["version_to_install"] as? String == "2.0")

            seedCatalog(items)
            _ = await lookup("Zoom")
            #expect(reportEntry("Zoom", "3.0")?["eligible"] as? Bool == false)
            let (_, afterLookup) = await install("Zoom--2.0")
            #expect(entry(afterLookup, "Zoom")?["version_to_install"] as? String == "2.0")
        }

        /// With no deployment anywhere, all of this has to match Munki's existing behavior.
        @Test func itemsWithoutADeploymentAreUntouched() async {
            seedCatalog([
                item("Firefox", "2.0", extra: ["requires": ["Zoom--3.0"], "autoremove": true]),
                item("Zoom", "2.0", path: installedPath),
                item("Zoom", "1.0"),
            ])
            var installInfo = PlistDict()
            _ = await processInstall("Zoom", catalogList: testCatalogs, installInfo: &installInfo)
            // existing behavior: any processed version counts as meeting a pinned requirement
            #expect(await processInstall("Firefox", catalogList: testCatalogs, installInfo: &installInfo))
            #expect(deploymentReportEntries().isEmpty)
            #expect(getAutoRemovalItems(installInfo: PlistDict(), catalogList: testCatalogs) == ["Firefox"])
        }

        /// A deployment that rejects a required item has to look the same as a failed installable_condition.
        @Test func unavailableRequirementMatchesAFailedCondition() async {
            seedCatalog([
                item("Firefox", "2.0", extra: ["requires": ["Zoom"]]),
                item("Zoom", "2.0", percent: 1),
            ])
            let (_, viaDeployment) = await install("Firefox")
            seedCatalog([
                item("Firefox", "2.0", extra: ["requires": ["Zoom"]]),
                item("Zoom", "2.0", extra: ["installable_condition": "FALSEPREDICATE"]),
            ])
            let (_, viaCondition) = await install("Firefox")
            #expect(entry(viaDeployment, "Firefox")?["note"] as? String == entry(viaCondition, "Firefox")?["note"] as? String)
            #expect(entry(viaDeployment, "Firefox")?["note"] != nil)
        }

        // MARK: removals

        private let removable: PlistDict = [
            "uninstallable": true, "uninstall_method": "uninstall_script", "uninstall_script": "#!/bin/sh\n",
        ]

        /// A specific version is looked up like any other, as with installable_condition.
        @Test func removingASpecificVersionFollowsItsDeployment() async {
            seedCatalog([item("Firefox", "2.0", percent: 1, path: installedPath, extra: removable)])
            var installInfo = PlistDict()
            #expect(await !processRemoval("Firefox--2.0", catalogList: testCatalogs, installInfo: &installInfo))
            #expect((installInfo["removals"] as? [PlistDict] ?? []).isEmpty)

            seedCatalog([item("Firefox", "2.0", path: installedPath, extra: removable.merging(["installable_condition": "FALSEPREDICATE"]) { _, new in new })])
            var viaCondition = PlistDict()
            #expect(await !processRemoval("Firefox--2.0", catalogList: testCatalogs, installInfo: &viaCondition))
        }

        /// Without a version, removal looks at every version by name and checks nothing.
        @Test func removingByNameIgnoresDeployments() async {
            seedCatalog([item("Firefox", "2.0", percent: 1, path: installedPath, extra: removable)])
            var installInfo = PlistDict()
            _ = await processRemoval("Firefox", catalogList: testCatalogs, installInfo: &installInfo)
            let removals = installInfo["removals"] as? [PlistDict] ?? []
            #expect(removals.contains { $0["name"] as? String == "Firefox" })
        }

        /// Munki's existing rule: an item already processed counts as meeting an unpinned requirement,
        /// and a deployment doesn't change the install list once it's built.
        @Test func aRequirementLeavesAVersionProcessedEarlier() async {
            seedCatalog([
                item("Firefox", "2.0", percent: 36, extra: ["requires": ["Zoom"]]),
                item("Zoom", "2.0", percent: 1),
                item("Zoom", "1.0"),
            ])
            var installInfo = PlistDict()
            _ = await processInstall("Zoom", catalogList: testCatalogs, installInfo: &installInfo)
            #expect(await processInstall("Firefox", catalogList: testCatalogs, installInfo: &installInfo))
            let order = (installInfo["managed_installs"] as? [PlistDict] ?? []).map { $0["version_to_install"] as? String }
            #expect(order == ["1.0", "2.0"])
        }

        /// Munki's existing rule: any processed version counts as meeting a pinned requirement, and
        /// the first one processed wins. A deployment on the version doesn't change that.
        @Test func aProcessedVersionMeetsAPinnedRequirement() async {
            for zoom3 in [item("Zoom", "3.0", percent: 1), item("Zoom", "3.0", deployment: notStarted)] {
                seedCatalog([
                    item("Firefox", "2.0", percent: 36, extra: ["requires": ["Zoom--3.0"]]),
                    zoom3,
                    item("Zoom", "1.0"),
                ])
                var installInfo = PlistDict()
                _ = await processInstall("Zoom", catalogList: testCatalogs, installInfo: &installInfo)
                #expect(await processInstall("Firefox", catalogList: testCatalogs, installInfo: &installInfo))
                #expect(entry(installInfo, "Zoom")?["version_to_install"] as? String == "1.0")
                #expect(entry(installInfo, "Firefox")?["version_to_install"] as? String == "2.0")
            }
        }

        /// The first one processed wins here too: the requirement's version, then the manifest's is skipped.
        @Test func aPinnedRequirementProcessedFirstWins() async {
            seedCatalog([
                item("Firefox", "2.0", percent: 36, extra: ["requires": ["Zoom--2.0"]]),
                item("Zoom", "2.0"),
                item("Zoom", "1.0"),
            ])
            var installInfo = PlistDict()
            _ = await processInstall("Firefox", catalogList: testCatalogs, installInfo: &installInfo)
            #expect(await processInstall("Zoom--1.0", catalogList: testCatalogs, installInfo: &installInfo))
            #expect(entry(installInfo, "Zoom")?["version_to_install"] as? String == "2.0")
        }

        /// No available version means it isn't offered, as with installable_condition.
        @Test func optionalUninstallFollowsTheDeployment() async {
            seedCatalog([item("Firefox", "2.0", percent: 1, path: installedPath, extra: removable)])
            var installInfo = PlistDict()
            await processOptionalUninstall("Firefox", catalogList: testCatalogs, installInfo: &installInfo)
            #expect(installInfo["optional_uninstalls"] == nil)
            #expect(installInfo["optional_installs"] == nil)
        }

        // MARK: managed updates

        @Test func managedUpdateWaitsForEligibility() async {
            seedCatalog([item("Firefox", "2.0", percent: 1, extra: otherVersionInstalled), item("Firefox", "1.0", path: installedPath)])
            var installInfo = PlistDict()
            await processManagedUpdate("Firefox", catalogList: testCatalogs, installInfo: &installInfo)
            #expect(entry(installInfo, "Firefox")?["installed"] as? Bool == true)
            #expect(entry(installInfo, "Firefox")?["version_to_install"] == nil)
        }

        @Test func managedUpdateOffersTheVersionOnceEligible() async {
            seedCatalog([item("Firefox", "2.0", percent: 36, extra: otherVersionInstalled), item("Firefox", "1.0", path: installedPath)])
            var installInfo = PlistDict()
            await processManagedUpdate("Firefox", catalogList: testCatalogs, installInfo: &installInfo)
            #expect(entry(installInfo, "Firefox")?["version_to_install"] as? String == "2.0")
        }

        // MARK: optional installs

        private func optional(_ name: String) async -> PlistDict? {
            var installInfo = PlistDict()
            await processOptionalInstall(name, catalogList: testCatalogs, installInfo: &installInfo)
            let entries = installInfo["optional_installs"] as? [PlistDict] ?? []
            return entries.first { $0["name"] as? String == name }
        }

        /// 1.0 is installed and 2.0 is rolling out. Only 1.0 is available, and it can be uninstalled.
        @Test func optionalOffersOnlyTheEligibleVersion() async throws {
            seedCatalog([
                item("Firefox", "2.0", percent: 1, path: missingPath),
                item("Firefox", "1.0", path: installedPath, extra: ["uninstallable": true, "uninstall_method": "uninstall_script"]),
            ])
            let found = try #require(await optional("Firefox"))
            #expect(found["version_to_install"] as? String == "1.0")
            #expect(found["installed"] as? Bool == true)
            #expect(found["needs_update"] as? Bool == false)
            #expect(found["uninstallable"] as? Bool == true)
        }

        @Test func optionalOffersTheUpdateOnceEligible() async throws {
            seedCatalog([
                item("Firefox", "2.0", percent: 36, extra: otherVersionInstalled),
                item("Firefox", "1.0", path: installedPath),
            ])
            let found = try #require(await optional("Firefox"))
            #expect(found["version_to_install"] as? String == "2.0")
            #expect(found["needs_update"] as? Bool == true)
        }

        @Test func optionalWithNoEligibleVersionIsNotListed() async {
            seedCatalog([item("Firefox", "2.0", percent: 1)])
            #expect(await optional("Firefox") == nil)
        }
    }
}

struct DeploymentOptionsTests {
    private func value(_ arguments: [String]) throws -> PlistDict? {
        return try DeploymentOptions.parse(arguments).pkginfoValue()
    }

    /// Checks the message too, so a typo in an option name can't pass for the rule being tested
    private func expectRejected(_ arguments: [String], _ message: String, sourceLocation: SourceLocation = #_sourceLocation) {
        do {
            _ = try DeploymentOptions.parse(arguments)
            Issue.record("\(arguments) was accepted", sourceLocation: sourceLocation)
        } catch {
            let actual = DeploymentOptions.message(for: error)
            #expect(actual.contains(message), "\(actual)", sourceLocation: sourceLocation)
        }
    }

    @Test func noOptionsMeansNoDeployment() throws {
        #expect(try value([]) == nil)
    }

    @Test func eachOptionSetsItsKey() throws {
        let startEnd = try #require(try value([
            "--deployment-start", "2026-10-12T09:00:00Z",
            "--deployment-end", "2026-10-13T17:00:00Z",
            "--deployment-step-hours", "2",
        ]))
        #expect(startEnd["start"] as? Date == date("2026-10-12 09:00"))
        #expect(startEnd["end"] as? Date == date("2026-10-13 17:00"))
        #expect(startEnd["step_hours"] as? Int == 2)
        #expect(startEnd.count == 3)

        let start = "2026-10-12T00:00:00Z"
        #expect(try value(["--deployment-start", start, "--deployment-percent-per-hour", "10"])?["percent_per_hour"] as? Int == 10)
        #expect(try value(["--deployment-start", start, "--deployment-percent-per-day", "20"])?["percent_per_day"] as? Int == 20)
        let perStep = try value(["--deployment-start", start, "--deployment-percent-per-step", "10", "--deployment-step-hours", "24"])
        #expect(perStep?["percent_per_step"] as? Int == 10)
        #expect(perStep?["step_hours"] as? Int == 24)
        #expect(try value(["--deployment-percent", "5"])?["percent"] as? Int == 5)
        #expect(try value(["--deployment-percent", "5", "--deployment-start", start])?["start"] as? Date == date("2026-10-12 00:00"))
    }

    /// The flags have to reach the pkginfo, as a real date.
    @Test func makepkginfoWritesTheDeployment() throws {
        let options = try PkginfoOptions(
            override: .parse(["--name", "Firefox", "--pkgvers", "1.0"]),
            script: .parse([]),
            dmg: .parse([]),
            pkg: .parse([]),
            force: .parse([]),
            deployment: .parse(["--deployment-start", "2026-10-12T00:00:00Z", "--deployment-percent-per-day", "10"]),
            installs: .parse([]),
            type: .parse(["--nopkg"]),
            other: .parse([]),
            hidden: .parse([])
        )
        let deployment = try #require(try makepkginfo(nil, options: options)["deployment"] as? PlistDict)
        #expect(deployment["start"] as? Date == date("2026-10-12 00:00"))
        #expect(deployment["percent_per_day"] as? Int == 10)
    }

    @Test func noFlagsMeansNoDeploymentKey() throws {
        let options = try PkginfoOptions(
            override: .parse(["--name", "Firefox", "--pkgvers", "1.0"]),
            script: .parse([]),
            dmg: .parse([]),
            pkg: .parse([]),
            force: .parse([]),
            deployment: .parse([]),
            installs: .parse([]),
            type: .parse(["--nopkg"]),
            other: .parse([]),
            hidden: .parse([])
        )
        #expect(try makepkginfo(nil, options: options)["deployment"] == nil)
    }

    @Test func invalidCombinationsAreRejected() {
        let start = ["--deployment-start", "2026-10-12T00:00:00Z"]
        let twoModes = "more than one mode"
        expectRejected(start + ["--deployment-end", "2026-10-13T00:00:00Z", "--deployment-percent", "5"], twoModes)
        expectRejected(start + ["--deployment-percent-per-hour", "5", "--deployment-percent-per-day", "5"], twoModes)
        expectRejected(start, "no mode")
        expectRejected(["--deployment-step-hours", "2"], "no mode")
        expectRejected(["--deployment-end", "2026-10-13T00:00:00Z"], "requires start")
        expectRejected(["--deployment-percent-per-hour", "5"], "requires start")
        expectRejected(["--deployment-percent-per-day", "5"], "requires start")
        expectRejected(["--deployment-percent-per-step", "5", "--deployment-step-hours", "2"], "requires start")
        let endAfterStart = "end must be after start"
        expectRejected(["--deployment-start", "2026-10-13T00:00:00Z", "--deployment-end", "2026-10-12T00:00:00Z"], endAfterStart)
        expectRejected(["--deployment-start", "2026-10-17T00:00:00Z", "--deployment-end", "2026-10-18T00:00:00Z"], endAfterStart)
        expectRejected(start + ["--deployment-percent-per-hour", "5", "--deployment-step-hours", "2"], "can't be combined with step_hours")
        expectRejected(start + ["--deployment-percent-per-day", "5", "--deployment-step-hours", "2"], "can't be combined with step_hours")
        expectRejected(start + ["--deployment-percent-per-step", "5"], "requires step_hours")
        expectRejected(["--deployment-percent", "5", "--deployment-step-hours", "2"], "can't be used with --deployment-percent")
        let range = "integer from 1 to 100"
        expectRejected(["--deployment-percent", "0"], range)
        expectRejected(["--deployment-percent", "101"], range)
        expectRejected(start + ["--deployment-percent-per-hour", "0"], range)
        expectRejected(start + ["--deployment-end", "2026-10-13T00:00:00Z", "--deployment-step-hours", "0"], "integer of 1 or more")
    }

    @Test func badDatesAreRejected() {
        let parse = "Can't parse 'deployment-start'"
        expectRejected(["--deployment-start", "soon", "--deployment-percent", "5"], parse)
        expectRejected(["--deployment-start", "2026-13-45T00:00:00Z", "--deployment-percent", "5"], parse)
        expectRejected(["--deployment-start", "2026-10-12", "--deployment-percent", "5"], parse)
        expectRejected(["--deployment-end", "2026-10-12", "--deployment-start", "2026-10-12T00:00:00Z"], "Can't parse 'deployment-end'")
        // an offset would be lost, since pkginfo dates mean local time
        expectRejected(["--deployment-start", "2026-10-12T09:00:00-07:00", "--deployment-percent", "5"], parse)
    }
}

struct DeploymentWarningsTests {
    private let monday = date("2026-10-12 09:00")
    private let tuesday = date("2026-10-13 09:00")
    private let saturday = date("2026-10-17 09:00")
    private let sunday = date("2026-10-18 09:00")

    @Test func nothingToSay() {
        #expect(deploymentWarnings(nil).isEmpty)
        #expect(deploymentWarnings(["percent": 5]).isEmpty)
        #expect(deploymentWarnings(["start": monday, "end": tuesday, "step_hours": 2]).isEmpty)
    }

    @Test func invalidDeployments() {
        let invalid: [[String: Any]] = [
            ["percent": 0],
            ["start": monday],
            ["start": tuesday, "end": monday],
            // no weekday time between them
            ["start": saturday, "end": sunday],
            ["start": monday, "percent_per_hour": 10, "step_hours": 2],
            ["start": monday, "percent_per_step": 10],
        ]
        for dict in invalid {
            let warnings = deploymentWarnings(dict)
            #expect(warnings.count == 1)
            #expect(warnings.first?.contains("invalid deployment") == true)
        }
        #expect(deploymentWarnings("not a dictionary").count == 1)
    }

    /// Saturday 00:00 is how to write the end of Friday, and clients leave it as it is.
    @Test func saturdayMidnightEndIsNotWorthAWarning() {
        #expect(deploymentWarnings(["start": monday, "end": date("2026-10-24 00:00")]).isEmpty)
        #expect(deploymentWarnings(["start": monday, "end": date("2026-10-24 00:01")]).count == 1)
    }

    @Test func validButProbablyNotWhatWasMeant() {
        func only(_ dict: [String: Any]) -> String {
            let warnings = deploymentWarnings(dict)
            #expect(warnings.count == 1)
            return warnings.first ?? ""
        }
        #expect(only(["start": saturday, "end": date("2026-10-20 09:00")]).contains("start on a weekend"))
        #expect(only(["start": monday, "end": sunday]).contains("end on a weekend"))
        #expect(only(["start": sunday, "percent": 5]).contains("start on a weekend"))
        #expect(only(["percent": 5, "step_hours": 2]).contains("ignore step_hours"))
    }
}

struct DeploymentIsUnfinishedTests {
    private let now = date("2026-10-20 12:00")

    @Test func noDeploymentIsNotUnfinished() {
        #expect(!deploymentIsUnfinished(nil, now: now))
    }

    @Test func unfinishedDeployments() {
        let unfinished: [[String: Any]] = [
            ["start": date("2099-01-05 00:00"), "percent": 5], // scheduled
            ["start": date("2026-10-12 00:00"), "end": date("2099-01-05 00:00")], // in progress
            ["percent": 99], // static below 100
            ["percent": 0], // invalid
        ]
        for dict in unfinished {
            #expect(deploymentIsUnfinished(dict, now: now))
        }
    }

    @Test func finishesWhenItReachesOneHundred() {
        let deployment: [String: Any] = ["start": date("2026-10-12 00:00"), "end": date("2026-10-13 00:00")]
        #expect(deploymentIsUnfinished(deployment, now: date("2026-10-12 23:59")))
        #expect(!deploymentIsUnfinished(deployment, now: date("2026-10-13 00:00")))
    }

    @Test func finishedDeployments() {
        let finished: [[String: Any]] = [
            ["start": date("2026-10-12 00:00"), "end": date("2026-10-13 00:00")],
            ["percent": 100],
            ["start": date("2026-10-12 00:00"), "percent": 100],
        ]
        for dict in finished {
            #expect(!deploymentIsUnfinished(dict, now: now))
        }
    }
}

/// A repo in memory, so deploymentutil's reading can be tested
private final class MemoryRepo: Repo {
    var files = [String: Data]()

    init(_: String) throws {}

    func list(_ kind: String) async throws -> [String] {
        return files.keys.filter { $0.hasPrefix(kind + "/") }.map { String($0.dropFirst(kind.count + 1)) }
    }

    func get(_ identifier: String) async throws -> Data {
        guard let data = files[identifier] else { throw MunkiError("no such item") }
        return data
    }

    func get(_: String, toFile _: String) async throws {}
    func put(_ identifier: String, content: Data) async throws {
        files[identifier] = content
    }

    func put(_: String, fromFile _: String) async throws {}
    func delete(_: String) async throws {}
    func pathFor(_: String) -> String? { return nil }
}

struct DeploymentMakeCatalogsTests {
    private func repo() throws -> MemoryRepo {
        let repo = try MemoryRepo("")
        let pkginfo: PlistDict = [
            "name": "Firefox",
            "version": "2.0",
            "catalogs": ["testing"],
            "installer_type": "nopkg",
            "deployment": ["percent": 0],
        ]
        repo.files["pkgsinfo/Firefox-2.0"] = try PropertyListSerialization.data(fromPropertyList: pkginfo, format: .xml, options: 0)
        return repo
    }

    @Test func warnsAndStillBuildsWithTheDeploymentUnchanged() async throws {
        let repo = try repo()
        var maker = try await CatalogsMaker(repo: repo, options: MakeCatalogOptions())
        await maker.makecatalogs()
        #expect(maker.warnings.filter { $0.contains("Firefox-2.0") && $0.contains("invalid deployment") }.count == 1)
        let data = try #require(repo.files["catalogs/testing"])
        let catalog = try #require(try PropertyListSerialization.propertyList(from: data, format: nil) as? [PlistDict])
        #expect(catalog.count == 1)
        #expect((catalog[0]["deployment"] as? PlistDict)?["percent"] as? Int == 0)
    }

    @Test func warnsWithSkipPkgCheck() async throws {
        var maker = try await CatalogsMaker(repo: try repo(), options: MakeCatalogOptions(skipPkgCheck: true))
        await maker.makecatalogs()
        #expect(maker.warnings.filter { $0.contains("invalid deployment") }.count == 1)
    }

    @Test func noDeploymentNoWarning() async throws {
        let repo = try MemoryRepo("")
        let pkginfo: PlistDict = ["name": "Firefox", "version": "2.0", "catalogs": ["testing"], "installer_type": "nopkg"]
        repo.files["pkgsinfo/Firefox-2.0"] = try PropertyListSerialization.data(fromPropertyList: pkginfo, format: .xml, options: 0)
        var maker = try await CatalogsMaker(repo: repo, options: MakeCatalogOptions())
        await maker.makecatalogs()
        #expect(maker.warnings.isEmpty)
    }
}

struct DeploymentUtilTests {
    private let now = date("2026-10-14 09:30")
    private let twoWeeks: [String: Any] = ["start": date("2026-10-12 00:00"), "end": date("2026-10-24 00:00")]

    private func pkginfo(_ name: String, _ version: String, _ deployment: Any?, catalogs: [String] = ["production"]) -> PlistDict {
        var pkginfo: PlistDict = ["name": name, "version": version, "catalogs": catalogs]
        pkginfo["deployment"] = deployment
        return pkginfo
    }

    private func row(_ deployment: Any?, serial: String? = nil, name: String = "Firefox") throws -> DeploymentRow {
        return try #require(deploymentRow(pkginfo(name, "131.0", deployment), now: now, serial: serial))
    }

    @Test func noDeploymentHasNoRow() {
        #expect(deploymentRow(pkginfo("Firefox", "1.0", nil), now: now) == nil)
    }

    @Test func inProgressRowMatchesTheDesign() throws {
        let found = try row(twoWeeks)
        #expect(found.mode == "start/end")
        #expect(found.step == 58)
        #expect(found.totalSteps == 241)
        #expect(found.currentPercent == 25)
        #expect(found.nextStepDate == date("2026-10-14 10:00"))
        #expect(found.status == "in progress")
    }

    @Test func statuses() throws {
        #expect(try row(["start": date("2099-01-05 00:00"), "end": date("2099-01-09 00:00")]).status == "scheduled")
        #expect(try row(["start": date("2099-01-05 00:00"), "percent": 5]).status == "scheduled")
        #expect(try row(["percent": 25]).status == "static")
        #expect(try row(["percent": 100]).status == "complete")
        #expect(try row(["start": date("2026-10-12 00:00"), "end": date("2026-10-13 00:00")]).status == "complete")
        #expect(try row(["percent": 0]).status == "invalid")
    }

    @Test func modes() throws {
        let start = date("2026-10-12 00:00")
        #expect(try row(twoWeeks).mode == "start/end")
        #expect(try row(["start": start, "percent_per_hour": 10]).mode == "per hour")
        #expect(try row(["start": start, "percent_per_day": 10]).mode == "per day")
        #expect(try row(["start": start, "percent_per_step": 10, "step_hours": 24]).mode == "per step")
        #expect(try row(["percent": 10]).mode == "static")
    }

    @Test func invalidRowSaysWhy() throws {
        let found = try row(["percent": 0])
        #expect(found.invalidReason?.contains("percent") == true)
        #expect(deploymentTable([found]).contains("invalid: deployment percent"))
    }

    @Test func serialWorksOutTheMachine() throws {
        // C02ABC123DEF hashes to 36 for Firefox and 73 for Zoom
        let firefox = try row(["percent": 36], serial: testSerial)
        #expect(firefox.packagePercent == 36)
        #expect(firefox.eligible == true)
        let zoom = try row(["percent": 36], serial: testSerial, name: "Zoom")
        #expect(zoom.packagePercent == 73)
        #expect(zoom.eligible == false)
        #expect(try row(["percent": 36]).packagePercent == nil)
    }

    @Test func finishedAreHiddenUnlessAskedFor() throws {
        let rows = [try row(["percent": 100]), try row(twoWeeks), try row(["percent": 0])]
        #expect(filteredDeploymentRows(rows).map(\.status) == ["in progress", "invalid"])
        #expect(filteredDeploymentRows(rows, all: true).count == 3)
    }

    @Test func catalogFilter() {
        let rows = [
            deploymentRow(pkginfo("A", "1.0", ["percent": 5], catalogs: ["testing"]), now: now)!,
            deploymentRow(pkginfo("B", "1.0", ["percent": 5], catalogs: ["production", "testing"]), now: now)!,
        ]
        #expect(filteredDeploymentRows(rows, catalog: "production").map(\.name) == ["B"])
        #expect(filteredDeploymentRows(rows, catalog: "testing").map(\.name) == ["A", "B"])
    }

    @Test func nameFilterIncludesFinishedVersionsNewestFirst() {
        let rows = [
            deploymentRow(pkginfo("A", "1.0", ["percent": 100]), now: now)!,
            deploymentRow(pkginfo("A", "10.0", ["percent": 5]), now: now)!,
            deploymentRow(pkginfo("A", "2.0", ["percent": 5]), now: now)!,
            deploymentRow(pkginfo("B", "1.0", ["percent": 5]), now: now)!,
        ]
        #expect(filteredDeploymentRows(rows, name: "A").map(\.version) == ["10.0", "2.0", "1.0"])
    }

    @Test func tableMatchesTheDesign() throws {
        let table = deploymentTable([try row(twoWeeks)])
        let lines = table.components(separatedBy: "\n")
        #expect(lines[0].hasPrefix("NAME"))
        #expect(lines[0].hasSuffix("STATUS"))
        let columns = lines[1].components(separatedBy: "  ").filter { !$0.isEmpty }.map { $0.trimmingCharacters(in: .whitespaces) }
        #expect(columns == ["Firefox", "131.0", "start/end", "2026-10-12 00:00", "2026-10-24 00:00", "58/241", "25", "2026-10-14 10:00", "in progress"])
    }

    @Test func staticShowsDashes() throws {
        let table = deploymentTable([try row(["percent": 25])])
        let columns = table.components(separatedBy: "\n")[1].components(separatedBy: "  ").filter { !$0.isEmpty }.map { $0.trimmingCharacters(in: .whitespaces) }
        #expect(columns == ["Firefox", "131.0", "static", "-", "-", "-", "25", "-", "static"])
    }

    @Test func scheduledRowShowsNoStepYet() throws {
        let table = deploymentTable([try row(["start": date("2099-01-05 00:00"), "end": date("2099-01-09 00:00")])])
        let columns = table.components(separatedBy: "\n")[1].components(separatedBy: "  ").filter { !$0.isEmpty }.map { $0.trimmingCharacters(in: .whitespaces) }
        #expect(columns == ["Firefox", "131.0", "start/end", "2099-01-05 00:00", "2099-01-09 00:00", "-", "0", "2099-01-05 00:00", "scheduled"])
    }

    @Test func tableHeader() throws {
        let header = deploymentTable([try row(["percent": 5])]).components(separatedBy: "\n")[0]
        let columns = header.components(separatedBy: "  ").filter { !$0.isEmpty }.map { $0.trimmingCharacters(in: .whitespaces) }
        #expect(columns == ["NAME", "VERSION", "MODE", "START", "END", "STEP", "CURRENT", "NEXT STEP", "STATUS"])
    }

    /// Names aren't cut off or misaligned, whatever characters they're made of.
    @Test func tablePadsNamesWithAnyCharacters() throws {
        let rows = [
            try row(["percent": 5], name: "Cafe\u{301}"),
            try row(["percent": 5], name: "App🎉"),
            try row(["percent": 5], name: "Plain"),
        ]
        let table = deploymentTable(rows)
        #expect(table.contains("Cafe\u{301}"))
        #expect(table.contains("App🎉"))
        let versionColumns = table.components(separatedBy: "\n").dropFirst().map { line in
            line.distance(from: line.startIndex, to: line.range(of: "131.0")!.lowerBound)
        }
        #expect(Set(versionColumns).count == 1)
    }

    @Test func invalidIsNotEligibleForAnySerial() throws {
        let found = try row(["percent": 0], serial: testSerial)
        #expect(found.packagePercent == 36)
        #expect(found.eligible == false)
        #expect(deploymentTable([found], showMachine: true).contains("no"))
    }

    @Test func tableWithSerialAddsMachineColumns() throws {
        let table = deploymentTable([try row(["percent": 36], serial: testSerial)], showMachine: true)
        #expect(table.contains("PACKAGE DEPLOY %"))
        #expect(table.contains("ELIGIBLE"))
        let columns = table.components(separatedBy: "\n")[1].components(separatedBy: "  ").filter { !$0.isEmpty }.map { $0.trimmingCharacters(in: .whitespaces) }
        #expect(columns.suffix(3) == ["36", "yes", "static"])
    }

    @Test func scheduleListsEveryStep() throws {
        let found = try row(["start": date("2026-10-20 08:00"), "end": date("2026-10-20 17:00"), "step_hours": 2])
        #expect(found.schedule.map(\.percent) == [17, 34, 50, 67, 84, 100])
        #expect(found.schedule.last?.date == date("2026-10-20 17:00"))
        let text = deploymentScheduleText([found])
        #expect(text.hasPrefix("Firefox 131.0 (start/end)\n"))
        #expect(text.contains("2026-10-20 08:00  17"))
        #expect(text.contains("2026-10-20 17:00  100"))
    }

    @Test func scheduleOfAStaticDeploymentHasNoSteps() throws {
        #expect(deploymentScheduleText([try row(["percent": 25])]).contains("25% (no steps)"))
    }

    @Test func scheduleOfAStaticDeploymentWithStartHasOneStep() throws {
        let found = try row(["start": date("2099-01-05 00:00"), "percent": 5])
        #expect(found.schedule.map(\.percent) == [5])
        #expect(deploymentScheduleText([found]).contains("2099-01-05 00:00  5"))
        #expect(!deploymentScheduleText([found]).contains("no steps"))
    }

    @Test func jsonParsesWithExpectedValues() throws {
        let text = try deploymentJSON([try row(twoWeeks), try row(["percent": 0])])
        let objects = try #require(try JSONSerialization.jsonObject(with: Data(text.utf8)) as? [[String: Any]])
        #expect(objects.count == 2)
        #expect(objects[0]["name"] as? String == "Firefox")
        #expect(objects[0]["current_deploy_percent"] as? Int == 25)
        #expect(objects[0]["step"] as? Int == 58)
        #expect(objects[0]["next_step_date"] as? String == "2026-10-14T10:00:00Z")
        #expect(objects[0]["schedule"] == nil)
        #expect(objects[0]["mode"] as? String == "start/end")
        #expect(objects[0]["start"] as? String == "2026-10-12T00:00:00Z")
        #expect(objects[0]["end"] as? String == "2026-10-24T00:00:00Z")
        #expect(objects[0]["total_steps"] as? Int == 241)
        #expect(objects[0]["catalogs"] as? [String] == ["production"])
        #expect(objects[1]["status"] as? String == "invalid")
        #expect(objects[1]["invalid_reason"] is String)
    }

    @Test func jsonIncludesTheMachineWithASerial() throws {
        let text = try deploymentJSON([try row(["percent": 36], serial: testSerial)])
        let objects = try #require(try JSONSerialization.jsonObject(with: Data(text.utf8)) as? [[String: Any]])
        #expect(objects[0]["package_deploy_percent"] as? Int == 36)
        #expect(objects[0]["eligible"] as? Bool == true)
    }

    @Test func jsonCanIncludeTheSchedule() throws {
        let text = try deploymentJSON([try row(["start": date("2026-10-20 08:00"), "percent_per_hour": 50])], includeSchedule: true)
        let objects = try #require(try JSONSerialization.jsonObject(with: Data(text.utf8)) as? [[String: Any]])
        let schedule = try #require(objects[0]["schedule"] as? [[String: Any]])
        #expect(schedule.map { $0["percent"] as? Int } == [50, 100])
        #expect(schedule.map { $0["date"] as? String } == ["2026-10-20T08:00:00Z", "2026-10-20T09:00:00Z"])
    }

    @Test func readsPkginfosAndReportsOnesItCant() async throws {
        let repo = try MemoryRepo("")
        repo.files["pkgsinfo/good"] = try PropertyListSerialization.data(fromPropertyList: pkginfo("A", "1.0", ["percent": 5]), format: .xml, options: 0)
        repo.files["pkgsinfo/sub/plain"] = try PropertyListSerialization.data(fromPropertyList: pkginfo("B", "1.0", nil), format: .xml, options: 0)
        repo.files["pkgsinfo/bad"] = Data("not a plist".utf8)
        repo.files["catalogs/all"] = Data()
        let (pkginfos, errors) = try await pkginfosFromRepo(repo)
        #expect(Set(pkginfos.compactMap { $0["name"] as? String }) == ["A", "B"])
        #expect(errors.count == 1)
        #expect(errors.first?.contains("pkgsinfo/bad") == true)
    }
}
