//
//  FileRepo.swift
//  munki
//
//  Created by Greg Neagle on 6/25/24.
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
import NetFS

// MARK: share mounting functions

// NetFS error codes
/*
 *    ENETFSPWDNEEDSCHANGE           -5045
 *    ENETFSPWDPOLICY                -5046
 *    ENETFSACCOUNTRESTRICTED        -5999
 *    ENETFSNOSHARESAVAIL            -5998
 *    ENETFSNOAUTHMECHSUPP           -5997
 *    ENETFSNOPROTOVERSSUPP          -5996
 *
 *  from <NetAuth/NetAuthErrors.h>
 *    kNetAuthErrorInternal          -6600
 *    kNetAuthErrorMountFailed       -6602
 *    kNetAuthErrorNoSharesAvailable -6003
 *    kNetAuthErrorGuestNotSupported -6004
 *    kNetAuthErrorAlreadyClosed     -6005
 */

enum ShareMountError: Error {
    case generalError(Int32)
    case authorizationNeeded(Int32)
}

/// Mounts a share at /Volumes, optionally using credentials.
/// Returns the mount point or throws an error
func mountShare(_ shareURL: String, username: String = "", password: String = "") throws -> String {
    let cfShareURL = CFURLCreateWithString(nil, shareURL as CFString, nil)
    // Set UI to reduced interaction
    let open_options: NSMutableDictionary = [kNAUIOptionKey: kNAUIOptionNoUI]
    // Allow mounting sub-directories of root shares
    let mount_options: NSMutableDictionary = [kNetFSAllowSubMountsKey: true]
    var mountpoints: Unmanaged<CFArray>? = nil
    var result: Int32 = 0
    if !username.isEmpty {
        result = NetFSMountURLSync(cfShareURL, nil, username as CFString, password as CFString, open_options as CFMutableDictionary, mount_options as CFMutableDictionary, &mountpoints)
    } else {
        result = NetFSMountURLSync(cfShareURL, nil, nil, nil, open_options as CFMutableDictionary, mount_options as CFMutableDictionary, &mountpoints)
    }
    // Check if it worked
    if result != 0 {
        if [-6600, EINVAL, ENOTSUP, EAUTH].contains(result) {
            // -6600 is kNetAuthErrorInternal in NetFS.h 10.9+
            // EINVAL is returned if an afp share needs a login in some versions of macOS
            // ENOTSUP is returned if an afp share needs a login in some versions of macOS
            // EAUTH is returned if authentication fails (SMB for sure)
            throw ShareMountError.authorizationNeeded(result)
        }
        throw ShareMountError.generalError(result)
    }
    let mounts = (mountpoints?.takeUnretainedValue()) as! [CFString]
    return mounts[0] as String
}

/// A wrapper for mountShare that first attempts without credentials, and if that fails
///  with .authorizationNeeded, prompts for credentials and tries again
func mountShareURL(_ share_url: String) throws -> String {
    do {
        return try mountShare(share_url)
    } catch ShareMountError.authorizationNeeded {
        // pass
    } catch {
        throw error
    }
    var username = ""
    print("Username: ", terminator: "")
    if let input = readLine(strippingNewline: true) {
        username = input
    }
    var password = ""
    if let input = getpass("Password: ") {
        password = String(cString: input, encoding: .utf8) ?? ""
    }
    return try mountShare(share_url, username: username, password: password)
}

// MARK: File repo class

// Implementation of the core file repo
class FileRepo: Repo {
    // MARK: instance variables

    var baseurl: String
    var urlScheme: String
    var root: String
    var weMountedTheRepo: Bool

    // MARK: init/deinit

    required init(_ url: String) throws {
        baseurl = url
        urlScheme = NSURL(string: url)?.scheme ?? ""
        root = ""
        if urlScheme == "file" {
            root = NSURL(string: url)?.path ?? ""
        } else {
            // repo is on a fileshare that will be mounted under /Volumes
            root = "/Volumes" + (NSURL(string: url)?.path ?? "")
        }
        weMountedTheRepo = false
        try _connect()
    }

    /// Destructor -- unmount the fileshare if we mounted it
    deinit {
        if weMountedTheRepo, pathIsDirectory(root) {
            print("Attempting to unmount \(root)...")
            let results = runCLI(
                "/usr/sbin/diskutil", arguments: ["unmount", root]
            )
            if results.exitcode == 0 {
                print(results.output)
            } else {
                print("Exit code: \(results.exitcode)")
                printStderr(results.error)
            }
        }
    }

    // MARK: utility methods

    /// Returns the full (absolute) filesystem path to identifier
    func fullPath(_ identifier: String) -> String {
        return (root as NSString).appendingPathComponent(identifier)
    }

    /// Returns the filesystem path to the parent dir of identifier
    func parentDir(_ identifier: String) -> String {
        return (fullPath(identifier) as NSString).deletingLastPathComponent
    }

    /// If self.root is present, return. Otherwise, if the url scheme is not
    /// "file" then try to mount the share url.
    private func _connect() throws {
        if pathIsDirectory(root) {
            return
        }
        if urlScheme != "file" {
            do {
                print("Attempting to mount fileshare \(baseurl)...")
                root = try mountShareURL(baseurl)
                weMountedTheRepo = true
            } catch is ShareMountError {
                throw MunkiError("Error mounting repo file share")
            }
        }
        // does root dir exist now?
        if !pathIsDirectory(root, followSymlinks: true) {
            throw MunkiError("Repo path does not exist")
        }
    }

    // MARK: API methods

    /// Returns a list of identifiers for each item of kind.
    /// Kind might be 'catalogs', 'manifests', 'pkgsinfo', 'pkgs', or 'icons'.
    /// For a file-backed repo this would be a list of pathnames.
    func list(_ kind: String) async throws -> [String] {
        let searchPath = (root as NSString).appendingPathComponent(kind)
        return listFilesRecursively(searchPath)
    }

    /// Returns the content of item with given resource_identifier.
    /// For a file-backed repo, a resource_identifier of
    /// 'pkgsinfo/apps/Firefox-52.0.plist' would return the contents of
    /// <repo_root>/pkgsinfo/apps/Firefox-52.0.plist.
    /// Avoid using this method with the 'pkgs' kind as it might return a
    /// really large blob of data.
    func get(_ identifier: String) async throws -> Data {
        let repoFilePath = fullPath(identifier)
        if let data = FileManager.default.contents(atPath: repoFilePath) {
            return data
        }
        throw MunkiError("Error getting contents from \(repoFilePath)")
    }

    /// Gets the contents of item with given resource_identifier and saves
    /// it to local_file_path.
    /// For a file-backed repo, a resource_identifier
    /// of 'pkgsinfo/apps/Firefox-52.0.plist' would copy the contents of
    /// <repo_root>/pkgsinfo/apps/Firefox-52.0.plist to a local file given by
    /// local_file_path.
    func get(_ identifier: String, toFile local_file_path: String) async throws {
        // TODO: make this atomic
        let filemanager = FileManager.default
        if filemanager.fileExists(atPath: local_file_path) {
            try filemanager.removeItem(atPath: local_file_path)
        }
        try filemanager.copyItem(atPath: fullPath(identifier), toPath: local_file_path)
    }

    /// Stores content on the repo based on resource_identifier.
    /// For a file-backed repo, a resource_identifier of
    /// 'pkgsinfo/apps/Firefox-52.0.plist' would result in the content being
    /// saved to <repo_root>/pkgsinfo/apps/Firefox-52.0.plist.
    func put(_ identifier: String, content: Data) async throws {
        let filemanager = FileManager.default
        let dirPath = parentDir(identifier)
        if !filemanager.fileExists(atPath: dirPath) {
            try filemanager.createDirectory(
                atPath: dirPath,
                withIntermediateDirectories: true,
                attributes: [.posixPermissions: 0o755]
            )
        }
        if !((content as NSData).write(toFile: fullPath(identifier), atomically: true)) {
            throw MunkiError("Write to \(identifier) failed")
        }
    }

    /// Copies the content of local_file_path to the repo based on
    /// resource_identifier. For a file-backed repo, a resource_identifier
    /// of 'pkgsinfo/apps/Firefox-52.0.plist' would result in the content
    /// being saved to <repo_root>/pkgsinfo/apps/Firefox-52.0.plist.
    func put(_ identifier: String, fromFile localFilePath: String) async throws {
        let filemanager = FileManager.default
        let dirPath = parentDir(identifier)
        if !filemanager.fileExists(atPath: dirPath) {
            try filemanager.createDirectory(
                atPath: dirPath,
                withIntermediateDirectories: true,
                attributes: [.posixPermissions: 0o755]
            )
        }
        let repoFilePath = fullPath(identifier)
        if filemanager.fileExists(atPath: repoFilePath) {
            // if file already exists, we have to remove it first
            try filemanager.removeItem(atPath: repoFilePath)
        }
        try filemanager.copyItem(atPath: localFilePath, toPath: repoFilePath)
    }

    /// Deletes a repo object located by resource_identifier.
    /// For a file-backed repo, a resource_identifier of
    /// 'pkgsinfo/apps/Firefox-52.0.plist' would result in the deletion of
    /// <repo_root>/pkgsinfo/apps/Firefox-52.0.plist.
    func delete(_ identifier: String) async throws {
        try FileManager.default.removeItem(atPath: fullPath(identifier))
    }

    /// Returns the filesystem path to the item in the repo
    /// Non-filesystem Repo subclasses should implement this but return nil
    func pathFor(_ identifier: String) -> String? {
        return fullPath(identifier)
    }
}
