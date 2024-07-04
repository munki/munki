//
//  osutils.swift
//  munki
//
//  Created by Greg Neagle on 7/2/24.
//

import Foundation

func getOSVersion(onlyMajorMinor: Bool = true) -> String {
    let version = ProcessInfo().operatingSystemVersion
    if onlyMajorMinor {
        return "\(version.majorVersion).\(version.minorVersion)"
    } else {
        return "\(version.majorVersion).\(version.minorVersion).\(version.patchVersion)"
    }
}

class TempDir {
    // a class to return a shared temp directory, and to clean it up when we exit
    static let shared = TempDir()
    
    private var url: URL?
    var path: String? {
        get {
            return url?.path
        }
    }
    
    private init() {
        let filemanager = FileManager.default
        let dirName = "munki-\(UUID().uuidString)"
        let tmpURL = filemanager.temporaryDirectory.appendingPathComponent(
            dirName, isDirectory: true)
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
