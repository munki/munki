//
//  stderrout.swift
//  munki
//
//  Created by Greg Neagle on 1/1/25.
//  Copyright 2025-2026 The Munki Project. All rights reserved.
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

/// similar to print() function, but prints to stderr
func printStderr(_ items: Any..., separator: String = " ", terminator: String = "\n") {
    let output = items
        .map { String(describing: $0) }
        .joined(separator: separator) + terminator

    FileHandle.standardError.write(output.data(using: .utf8)!)
}
