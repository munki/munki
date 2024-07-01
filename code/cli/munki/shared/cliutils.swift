//
//  cliutils.swift
//  munki
//
//  Created by Greg Neagle on 6/26/24.
//

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
        error: errorString)
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
