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

func munkiLog(_ message: String, logFile: String = "") {
    // General logging function
    // TODO: add support for logging to /var/log/system.log
    // TODO: add support for logging to Apple unified logging

    // date format like `Jul 01 2024 17:30:36 -0700`
    let dateformatter = DateFormatter()
    dateformatter.dateFormat = "MMM dd yyyy HH:mm:ss Z"
    let timestamp = dateformatter.string(from: Date())
    let logString = "\(timestamp) \(message)\n"
    #if DEBUG
        let defaultLogPath = "/Users/Shared/Managed Installs/Logs/ManagedSoftwareUpdate.log"
    #else
        let defaultLogPath = pref("LogFile") as? String ?? managedInstallsDir(subpath: "Logs/ManagedSoftwareUpdate.log")
    #endif
    var logPath = ""
    if logFile.isEmpty {
        logPath = defaultLogPath
    } else {
        logPath = (defaultLogPath as NSString).deletingLastPathComponent
        logPath = (logPath as NSString).appendingPathComponent(logFile)
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

// TODO: implement log rotation
