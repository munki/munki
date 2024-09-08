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

func loggingLevel() -> Int {
    // returns the logging level
    return pref("LoggingLevel") as? Int ?? 1
}

func mainLogPath() -> String {
    #if DEBUG
        return "/Users/Shared/Managed Installs/Logs/ManagedSoftwareUpdate.log"
    #else
        return pref("LogFile") as? String ?? managedInstallsDir(subpath: "Logs/ManagedSoftwareUpdate.log")
    #endif
}

func logNamed(_ name: String) -> String {
    // returns path to log file in same dir as main log
    return ((mainLogPath() as NSString).deletingLastPathComponent as NSString).appendingPathComponent(name)
}

func munkiLog(_ message: String, logFile: String = "") {
    // General logging function
    // TODO: add support for logging to /var/log/system.log
    // TODO: add support for logging to Apple unified logging

    // date format like `Jul 01 2024 17:30:36 -0700`
    let dateformatter = DateFormatter()
    dateformatter.dateFormat = "MMM dd yyyy HH:mm:ss Z"
    let timestamp = dateformatter.string(from: Date())
    let logString = "\(timestamp) \(message)\n"
    var logPath = ""
    if logFile.isEmpty {
        logPath = mainLogPath()
    } else {
        logPath = logNamed(logFile)
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
}

private func rotateLog(_ logFilePath: String) {
    // rotate a log
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

func munkiLogResetErrors() {
    // Rotate our errors.log
    rotateLog(logNamed("errors.log"))
}

func munkiLogResetWarnings() {
    // rotate our errors.log
    rotateLog(logNamed("warnings.log"))
}

func munkiLogRotateMainLog() {
    // rotate our main log if it's too large
    let mainLog = mainLogPath()
    if pathIsRegularFile(mainLog),
       let attributes = try? FileManager.default.attributesOfItem(atPath: mainLog)
    {
        let filesize = (attributes as NSDictionary).fileSize()
        if filesize > 1_000_000 {
            rotateLog(mainLog)
        }
    }
}
