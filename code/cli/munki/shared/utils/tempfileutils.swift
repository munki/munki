//
//  tempfileutils.swift
//  munki
//
//  Created by Greg Neagle on 5/8/25.
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

// A class to return a shared temp directory, and to clean it up when we exit
class TempDir {
    static let shared = TempDir()

    private var url: URL?
    var path: String? {
        return url?.path
    }

    init() {
        let filemanager = FileManager.default
        let dirName = "munki-\(UUID().uuidString)"
        let tmpURL = filemanager.temporaryDirectory.appendingPathComponent(
            dirName, isDirectory: true
        )
        do {
            try filemanager.createDirectory(at: tmpURL, withIntermediateDirectories: true)
            url = tmpURL
        } catch {
            url = nil
        }
    }

    func makeTempDir() -> String? {
        if let url {
            let tmpURL = url.appendingPathComponent(UUID().uuidString)
            do {
                try FileManager.default.createDirectory(at: tmpURL, withIntermediateDirectories: true)
                return tmpURL.path
            } catch {
                return nil
            }
        }
        return nil
    }

    func cleanUp() {
        if let url {
            do {
                try FileManager.default.removeItem(at: url)
                self.url = nil
            } catch {
                // nothing
            }
        }
    }

    deinit {
        cleanUp()
    }
}

/// Returns a path to use for a temporary file
func tempFile() -> String? {
    guard let tempDir = TempDir.shared.path else {
        return nil
    }
    let basename = UUID().uuidString
    return (tempDir as NSString).appendingPathComponent(basename)
}
