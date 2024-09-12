//
//  SignalHandler.swift
//  munki
//
//  Created by Greg Neagle on 9/4/24.
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

/// Given a signal number, return the name
func signalName(_ sig: Int32) -> String {
    switch sig {
    case SIGHUP:
        return "SIGHUP"
    case SIGINT:
        return "SIGINT"
    case SIGQUIT:
        return "SIGQUIT"
    case SIGABRT:
        return "SIGABRT"
    case SIGKILL:
        return "SIGKILL"
    case SIGALRM:
        return "SIGALRM"
    case SIGTERM:
        return "SIGTERM"
    default:
        return String(sig)
    }
}

/// Installs a signal handler and returns an object that controls it;
/// Be sure to activate it!
func installSignalHandler(_ sig: Int32) -> DispatchSourceSignal {
    // the intent here is to kill our child process(es) when we get a SIGINT or SIGTERM
    // (sadly we can't do it for SIGKILL) so they don't keep running if we're stopped
    // by the user (or killed by another process)
    signal(sig, SIG_IGN) // // Make sure the signal does not terminate the application.

    let sigSrc = DispatchSource.makeSignalSource(signal: sig, queue: .main)
    sigSrc.setEventHandler {
        munkiLog("Got signal \(signalName(sig))")
        // kill all our child processes
        let ourPid = ProcessInfo.processInfo.processIdentifier
        for task in processesWithPPID(ourPid) {
            munkiLog("Sending signal \(signalName(sig)) to \(task.command), pid \(task.pid)...")
            kill(task.pid, sig)
        }
        // clean up our temp dirs
        TempDir.shared.cleanUp()
        // resend the signal to ourselves
        signal(sig, SIG_DFL)
        kill(ourPid, sig)
    }
    return sigSrc
}
