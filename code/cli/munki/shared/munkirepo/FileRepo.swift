//
//  FileRepo.swift
//  munki
//
//  Created by Greg Neagle on 6/25/24.
//

import Foundation
import NetFS

// Base classes
enum RepoError: Error {
    /// General error class for repo errors
    case error(description: String)
}

protocol Repo {
    // Defines methods all repo classes must implement
    init(_ url: String) throws
    func list(_ kind: String) throws -> [String]
    func get(_ identifier: String) throws -> Data
    func get(_ identifier: String, toFile local_file_path: String) throws
    func put(_ identifier: String, content: Data) throws
    func put(_ identifier: String, fromFile local_file_path: String) throws
    func delete(_ identifier: String) throws
}

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

func mountShare(_ shareURL: String, username: String = "", password: String = "") throws -> String {
    // Mounts a share at /Volumes, optionally using credentials.
    // Returns the mount point or throws an error
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

    deinit {
        // Destructor -- unmount the fileshare if we mounted it
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

    func fullPath(_ identifier: String) -> String {
        // returns the full (absolute) filesystem path to identifier
        return (root as NSString).appendingPathComponent(identifier)
    }

    func parentDir(_ identifier: String) -> String {
        // returns the filesystem path to the parent dir of identifier
        return (fullPath(identifier) as NSString).deletingLastPathComponent
    }

    private func _connect() throws {
        // If self.root is present, return. Otherwise, if the url scheme is not
        // "file" then try to mount the share url.
        if pathIsDirectory(root) {
            return
        }
        if urlScheme != "file" {
            do {
                print("Attempting to mount fileshare \(baseurl)...")
                root = try mountShareURL(baseurl)
                weMountedTheRepo = true
            } catch is ShareMountError {
                throw RepoError.error(description: "Error mounting repo file share")
            }
        }
        // does root dir exist now?
        if !pathIsDirectory(root) {
            throw RepoError.error(description: "Repo path does not exist")
        }
    }

    // MARK: API methods

    func list(_ kind: String) throws -> [String] {
        // Returns a list of identifiers for each item of kind.
        // Kind might be 'catalogs', 'manifests', 'pkgsinfo', 'pkgs', or 'icons'.
        // For a file-backed repo this would be a list of pathnames.
        var fileList = [String]()
        let searchPath = (root as NSString).appendingPathComponent(kind)
        let filemanager = FileManager.default
        let dirEnum = filemanager.enumerator(atPath: searchPath)
        while let file = dirEnum?.nextObject() as? String {
            let fullpath = (searchPath as NSString).appendingPathComponent(file)
            if !pathIsDirectory(fullpath) {
                let basename = (file as NSString).lastPathComponent
                if !basename.hasPrefix(".") {
                    fileList.append(file)
                }
            }
        }
        return fileList
    }

    func get(_ identifier: String) throws -> Data {
        // Returns the content of item with given resource_identifier.
        // For a file-backed repo, a resource_identifier of
        // 'pkgsinfo/apps/Firefox-52.0.plist' would return the contents of
        // <repo_root>/pkgsinfo/apps/Firefox-52.0.plist.
        // Avoid using this method with the 'pkgs' kind as it might return a
        // really large blob of data.
        let repoFilePath = fullPath(identifier)
        if let data = FileManager.default.contents(atPath: repoFilePath) {
            return data
        }
        throw RepoError.error(description: "Error getting contents from \(repoFilePath)")
    }

    func get(_ identifier: String, toFile local_file_path: String) throws {
        // Gets the contents of item with given resource_identifier and saves
        // it to local_file_path.
        // For a file-backed repo, a resource_identifier
        // of 'pkgsinfo/apps/Firefox-52.0.plist' would copy the contents of
        // <repo_root>/pkgsinfo/apps/Firefox-52.0.plist to a local file given by
        // local_file_path.
        // TODO: make this atomic
        let filemanager = FileManager.default
        if filemanager.fileExists(atPath: local_file_path) {
            try filemanager.removeItem(atPath: local_file_path)
        }
        try filemanager.copyItem(atPath: fullPath(identifier), toPath: local_file_path)
    }

    func put(_ identifier: String, content: Data) throws {
        // Stores content on the repo based on resource_identifier.
        // For a file-backed repo, a resource_identifier of
        // 'pkgsinfo/apps/Firefox-52.0.plist' would result in the content being
        // saved to <repo_root>/pkgsinfo/apps/Firefox-52.0.plist.
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
            throw RepoError.error(description: "write failed")
        }
    }

    func put(_ identifier: String, fromFile localFilePath: String) throws {
        // Copies the content of local_file_path to the repo based on
        // resource_identifier. For a file-backed repo, a resource_identifier
        // of 'pkgsinfo/apps/Firefox-52.0.plist' would result in the content
        // being saved to <repo_root>/pkgsinfo/apps/Firefox-52.0.plist.
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

    func delete(_ identifier: String) throws {
        // Deletes a repo object located by resource_identifier.
        // For a file-backed repo, a resource_identifier of
        // 'pkgsinfo/apps/Firefox-52.0.plist' would result in the deletion of
        // <repo_root>/pkgsinfo/apps/Firefox-52.0.plist.
        try FileManager.default.removeItem(atPath: fullPath(identifier))
    }
}
