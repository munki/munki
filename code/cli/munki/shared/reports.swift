//
//  reports.swift
//  munki
//
//  Created by Greg Neagle on 7/1/24.
//

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
            if let temp = try readPlist(reportFile()) {
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
