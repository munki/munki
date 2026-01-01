//
//  repoutils.swift
//  munki
//
//  Created by Greg Neagle on 7/15/24.
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

// TODO: get rid of this
/// Returns a list of items of kind. Relative pathnames are prepended
/// with kind. (example: ["icons/Bar.png", "icons/Foo.png"])
/// Could throw RepoError
func listItemsOfKind(_ repo: Repo, _ kind: String) async throws -> [String] {
    let itemlist = try await repo.list(kind)
    return itemlist.map(
        { (kind as NSString).appendingPathComponent($0) }
    )
}
