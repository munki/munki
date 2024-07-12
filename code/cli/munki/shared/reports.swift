//
//  reports.swift
//  munki
//
//  Created by Greg Neagle on 7/1/24.
//
//  Copyright 2024 Greg Neagle.
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

class Report {
    // a Singleton struct to manage reports
    static let shared = Report()

    var report: PlistDict

    private init() {
        report = PlistDict()
    }

    func record(_ value: Any, to key: String) {
        report[key] = value
    }

    func add(_ newValue: String, to key: String) {
        if var value = report[key] as? [String] {
            value.append(newValue)
            report[key] = value
        } else {
            report[key] = newValue
        }
    }

    func reportFile() -> String {
        // returns path to report file
        let reportDir = pref("ManagedInstallDir") as? String ?? DEFAULT_MANAGED_INSTALLS_DIR
        return (reportDir as NSString).appendingPathComponent("ManagedInstallReport.plist")
    }

    func save() {
        // saves our report
        do {
            try writePlist(report, toFile: reportFile())
        } catch {
            displayError(
                "Failed to write ManagedInstallReport.plist: \(error)",
                addToReport: false
            )
        }
    }

    func read() {
        // read report data from file
        do {
            if let temp = try readPlist(fromFile: reportFile()) {
                report = temp as? PlistDict ?? PlistDict()
            }
        } catch {
            report = PlistDict()
        }
    }

    func archiveReport() {
        // Archive current report file
        // TODO: implement this
    }
}
