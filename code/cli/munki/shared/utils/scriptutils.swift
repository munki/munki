//
//  scriptutils.swift
//  munki
//
//  Created by Greg Neagle on 8/5/24.
//

import Foundation

private let display = DisplayAndLog.main

/// Writes string data to path.
/// Returns success or failure as a boolean.
func createExecutableFile(
    atPath path: String,
    withStringContents stringContents: String,
    posixPermissions: Int = 0o700
) -> Bool {
    let data = stringContents.data(using: .utf8)
    return FileManager.default.createFile(
        atPath: path,
        contents: data,
        attributes: [FileAttributeKey.posixPermissions: posixPermissions]
    )
}

/// Runs a script, processes its output
class ScriptRunner: AsyncProcessRunner {
    private var remainingOutput = ""
    private var remainingError = ""

    func linesAndRemainderOf(_ str: String) -> ([String], String) {
        var lines = str.trailingNewlineTrimmed.split(
            omittingEmptySubsequences: false,
            whereSeparator: \.isNewline
        ).map(String.init)
        var remainder = ""
        if lines.count > 0, !str.hasSuffix("\n") {
            // last line of string did not end with a newline; might be a partial
            remainder = lines.last ?? ""
            lines.removeLast()
        }
        return (lines, remainder)
    }

    override func processOutput(_ str: String) {
        super.processOutput(str)
        let (lines, remainder) = linesAndRemainderOf(remainingOutput + str)
        remainingOutput = remainder
        for line in lines {
            display.info(line)
        }
    }

    override func processError(_ str: String) {
        super.processError(str)
        let (lines, remainder) = linesAndRemainderOf(remainingError + str)
        remainingError = remainder
        for line in lines {
            display.info(line)
        }
    }
}

/// Runs a script, Returns return code.
func runScript(_ path: String, itemName: String, scriptName: String, suppressError: Bool = false) async -> Int {
    if suppressError {
        display.detail("Running \(scriptName) for \(itemName)")
    } else {
        display.minorStatus("Running \(scriptName) for \(itemName)")
    }
    if DisplayOptions.munkistatusoutput {
        // set indeterminate progress bar
        munkiStatusPercent(-1)
    }

    let proc = ScriptRunner(path)
    await proc.run()
    let result = proc.results

    if result.exitcode != 0, !suppressError {
        display.error("Running \(scriptName) for \(itemName) failed.")
        display.error("stderr:")
        display.error(String(repeating: "-", count: 78))
        for line in proc.results.error.components(separatedBy: .newlines) {
            display.error("    " + line)
        }
        display.error(String(repeating: "-", count: 78))
        display.error("stdout:")
        display.error(String(repeating: "-", count: 78))
        for line in proc.results.output.components(separatedBy: .newlines) {
            display.error("    " + line)
        }
        display.error(String(repeating: "-", count: 78))
    } else if !suppressError {
        munkiLog("Running \(scriptName) for \(itemName) was successful.")
    }

    if DisplayOptions.munkistatusoutput {
        // clear indeterminate progress bar
        munkiStatusPercent(0)
    }

    return result.exitcode
}

/// Runs a script, Returns CLIResults.
func runScriptAndReturnResults(_ path: String, itemName: String, scriptName: String, suppressError: Bool = false) async -> CLIResults {
    if suppressError {
        display.detail("Running \(scriptName) for \(itemName)")
    } else {
        display.minorStatus("Running \(scriptName) for \(itemName)")
    }
    if DisplayOptions.munkistatusoutput {
        // set indeterminate progress bar
        munkiStatusPercent(-1)
    }

    let results = await runCliAsync(path)

    if DisplayOptions.munkistatusoutput {
        // clear indeterminate progress bar
        munkiStatusPercent(0)
    }

    return results
}

/// Runs a script embedded in the pkginfo.
/// Returns the result code.
func runEmbeddedScript(name: String, pkginfo: PlistDict, suppressError: Bool = false) async -> Int {
    // get the script text
    let itemName = pkginfo["name"] as? String ?? "<unknown>"
    guard let scriptText = pkginfo[name] as? String else {
        display.error("Missing script \(name) for \(itemName)")
        return -1
    }

    // write the script to a temp file
    guard let tempdir = TempDir.shared.makeTempDir() else {
        display.error("Could not create a temporary directory for \(name)")
        return -1
    }
    let scriptPath = (tempdir as NSString).appendingPathComponent(name)
    if createExecutableFile(atPath: scriptPath, withStringContents: scriptText) {
        return await runScript(scriptPath, itemName: itemName, scriptName: name, suppressError: suppressError)
    } else {
        display.error("Failed to create executable file for \(name)")
        return -1
    }
}

/// Runs a script embedded in the pkginfo.
/// Returns CLIResults
func runEmbeddedScriptAndReturnResults(name: String, pkginfo: PlistDict, suppressError: Bool = false) async -> CLIResults {
    // get the script text
    let itemName = pkginfo["name"] as? String ?? "<unknown>"
    guard let scriptText = pkginfo[name] as? String else {
        return CLIResults(exitcode: -1, error: "Missing script \(name) for \(itemName)")
    }

    // write the script to a temp file
    guard let tempdir = TempDir.shared.makeTempDir() else {
        return CLIResults(exitcode: -1, error: "Could not create a temporary directory for \(name)")
    }
    let scriptPath = (tempdir as NSString).appendingPathComponent(name)
    if createExecutableFile(atPath: scriptPath, withStringContents: scriptText) {
        return await runScriptAndReturnResults(scriptPath, itemName: itemName, scriptName: name, suppressError: suppressError)
    } else {
        return CLIResults(exitcode: -1, error: "Failed to create executable file for \(name)")
    }
}

enum ExternalScriptError: Error {
    case general
    case notFound
    case statusError(detail: String)
    case insecurePermissions(detail: String)
}

/// Check the permissions on a given file path; fail if owner or group
/// does not match the munki process (default: root/admin) or the group is not
/// 'wheel', or if other users are able to write to the file. This prevents
/// escalated execution of arbitrary code.
func verifyFileOnlyWritableByMunkiAndRoot(_ path: String) throws {
    let filemanager = FileManager.default
    let thisProcessOwner = NSUserName()
    var attributes: NSDictionary
    do {
        attributes = try filemanager.attributesOfItem(atPath: path) as NSDictionary
    } catch {
        throw ExternalScriptError.statusError(
            detail: "\(path): could not get filesystem attributes")
    }
    let owner = attributes.fileOwnerAccountName()
    let group = attributes.fileGroupOwnerAccountName()
    let mode = attributes.filePosixPermissions()
    if !["root", thisProcessOwner].contains(owner) {
        throw ExternalScriptError.insecurePermissions(
            detail: "\(path) owner is not root or owner of munki process!")
    }
    if !["admin", "wheel"].contains(group) {
        throw ExternalScriptError.insecurePermissions(
            detail: "\(path) group is not in wheel or admin!")
    }
    if UInt16(mode) & S_IWOTH != 0 {
        throw ExternalScriptError.insecurePermissions(
            detail: "\(path) is world writable!")
    }
}

/// Verifies path is executable
func verifyExecutable(_ path: String) throws {
    if !FileManager.default.isExecutableFile(atPath: path) {
        throw ExternalScriptError.statusError(
            detail: "\(path) is not executable")
    }
}

/// Run a script (e.g. preflight/postflight) and return a result.
func runExternalScript(_ scriptPath: String, arguments: [String] = [], allowInsecure: Bool = false, timeout: Int = 60) async throws -> CLIResults {
    if !pathExists(scriptPath) {
        throw ExternalScriptError.notFound
    }
    if !allowInsecure {
        do {
            try verifyFileOnlyWritableByMunkiAndRoot(scriptPath)
        } catch let ExternalScriptError.insecurePermissions(detail) {
            throw ProcessError.error(
                description: "Skipping execution: \(detail)")
        } catch let ExternalScriptError.statusError(detail) {
            throw ProcessError.error(
                description: "Skipping execution: \(detail)")
        }
    }
    do {
        try verifyExecutable(scriptPath)
    } catch let ExternalScriptError.statusError(detail) {
        throw ProcessError.error(
            description: "Skipping execution: \(detail)")
    }

    return try await runCliAsync(scriptPath, arguments: arguments, timeout: timeout)
}
