//
//  display.swift
//  munki
//
//  Created by Greg Neagle on 6/30/24.
//

import Darwin.C
import Foundation

struct DisplayOptions {
    // a Singleton struct to hold shared config values
    // this might eventually be replaced by a more encompassing struct
    static let shared = DisplayOptions()
    
    var verbose: Int
    var munkistatusoutput: Bool
    
    private init(verbose: Int = 1, munkistatusoutput: Bool = false) {
        self.verbose = verbose
        self.munkistatusoutput = munkistatusoutput
    }
}
    
func displayPercentDone(current: Int, maximum: Int) {
    // displays percent-done info
    var percentDone = 0
    if current >= maximum {
        percentDone = 100
    } else {
        percentDone = Int(Double(current)/Double(maximum) * 100)
    }
    
    if DisplayOptions.shared.munkistatusoutput {
        // TODO: implement munkistatus stuff
        // munkistatusPercentDone(percentDone)
    }
    
    if DisplayOptions.shared.verbose > 0 {
        let step = [0, 7, 13, 20, 27, 33, 40, 47, 53, 60, 67, 73, 80, 87, 93, 100]
        let indicator = ["\t0", ".", ".", "20", ".", ".", "40", ".", ".",
                         "60", ".", ".", "80", ".", ".", "100\n"]
        var output = ""
        for i in 0...15 {
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
    
    // TODO: implement logging
    // munkiLog(message)
    if DisplayOptions.shared.munkistatusoutput {
        // TODO: implement munkistatus stuff
        // munkistatusMessage(message)
        // munkistatusDetail("")
        // munkistatusPercent(-1)
    }
    if DisplayOptions.shared.verbose > 0 {
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
    
    // TODO: implement logging
    // munkiLog("    \(message)")
    if DisplayOptions.shared.munkistatusoutput {
        // TODO: implement munkistatus stuff
        // munkistatusDetail(message)
    }
    if DisplayOptions.shared.verbose > 0 {
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
    
    // TODO: implement logging
    // munkiLog("    \(message)")
    if DisplayOptions.shared.verbose > 0 {
        print("    \(message)")
        fflush(stdout)
    }
}

func displayDetail(_ message: String) {
    // Displays minor info messages.
    // Not displayed in MunkiStatus.
    // These are usually logged only, but can be printed to
    // stdout if verbose is set greater than 1
    if DisplayOptions.shared.verbose > 1 {
        print("    \(message)")
        fflush(stdout)
    }
    // TODO: implement logging
    // if munkiLoggingLevel() > 0 {
    //     munkiLog("   \(message)")
    // }
}

func displayDebug1(_ message: String) {
    // Displays debug level 1 messages.
    if DisplayOptions.shared.verbose > 2 {
        print("    \(message)")
        fflush(stdout)
    }
    // TODO: implement logging
    // if munkiLoggingLevel() > 1 {
    //     munkiLog("DEBUG1: \(message)")
    // }
}

func displayDebug2(_ message: String) {
    // Displays debug level 2 messages.
    if DisplayOptions.shared.verbose > 3 {
        print("    \(message)")
        fflush(stdout)
    }
    // TODO: implement logging
    // if munkiLoggingLevel() > 2 {
    //     munkiLog("DEBUG2: \(message)")
    // }
}

func displayWarning(_ message: String) {
    // Prints warning message to stderr and the log
    let warning = "WARNING: \(message)"
    if DisplayOptions.shared.verbose > 0 {
        printStderr(warning)
    }
    // TODO: implement logging
    // munkiLog(warning)
    // munkiLog(warning, logfile: "warnings.log")
    
    // TODO: implement report collection
    // report(key: "Warnings", append: warning)
}

func displayError(_ message: String) {
    // Prints error message to stderr and the log
    let errorMsg = "ERROR: \(message)"
    if DisplayOptions.shared.verbose > 0 {
        printStderr(errorMsg)
    }
    // TODO: implement logging
    // munkiLog(errorMsg)
    // munkiLog(errorMsg, logfile: "errors.log")
    
    // TODO: implement report collection
    // report(key: "Errors", append: errorMsg)
}





