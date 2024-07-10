//
//  cliutils.swift
//  munki
//
//  Created by Greg Neagle on 6/26/24.
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

func printStderr(_ items: Any..., separator: String = " ", terminator: String = "\n") {
    // similar to print() function, but prints to stderr
    let output = items
        .map { String(describing: $0) }
        .joined(separator: separator) + terminator

    FileHandle.standardError.write(output.data(using: .utf8)!)
}

func trimTrailingNewline(_ s: String) -> String {
    var trimmedString = s
    if trimmedString.last == "\n" {
        trimmedString = String(trimmedString.dropLast())
    }
    return trimmedString
}

struct CLIResults {
    var exitcode: Int = 0
    var output: String = ""
    var error: String = ""
}

func runCLI(_ tool: String, arguments: [String] = [], stdIn: String = "") -> CLIResults {
    // runs a command line tool synchronously, returns CLIResults
    // not a good choice for tools that might generate a lot of output or error output
    let inPipe = Pipe()
    let outPipe = Pipe()
    let errorPipe = Pipe()

    let task = Process()
    task.launchPath = tool
    task.arguments = arguments

    task.standardInput = inPipe
    task.standardOutput = outPipe
    task.standardError = errorPipe

    task.launch()
    if stdIn != "" {
        if let data = stdIn.data(using: .utf8) {
            inPipe.fileHandleForWriting.write(data)
        }
    }
    inPipe.fileHandleForWriting.closeFile()
    task.waitUntilExit()

    let outputData = outPipe.fileHandleForReading.readDataToEndOfFile()
    let outputString = trimTrailingNewline(String(data: outputData, encoding: .utf8) ?? "")
    outPipe.fileHandleForReading.closeFile()

    let errorData = errorPipe.fileHandleForReading.readDataToEndOfFile()
    let errorString = trimTrailingNewline(String(data: errorData, encoding: .utf8) ?? "")
    errorPipe.fileHandleForReading.closeFile()

    return CLIResults(
        exitcode: Int(task.terminationStatus),
        output: outputString,
        error: errorString
    )
}

enum CalledProcessError: Error {
    case error(description: String)
}

func checkCall(_ tool: String, arguments: [String] = [], stdIn: String = "") throws -> String {
    // like Python's subprocess.check_call
    let result = runCLI(tool, arguments: arguments, stdIn: stdIn)
    if result.exitcode != 0 {
        throw CalledProcessError.error(description: result.error)
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
    var outputProcessing = false
    var errorProcessing = false
}

protocol AsyncProcessDelegate: AnyObject {
    func processUpdated()
}

class AsyncProcessRunner {
    let task = Process()
    var status = AsyncProcessStatus()
    var results = CLIResults()
    var delegate: AsyncProcessDelegate?

    init(_ tool: String, arguments: [String] = [], stdIn _: String = "") {
        task.launchPath = tool
        task.arguments = arguments

        // set up our stdout and stderr pipes and handlers
        task.standardOutput = Pipe()
        let outputHandler = { (file: FileHandle!) in
            self.processOutput(file)
        }
        (task.standardOutput as? Pipe)?.fileHandleForReading.readabilityHandler = outputHandler
        task.standardError = Pipe()
        let errorHandler = { (file: FileHandle!) in
            self.processError(file)
        }
        (task.standardError as? Pipe)?.fileHandleForReading.readabilityHandler = errorHandler
    }

    deinit {
        // make sure the task gets terminated
        cancel()
    }

    func cancel() {
        task.terminate()
    }

    func run() async {
        if !task.isRunning {
            do {
                try task.run()
            } catch {
                // task didn't start
                displayError("ERROR running \(String(describing: task.launchPath))")
                displayError(error.localizedDescription)
                status.phase = .ended
                delegate?.processUpdated()
                return
            }
            status.phase = .started
            delegate?.processUpdated()
        }
        task.waitUntilExit()

        // wait until all stdout/stderr is processed
        while status.outputProcessing || status.errorProcessing {
            do {
                try await Task.sleep(nanoseconds: 100_000_000)
            } catch {
                // do nothing
            }
        }

        // reset the readability handlers
        (task.standardOutput as? Pipe)?.fileHandleForReading.readabilityHandler = nil
        (task.standardError as? Pipe)?.fileHandleForReading.readabilityHandler = nil

        status.phase = .ended
        status.terminationStatus = task.terminationStatus
        results.exitcode = Int(task.terminationStatus)
        delegate?.processUpdated()
    }

    func readData(_ file: FileHandle) -> String {
        // read available data from a file handle and return a string
        let data = file.availableData
        if data.count > 0 {
            return String(bytes: data, encoding: .utf8) ?? ""
        }
        return ""
    }

    func processError(_ file: FileHandle) {
        status.errorProcessing = true
        results.error.append(readData(file))
        status.errorProcessing = false
    }

    func processOutput(_ file: FileHandle) {
        status.outputProcessing = true
        results.output.append(readData(file))
        status.outputProcessing = false
    }
}

func runCliAsync(_ tool: String, arguments: [String] = [], stdIn: String = "") async -> CLIResults {
    // a basic wrapper intended to be used just as you would runCLI, but with tasks that
    // return a lot of output and would overflow the buffer
    let proc = AsyncProcessRunner(tool, arguments: arguments, stdIn: stdIn)
    await proc.run()
    return proc.results
}
