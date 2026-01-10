//
//  cliutils.swift
//  munki
//
//  Created by Greg Neagle on 6/26/24.
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

// TODO: there is too much repetition in this module; consolidate
// and/or eliminate some of this

import Darwin
import Foundation

/// Get system uptime in seconds. Uptime is paused while the device is sleeping.
func get_uptime() -> Double {
    let uptime = clock_gettime_nsec_np(CLOCK_UPTIME_RAW_APPROX)
    let seconds = Double(uptime) / Double(NSEC_PER_SEC)
    return seconds
}

struct CLIResults {
    var exitcode: Int = 0
    var output: String = "" // process stdout
    var error: String = "" // process stderr
    var timedOut: Bool = false
    var failureDetail: String = "" // error text from this code
}

/// A class to run processes synchronously
class ProcessRunner {
    let task = Process()
    var results = CLIResults()
    // var delegate: ProcessDelegate?

    init(_ tool: String,
         arguments: [String] = [],
         environment: [String: String] = [:],
         stdIn: String = "")
    {
        task.executableURL = URL(fileURLWithPath: tool)
        task.arguments = arguments
        if !environment.isEmpty {
            task.environment = environment
        }

        // set up input pipe
        let inPipe = Pipe()
        task.standardInput = inPipe
        // set up our stdout and stderr pipes and handlers
        let outputPipe = Pipe()
        outputPipe.fileHandleForReading.readabilityHandler = { fh in
            let data = fh.availableData
            if data.isEmpty { // EOF on the pipe
                fh.readabilityHandler = nil
                try? fh.close()
            } else {
                self.processOutput(String(data: data, encoding: .utf8)!)
            }
        }
        let errorPipe = Pipe()
        errorPipe.fileHandleForReading.readabilityHandler = { fh in
            let data = fh.availableData
            if data.isEmpty { // EOF on the pipe
                fh.readabilityHandler = nil
                try? fh.close()
            } else {
                self.processError(String(data: data, encoding: .utf8)!)
            }
        }
        let inputPipe = Pipe()
        inputPipe.fileHandleForWriting.writeabilityHandler = { fh in
            if !stdIn.isEmpty {
                if let data = stdIn.data(using: .utf8) {
                    fh.write(data)
                }
            }
            try? fh.close()
            fh.writeabilityHandler = nil
        }
        task.standardOutput = outputPipe
        task.standardError = errorPipe
        task.standardInput = inputPipe
    }

    deinit {
        // make sure the task gets terminated
        cancel()
    }

    func cancel() {
        task.terminate()
    }

    func run() {
        if !task.isRunning {
            do {
                try task.run()
            } catch {
                // task didn't start
                results.failureDetail.append("error running \(task.executableURL?.path ?? "")")
                results.failureDetail.append(error.localizedDescription)
                results.exitcode = -1
                // delegate?.processUpdated()
                return
            }
            // delegate?.processUpdated()
        }
        // task.waitUntilExit()
        while task.isRunning {
            // loop until process exits
            usleep(10000)
        }

        let timestamp = get_uptime()
        while (task.standardOutput as? Pipe)?.fileHandleForReading.readabilityHandler != nil ||
            (task.standardError as? Pipe)?.fileHandleForReading.readabilityHandler != nil
        {
            // wait no more than 1 second for stdout and stderr to close
            if get_uptime() >= timestamp + Double(1.0) {
                break
            }
            // loop until stdout and stderr pipes close
            usleep(10000)
        }

        results.exitcode = Int(task.terminationStatus)
        // delegate?.processUpdated()
    }

    // making this a separate method so the non-timeout calls
    // don't need to worry about catching exceptions
    // NOTE: the timeout here is _not_ an idle timeout;
    // it's the maximum time the process can run
    func run(timeout: Int = -1) throws {
        var deadline: Double?
        if !task.isRunning {
            do {
                if timeout > 0 {
                    deadline = get_uptime() + Double(timeout)
                }
                try task.run()
            } catch {
                // task didn't start
                results.failureDetail.append("ERROR running \(task.executableURL?.path ?? "")")
                results.failureDetail.append(error.localizedDescription)
                results.exitcode = -1
                // delegate?.processUpdated()
                return
            }
            // delegate?.processUpdated()
        }
        // task.waitUntilExit()
        while task.isRunning {
            // loop until process exits
            if let deadline {
                if get_uptime() >= deadline {
                    results.failureDetail.append("ERROR: \(task.executableURL?.path ?? "") timed out after \(timeout) seconds")
                    task.terminate()
                    results.exitcode = Int.max // maybe we should define a specific code
                    results.timedOut = true
                    throw ProcessError.timeout
                }
            }
            usleep(10000)
        }

        let timestamp = get_uptime()
        while (task.standardOutput as? Pipe)?.fileHandleForReading.readabilityHandler != nil ||
            (task.standardError as? Pipe)?.fileHandleForReading.readabilityHandler != nil
        {
            // wait no more than 1 second for stdout and stderr to close
            if get_uptime() >= timestamp + Double(1.0) {
                break
            }
            // loop until stdout and stderr pipes close
            usleep(10000)
        }

        results.exitcode = Int(task.terminationStatus)
        // delegate?.processUpdated()
    }

    func processOutput(_ str: String) {
        // can be overridden by subclasses
        results.output.append(str)
    }

    func processError(_ str: String) {
        // can be overridden by subclasses
        results.error.append(str)
    }
}

/// Runs a command line tool synchronously, returns CLIResults
/// this implementation attempts to handle scenarios in which a large amount of stdout
/// or stderr output is generated
// TODO: reimplement this to use ProcessRunner
func runCLI(_ tool: String,
            arguments: [String] = [],
            environment: [String: String] = [:],
            stdIn: String = "") -> CLIResults
{
    var results = CLIResults()
    var stdoutData = Data()
    var stderrData = Data()

    let task = Process()
    task.executableURL = URL(fileURLWithPath: tool)
    task.arguments = arguments
    if !environment.isEmpty {
        task.environment = environment
    }

    // set up our stdout and stderr pipes and handlers
    let outputPipe = Pipe()
    outputPipe.fileHandleForReading.readabilityHandler = { fh in
        let data = fh.availableData
        if data.isEmpty { // EOF on the pipe
            fh.readabilityHandler = nil
            try? fh.close()
        } else {
            stdoutData.append(data)
            // try to decode the data we've received as a string
            if let outputString = String(data: stdoutData, encoding: .utf8) {
                results.output.append(outputString)
                stdoutData.removeAll(keepingCapacity: false)
            }
        }
    }
    let errorPipe = Pipe()
    errorPipe.fileHandleForReading.readabilityHandler = { fh in
        let data = fh.availableData
        if data.isEmpty { // EOF on the pipe
            fh.readabilityHandler = nil
            try? fh.close()
        } else {
            stderrData.append(data)
            // try to decode the data we've received as a string
            if let errString = String(data: stderrData, encoding: .utf8) {
                results.error.append(errString)
                stderrData.removeAll(keepingCapacity: false)
            }
        }
    }
    let inputPipe = Pipe()
    inputPipe.fileHandleForWriting.writeabilityHandler = { fh in
        if !stdIn.isEmpty {
            if let data = stdIn.data(using: .utf8) {
                fh.write(data)
            }
        }
        try? fh.close()
        fh.writeabilityHandler = nil
    }
    task.standardOutput = outputPipe
    task.standardError = errorPipe
    task.standardInput = inputPipe

    do {
        try task.run()
    } catch {
        // task didn't launch
        results.exitcode = -1
        return results
    }
    // task.waitUntilExit()
    while task.isRunning {
        // loop until process exits
        usleep(10000)
    }

    let timestamp = get_uptime()
    while outputPipe.fileHandleForReading.readabilityHandler != nil ||
        errorPipe.fileHandleForReading.readabilityHandler != nil
    {
        // wait no more than 1 second for stdout and stderr to close
        if get_uptime() >= timestamp + Double(1.0) {
            break
        }
        // loop until stdout and stderr pipes close
        usleep(10000)
    }

    results.exitcode = Int(task.terminationStatus)

    results.output = String(results.output.trailingNewlineTrimmed)
    results.error = String(results.error.trailingNewlineTrimmed)

    return results
}

enum ProcessError: Error {
    case error(description: String)
    case timeout
}

/// like Python's subprocess.check_output
func checkOutput(_ tool: String,
                 arguments: [String] = [],
                 environment: [String: String] = [:],
                 stdIn: String = "") throws -> String
{
    let result = runCLI(
        tool,
        arguments: arguments,
        environment: environment,
        stdIn: stdIn
    )
    if result.exitcode != 0 {
        throw ProcessError.error(description: result.error)
    }
    return result.output
}

enum AsyncProcessPhase: Int {
    case notStarted
    case started
    case ended
}

struct AsyncProcessStatus {
    var phase: AsyncProcessPhase = .notStarted
    var terminationStatus: Int32 = 0
}

protocol AsyncProcessDelegate: AnyObject {
    func processUpdated()
}

/// A class to run processes in an async manner
class AsyncProcessRunner {
    let task = Process()
    var status = AsyncProcessStatus()
    var results = CLIResults()
    var delegate: AsyncProcessDelegate?
    var stdoutData = Data()
    var stderrData = Data()

    init(_ tool: String,
         arguments: [String] = [],
         environment: [String: String] = [:],
         stdIn: String = "")
    {
        task.executableURL = URL(fileURLWithPath: tool)
        task.arguments = arguments
        if !environment.isEmpty {
            task.environment = environment
        }

        // set up input pipe
        let inPipe = Pipe()
        task.standardInput = inPipe
        // set up our stdout and stderr pipes and handlers
        let outputPipe = Pipe()
        outputPipe.fileHandleForReading.readabilityHandler = { fh in
            let data = fh.availableData
            if data.isEmpty { // EOF on the pipe
                fh.readabilityHandler = nil
                fh.closeFile()
            } else {
                self.stdoutData.append(data)
                // try to decode the data we've received as a string
                if let outputString = String(data: self.stdoutData, encoding: .utf8) {
                    self.processOutput(outputString)
                    self.stdoutData.removeAll(keepingCapacity: false)
                }
            }
        }
        let errorPipe = Pipe()
        errorPipe.fileHandleForReading.readabilityHandler = { fh in
            let data = fh.availableData
            if data.isEmpty { // EOF on the pipe
                fh.readabilityHandler = nil
                fh.closeFile()
            } else {
                self.stderrData.append(data)
                // try to decode the data we've received as a string
                if let errorString = String(data: self.stdoutData, encoding: .utf8) {
                    self.processError(errorString)
                    self.stderrData.removeAll(keepingCapacity: false)
                }
            }
        }
        let inputPipe = Pipe()
        inputPipe.fileHandleForWriting.writeabilityHandler = { fh in
            if !stdIn.isEmpty {
                if let data = stdIn.data(using: .utf8) {
                    fh.write(data)
                }
            }
            fh.closeFile()
            fh.writeabilityHandler = nil
        }
        task.standardOutput = outputPipe
        task.standardError = errorPipe
        task.standardInput = inputPipe
    }

    deinit {
        // make sure the task gets terminated
        cancel()
    }

    func cancel() {
        if task.isRunning {
            task.terminate()
        }
    }

    func run() async {
        if !task.isRunning {
            do {
                try task.run()
            } catch {
                // task didn't start
                results.failureDetail.append("error running \(task.executableURL?.path ?? "")")
                results.failureDetail.append(": \(error.localizedDescription)")
                results.exitcode = -1
                status.phase = .ended
                delegate?.processUpdated()
                return
            }
            status.phase = .started
            delegate?.processUpdated()
        }
        // task.waitUntilExit()
        while task.isRunning {
            // loop until process exits
            await Task.yield()
        }

        let timestamp = get_uptime()
        while (task.standardOutput as? Pipe)?.fileHandleForReading.readabilityHandler != nil ||
            (task.standardError as? Pipe)?.fileHandleForReading.readabilityHandler != nil
        {
            // wait no more than 1 second for stdout and stderr to close
            if get_uptime() >= timestamp + Double(1.0) {
                break
            }
            // loop until stdout and stderr pipes close
            await Task.yield()
        }

        status.phase = .ended
        status.terminationStatus = task.terminationStatus
        results.exitcode = Int(task.terminationStatus)
        delegate?.processUpdated()
    }

    // making this a separate method so the non-timeout calls
    // don't need to worry about catching exceptions
    // NOTE: the timeout here is _not_ an idle timeout;
    // it's the maximum time the process can run
    func run(timeout: Int = -1) async throws {
        var deadline: Double?
        if !task.isRunning {
            do {
                if timeout > 0 {
                    deadline = get_uptime() + Double(timeout)
                }
                try task.run()
            } catch {
                // task didn't start
                results.failureDetail.append("ERROR running \(task.executableURL?.path ?? "")")
                results.failureDetail.append(error.localizedDescription)
                results.exitcode = -1
                status.phase = .ended
                delegate?.processUpdated()
                return
            }
            status.phase = .started
            delegate?.processUpdated()
        }
        // task.waitUntilExit()
        while task.isRunning {
            // loop until process exits
            if let deadline {
                if get_uptime() >= deadline {
                    results.failureDetail.append("ERROR: \(task.executableURL?.path ?? "") timed out after \(timeout) seconds")
                    task.terminate()
                    results.exitcode = Int.max // maybe we should define a specific code
                    results.timedOut = true
                    throw ProcessError.timeout
                }
            }
            await Task.yield()
        }

        let timestamp = get_uptime()
        while (task.standardOutput as? Pipe)?.fileHandleForReading.readabilityHandler != nil ||
            (task.standardError as? Pipe)?.fileHandleForReading.readabilityHandler != nil
        {
            // wait no more than 1 second for stdout and stderr to close
            if get_uptime() >= timestamp + Double(1.0) {
                break
            }
            // loop until stdout and stderr pipes close
            await Task.yield()
        }

        status.phase = .ended
        status.terminationStatus = task.terminationStatus
        results.exitcode = Int(task.terminationStatus)
        delegate?.processUpdated()
    }

    func processOutput(_ str: String) {
        // can be overridden by subclasses
        results.output.append(str)
    }

    func processError(_ str: String) {
        // can be overridden by subclasses
        results.error.append(str)
    }
}

/// a basic wrapper intended to be used just as you would runCLI, but async
func runCliAsync(_ tool: String,
                 arguments: [String] = [],
                 environment: [String: String] = [:],
                 stdIn: String = "") async -> CLIResults
{
    let proc = AsyncProcessRunner(
        tool,
        arguments: arguments,
        environment: environment,
        stdIn: stdIn
    )
    await proc.run()

    // trim trailing newlines in output and stderr to match behavior of runCLI
    proc.results.output = String(proc.results.output.trailingNewlineTrimmed)
    proc.results.error = String(proc.results.error.trailingNewlineTrimmed)
    return proc.results
}

/// a basic wrapper intended to be used just as you would runCLI,
/// but async and with a timeout
/// throws ProcessError.timeout if the process times out
func runCliAsync(_ tool: String,
                 arguments: [String] = [],
                 environment: [String: String] = [:],
                 stdIn: String = "",
                 timeout: Int) async throws -> CLIResults
{
    let proc = AsyncProcessRunner(
        tool,
        arguments: arguments,
        environment: environment,
        stdIn: stdIn
    )
    try await proc.run(timeout: timeout)

    // trim trailing newlines in output and stderr to match behavior of runCLI
    proc.results.output = String(proc.results.output.trailingNewlineTrimmed)
    proc.results.error = String(proc.results.error.trailingNewlineTrimmed)
    return proc.results
}
