//
//  main.swift
//  launchapp
//
//  Created by Greg Neagle on 8/7/24.
//
//  Copyright 2024-2026 The Munki Project.
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
import SystemConfiguration

/// A tool that launches the app in arguments in the context of the current user.

/// Return console user (current GUI user)
func getConsoleUser() -> String {
    return SCDynamicStoreCopyConsoleUser(nil, nil, nil) as? String ?? ""
}

func main() {
    let consoleUser = getConsoleUser().lowercased()
    let thisUser = NSUserName().lowercased()
    if (consoleUser == thisUser) || (consoleUser.isEmpty && thisUser == "root") {
        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/usr/bin/open")
        var arguments = CommandLine.arguments
        if arguments.count > 1 {
            arguments.removeFirst()
            task.arguments = arguments
        } else {
            print("Must specify an app to launch!")
            exit(-1)
        }
        do {
            try task.run()
        } catch {
            print("Error launching app: \(error)")
            exit(-1)
        }
        task.waitUntilExit()
        // sleep 10 secs to make launchd happy
        usleep(10_000_000)
        exit(0)
    } else {
        // we aren't in the current GUI session
        // sleep 10 secs to make launchd happy
        usleep(10_000_000)
        exit(0)
    }
}

main()
