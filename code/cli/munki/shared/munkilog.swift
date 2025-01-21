//
//  munkilog.swift
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
import OSLog

/// Returns the logging level
func loggingLevel() -> Int {
    return pref("LoggingLevel") as? Int ?? 1
}

/// Returns the path to the main log
func mainLogPath() -> String {
    #if DEBUG
        return "/Users/Shared/Managed Installs/Logs/ManagedSoftwareUpdate.log"
    #else
        return pref("LogFile") as? String ?? managedInstallsDir(subpath: "Logs/ManagedSoftwareUpdate.log")
    #endif
}

/// Returns the path to a log with the given name in the same directory as our main log
func logNamed(_ name: String) -> String {
    // returns path to log file in same dir as main log
    return ((mainLogPath() as NSString).deletingLastPathComponent as NSString).appendingPathComponent(name)
}

/// General logging function
func munkiLog(_ message: String, logFile: String = "") {
    // date format like `Jul 01 2024 17:30:36 -0700`
    let dateformatter = DateFormatter()
    dateformatter.dateFormat = "MMM dd yyyy HH:mm:ss Z"
    let timestamp = dateformatter.string(from: Date())
    let logString = "\(timestamp) \(message)\n"
    var logPath = ""
    var subsystem = "com.googlecode.munki.managedsoftwareupdate"
    if logFile.isEmpty {
        logPath = mainLogPath()
    } else {
        logPath = logNamed(logFile)
        subsystem = "com.googlecode.munki.\(logFile)"
    }
    if let logData = logString.data(using: String.Encoding.utf8) {
        if !pathExists(logPath) {
            FileManager.default.createFile(atPath: logPath, contents: nil)
        }
        if let fh = FileHandle(forUpdatingAtPath: logPath) {
            let _ = fh.seekToEndOfFile()
            fh.write(logData)
        }
    }
    // log to Apple unified logging
    if #available(macOS 11.0, *), boolPref("LogToSyslog") ?? false {
        let logger = Logger(subsystem: subsystem, category: "")
        logger.log("\(message, privacy: .public)")
    }
}

/// Rotate a log
func rotateLog(_ logFilePath: String) {
    if !pathExists(logFilePath) {
        // nothing to do
        return
    }
    let filemanager = FileManager.default
    for i in [3, 2, 1, 0] {
        let olderLog = logFilePath + ".\(i + 1)"
        let newerLog = logFilePath + ".\(i)"
        try? filemanager.removeItem(atPath: olderLog)
        try? filemanager.moveItem(atPath: newerLog, toPath: olderLog)
    }
    try? filemanager.moveItem(atPath: logFilePath, toPath: logFilePath + ".0")
}

/// Rotate our errors.log
func munkiLogResetErrors() {
    rotateLog(logNamed("errors.log"))
}

/// Rotate our warnings.log
func munkiLogResetWarnings() {
    rotateLog(logNamed("warnings.log"))
}

/// Rotate our main log if it's too large
func munkiLogRotateMainLog() {
    let MAX_LOGFILE_SIZE = 1_000_000
    let mainLog = mainLogPath()
    if pathIsRegularFile(mainLog),
       let attributes = try? FileManager.default.attributesOfItem(atPath: mainLog)
    {
        let filesize = (attributes as NSDictionary).fileSize()
        if filesize > MAX_LOGFILE_SIZE {
            rotateLog(mainLog)
        }
    }
}
