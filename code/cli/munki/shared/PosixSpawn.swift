//
//  PosixSpawn.swift
//  munki
//
//  Created by Greg Neagle on 7/28/25.
//  Copyright 2025-2026 The Munki Project.
//

// Based on https://stackoverflow.com/a/69143985

import Darwin

class PosixSpawnError: MunkiError {}

/// Uses posix_spawn to run a subprocess. munkiimport uses this function to run a CLI editor
/// (like vi) if needed. Running an interactive process using Foundation's NSTask/Process doesn't
/// work properly because it doesn't properly connect stdin and stdout to the terminal
public func posixSpawn(_ executablePath: String, _ arguments: String...) throws {
    var pid: pid_t = 0
    guard let path = executablePath.withCString(strdup) else {
        throw PosixSpawnError("Could not spawn \(executablePath): could not create cstring from executablePath")
    }
    let args = try arguments.map {
        if let arg = $0.withCString(strdup) {
            return arg
        } else {
            throw PosixSpawnError("Could not spawn \(executablePath): could not create cstrings from arguments")
        }
    }
    defer {
        ([path] + args).forEach { free($0) }
    }
    if posix_spawn(&pid, path, nil, nil, [path] + args + [nil], environ) < 0 {
        throw PosixSpawnError("Could not spawn \(executablePath): error \(errno)")
    }
    if waitpid(pid, nil, 0) < 0 {
        throw PosixSpawnError("Could not spawn \(executablePath): error \(errno)")
    }
}
