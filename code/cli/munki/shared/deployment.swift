//
//  deployment.swift
//  munki
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

// Schedule and hash logic for pkginfo `deployment` dicts.
// See docs/deployment/deployment_design.md, sections 1-3.
//
// This file is built into makecatalogs on Linux, so it can only depend on
// Foundation and shared/munkihash.swift.

import Foundation

private let secondsPerHour = 3600
private let secondsPerDay = 24 * secondsPerHour
private let weekdaySecondsPerWeek = 5 * secondsPerDay
private let secondsPerWeek = 7 * secondsPerDay
/// 1970-01-01 was a Thursday. Adding this makes multiples of a week land on Monday 00:00.
private let secondsSinceMonday = 3 * secondsPerDay
/// Dates outside this range (about 3000 years either side of 1970) are invalid. This also
/// keeps conversion to Int and the arithmetic below from trapping.
private let maxDateSeconds = 100_000_000_000.0
// ponytail: larger step_hours act the same, since a step this long never arrives.
// Clamping keeps the arithmetic from overflowing.
private let maxStepHours = 1_000_000

private func floorDivide(_ value: Int, _ divisor: Int) -> (quotient: Int, remainder: Int) {
    let remainder = ((value % divisor) + divisor) % divisor
    return ((value - remainder) / divisor, remainder)
}

private func ceilDivide(_ value: Int, _ divisor: Int) -> Int {
    return floorDivide(value + divisor - 1, divisor).quotient
}

private func wholeSeconds(_ date: Date) -> Int {
    return Int(date.timeIntervalSince1970.rounded(.down))
}

private func isWeekend(_ seconds: Int) -> Bool {
    return floorDivide(seconds + secondsSinceMonday, secondsPerWeek).remainder >= weekdaySecondsPerWeek
}

/// Converts seconds to a clock that stops on weekends: it counts weekday seconds only, so
/// Saturday and Sunday all share the value of the following Monday 00:00.
private func weekdayClock(_ seconds: Int) -> Int {
    let (weeks, remainder) = floorDivide(seconds + secondsSinceMonday, secondsPerWeek)
    return weeks * weekdaySecondsPerWeek + min(remainder, weekdaySecondsPerWeek)
}

/// The inverse of weekdayClock. A value on a week boundary gives Monday 00:00.
private func secondsFromWeekdayClock(_ clock: Int) -> Int {
    let (weeks, remainder) = floorDivide(clock, weekdaySecondsPerWeek)
    return weeks * secondsPerWeek + remainder - secondsSinceMonday
}

/// The Saturday 00:00 of the weekend containing `seconds`.
private func saturdayMidnight(_ seconds: Int) -> Int {
    let weeks = floorDivide(seconds + secondsSinceMonday, secondsPerWeek).quotient
    return weeks * secondsPerWeek + weekdaySecondsPerWeek - secondsSinceMonday
}

/// Returns the value only if it's a plist `<integer>`. A plain `as? Int` also accepts
/// `<true/>` and a whole-number `<real>`, because they bridge through NSNumber.
private func strictInteger(_ value: Any?) -> Int? {
    #if canImport(ObjectiveC)
        guard let number = value as? NSNumber,
              CFGetTypeID(number) != CFBooleanGetTypeID(),
              !CFNumberIsFloatType(number)
        else {
            return nil
        }
        return number.intValue
    #else
        // CFNumberIsFloatType isn't available here. `<true/>` already fails `as? Int`.
        guard let number = value as? NSNumber, !["d", "f"].contains(String(cString: number.objCType)) else {
            return nil
        }
        return value as? Int
    #endif
}

enum DeploymentStatus: String {
    case scheduled
    case inProgress = "in progress"
    case fixed = "static"
    case complete
}

/// Where a deployment is at a moment in time.
struct DeploymentState {
    let status: DeploymentStatus
    /// current_deploy_percent
    let currentPercent: Int
    /// The step reached so far (0 before start) and the total. nil for static deployments.
    let step: Int?
    let totalSteps: Int?
    /// When the next step opens. A step can leave currentPercent unchanged when there are
    /// more than 100 steps. nil once complete, and for static deployments once started.
    let nextStepDate: Date?
    /// When currentPercent next goes up. nil once complete, and for static deployments
    /// once started.
    let nextIncreaseDate: Date?
}

/// A validated `deployment` dict from a pkginfo.
struct Deployment {
    private enum Schedule {
        case fixed(percent: Int, start: Date?)
        case dated(DatedSchedule)
    }

    /// Steps are numbered from 1, and all `Clock` values are weekday clock values.
    /// Step i's percent is `ceil(i * percentNumerator / percentDenominator)`.
    private struct DatedSchedule {
        let startClock: Int
        /// Start rounded down to the hour. Steps after the first are multiples of
        /// `stepSeconds` from here, so a 08:30 start with 2-hour steps continues at 10:00.
        let baseClock: Int
        let stepSeconds: Int
        let totalSteps: Int
        /// The moment the last step opens, for start/end mode. nil for rate modes.
        let endSeconds: Int?
        let percentNumerator: Int
        let percentDenominator: Int

        func percent(forStep step: Int) -> Int {
            if step <= 0 { return 0 }
            if step >= totalSteps { return 100 }
            // only the last step reaches 100, even when rounding up would get there sooner
            return min(99, ceilDivide(step * percentNumerator, percentDenominator))
        }

        func date(forStep step: Int) -> Date {
            let seconds = if step <= 1 {
                secondsFromWeekdayClock(startClock)
            } else if step == totalSteps, let endSeconds {
                endSeconds
            } else {
                secondsFromWeekdayClock(baseClock + (step - 1) * stepSeconds)
            }
            return Date(timeIntervalSince1970: Double(seconds))
        }

        /// The last step open at `now`, or 0 before start. Each step's date is converted, then
        /// searched, so far-off dates stay fast. The conversion can put steps out of order for
        /// up to an hour around a clock change, which at worst makes the result one step off.
        func step(at now: Date, toRealDate: (Date) -> Date) -> Int {
            var low = 0
            var high = totalSteps
            while low < high {
                let middle = (low + high + 1) / 2
                if toRealDate(date(forStep: middle)) <= now {
                    low = middle
                } else {
                    high = middle - 1
                }
            }
            return low
        }

        /// The first step after `step` with a higher percent.
        func stepOfNextIncrease(after step: Int) -> Int {
            let current = percent(forStep: step)
            if current >= 99 { return totalSteps }
            return min(totalSteps, current * percentDenominator / percentNumerator + 1)
        }
    }

    private let schedule: Schedule

    /// Validates a pkginfo's `deployment` value, throwing MunkiError if it's malformed. No
    /// machine is eligible for a version with an invalid deployment.
    init(_ value: Any?) throws {
        guard let dict = value as? [String: Any] else {
            throw MunkiError("deployment is not a dictionary")
        }
        let modeKeys = ["end", "percent_per_hour", "percent_per_day", "percent_per_step", "percent"].filter { dict[$0] != nil }
        if modeKeys.isEmpty {
            throw MunkiError("deployment has no mode: needs end, percent_per_hour, percent_per_day, percent_per_step, or percent")
        }
        if modeKeys.count > 1 {
            throw MunkiError("deployment has more than one mode: \(modeKeys.joined(separator: ", "))")
        }
        let modeKey = modeKeys[0]

        if modeKey == "percent" {
            // start is optional here. A weekend start behaves like Monday 00:00, as in dated modes.
            var start: Date?
            if dict["start"] != nil {
                let seconds = secondsFromWeekdayClock(weekdayClock(try Deployment.dateSeconds(dict, key: "start")))
                start = Date(timeIntervalSince1970: Double(seconds))
            }
            schedule = try .fixed(percent: Deployment.percentValue(dict, key: modeKey), start: start)
            return
        }

        guard dict["start"] != nil else {
            throw MunkiError("deployment \(modeKey) requires start")
        }
        let start = try Deployment.dateSeconds(dict, key: "start")
        if ["percent_per_hour", "percent_per_day"].contains(modeKey), dict["step_hours"] != nil {
            throw MunkiError("deployment \(modeKey) can't be combined with step_hours")
        }
        if modeKey == "percent_per_step", dict["step_hours"] == nil {
            throw MunkiError("deployment percent_per_step requires step_hours")
        }
        var stepHours = 1
        if dict["step_hours"] != nil {
            guard let value = strictInteger(dict["step_hours"]), value >= 1 else {
                throw MunkiError("deployment step_hours must be an integer of 1 or more")
            }
            stepHours = min(value, maxStepHours)
        }
        let stepSeconds = stepHours * secondsPerHour
        let startClock = weekdayClock(start)
        let baseClock = floorDivide(startClock, secondsPerHour).quotient * secondsPerHour

        switch modeKey {
        case "end":
            let end = try Deployment.dateSeconds(dict, key: modeKey)
            let endClock = weekdayClock(end)
            // comparing clocks also catches a start and end in the same weekend, since the
            // client moves that start to Monday and that end back to Saturday
            guard endClock > startClock else {
                throw MunkiError("deployment end must be after start, not counting weekends")
            }
            // the start, the on-the-hour steps before the end, and the end
            let totalSteps = ceilDivide(endClock - baseClock, stepSeconds) + 1
            schedule = .dated(DatedSchedule(
                startClock: startClock,
                baseClock: baseClock,
                stepSeconds: stepSeconds,
                totalSteps: totalSteps,
                endSeconds: isWeekend(end) ? saturdayMidnight(end) : end,
                percentNumerator: 100,
                percentDenominator: totalSteps
            ))
        default:
            let numerator = try Deployment.percentValue(dict, key: modeKey)
            let denominator = modeKey == "percent_per_day" ? 24 : 1
            schedule = .dated(DatedSchedule(
                startClock: startClock,
                baseClock: baseClock,
                stepSeconds: stepSeconds,
                // the first step where the percent rounds up to 100
                totalSteps: 99 * denominator / numerator + 1,
                endSeconds: nil,
                percentNumerator: numerator,
                percentDenominator: denominator
            ))
        }
    }

    private static func percentValue(_ dict: [String: Any], key: String) throws -> Int {
        guard let value = strictInteger(dict[key]), (1 ... 100).contains(value) else {
            throw MunkiError("deployment \(key) must be an integer from 1 to 100")
        }
        return value
    }

    private static func dateSeconds(_ dict: [String: Any], key: String) throws -> Int {
        guard let date = dict[key] as? Date, abs(date.timeIntervalSince1970) < maxDateSeconds else {
            throw MunkiError("deployment \(key) must be a valid date")
        }
        return wholeSeconds(date)
    }

    /// Returns every step and its percent, in the raw pkginfo frame. A static deployment
    /// has one step at its start, or none without a start.
    func allSteps() -> [(date: Date, percent: Int)] {
        guard case let .dated(dated) = schedule else {
            if case let .fixed(percent, start?) = schedule {
                return [(start, percent)]
            }
            return []
        }
        return (1 ... dated.totalSteps).map { (dated.date(forStep: $0), dated.percent(forStep: $0)) }
    }

    /// Returns the deployment's state at `now`.
    ///
    /// pkginfo dates mean local time, so `12:00:00Z` is noon on each machine. The client passes
    /// `subtractTZOffsetFromDate` as `toRealDate`, the same way `force_install_after_date` is
    /// read. It's a parameter because dateutils.swift isn't in the Linux makecatalogs build.
    /// Returned dates have been through `toRealDate`.
    func state(at now: Date, toRealDate: (Date) -> Date = { $0 }) -> DeploymentState {
        switch schedule {
        case let .fixed(percent, start):
            if let start, toRealDate(start) > now {
                return DeploymentState(
                    status: .scheduled,
                    currentPercent: 0,
                    step: nil,
                    totalSteps: nil,
                    nextStepDate: toRealDate(start),
                    nextIncreaseDate: toRealDate(start)
                )
            }
            return DeploymentState(
                status: percent == 100 ? .complete : .fixed,
                currentPercent: percent,
                step: nil,
                totalSteps: nil,
                nextStepDate: nil,
                nextIncreaseDate: nil
            )
        case let .dated(dated):
            let step = dated.step(at: now, toRealDate: toRealDate)
            let isComplete = step >= dated.totalSteps
            return DeploymentState(
                status: isComplete ? .complete : (step == 0 ? .scheduled : .inProgress),
                currentPercent: dated.percent(forStep: step),
                step: step,
                totalSteps: dated.totalSteps,
                nextStepDate: isComplete ? nil : toRealDate(dated.date(forStep: step + 1)),
                nextIncreaseDate: isComplete ? nil : toRealDate(dated.date(forStep: dated.stepOfNextIncrease(after: step)))
            )
        }
    }
}

/// `hash(input) % 100 + 1`, using the first 8 bytes of SHA-256 as a big-endian integer.
/// This value decides which machines get which versions. Changing it reshuffles the fleet.
private func deployPercent(hashing input: String) -> Int {
    let hexDigest = sha256hash(data: Data(input.utf8))
    guard let value = UInt64(hexDigest.prefix(16), radix: 16) else {
        return 100
    }
    return Int(value % 100) + 1
}

/// The identifier a machine's deploy_percent is based on: the serial number, falling back to
/// the hardware UUID. nil if neither can be read.
func deployPercentIdentifier(serial: String?, hardwareUUID: String?) -> String? {
    if let serial, !serial.isEmpty, serial != "UNKNOWN" {
        return serial
    }
    if let hardwareUUID, !hardwareUUID.isEmpty {
        return hardwareUUID
    }
    return nil
}

/// The machine's unsalted deploy_percent. 100 (the last group) with no identifier.
func machineDeployPercent(identifier: String?) -> Int {
    guard let identifier else { return 100 }
    return deployPercent(hashing: identifier)
}

/// The machine's deploy_percent for one item, salted with the item's name so the same machines
/// don't get every release first. 100 (the last group) with no identifier.
func packageDeployPercent(identifier: String?, itemName: String) -> Int {
    guard let identifier else { return 100 }
    return deployPercent(hashing: "\(identifier):\(itemName)")
}

/// Returns what an admin should hear about a pkginfo's `deployment`, for makecatalogs.
/// The list is empty if there's no deployment or nothing to mention.
func deploymentWarnings(_ value: Any?) -> [String] {
    guard let value else { return [] }
    do {
        _ = try Deployment(value)
    } catch {
        return ["has an invalid deployment, so no machine is eligible for this version: \(error)"]
    }
    var warnings = [String]()
    let dict = value as? [String: Any] ?? [:]
    if let start = dict["start"] as? Date, isWeekend(wholeSeconds(start)) {
        warnings.append("has a deployment start on a weekend, which clients treat as the following Monday 00:00")
    }
    // Saturday 00:00 is how to write the end of Friday
    if let end = dict["end"] as? Date, isWeekend(wholeSeconds(end)), wholeSeconds(end) != saturdayMidnight(wholeSeconds(end)) {
        warnings.append("has a deployment end on a weekend, which clients treat as the preceding Saturday 00:00")
    }
    if dict["percent"] != nil, dict["step_hours"] != nil {
        warnings.append("has a deployment with both percent and step_hours, and clients ignore step_hours")
    }
    return warnings
}

/// Returns true if a pkginfo has a `deployment` that hasn't reached 100, or is invalid.
/// Machines may still need older versions of the item while this is true.
func deploymentIsUnfinished(_ value: Any?, now: Date) -> Bool {
    guard let value else { return false }
    guard let deployment = try? Deployment(value) else { return true }
    return deployment.state(at: now).status != .complete
}
