//
//  PosixProcesss.swift
//  munki
//
//  Created by Greg Neagle on 7/27/25.
//

// Based on https://stackoverflow.com/a/69143985

class PosixProcesssError: MunkiError {}

public struct PosixProcess {
    public let executablePath: String
    public let arguments: [String]

    public init(_ executablePath: String, _ arguments: String...) {
        self.executablePath = executablePath
        self.arguments = arguments
    }

    public func spawn() throws {
        var pid: pid_t = 0
        guard let path = executablePath.withCString(strdup) else {
            throw PosixProcesssError("Could not spawn \(executablePath): could not create cstring from executablePath")
        }
        let args = try arguments.map {
            if let arg = $0.withCString(strdup) {
                return arg
            } else {
                throw PosixProcesssError("Could not spawn \(executablePath): could not create cstrings from arguments")
            }
        }
        defer {
            ([path] + args).forEach { free($0) }
        }
        if posix_spawn(&pid, path, nil, nil, [path] + args + [nil], environ) < 0 {
            throw PosixProcesssError("Could not spawn \(executablePath): error \(errno)")
        }
        if waitpid(pid, nil, 0) < 0 {
            throw PosixProcesssError("Could not spawn \(executablePath): error \(errno)")
        }
    }
}
