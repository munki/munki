//
//  supervisor.swift
//  supervisor
//
//  Created by Greg Neagle on 4/28/25.
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

import ArgumentParser
import Foundation

private let PROCESS_DID_NOT_START: Int32 = 127
private let PROCESS_TIMED_OUT: Int32 = 126
private let signalName = [
    SIGINT: "SIGINT",
    SIGTERM: "SIGTERM",
]

func signalHandler(_ sig: Int32) -> DispatchSourceSignal {
    // the intent here is to kill our child process(es) when we get a SIGINT or SIGTERM
    // (sadly we can't do it for SIGKILL) so they don't keep running if we're stopped
    // by the user (or killed by another process)
    signal(sig, SIG_IGN) // // Make sure the signal does not terminate the application.

    let sigSrc = DispatchSource.makeSignalSource(signal: sig, queue: .main)
    sigSrc.setEventHandler {
        printStderr("Got signal \(signalName[sig] ?? String(sig))")
        // kill all our child processes
        let ourPid = ProcessInfo.processInfo.processIdentifier
        for task in processesWithPPID(ourPid) {
            printStderr("Sending signal \(signalName[sig] ?? String(sig)) to \(task.command), pid \(task.pid)...")
            let osErr = kill(task.pid, sig)
            if osErr != noErr {
                printStderr("Got err \(osErr) when sending \(signalName[sig] ?? String(sig)) to \(task.command), pid \(task.pid)")
            }
        }
        // reset the signal handler to default
        signal(sig, SIG_DFL)
        kill(ourPid, sig)
    }
    return sigSrc
}

class SupervisorProcessRunner {
    let task = Process()
    var timeout: Int = 0

    init(_ command: String, arguments: [String] = [], timeout: Int = 0) {
        task.executableURL = URL(fileURLWithPath: command)
        task.arguments = arguments
        self.timeout = timeout
    }

    deinit {
        // make sure the task gets terminated
        killTask()
    }

    func killTask() {
        let KILL_WAIT_TIME_USEC = useconds_t(1_000_000)
        task.terminate() // sends SIGTERM
        usleep(KILL_WAIT_TIME_USEC)
        if !task.isRunning {
            return
        }
        let pid = task.processIdentifier
        _signal.kill(pid, SIGKILL)
        usleep(KILL_WAIT_TIME_USEC)
        if task.isRunning {
            // log("pid \(pid) won't die")
        }
    }

    func run() async -> Int32 {
        var deadline: Date?
        if !task.isRunning {
            do {
                if timeout > 0 {
                    deadline = Date().addingTimeInterval(TimeInterval(timeout))
                }
                try task.run()
            } catch {
                // task didn't start
                printStderr("ERROR running \(task.executableURL?.path ?? "")")
                printStderr(error.localizedDescription)
                return PROCESS_DID_NOT_START
            }
        }
        while task.isRunning {
            // loop until process exits
            if let deadline {
                if Date() >= deadline {
                    printStderr("ERROR: \(task.executableURL?.path ?? "") timed out after \(timeout) seconds")
                    killTask()
                    return PROCESS_TIMED_OUT
                }
            }
            await Task.yield()
        }
        return task.terminationStatus
    }
}

class Supervisor {
    var timeout: Int
    var delayRandom: Int
    var command: String
    var arguments: [String]

    init(timeout: Int, delayRandom: Int, command: String, arguments: [String]) {
        self.timeout = timeout
        self.delayRandom = delayRandom
        self.command = command
        self.arguments = arguments
    }

    func execute() async -> Int32 {
        // log("Executing \(command) with arguments: \(arguments)")
        if delayRandom > 0 {
            let randomDelay = Int.random(in: 0 ... delayRandom)
            usleep(useconds_t(randomDelay * 1_000_000))
        }
        return await SupervisorProcessRunner(command, arguments: arguments, timeout: timeout).run()
    }
}

@main
struct SupervisorCommand: AsyncParsableCommand {
    static var configuration = CommandConfiguration(
        usage: "supervisor [options] -- <path_to_executable> [arguments]"
    )

    @Option(help: ArgumentHelp("after n seconds, terminate the executable",
                               discussion: "0 seconds means never timeout",
                               valueName: "n")
    )
    var timeout: Int = 0

    @Option(name: [.customLong("delayrandom")],
            help: ArgumentHelp("delay the execution of executable by random seconds up to n", valueName: "n"))
    var delayRandom: Int = 0

    @Argument(parsing: .postTerminator,
              help: ArgumentHelp(valueName: "path_to_executable [arguments]"))
    var commandAndArgs: [String]

    mutating func run() async throws {
        // install handlers for SIGINT and SIGTERM
        let sigintSrc = signalHandler(SIGINT)
        sigintSrc.activate()
        let sigtermSrc = signalHandler(SIGTERM)
        sigtermSrc.activate()

        let command = commandAndArgs[0]
        let arguments = Array(commandAndArgs[1...])
        throw await ExitCode(
            Supervisor(
                timeout: timeout,
                delayRandom: delayRandom,
                command: command,
                arguments: arguments
            ).execute()
        )
    }
}
