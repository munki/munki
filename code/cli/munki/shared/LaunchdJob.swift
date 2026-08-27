//
//  LaunchdJob.swift
//  munki
//
//  Created by Greg Neagle on 8/2/24.
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

enum LaunchdJobState {
    case unknown
    case stopped
    case running
}

struct LaunchdJobInfo {
    var state: LaunchdJobState
    var pid: Int?
    var lastExitStatus: Int?
}

/// Get info about a launchd job. Returns LaunchdJobInfo.
func launchdJobInfo(_ jobLabel: String) -> LaunchdJobInfo {
    var info = LaunchdJobInfo(
        state: .unknown,
        pid: nil,
        lastExitStatus: nil
    )
    let result = runCLI("/bin/launchctl", arguments: ["list"])
    if result.exitcode != 0 || result.output.isEmpty {
        return info
    }
    let lines = result.output.components(separatedBy: .newlines)
    let jobLines = lines.filter {
        $0.hasSuffix("\t\(jobLabel)")
    }
    if jobLines.count != 1 {
        // unexpected number of lines matched our label
        return info
    }
    let infoParts = jobLines[0].components(separatedBy: "\t")
    if infoParts.count != 3 {
        // unexpected number of fields in the line
        return info
    }
    if infoParts[0] == "-" {
        info.pid = nil
        info.state = .stopped
    } else {
        info.pid = Int(infoParts[0])
        info.state = .running
    }
    if infoParts[1] == "-" {
        info.lastExitStatus = nil
    } else {
        info.lastExitStatus = Int(infoParts[1])
    }
    return info
}

/// Stop a launchd job
func stopLaunchdJob(_ jobLabel: String) throws {
    let result = runCLI("/bin/launchctl", arguments: ["stop", jobLabel])
    if result.exitcode != 0 {
        throw MunkiError("launchctl stop error \(result.exitcode): \(result.error)")
    }
}

/// Remove a launchd job by label
func removeLaunchdJob(_ jobLabel: String) throws {
    let result = runCLI("/bin/launchctl", arguments: ["remove", jobLabel])
    if result.exitcode != 0 {
        throw MunkiError("launchctl remove error \(result.exitcode): \(result.error)")
    }
}

/// launchd job object
class LaunchdJob {
    var label: String
    var cleanUpAtExit: Bool
    var stdout: FileHandle?
    var stderr: FileHandle?
    var stdOutPath: String
    var stdErrPath: String
    var plist: PlistDict
    var plistPath: String

    init(
        cmd: [String],
        environmentVars: [String: String]? = nil,
        jobLabel: String? = nil,
        cleanUpAtExit: Bool = true
    ) throws {
        // Initialize our launchd job
        var tmpdir = TempDir.shared.path
        if !cleanUpAtExit {
            // need to use a different tmpdir than the shared one,
            // which will get cleaned up when managedsoftwareupdate
            // exits
            tmpdir = "/private/tmp/munki-\(UUID().uuidString)"
            if let tmpdir {
                do {
                    try FileManager.default.createDirectory(atPath: tmpdir, withIntermediateDirectories: true)
                } catch {
                    // will be dealt with later when we check for existence of the tmpdir
                }
            }
        }
        guard let tmpdir, pathExists(tmpdir) else {
            throw MunkiError("Could not allocate temp dir for launchd job")
        }
        // label this job
        label = jobLabel ?? "com.googlecode.munki." + UUID().uuidString
        self.cleanUpAtExit = cleanUpAtExit
        stdOutPath = (tmpdir as NSString).appendingPathComponent(label + ".stdout")
        stdErrPath = (tmpdir as NSString).appendingPathComponent(label + ".stderr")
        plistPath = (tmpdir as NSString).appendingPathComponent(label + ".plist")
        plist = [
            "Label": label,
            "ProgramArguments": cmd,
            "StandardOutPath": stdOutPath,
            "StandardErrorPath": stdErrPath,
        ]
        if let environmentVars {
            plist["EnvironmentVariables"] = environmentVars
        }
        // create stdout and stderr files
        guard FileManager.default.createFile(atPath: stdOutPath, contents: nil),
              FileManager.default.createFile(atPath: stdErrPath, contents: nil)
        else {
            throw MunkiError("Could not create stdout/stderr files for launchd job \(label)")
        }
        // write out launchd plist
        do {
            try writePlist(plist, toFile: plistPath)
            // set owner, group and mode to those required
            // by launchd
            try FileManager.default.setAttributes(
                [.ownerAccountID: 0,
                 .groupOwnerAccountID: 0,
                 .posixPermissions: 0o644],
                ofItemAtPath: plistPath
            )
        } catch {
            throw MunkiError("Could not create plist for launchd job \(label): \(error.localizedDescription)")
        }
        // load the job
        let result = runCLI("/bin/launchctl", arguments: ["load", plistPath])
        if result.exitcode != 0 {
            throw MunkiError("launchctl load error for \(label): \(result.exitcode): \(result.error)")
        }
    }

    deinit {
        /// Attempt to clean up
        if cleanUpAtExit {
            if !plistPath.isEmpty {
                _ = runCLI("/bin/launchctl", arguments: ["unload", plistPath])
            }
            try? stdout?.close()
            try? stderr?.close()
            let fm = FileManager.default
            try? fm.removeItem(atPath: plistPath)
            try? fm.removeItem(atPath: stdOutPath)
            try? fm.removeItem(atPath: stdErrPath)
        }
    }

    /// Start the launchd job
    func start() throws {
        let result = runCLI("/bin/launchctl", arguments: ["start", label])
        if result.exitcode != 0 {
            throw MunkiError("Could not start launchd job \(label): \(result.error)")
        }
        // open the stdout and stderr output files and
        // store their file handles for use
        stdout = FileHandle(forReadingAtPath: stdOutPath)
        stderr = FileHandle(forReadingAtPath: stdErrPath)
    }

    /// Stop the launchd job
    func stop() {
        try? stopLaunchdJob(label)
    }

    /// Get info about the launchd job.
    func info() -> LaunchdJobInfo {
        return launchdJobInfo(label)
    }

    /// Returns the process exit code, if the job has exited; otherwise,
    /// returns nil
    func exitcode() -> Int? {
        let info = info()
        if info.state == .stopped {
            return info.lastExitStatus
        }
        return nil
    }
}
