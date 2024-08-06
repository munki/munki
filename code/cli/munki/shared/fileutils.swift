//
//  fileutils.swift
//  munki
//
//  Created by Greg Neagle on 7/9/24.
//
//  Copyright 2024 Greg Neagle.
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

class TempDir {
    // a class to return a shared temp directory, and to clean it up when we exit
    static let shared = TempDir()

    private var url: URL?
    var path: String? {
        return url?.path
    }

    private init() {
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

func pathExists(_ path: String) -> Bool {
    // Returns true if path exists
    return FileManager.default.fileExists(atPath: path)
}

func fileType(_ path: String) -> String? {
    // FileAttributeType is really a String
    return try? (FileManager.default.attributesOfItem(atPath: path) as NSDictionary).fileType()
}

func pathIsRegularFile(_ path: String) -> Bool {
    // Returns true if path is a regular file
    if let fileType = fileType(path) {
        return fileType == FileAttributeType.typeRegular.rawValue
    }
    return false
}

func pathIsSymlink(_ path: String) -> Bool {
    // Returns true if path is a symlink
    if let fileType = fileType(path) {
        return fileType == FileAttributeType.typeSymbolicLink.rawValue
    }
    return false
}

func pathIsDirectory(_ path: String) -> Bool {
    // Returns true if path is a directory
    if let fileType = fileType(path) {
        return fileType == FileAttributeType.typeDirectory.rawValue
    }
    return false
}

func getSizeOfDirectory(_ path: String) -> Int {
    // returns size of directory in Kbytes by recursively adding
    // up the size of all files within
    var totalSize = 0
    let filemanager = FileManager.default
    let dirEnum = filemanager.enumerator(atPath: path)
    while let file = dirEnum?.nextObject() as? String {
        let fullpath = (path as NSString).appendingPathComponent(file)
        if pathIsRegularFile(fullpath) {
            if let attributes = try? filemanager.attributesOfItem(atPath: fullpath) {
                let filesize = (attributes as NSDictionary).fileSize()
                totalSize += Int(filesize)
            }
        }
    }
    return totalSize
}

func getAbsolutePath(_ path: String) -> String {
    // returns absolute path to item referred to by path
    if (path as NSString).isAbsolutePath {
        return ((path as NSString).standardizingPath as NSString).resolvingSymlinksInPath
    }
    let cwd = FileManager.default.currentDirectoryPath
    let composedPath = (cwd as NSString).appendingPathComponent(path)
    return ((composedPath as NSString).standardizingPath as NSString).resolvingSymlinksInPath
}
