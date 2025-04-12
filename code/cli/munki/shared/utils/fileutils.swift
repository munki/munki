//
//  fileutils.swift
//  munki
//
//  Created by Greg Neagle on 7/9/24.
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

/// Returns true if path exists/
func pathExists(_ path: String) -> Bool {
    return FileManager.default.fileExists(atPath: path)
}

/// Returns type of file at path
func fileType(_ path: String) -> String? {
    // FileAttributeType is really a String
    return try? (FileManager.default.attributesOfItem(atPath: path) as NSDictionary).fileType()
}

/// Returns true if path is a regular file/
func pathIsRegularFile(_ path: String) -> Bool {
    if let fileType = fileType(path) {
        return fileType == FileAttributeType.typeRegular.rawValue
    }
    return false
}

/// Returns true if path is a symlink/
func pathIsSymlink(_ path: String) -> Bool {
    if let fileType = fileType(path) {
        return fileType == FileAttributeType.typeSymbolicLink.rawValue
    }
    return false
}

/// Returns true if path is a directory/
func pathIsDirectory(_ path: String) -> Bool {
    if let fileType = fileType(path) {
        return fileType == FileAttributeType.typeDirectory.rawValue
    }
    return false
}

/// Returns true if path is a file and is executable/
func pathIsExecutableFile(_ path: String) -> Bool {
    if pathIsDirectory(path) {
        return false
    }
    do {
        let attributes = try FileManager.default.attributesOfItem(atPath: path) as NSDictionary
        let mode = attributes.filePosixPermissions()
        return Int32(mode) & X_OK != 0
    } catch {
        // fall through
    }
    return false
}

/// Returns size of file in bytes
func getSizeOfFile(_ path: String) -> Int {
    if let attributes = try? FileManager.default.attributesOfItem(atPath: path) {
        return Int((attributes as NSDictionary).fileSize())
    }
    return 0
}

/// Returns size of directory in bytes by recursively adding
/// up the size of all files within
func getSizeOfDirectory(_ path: String) -> Int {
    var totalSize = 0
    let filemanager = FileManager.default
    let dirEnum = filemanager.enumerator(atPath: path)
    while let file = dirEnum?.nextObject() as? String {
        let fullpath = (path as NSString).appendingPathComponent(file)
        if pathIsRegularFile(fullpath),
           let attributes = try? filemanager.attributesOfItem(atPath: fullpath)
        {
            let filesize = (attributes as NSDictionary).fileSize()
            totalSize += Int(filesize)
        }
    }
    return totalSize
}

/// Recursively gets size of pathname in bytes
func getSize(_ path: String) -> Int {
    if pathIsDirectory(path) {
        return getSizeOfDirectory(path)
    }
    if pathIsRegularFile(path) {
        return getSizeOfFile(path)
    }
    return 0
}

// Returns absolute path to item referred to by path
func getAbsolutePath(_ path: String) -> String {
    if (path as NSString).isAbsolutePath {
        return ((path as NSString).standardizingPath as NSString).resolvingSymlinksInPath
    }
    let cwd = FileManager.default.currentDirectoryPath
    let composedPath = (cwd as NSString).appendingPathComponent(path)
    return ((composedPath as NSString).standardizingPath as NSString).resolvingSymlinksInPath
}

/// Remove items in dirPath that aren't in the keepList
func cleanUpDir(_ dirPath: String, keeping keepList: [String]) {
    if !pathIsDirectory(dirPath) {
        return
    }
    let filemanager = FileManager.default
    let dirEnum = filemanager.enumerator(atPath: dirPath)
    var foundDirectories = [String]()
    while let file = dirEnum?.nextObject() as? String {
        let fullPath = (dirPath as NSString).appendingPathComponent(file)
        if pathIsDirectory(fullPath) {
            foundDirectories.append(fullPath)
            continue
        }
        if !keepList.contains(file) {
            try? filemanager.removeItem(atPath: fullPath)
        }
    }
    // clean up any empty directories
    for directory in foundDirectories.reversed() {
        if let contents = try? filemanager.contentsOfDirectory(atPath: directory),
           contents.isEmpty
        {
            try? filemanager.removeItem(atPath: directory)
        }
    }
}

/// Return a basename string.
/// Examples:
///    "http://foo/bar/path/foo.dmg" => "foo.dmg"
///    "/path/foo.dmg" => "foo.dmg"
func baseName(_ str: String) -> String {
    if let url = URL(string: str) {
        return url.lastPathComponent
    } else {
        return (str as NSString).lastPathComponent
    }
}

/// Return a dirname string.
/// Examples::
///    "/path/foo.dmg" => "/path"
///    "/path" => "/"
///    "/" => "/"
///    "foo.dmg" => ""
func dirName(_ str: String) -> String {
    return (str as NSString).deletingLastPathComponent
}

/// Return the path to the current executable's directory
func currentExecutableDir(appendingPathComponent: String = "") -> String {
    if let executablePath = Bundle.main.executablePath {
        return ((executablePath as NSString).deletingLastPathComponent as NSString).appendingPathComponent(appendingPathComponent)
    }
    return appendingPathComponent
}

/// Check the permissions on a given file path; fail if owner or group
/// is not root/admin or the group is not 'wheel', or
/// if other users are able to write to the file. This prevents
/// escalated execution of arbitrary code.
func verifyPathOwnershipAndPermissions(_ path: String) -> Bool {
    let filemanager = FileManager.default
    var attributes: NSDictionary
    do {
        attributes = try filemanager.attributesOfItem(atPath: path) as NSDictionary
    } catch {
        printStderr("\(path): could not get filesystem attributes")
        return false
    }
    let owner = attributes.fileOwnerAccountName()
    let group = attributes.fileGroupOwnerAccountName()
    let mode = attributes.filePosixPermissions()
    if owner != "root" {
        printStderr("\(path) owner is not root!")
        return false
    }
    if !["admin", "wheel"].contains(group) {
        printStderr("\(path) group is not in wheel or admin!")
        return false
    }
    if UInt16(mode) & S_IWOTH != 0 {
        printStderr("\(path) is world writable!")
        return false
    }
    // passed all the tests!
    return true
}

/// Make sure that the executable and all containing directories are owned
/// by root:wheel or root:admin, and not writeable by other users.
func verifyExecutableOwnershipAndPermissions() -> Bool {
    guard var path = Bundle.main.executablePath else {
        printStderr("Could not get path to this executable!")
        return false
    }
    while path != "/" {
        if !verifyPathOwnershipAndPermissions(path) {
            return false
        }
        path = (path as NSString).deletingLastPathComponent
    }
    return true
}
