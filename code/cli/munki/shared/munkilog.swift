//
//  munkilog.swift
//  munki
//
//  Created by Greg Neagle on 7/1/24.
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
func munkiLog(_ message: String, logFile: String = "", logLevel: OSLogType = .default) {
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
        if logFile != MAIN_LOG_NAME {
            subsystem = "com.googlecode.munki.\((logFile as NSString).deletingPathExtension)"
        }
    }
    if let logData = logString.data(using: String.Encoding.utf8) {
        let fm = FileManager.default
        if !fm.fileExists(atPath: logPath) {
            if !pathIsDirectory(dirName(logPath), followSymlinks: true) {
                try? fm.createDirectory(atPath: dirName(logPath), withIntermediateDirectories: true)
            }
            fm.createFile(atPath: logPath, contents: nil)
        }
        if let fh = FileHandle(forUpdatingAtPath: logPath) {
            let _ = fh.seekToEndOfFile()
            fh.write(logData)
        }
    }
    // log to Apple unified logging
    // (skip unified logging when doing duplicate logging to errors.log or warnings.log)
    if #available(macOS 11.0, *),
       boolPref("LogToSyslog") ?? false,
       !["com.googlecode.munki.errors", "com.googlecode.munki.warnings"].contains(subsystem)
    {
        let logger = Logger(subsystem: subsystem, category: "")
        logger.log(level: logLevel, "\(message, privacy: .public)")
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

/// Rotate a log if it's too large (or rotate regardless if we don't specify maxSize)
func rotateLog(_ logname: String, ifLargerThan maxSize: Int = 0) {
    let logpath = logNamed(logname)
    if let attributes = try? FileManager.default.attributesOfItem(atPath: logpath) {
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
    if let attributes = try? FileManager.default.attributesOfItem(atPath: mainLog) {
        let filesize = (attributes as NSDictionary).fileSize()
        if filesize > MAX_LOGFILE_SIZE {
            rotateLog(mainLog)
        }
    }
}

/// A nicer abstraction for the various Munki logging functions.
/// The "classic" UNIX logging levels each have a method, though traditionally Munki has
/// not used many of these levels.
class MunkiLogger {
    // an easy way to get the standard logger. can't use the name "default"
    static let standard = MunkiLogger(logname: MAIN_LOG_NAME)

    let logname: String
    var level = loggingLevel()

    init(logname: String) {
        self.logname = logname
    }

    func rotate(ifLargerThan maxSize: Int = 0) {
        rotateLog(logNamed(logname), ifLargerThan: maxSize)
    }

    func emergency(_ message: String) {
        munkiLog("EMERGENCY: \(message)", logFile: logname, logLevel: .fault)
    }

    func alert(_ message: String) {
        munkiLog("ALERT: \(message)", logFile: logname, logLevel: .fault)
    }

    func critical(_ message: String) {
        munkiLog("CRITICAL: \(message)", logFile: logname, logLevel: .fault)
    }

    func error(_ message: String) {
        munkiLog("ERROR: \(message)", logFile: logname, logLevel: .error)
    }

    func warning(_ message: String) {
        munkiLog("WARNING: \(message)", logFile: logname, logLevel: .error)
    }

    func notice(_ message: String) {
        if level > 0 {
            munkiLog(message, logFile: logname, logLevel: .default)
        }
    }

    func info(_ message: String) {
        if level > 0 {
            munkiLog(message, logFile: logname, logLevel: .default)
        }
    }

    func detail(_ message: String) {
        if level > 0 {
            munkiLog(message, logFile: logname, logLevel: .info)
        }
    }

    func debug(_ message: String) {
        debug1(message)
    }

    /// These aren't traditional UNIX logging levels, but Munki has traditionally used them
    func debug1(_ message: String) {
        if level > 1 {
            munkiLog("DEBUG1: \(message)", logFile: logname, logLevel: .debug)
        }
    }

    /// These aren't traditional UNIX logging levels, but Munki has traditionally used them
    func debug2(_ message: String) {
        if level > 2 {
            munkiLog("DEBUG2: \(message)", logFile: logname, logLevel: .debug)
        }
    }
}
