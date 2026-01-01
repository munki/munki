//
//  display.swift
//  munki
//
//  Created by Greg Neagle on 6/30/24.
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

import Darwin.C
import Foundation

/// a Singleton struct to hold shared config values
/// this might eventually be replaced by a more encompassing struct
struct DisplayOptions {
    static var verbose = 1
    static var munkistatusoutput = false

    private init() {} // prevents assigning an instance to another variable
}

/// Displays percent-done info, both at the command-line, and via MunkiStatus
/// Not displayed at the command-line if verbose is 0 (-q/--quiet)
func displayPercentDone(current: Int, maximum: Int) {
    var percentDone = 0
    if current >= maximum {
        percentDone = 100
    } else {
        percentDone = Int(Double(current) / Double(maximum) * 100)
    }

    if DisplayOptions.munkistatusoutput {
        munkiStatusPercent(percentDone)
    }

    if DisplayOptions.verbose > 0 {
        let step = [0, 7, 13, 20, 27, 33, 40, 47, 53, 60, 67, 73, 80, 87, 93, 100]
        let indicator = ["\t0", ".", ".", "20", ".", ".", "40", ".", ".",
                         "60", ".", ".", "80", ".", ".", "100\n"]
        var output = ""
        for i in 0 ... 15 {
            if percentDone >= step[i] {
                output += indicator[i]
            }
        }
        if !output.isEmpty {
            print("\r" + output, terminator: "")
            fflush(stdout)
        }
    }
}

/// a class to display messages to the user and also write to a log
class DisplayAndLog: MunkiLogger {
    // can't override "standard", can't use "default", so...
    static let main = DisplayAndLog(logname: MAIN_LOG_NAME)

    var verbose = DisplayOptions.verbose
    var munkistatusoutput = DisplayOptions.munkistatusoutput

    /// Prints error message to stderr and the log
    override func error(_ message: String) {
        let errorMsg = "ERROR: \(message)"
        if verbose > 0 {
            printStderr(errorMsg)
        }
        if logname == MAIN_LOG_NAME {
            // also log to our special errors log and add to report
            munkiLog(errorMsg, logFile: "errors.log")
            Report.shared.add(string: errorMsg, to: "Errors")
        }
        // let the superclass handle logging to the main log
        super.error(message)
    }

    /// Prints warning message to stderr and the log
    override func warning(_ message: String) {
        let warningMsg = "WARNING: \(message)"
        if verbose > 0 {
            printStderr(warningMsg)
        }
        if logname == MAIN_LOG_NAME {
            // also log to our special warnings log and add to report
            munkiLog(warningMsg, logFile: "warnings.log")
            Report.shared.add(string: warningMsg, to: "Warnings")
        }
        // let the superclass handle logging to the main log
        super.warning(message)
    }

    /// Displays major status messages, formatting as needed
    /// for verbose/non-verbose and munkistatus-style output.
    /// Not printed if verbose is 0
    func majorStatus(_ message: String) {
        if munkistatusoutput {
            munkiStatusMessage(message)
            munkiStatusDetail("")
            munkiStatusPercent(-1)
        }
        if verbose > 0 {
            if message.hasSuffix(".") || message.hasSuffix("…") {
                print(message)
            } else {
                print("\(message)...")
            }
            fflush(stdout)
        }
        // let the superclass handle logging to the main log
        super.notice(message)
    }

    /// Displays minor status messages, formatting as needed
    /// for verbose/non-verbose and munkistatus-style output.
    /// Not printed if verbose is 0
    func minorStatus(_ message: String) {
        if munkistatusoutput {
            munkiStatusDetail(message)
        }
        if verbose > 0 {
            if message.hasSuffix(".") || message.hasSuffix("…") {
                print("    \(message)")
            } else {
                print("    \(message)...")
            }
            fflush(stdout)
        }
        // let the superclass handle logging to the main log
        super.notice("    \(message)")
    }

    /// Displays info messages. Not displayed in MunkiStatus.
    /// Not printed if verbose is 0
    override func info(_ message: String) {
        if verbose > 0 {
            print("    \(message)")
            fflush(stdout)
        }
        // let the superclass handle logging to the main log
        super.info(message)
    }

    /// Displays minor info messages. Not displayed in MunkiStatus.
    /// These are usually logged only, but can be printed to stdout
    /// if verbose is set greater than 1 (-v)
    override func detail(_ message: String) {
        if verbose > 1 {
            print("    \(message)")
            fflush(stdout)
        }
        // let the superclass handle logging to the main log
        super.detail(message)
    }

    /// Displays debug level 1 messages. (verbose is set to 3 or more (-vv))
    /// Not displayed in MunkiStatus.
    override func debug(_ message: String) {
        debug1(message)
    }

    /// Displays debug level 1 messages. (verbose is set to 3 or more (-vv))
    /// Not displayed in MunkiStatus.
    override func debug1(_ message: String) {
        if verbose > 2 {
            print("    \(message)")
            fflush(stdout)
        }
        // let the superclass handle logging to the main log
        super.debug1(message)
    }

    /// Displays debug level 2 messages. (verbose is set to 4 or more (-vvv))
    override func debug2(_ message: String) {
        if verbose > 3 {
            print("    \(message)")
            fflush(stdout)
        }
        // let the superclass handle logging to the main log
        super.debug2(message)
    }
}
