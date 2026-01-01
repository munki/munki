//
//  pkg.swift
//  munki
//
//  Created by Greg Neagle on 8/3/24.
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

import Foundation

private let display = DisplayAndLog.main

/// Stub function
func removeBundleRelocationInfo() {
    display.warning("'suppress_bundle_relocation' is no longer supported. Ignoring.")
}

/// Query a package for its RestartAction. Returns true if a restart is needed, false otherwise
func pkgNeedsRestart(_ pkgpath: String, options: PlistDict) -> Bool {
    let tool = "/usr/sbin/installer"
    var arguments = ["-query", "RestartAction", "-pkg", pkgpath, "-plist"]
    if let choicesXML = options["installer_choices_xml"] as? PlistDict,
       let tempDir = TempDir.shared.path
    {
        let choicesXMLPath = (tempDir as NSString).appendingPathComponent("choices.xml")
        do {
            try writePlist(choicesXML, toFile: choicesXMLPath)
            arguments += ["-applyChoiceChangesXML", choicesXMLPath]
        } catch {}
    }
    if let allowUntrusted = options["allow_untrusted"] as? Bool,
       allowUntrusted == true
    {
        arguments.append("-allowUntrusted")
    }
    let result = runCLI(tool, arguments: arguments)
    if result.exitcode != 0 {
        display.warning("/usr/bin/installer error when getting restart info for \((pkgpath as NSString).lastPathComponent): \(result.error)")
        return false
    }
    let (pliststr, _) = parseFirstPlist(fromString: result.output)
    if !pliststr.isEmpty,
       let plist = try? readPlist(fromString: pliststr) as? PlistDict,
       let restartAction = plist["RestartAction"] as? String
    {
        return ["RequireRestart", "RecommendRestart"].contains(restartAction)
    }
    display.warning("/usr/bin/installer returned unexpected value when getting restart info for \((pkgpath as NSString).lastPathComponent): \(result.output)")
    return false
}

func getInstallerEnvironment(_ customEnv: [String: String]?) -> [String: String] {
    var env = ProcessInfo.processInfo.environment
    env["USER"] = NSUserName()
    env["HOME"] = NSHomeDirectory()
    if let customEnv {
        for (key, value) in customEnv {
            if key == "USER", value == "CURRENT_CONSOLE_USER" {
                var consoleUser = getConsoleUser()
                if consoleUser == "" || consoleUser == "loginwindow" {
                    consoleUser = "root"
                }
                env["USER"] = consoleUser
                env["HOME"] = NSHomeDirectoryForUser(consoleUser)
            } else {
                env[key] = value
            }
        }
        display.debug1("Using custom installer environment variables: \(env)")
    }
    return env
}

/// Parses a line of output from installer, displays it as progress output and logs it
func displayInstallerOutput(_ text: String) {
    if !text.hasPrefix("installer:") {
        // this should not have been sent to this function!
        return
    }
    var msg = text.trimmingCharacters(in: .newlines)
    // delete "installer:" prefix
    msg.removeFirst("installer:".count)
    if msg.hasPrefix("PHASE:") {
        msg.removeFirst("PHASE:".count)
        if !msg.isEmpty {
            display.minorStatus(msg)
        }
    } else if msg.hasPrefix("STATUS:") {
        msg.removeFirst("STATUS:".count)
        if !msg.isEmpty {
            display.minorStatus(msg)
        }
    } else if msg.hasPrefix("%") {
        msg.removeFirst()
        if let percent = Double(msg) {
            munkiStatusPercent(Int(percent))
            display.minorStatus("\(msg) percent complete")
        }
    } else if msg.hasPrefix(" Error") || msg.hasPrefix(" Cannot install") {
        display.error(msg)
        munkiStatusDetail(msg)
    } else {
        munkiLog(msg)
    }
}

/// Subclass of AsyncProcessRunner that handles the progress output from /usr/sbin/installer
class installerRunner: AsyncProcessRunner {
    var remainingOutput = ""
    var lastProcessedOutputLine = ""

    override init(_ tool: String = "/usr/sbin/installer",
                  arguments: [String] = [],
                  environment: [String: String] = [:],
                  stdIn: String = "")
    {
        super.init(tool, arguments: arguments, environment: environment, stdIn: stdIn)
    }

    func linesAndRemainderOf(_ str: String) -> ([String], String) {
        var lines = str.components(separatedBy: "\n")
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
            if line == lastProcessedOutputLine {
                // if the output line is the same, just skip
                continue
            } else if line.hasPrefix("installer:") {
                displayInstallerOutput(line)
                lastProcessedOutputLine = line
            }
        }
    }
}

/// Runs /usr/sbin/installer, parses and displays the output, and returns the process exit code
func runInstaller(arguments: [String], environment: [String: String], pkgName: String) async -> Int {
    let proc = installerRunner(arguments: arguments, environment: environment)
    await proc.run()
    let results = proc.results
    if results.exitcode != 0 {
        display.minorStatus("Install of \(pkgName) failed with return code \(results.exitcode)")
        display.error(String(repeating: "-", count: 78))
        for line in results.output.components(separatedBy: "\n") {
            display.error(line)
        }
        for line in results.error.components(separatedBy: "\n") {
            display.error(line)
        }
        display.error(String(repeating: "-", count: 78))
    }
    return results.exitcode
}

// Uses the Apple installer to install the package or metapackage at pkgpath.
// Returns a tuple:
//    the installer return code and restart needed as a boolean.
func install(_ pkgpath: String, options: PlistDict = [:]) async -> (Int, Bool) {
    var restartNeeded = false
    let packageName = (pkgpath as NSString).lastPathComponent
    let displayName = options["display_name"] as? String ?? options["name"] as? String ?? packageName

    var resolvedPkgPath = pkgpath
    if pathIsSymlink(pkgpath) {
        resolvedPkgPath = getAbsolutePath(pkgpath)
    }

    if let suppressBundleRelocation = options["suppress_bundle_relocation"] as? Bool, suppressBundleRelocation == true {
        removeBundleRelocationInfo()
    }

    munkiLog("Installing \(displayName) from \(packageName)")
    if pkgNeedsRestart(resolvedPkgPath, options: options) {
        display.minorStatus("\(displayName) requires a restart after installation.")
        restartNeeded = true
    }

    var arguments = ["-verboseR", "-pkg", resolvedPkgPath, "-target", "/"]
    if let choicesXML = options["installer_choices_xml"] as? [PlistDict],
       let tempDir = TempDir.shared.path
    {
        let choicesXMLPath = (tempDir as NSString).appendingPathComponent("choices.xml")
        do {
            try writePlist(choicesXML, toFile: choicesXMLPath)
            arguments += ["-applyChoiceChangesXML", choicesXMLPath]
        } catch {
            // could not write choices.xml, should not proceed
            display.error("Could not write choices.xml for \(packageName)")
            return (-1, false)
        }
    }
    if let allowUntrusted = options["allow_untrusted"] as? Bool,
       allowUntrusted == true
    {
        arguments.append("-allowUntrusted")
    }

    // get installer environment
    let envVars = getInstallerEnvironment(options["installer_environment"] as? [String: String])

    // run it
    let retcode = await runInstaller(arguments: arguments, environment: envVars, pkgName: packageName)
    if retcode != 0 {
        restartNeeded = false
    }
    return (retcode, restartNeeded)
}

// The Python version of Munki would actually install _all_ the pkgs from a given
// directory (which was usually the root of a mounted disk image). This was rarely
// what was actually wanted. This version just installs the first installable item in
// the directory.
// Returns a tuple containing the exit code of the installer process and a boolean
// indicating if a restart is needed
func installFromDirectory(_ directoryPath: String, options: PlistDict = [:]) async -> (Int, Bool) {
    if stopRequested() {
        return (0, false)
    }
    if let items = try? FileManager.default.contentsOfDirectory(atPath: directoryPath) {
        for item in items {
            let itempath = (directoryPath as NSString).appendingPathComponent(item)
            if hasValidDiskImageExt(item) {
                display.info("Mounting disk image \(item)")
                guard let mountpoint = try? mountdmg(itempath, useShadow: true, skipVerification: true) else {
                    display.error("No filesystems mounted from \(item)")
                    return (-1, false)
                }
                // make sure we unmount this when done
                defer {
                    do {
                        try unmountdmg(mountpoint)
                    } catch {
                        display.error(error.localizedDescription)
                    }
                }
                // call us recursively to install a pkg at the root of this diskimage
                return await installFromDirectory(mountpoint, options: options)
            }
            if hasValidPackageExt(item) {
                return await install(itempath, options: options)
            }
        }
    }
    // if we get here, no valid items to install were found
    display.warning("No items to install were found in \(directoryPath)")
    return (-1, false)
}
