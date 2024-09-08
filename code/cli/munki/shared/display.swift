//
//  display.swift
//  munki
//
//  Created by Greg Neagle on 6/30/24.
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

import Darwin.C
import Foundation

struct DisplayOptions {
    // a Singleton struct to hold shared config values
    // this might eventually be replaced by a more encompassing struct

    static var verbose = 1
    static var munkistatusoutput = false

    private init() {}
}

func displayPercentDone(current: Int, maximum: Int) {
    // displays percent-done info
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

func displayMajorStatus(_ message: String) {
    // Displays major status messages, formatting as needed
    // for verbose/non-verbose and munkistatus-style output.

    munkiLog(message)
    if DisplayOptions.munkistatusoutput {
        munkiStatusMessage(message)
        munkiStatusDetail("")
        munkiStatusPercent(-1)
    }
    if DisplayOptions.verbose > 0 {
        if message.hasSuffix(".") || message.hasSuffix("…") {
            print(message)
        } else {
            print("\(message)...")
        }
        fflush(stdout)
    }
}

func displayMinorStatus(_ message: String) {
    // Displays minor status messages, formatting as needed
    // for verbose/non-verbose and munkistatus-style output.

    munkiLog("    \(message)")
    if DisplayOptions.munkistatusoutput {
        munkiStatusDetail(message)
    }
    if DisplayOptions.verbose > 0 {
        if message.hasSuffix(".") || message.hasSuffix("…") {
            print("    \(message)")
        } else {
            print("    \(message)...")
        }
        fflush(stdout)
    }
}

func displayInfo(_ message: String) {
    // Displays info messages.
    // Not displayed in MunkiStatus.

    munkiLog("    \(message)")
    if DisplayOptions.verbose > 0 {
        print("    \(message)")
        fflush(stdout)
    }
}

func displayDetail(_ message: String) {
    // Displays minor info messages.
    // Not displayed in MunkiStatus.
    // These are usually logged only, but can be printed to
    // stdout if verbose is set greater than 1
    if DisplayOptions.verbose > 1 {
        print("    \(message)")
        fflush(stdout)
    }
    if loggingLevel() > 0 {
        munkiLog("   \(message)")
    }
}

func displayDebug1(_ message: String) {
    // Displays debug level 1 messages.
    if DisplayOptions.verbose > 2 {
        print("    \(message)")
        fflush(stdout)
    }
    if loggingLevel() > 1 {
        munkiLog("DEBUG1: \(message)")
    }
}

func displayDebug2(_ message: String) {
    // Displays debug level 2 messages.
    if DisplayOptions.verbose > 3 {
        print("    \(message)")
        fflush(stdout)
    }
    if loggingLevel() > 2 {
        munkiLog("DEBUG2: \(message)")
    }
}

func displayWarning(_ message: String, addToReport: Bool = true) {
    // Prints warning message to stderr and the log
    let warning = "WARNING: \(message)"
    if DisplayOptions.verbose > 0 {
        printStderr(warning)
    }
    munkiLog(warning)
    munkiLog(warning, logFile: "warnings.log")

    if addToReport {
        Report.shared.add(string: warning, to: "Warnings")
    }
}

func displayError(_ message: String, addToReport: Bool = true) {
    // Prints error message to stderr and the log
    let errorMsg = "ERROR: \(message)"
    if DisplayOptions.verbose > 0 {
        printStderr(errorMsg)
    }
    munkiLog(errorMsg)
    munkiLog(errorMsg, logFile: "errors.log")

    if addToReport {
        Report.shared.add(string: errorMsg, to: "Errors")
    }
}
