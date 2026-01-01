//
//  reports.swift
//  munki
//
//  Created by Greg Neagle on 7/1/24.
//
//  Copyright 2024-2026 The Munki Project. All rights reserved.
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

/// A Singleton class to manage reports
class Report {
    static let shared = Report()

    var report: PlistDict

    private init() {
        report = PlistDict()
    }

    func record(_ value: Any, to key: String) {
        report[key] = value
    }

    func retrieve(key: String) -> Any? {
        return report[key]
    }

    func add(string newValue: String, to key: String) {
        if var value = report[key] as? [String] {
            value.append(newValue)
            report[key] = value
        } else {
            report[key] = [newValue]
        }
    }

    func add(dict newValue: PlistDict, to key: String) {
        if var value = report[key] as? [PlistDict] {
            value.append(newValue)
            report[key] = value
        } else {
            report[key] = [newValue]
        }
    }

    /// Returns path to report file
    func reportFile() -> String {
        return managedInstallsDir(subpath: "ManagedInstallReport.plist")
    }

    /// Saves our report
    func save() {
        do {
            try writePlist(report, toFile: reportFile())
        } catch {
            DisplayAndLog.main.error(
                "Failed to write ManagedInstallReport.plist: \(error)"
            )
        }
    }

    /// Read report data from file
    func read() {
        do {
            if let temp = try readPlist(fromFile: reportFile()) {
                report = temp as? PlistDict ?? PlistDict()
            }
        } catch {
            report = PlistDict()
        }
    }

    /// Archive current report file
    func archiveReport() {
        let display = DisplayAndLog.main
        let reportFile = managedInstallsDir(subpath: "ManagedInstallReport.plist")
        if !pathExists(reportFile) {
            // nothing to do
            return
        }
        let dateformatter = DateFormatter()
        dateformatter.dateFormat = "yyyy-MM-dd-HHmmss"
        let timestamp = dateformatter.string(from: Date())
        let archiveName = "ManagedInstallReport-\(timestamp).plist"
        let archiveDir = managedInstallsDir(subpath: "Archives")
        if !pathExists(archiveDir) {
            do {
                try FileManager.default.createDirectory(atPath: archiveDir, withIntermediateDirectories: false)
            } catch {
                display.warning("Could not create report archive directory: \(error.localizedDescription)")
            }
        }
        let fullArchivePath = (archiveDir as NSString).appendingPathComponent(archiveName)
        do {
            try FileManager.default.moveItem(atPath: reportFile, toPath: fullArchivePath)
        } catch {
            display.warning("Could not archive report: \(error.localizedDescription)")
        }
        // now keep number of archived reports to 100 or fewer
        let directoryURL = URL(fileURLWithPath: archiveDir)
        do {
            let contents = try
                FileManager.default.contentsOfDirectory(
                    at: directoryURL,
                    includingPropertiesForKeys: [.contentModificationDateKey],
                    options: [.skipsHiddenFiles, .skipsSubdirectoryDescendants]
                )
                .filter { $0.lastPathComponent.hasPrefix("ManagedInstallReport-") }
                .sorted(by: {
                    let date0 = try $0.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate!
                    let date1 = try $1.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate!
                    return date0.compare(date1) == .orderedDescending
                })
            if contents.count > 100 {
                for item in contents[100...] {
                    do {
                        try FileManager.default.removeItem(at: item)
                    } catch {
                        display.warning("Error removing \(item.path): \(error.localizedDescription)")
                    }
                }
            }
        } catch {
            display.warning("Error accessing archived report directory: \(error.localizedDescription)")
        }
    }
}
