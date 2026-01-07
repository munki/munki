//
//  UNIXProcessInfo.swift
//  munki
//
//  Created by Greg Neagle on 9/4/24.
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

import Darwin
import Foundation

struct UNIXProcessInfo {
    let pid: Int32
    let ppid: Int32
    let uid: UInt32
    let starttime: Int
    let command: String
}

/// Returns a list of running processes
func UNIXProcessList() -> [UNIXProcessInfo] {
    var list = [UNIXProcessInfo]()
    var mib: [Int32] = [CTL_KERN, KERN_PROC, KERN_PROC_ALL, 0]
    var size = 0

    // First need to need size of process list array
    var result = sysctl(&mib, u_int(mib.count), nil, &size, nil, 0)
    assert(result == KERN_SUCCESS)

    // Get process list
    let procCount = size / MemoryLayout<kinfo_proc>.stride
    var kinfoList = [kinfo_proc](repeating: kinfo_proc(), count: procCount)
    result = sysctl(&mib, u_int(mib.count), &kinfoList, &size, nil, 0)
    assert(result == KERN_SUCCESS)

    for task in kinfoList {
        var kinfo = task
        let command = withUnsafePointer(to: &kinfo.kp_proc.p_comm) {
            String(cString: UnsafeRawPointer($0).assumingMemoryBound(to: CChar.self))
        }
        list.append(
            UNIXProcessInfo(
                pid: kinfo.kp_proc.p_pid,
                ppid: kinfo.kp_eproc.e_ppid,
                uid: kinfo.kp_eproc.e_ucred.cr_uid,
                starttime: kinfo.kp_proc.p_un.__p_starttime.tv_sec,
                command: command
            )
        )
    }
    return list
}

/// Returns a list of running processes with the given parent pid
func processesWithPPID(_ ppid: Int32) -> [UNIXProcessInfo] {
    let list = UNIXProcessList()
    return list.filter { $0.ppid == ppid }
}

/// Gets the (raw) process argument data
func argumentData(for pid: pid_t) -> Data? {
    // Lifted from Quinn's work here: https://developer.apple.com/forums/thread/681817

    // There should be a better way to get a process’s arguments
    // (FB9149624) but right now you have to use `KERN_PROCARGS2`
    // and then parse the results.

    var argMax: CInt = 0
    var argMaxSize = size_t(MemoryLayout.size(ofValue: argMax))
    let err = sysctlbyname("kern.argmax", &argMax, &argMaxSize, nil, 0)
    guard err >= 0 else {
        return nil
    }
    // precondition(argMaxSize != 0)
    var result = Data(count: Int(argMax))
    let resultSize = result.withUnsafeMutableBytes { buf -> Int in
        var mib: [CInt] = [
            CTL_KERN,
            KERN_PROCARGS2,
            pid,
        ]
        var bufSize = buf.count
        let err = sysctl(&mib, CUnsignedInt(mib.count), buf.baseAddress!, &bufSize, nil, 0)
        guard err >= 0 else {
            return -1
        }
        return bufSize
    }
    if resultSize < 0 {
        return nil
    }
    result = result.prefix(resultSize)
    return result
}

enum ParseError: Error {
    case unexpectedEnd
    case argumentIsNotUTF8
}

/// Parses the argument data into a list of strings
func parseArgumentData(_ data: Data) throws -> [String] {
    // Lifted from Quinn's work here: https://developer.apple.com/forums/thread/681817

    // The algorithm here was was ‘stolen’ from the Darwin source for `ps`.
    //
    // <https://opensource.apple.com/source/adv_cmds/adv_cmds-176/ps/print.c.auto.html>

    // returns a list of strings: [0] is the executable path,
    // the rest is `argv[0]` through `argv[argc - 1]

    // Parse `argc`.  We’re assuming the value is little endian here, which is
    // currently accurate but it could be a problem if we’ve “gone back to
    // metric”.
    var remaining = data[...]
    guard remaining.count >= 6 else {
        throw ParseError.unexpectedEnd
    }
    let count32 = remaining.prefix(4).reversed().reduce(0) { $0 << 8 | UInt32($1) }
    remaining = remaining.dropFirst(4)

    // Get the executable path
    let exeBytes = remaining.prefix(while: { $0 != 0 })
    guard let executable = String(bytes: exeBytes, encoding: .utf8) else {
        throw ParseError.argumentIsNotUTF8
    }
    remaining = remaining.dropFirst(exeBytes.count)
    guard remaining.count != 0 else {
        throw ParseError.unexpectedEnd
    }
    // Skip any zeros until the next non-zero
    remaining = remaining.drop(while: { $0 == 0 })

    // Now parse `argv[0]` through `argv[argc - 1]`.
    var result: [String] = [executable]
    for _ in 0 ..< count32 {
        let argBytes = remaining.prefix(while: { $0 != 0 })
        guard let arg = String(bytes: argBytes, encoding: .utf8) else {
            throw ParseError.argumentIsNotUTF8
        }
        result.append(arg)
        remaining = remaining.dropFirst(argBytes.count)
        guard remaining.count != 0 else {
            throw ParseError.unexpectedEnd
        }
        remaining = remaining.dropFirst()
    }
    return result
}

/// Returns the executable path and all arguments as a list of strings
func executableAndArgsForPid(_ pid: Int32) -> [String]? {
    if let data = argumentData(for: pid) {
        return try? parseArgumentData(data)
    }
    return nil
}

struct UNIXProcessInfoWithPath {
    let pid: Int32
    let ppid: Int32
    let uid: UInt32
    let starttime: Int
    let command: String
    let path: String
}

/// Returns a list of running processes with pid, ppid, uid, command, and path
func UNIXProcessListWithPaths() -> [UNIXProcessInfoWithPath] {
    let procList = UNIXProcessList()
    var processes = [UNIXProcessInfoWithPath]()
    for proc in procList {
        if proc.pid != 0,
           let data = argumentData(for: proc.pid)
        {
            let args = (try? parseArgumentData(data)) ?? []
            if !args.isEmpty {
                processes.append(
                    UNIXProcessInfoWithPath(
                        pid: proc.pid,
                        ppid: proc.ppid,
                        uid: proc.uid,
                        starttime: proc.starttime,
                        command: proc.command,
                        path: args[0]
                    )
                )
            }
        }
    }
    return processes
}
