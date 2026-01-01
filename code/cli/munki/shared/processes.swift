//
//  processes.swift
//  munki
//
//  Created by Greg Neagle on 8/5/24.
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

/// Returns a list of paths of running processes
func getRunningProcesses() -> [String] {
    let procList = UNIXProcessList()
    var processPaths = [String]()
    for proc in procList {
        if proc.pid != 0,
           let data = argumentData(for: proc.pid)
        {
            let args = (try? parseArgumentData(data)) ?? []
            if !args.isEmpty {
                processPaths.append(args[0])
            }
        }
    }
    return processPaths
}

/// Returns ProcessID for a running python script matching the scriptName
/// as long as the pid is not the same as ours
/// this is used to see if the managedsoftwareupdate script is already running
func pythonScriptRunning(_ scriptName: String) -> UNIXProcessInfoWithPath? {
    let ourPid = ProcessInfo().processIdentifier
    let processes = UNIXProcessListWithPaths()
    for item in processes {
        if item.pid == ourPid {
            continue
        }
        let executable = (item.path as NSString).lastPathComponent
        if executable.contains("python") || executable.contains("Python") {
            // get all the args for this pid
            if var args = executableAndArgsForPid(item.pid), args.count > 2 {
                // first value is executable path, drop it
                // next value is command, drop it
                args = Array(args.dropFirst(2))
                // drop leading args that start with a hyphen
                args = Array(args.drop(while: { $0.hasPrefix("-") }))
                if args.count > 0, args[0].hasSuffix(scriptName) {
                    return item
                }
            }
        }
    }
    return nil
}

/// Returns Process ID for a running executable matching the name
/// as long as it isn't our pid
func executableRunning(_ name: String) -> UNIXProcessInfoWithPath? {
    let ourPid = ProcessInfo().processIdentifier
    let processes = UNIXProcessListWithPaths()
    for item in processes {
        if item.pid == ourPid {
            continue
        }
        if name.hasPrefix("/") {
            // full path, so exact comparison
            if item.path == name {
                return item
            }
        } else {
            // does executable path end with the name?
            if item.path.hasSuffix(name) {
                return item
            }
        }
    }
    return nil
}

/// Returns the pid of another managedsoftwareupdate process, if found
func anotherManagedsoftwareupdateInstanceRunning() -> UNIXProcessInfoWithPath? {
    // A Python version of managedsoftwareupdate might be running,
    // or a compiled version
    if let item = executableRunning("managedsoftwareupdate") {
        return item
    }
    if let item = pythonScriptRunning(".managedsoftwareupdate.py") {
        return item
    }
    if let item = pythonScriptRunning("managedsoftwareupdate.py") {
        return item
    }
    if let item = pythonScriptRunning("managedsoftwareupdate") {
        return item
    }
    return nil
}
