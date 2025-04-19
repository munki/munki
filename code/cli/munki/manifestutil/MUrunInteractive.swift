//
//  MUrunInteractive.swift
//  manifestutil
//
//  Created by Greg Neagle on 4/15/25.
//
//  Copyright 2024-2025 Greg Neagle.
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

import ArgumentParser
import Foundation

@_cdecl("tabCompleter")
func tabCompleter(_: UnsafePointer<CChar>?, _: Int32) -> Int32 {
    return 0
}

func setupTabCompleter() {
    rl_completion_entry_function = tabCompleter
}

extension ManifestUtil {
    struct RunInteractive: ParsableCommand {
        static var configuration = CommandConfiguration(
            abstract: "Runs this utility in interactive mode.")

        func run() throws {
            while true {
                if let commandLine = getInput(prompt: "> ") {
                    let args = (commandLine as NSString).components(separatedBy: " ")
                    do {
                        var command = try ManifestUtil.parseAsRoot(args)
                        try command.run()
                    } catch {
                        printStderr(error.localizedDescription)
                    }
                }
            }
        }
    }
}
