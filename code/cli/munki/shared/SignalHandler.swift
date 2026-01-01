//
//  SignalHandler.swift
//  munki
//
//  Created by Greg Neagle on 9/4/24.
//  Copyright 2024-2026 The Munki Project.
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
///
/// Why does this exist?
///
/// When our process is terminated via SIGINT (think Control-C), SIGTERM (think `kill` or `killall`),
/// any subprocesses it has started are _not_ automatically terminated,
/// This could be a problem if the user hits control-C while running `managedsoftwareupdate`, expecting
/// to stop an in-progress install, or while running `munkiimport`, expecting it to stop building a huge disk image
/// containing Xcode. In fact, I'd say the user would most likely expect that any subprocess would also be stopped.
/// While we can't do anything about SIGKILL, we can install handlers for SIGINT and SIGTERM that can find all
/// of the processes that are children of the current process, and send SIGINT or SIGTERM to those processes
/// before exiting this process.
///
/// A complication: some of the tools call libedit's readline function, which seems to do it's own mangling
/// of signal handling, in such a way that if we have these handlers in place, you cannot use SIGINT (again, think
/// Control-C) or SIGTERM to stop the process while it's waiting for input. So we've added a way to kill the
/// libedit/readline "session" as part of these signal handlers by passing a cleanup function to be run.
///
/// Additionally, if the libedit readline function is active when the process receives SIGINT or SIGTERM, the
/// signal handling enters an infinite loop if you try to send the original signal to the original process. So
/// instead of doing that, we just exit.
///
/// One more complication: I find `hdiutil create` doesn't always exit when send a SIGINT or SIGTERM.
/// Still investigating this one, but replicated the behavior in the terminal!
///
/// All of this feels hacky, but it's the best I could come up with. Would love to learn of a better approach!
func installSignalHandler(
    _ sig: Int32,
    logger: MunkiLogger? = nil,
    cleanUpFunction: (() -> Void)? = nil
) -> DispatchSourceSignal {
    // the intent here is to kill our child process(es) when we get a SIGINT or SIGTERM
    // (sadly we can't do it for SIGKILL) so they don't keep running if we're stopped
    // by the user (or killed by another process)
    signal(sig, SIG_IGN) // // Make sure the signal does not terminate the application.

    let sigSrc = DispatchSource.makeSignalSource(signal: sig, queue: .main)
    sigSrc.setEventHandler {
        if let logger {
            logger.alert("Got signal \(signalName(sig))")
        }

        // kill all our child processes
        let ourPid = ProcessInfo.processInfo.processIdentifier
        for task in processesWithPPID(ourPid) {
            if let logger {
                logger.notice("Sending signal \(signalName(sig)) to \(task.command), pid \(task.pid)...")
            }
            let osErr = kill(task.pid, sig)
            if osErr != noErr, let logger {
                logger.error("Got err \(osErr) when sending \(signalName(sig)) to \(task.command), pid \(task.pid)")
            }
        }
        // clean up our temp dirs
        TempDir.shared.cleanUp()
        if let cleanUpFunction {
            // an additional cleanup function was specified; run it
            cleanUpFunction()
        }
        // reset the signal handler to default
        signal(sig, SIG_DFL)
        // kill(ourPid, sig)  // this causes an infinite loop with readline
        // So just exit with code to show what signal we got
        exit(128 + sig)
    }
    return sigSrc
}
