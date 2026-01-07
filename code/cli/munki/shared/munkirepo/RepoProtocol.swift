//
//  RepoProtocol.swift
//  munki
//
//  Created by Greg Neagle on 5/8/25.
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

/// Defines methods all repo classes must implement
public protocol Repo {
    init(_ url: String) throws
    func list(_ kind: String) async throws -> [String]
    func get(_ identifier: String) async throws -> Data
    func get(_ identifier: String, toFile local_file_path: String) async throws
    func put(_ identifier: String, content: Data) async throws
    func put(_ identifier: String, fromFile local_file_path: String) async throws
    func delete(_ identifier: String) async throws
    func pathFor(_ identifier: String) -> String?
}

open class RepoPluginBuilder {
    // public init() {}

    open func connect(_: String) -> Repo? {
        fatalError("You have to override this method.")
    }
}
