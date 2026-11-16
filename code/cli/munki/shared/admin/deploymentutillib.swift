//
//  deploymentutillib.swift
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

import Foundation

/// A pkginfo's `deployment`, as deploymentutil shows it. Dates are in the pkginfo's frame,
/// where `12:00:00Z` means noon local time, so they're displayed as UTC.
struct DeploymentRow {
    let name: String
    let version: String
    let catalogs: [String]
    let mode: String
    let start: Date?
    let end: Date?
    let step: Int?
    let totalSteps: Int?
    let currentPercent: Int?
    let nextStepDate: Date?
    let status: String
    let invalidReason: String?
    let packagePercent: Int?
    let eligible: Bool?
    let deployment: Deployment?

    /// Built when asked for, since a far-off end date can mean millions of steps
    var schedule: [(date: Date, percent: Int)] {
        return deployment?.allSteps() ?? []
    }
}

/// Reads every pkginfo in the repo. It reads pkginfos, not catalogs, so it's accurate
/// even before makecatalogs has run. Returns the pkginfos and any errors reading them.
func pkginfosFromRepo(_ repo: Repo) async throws -> (pkginfos: [PlistDict], errors: [String]) {
    var pkginfos = [PlistDict]()
    var errors = [String]()
    for name in try await repo.list("pkgsinfo") {
        let identifier = "pkgsinfo/" + name
        do {
            let data = try await repo.get(identifier)
            pkginfos.append(try readPlist(fromData: data) as? PlistDict ?? PlistDict())
        } catch {
            errors.append("Unexpected error reading \(identifier): \(error)")
        }
    }
    return (pkginfos, errors)
}

/// Returns a row for a pkginfo, or nil if it has no `deployment`. `now` is in the pkginfo's frame.
/// With a `serial`, also works out where that machine falls, the same way the client does.
func deploymentRow(_ pkginfo: PlistDict, now: Date, serial: String? = nil) -> DeploymentRow? {
    guard let value = pkginfo["deployment"] else { return nil }
    let name = pkginfo["name"] as? String ?? "<unknown>"
    let version = pkginfo["version"] as? String ?? "<unknown>"
    let catalogs = pkginfo["catalogs"] as? [String] ?? []
    let dict = value as? PlistDict ?? PlistDict()
    let packagePercent = serial.map { packageDeployPercent(identifier: $0, itemName: name) }

    let deployment: Deployment
    do {
        deployment = try Deployment(value)
    } catch {
        return DeploymentRow(
            name: name, version: version, catalogs: catalogs, mode: "-", start: nil, end: nil,
            step: nil, totalSteps: nil, currentPercent: nil, nextStepDate: nil,
            status: "invalid", invalidReason: "\(error)", packagePercent: packagePercent,
            eligible: packagePercent.map { _ in false }, deployment: nil
        )
    }
    let mode = if dict["end"] != nil {
        "start/end"
    } else if dict["percent_per_hour"] != nil {
        "per hour"
    } else if dict["percent_per_day"] != nil {
        "per day"
    } else if dict["percent_per_step"] != nil {
        "per step"
    } else {
        "static"
    }
    let state = deployment.state(at: now)
    return DeploymentRow(
        name: name,
        version: version,
        catalogs: catalogs,
        mode: mode,
        start: dict["start"] as? Date,
        end: dict["end"] as? Date,
        step: state.step,
        totalSteps: state.totalSteps,
        currentPercent: state.currentPercent,
        nextStepDate: state.nextStepDate,
        status: state.status.rawValue,
        invalidReason: nil,
        packagePercent: packagePercent,
        eligible: packagePercent.map { $0 <= state.currentPercent },
        deployment: deployment
    )
}

/// Keeps what deploymentutil shows by default, or with its filters: finished
/// deployments are hidden unless `all` is set. Sorted by name, newest version first.
func filteredDeploymentRows(
    _ rows: [DeploymentRow],
    all: Bool = false,
    catalog: String? = nil,
    name: String? = nil
) -> [DeploymentRow] {
    return rows.filter { row in
        (all || name != nil || row.status != DeploymentStatus.complete.rawValue) &&
            (catalog == nil || row.catalogs.contains(catalog ?? "")) &&
            (name == nil || row.name == name)
    }.sorted {
        $0.name == $1.name ? MunkiVersion($0.version) > MunkiVersion($1.version) : $0.name < $1.name
    }
}

private func displayDate(_ date: Date?) -> String {
    guard let date else { return "-" }
    let formatter = DateFormatter()
    formatter.locale = Locale(identifier: "en_US_POSIX")
    formatter.timeZone = TimeZone(secondsFromGMT: 0)
    formatter.dateFormat = "yyyy-MM-dd HH:mm"
    return formatter.string(from: date)
}

private func paddedTable(_ rows: [[String]]) -> String {
    let columnCount = rows.first?.count ?? 0
    let widths = (0 ..< columnCount).map { column in rows.map { $0[column].count }.max() ?? 0 }
    return rows.map { row in
        row.enumerated().map { column, value in
            column == columnCount - 1 ? value : value + String(repeating: " ", count: widths[column] - value.count)
        }.joined(separator: "  ")
    }.joined(separator: "\n")
}

/// Returns the table deploymentutil prints
func deploymentTable(_ rows: [DeploymentRow], showMachine: Bool = false) -> String {
    var header = ["NAME", "VERSION", "MODE", "START", "END", "STEP", "CURRENT", "NEXT STEP"]
    if showMachine {
        header += ["PACKAGE DEPLOY %", "ELIGIBLE"]
    }
    header.append("STATUS")
    return paddedTable([header] + rows.map { row in
        var step = "-"
        if let current = row.step, let total = row.totalSteps, current > 0 {
            step = "\(current)/\(total)"
        }
        var columns = [
            row.name,
            row.version,
            row.mode,
            displayDate(row.start),
            displayDate(row.end),
            step,
            row.currentPercent.map { String($0) } ?? "-",
            displayDate(row.nextStepDate),
        ]
        if showMachine {
            columns.append(row.packagePercent.map { String($0) } ?? "-")
            columns.append(row.eligible.map { $0 ? "yes" : "no" } ?? "-")
        }
        columns.append(row.invalidReason.map { "invalid: \($0)" } ?? row.status)
        return columns
    })
}

/// Returns the text deploymentutil prints for --schedule
func deploymentScheduleText(_ rows: [DeploymentRow]) -> String {
    return rows.map { row in
        var lines = ["\(row.name) \(row.version) (\(row.invalidReason.map { "invalid: \($0)" } ?? row.mode))"]
        if row.schedule.isEmpty, row.invalidReason == nil {
            lines.append("  \(row.currentPercent ?? 0)% (no steps)")
        }
        lines += row.schedule.map { "  \(displayDate($0.date))  \($0.percent)" }
        return lines.joined(separator: "\n")
    }.joined(separator: "\n\n")
}

/// Returns the JSON deploymentutil prints for --json
func deploymentJSON(_ rows: [DeploymentRow], includeSchedule: Bool = false) throws -> String {
    let formatter = ISO8601DateFormatter()
    let objects: [[String: Any]] = rows.map { row in
        var object: [String: Any] = [
            "name": row.name,
            "version": row.version,
            "catalogs": row.catalogs,
            "mode": row.mode,
            "status": row.status,
        ]
        object["start"] = row.start.map { formatter.string(from: $0) }
        object["end"] = row.end.map { formatter.string(from: $0) }
        object["step"] = row.step
        object["total_steps"] = row.totalSteps
        object["current_deploy_percent"] = row.currentPercent
        object["next_step_date"] = row.nextStepDate.map { formatter.string(from: $0) }
        object["invalid_reason"] = row.invalidReason
        object["package_deploy_percent"] = row.packagePercent
        object["eligible"] = row.eligible
        if includeSchedule {
            object["schedule"] = row.schedule.map {
                ["date": formatter.string(from: $0.date), "percent": $0.percent] as [String: Any]
            }
        }
        return object
    }
    let data = try JSONSerialization.data(withJSONObject: objects, options: [.prettyPrinted, .sortedKeys])
    return String(data: data, encoding: .utf8) ?? "[]"
}
