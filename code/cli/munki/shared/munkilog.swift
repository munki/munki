//
//  munkilog.swift
//  munki
//
//  Created by Greg Neagle on 7/1/24.
//

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
    let defaultLogPath = pref("LogFile") as? String ?? "\(DEFAULT_MANAGED_INSTALLS_DIR)/Logs/ManagedSoftwareUpdate.log"
    var logPath = ""
    if logFile.isEmpty {
        logPath = defaultLogPath
    } else {
        logPath = (defaultLogPath as NSString).deletingLastPathComponent
        logPath = (logPath as NSString).appendingPathComponent(logFile)
    }
    if let logData = logString.data(using: String.Encoding.utf8) {
        if let fh = FileHandle(forUpdatingAtPath: logPath) {
            let _ = fh.seekToEndOfFile()
            fh.write(logData)
        }
    }
}

// TODO: implement log rotation
