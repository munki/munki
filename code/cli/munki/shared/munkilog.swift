//
//  munkilog.swift
//  munki
//
//  Created by Greg Neagle on 7/1/24.
//
//  Copyright 2024-2025 Greg Neagle.
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

let MAIN_LOG_NAME = "ManagedSoftwareUpdate.log"

/// Returns the logging level
func loggingLevel() -> Int {
    return pref("LoggingLevel") as? Int ?? 1
}

/// Returns the path to the main log
func mainLogDir() -> String {
    if let logFile = pref("LogFile") as? String {
        return (logFile as NSString).deletingLastPathComponent
    }
    return managedInstallsDir(subpath: "Logs")
}

/// Returns the path to a log with the given name in the same directory as our main log
func logNamed(_ name: String) -> String {
    // returns path to log file in same dir as main log
    return (mainLogDir() as NSString).appendingPathComponent(name)
}

/// General logging function
func munkiLog(_ message: String, logFile: String = "") {
    // RFC 3339 date format like `2024-07-01T17:30:32-08:00`
    let dateformatter = ISO8601DateFormatter()
    dateformatter.timeZone = TimeZone.current
    dateformatter.formatOptions = [.withInternetDateTime, .withSpaceBetweenDateAndTime, .withFractionalSeconds]
    let timestamp = dateformatter.string(from: Date())
    let logString = "\(timestamp) \(message)\n"
    var logPath = ""
    var subsystem = "com.googlecode.munki.managedsoftwareupdate"
    if logFile.isEmpty {
        logPath = logNamed(MAIN_LOG_NAME)
    } else {
        logPath = logNamed(logFile)
        subsystem = "com.googlecode.munki.\((logFile as NSString).deletingPathExtension)"
    }
    if let logData = logString.data(using: String.Encoding.utf8) {
        if !FileManager.default.fileExists(atPath:logPath) {
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
    let filemanager = FileManager.default
    if !filemanager.fileExists(atPath: logFilePath) {
        // nothing to do
        return
    }
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

/// Rotate a log if it's too large
func rotateLog(_ logname: String, ifLargerThan maxSize: Int) {
    let logpath = logNamed(logname)
    if let attributes = try? FileManager.default.attributesOfItem(atPath: logpath)
    {
        let filesize = (attributes as NSDictionary).fileSize()
        if filesize > maxSize {
            rotateLog(logpath)
        }
    }
}

/// Rotate our main log if it's too large
func munkiLogRotateMainLog() {
    let MAX_LOGFILE_SIZE = 1_000_000
    let mainLog = logNamed(MAIN_LOG_NAME)
    if let attributes = try? FileManager.default.attributesOfItem(atPath: mainLog)
    {
        let filesize = (attributes as NSDictionary).fileSize()
        if filesize > MAX_LOGFILE_SIZE {
            rotateLog(mainLog)
        }
    }
}

/// A nicer abstraction for the various Munki logging functions
class MunkiLogger {
    let logname: String
    var level = loggingLevel()

    init(logname: String = MAIN_LOG_NAME) {
        self.logname = logname
    }

    func rotate() {
        rotateLog(logNamed(logname))
    }

    func emergency(_ message: String) {
        munkiLog(message, logFile: logname)
    }

    func alert(_ message: String) {
        munkiLog(message, logFile: logname)
    }

    func critical(_ message: String) {
        munkiLog(message, logFile: logname)
    }

    func error(_ message: String) {
        munkiLog(message, logFile: logname)
    }

    func warning(_ message: String) {
        munkiLog(message, logFile: logname)
    }

    func notice(_ message: String) {
        if level > 0 {
            munkiLog(message, logFile: logname)
        }
    }

    func info(_ message: String) {
        if level > 1 {
            munkiLog(message, logFile: logname)
        }
    }

    func debug(_ message: String) {
        if level > 2 {
            munkiLog(message, logFile: logname)
        }
    }

    func debug1(_ message: String) {
        if level > 2 {
            munkiLog(message, logFile: logname)
        }
    }

    func debug2(_ message: String) {
        if level > 3 {
            munkiLog(message, logFile: logname)
        }
    }
}
