//
//  msclib.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 6/6/18.
//  Copyright © 2018-2026 The Munki Project. All rights reserved.
//

import Foundation

var _msclib_html_dir = "" // TO-DO: eliminate this global var

func appleUpdateCountMessage(_ count: Int) -> String {
    // Return a localized message describing the count of Apple updates to install
    if count == 0 {
        return NSLocalizedString("Apple software is up to date", comment: "No Apple updates message") as String
    } else if count == 1 {
        return NSLocalizedString("1 available Apple update", comment: "One Apple update message") as String
    } else {
        let formatString = NSLocalizedString("%@ available Apple updates", comment: "Multiple Apple updates message")
        return NSString(format: (formatString as NSString), String(count)) as String
    }
}

func updateCountMessage(_ count: Int, appleUpdateCount: Int = 0) -> String {
    // Return a localized message describing the count of updates to install
    if count == 0 {
        if appleUpdateCount == 0 {
            return NSLocalizedString("No pending updates", comment: "No Updates message") as String
        }
        return NSLocalizedString("Managed software is up to date", comment: "No managed updates message") as String
    } else if count == 1 {
        return NSLocalizedString("1 pending managed update", comment: "One managed updates message") as String
    } else {
        let formatString = NSLocalizedString("%@ pending managed updates", comment: "Multiple managed updates message")
        return NSString(format: (formatString as NSString), String(count)) as String
    }
}

func getInstallAllButtonTextForCount(_ count: Int) -> String {
    // Return localized display text for action button in Updates view
    if count == 0 {
        return NSLocalizedString("Check Again", comment: "Check Again button title") as String
    } else if count == 1 {
        return NSLocalizedString("Update", comment: "Update button title/action text") as String
    } else {
        return NSLocalizedString("Update All", comment: "Update All button title") as String
    }
}

func runProcess(_ command: String, args: [String] = []) -> (exitcode: Int, stdout: String, stderr: String) {
    // Run an external process. Return a tuple of (exitcode, stdout, stderr)
    // Probably won't deal well with commands that produce a large amount of
    // output or error output.
    let proc = Process()
    let stdout_pipe = Pipe()
    let stderr_pipe = Pipe()

    msc_debug_log("Running process \(command) with args \(args)")
    proc.launchPath = command
    proc.arguments = args
    proc.standardOutput = stdout_pipe
    proc.standardError = stderr_pipe

    proc.launch()
    proc.waitUntilExit()

    let stdout = stdout_pipe.fileHandleForReading.readDataToEndOfFile()
    let stderr = stderr_pipe.fileHandleForReading.readDataToEndOfFile()
    let exitcode = proc.terminationStatus

    return (Int(exitcode),
            String(data: stdout, encoding: String.Encoding.utf8)!,
            String(data: stderr, encoding: String.Encoding.utf8)!)
}

func runEmbeddedScript(_ scriptText: String, scriptName: String = "script") -> (exitcode: Int, stdout: String, stderr: String) {
    // Run an embedded script by writing it to a temp file and executing it.
    // Returns a tuple of (exitcode, stdout, stderr)
    let tempDir = NSTemporaryDirectory()
    let scriptPath = (tempDir as NSString).appendingPathComponent(
        "\(scriptName)_\(UUID().uuidString)")

    // Write script to temp file
    do {
        try scriptText.write(toFile: scriptPath, atomically: true, encoding: .utf8)
    } catch {
        msc_debug_log("Failed to write script to \(scriptPath): \(error)")
        return (-1, "", "Failed to write script: \(error)")
    }

    // Make it executable (0o700)
    do {
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o700], ofItemAtPath: scriptPath)
    } catch {
        msc_debug_log("Failed to set permissions on \(scriptPath): \(error)")
        try? FileManager.default.removeItem(atPath: scriptPath)
        return (-1, "", "Failed to set script permissions: \(error)")
    }

    msc_debug_log("Running embedded script: \(scriptName)")
    let result = runProcess(scriptPath)

    // Clean up temp file
    try? FileManager.default.removeItem(atPath: scriptPath)

    if result.exitcode != 0 {
        msc_debug_log("Script \(scriptName) exited with code \(result.exitcode)")
        if !result.stderr.isEmpty {
            msc_debug_log("Script stderr: \(result.stderr)")
        }
    }

    return result
}

enum ZipExtractError: Error {
    case error(description: String)
}

func extractZipFiles(from source_path: String, to dest_path: String) throws {
    // Uses /usr/bin/unzip to expand the zip files.
    // TO-DO: replace with a "real" library!
    let command = "/usr/bin/unzip"
    let arguments = ["-q", source_path, "-d", dest_path]
    let (exitcode, _, stderr) = runProcess(command, args: arguments)
    if exitcode != 0 {
        throw ZipExtractError.error(description: stderr)
    }
}

func get_custom_resources() {
    // copies custom resources into our html dir
    if _msclib_html_dir.isEmpty {
        return
    }
    if let managed_install_dir = pref("ManagedInstallDir") as? String {
        let source_path = NSString.path(
            withComponents: [managed_install_dir, "client_resources/custom.zip"])
        if FileManager.default.fileExists(atPath: source_path) {
            let dest_path = NSString.path(withComponents: [_msclib_html_dir, "custom"])
            if FileManager.default.fileExists(atPath: dest_path) {
                do {
                    try FileManager.default.removeItem(atPath: dest_path)
                } catch {
                    msc_debug_log("Error clearing \(dest_path): \(error)")
                }
            }
            if !FileManager.default.fileExists(atPath: dest_path) {
                do {
                    try FileManager.default.createDirectory(
                        atPath: dest_path, withIntermediateDirectories: false, attributes: nil)
                } catch {
                    msc_debug_log("Error creating \(dest_path): \(error)")
                }
            }
            do {
                try extractZipFiles(from: source_path, to: dest_path)
            } catch {
                msc_debug_log("Error extracting files from \(source_path): \(error)")
            }
        }
    }
}

func linkOrCopy(_ sourcePath: String, _ destPath: String) {
    // if sourcePath and destPath are on the same volume (device)
    // symlink, otherwise copy. This works around an issue with WKWebView
    // where it will refuse to get file:// resources that include symlinks
    // that point to paths on a different volume
    // by default, symlink instead of copy
    var prefer_symlink = true
    // destPath might not yet exist so get its parent directory
    let destDir = (destPath as NSString).deletingLastPathComponent
    do {
        let source_filesystem = try FileManager.default.attributesOfItem(atPath: sourcePath)[.systemNumber] as? Int ?? 0
        let dest_filesystem = try FileManager.default.attributesOfItem(atPath: destDir)[.systemNumber] as? Int ?? 0
        prefer_symlink = (source_filesystem == dest_filesystem)
    } catch {
        msc_debug_log("Can't get filesystem attributes while setting up html dir: \(error)")
    }
    if prefer_symlink {
        do {
            // symlinks sort of invert the idea of source and destination.
            // in this case, sourcePath is the original content in its "real" location
            // and destPath is where the symlink itself resides
            try FileManager.default.createSymbolicLink(atPath: destPath, withDestinationPath: sourcePath)
        } catch {
            msc_debug_log("Error creating symlink \(destPath): \(error)")
        }
    } else {
        do {
            try FileManager.default.copyItem(atPath:sourcePath, toPath: destPath)
        } catch {
            msc_debug_log("Error copying \(sourcePath) to \(destPath): \(error)")
        }
    }
}

func html_dir() -> String {
    // sets up our local html cache directory if needed
    // returns path to our html directory
    if !_msclib_html_dir.isEmpty {
        return _msclib_html_dir
    }
    if let bundle_id = Bundle.main.bundleIdentifier {
        let cache_dir_urls = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)
        var cache_dir = "/private/tmp"
        if cache_dir_urls.count > 0 {
            cache_dir = cache_dir_urls[0].path
        }
        let our_cache_dir = NSString.path(withComponents: [cache_dir, bundle_id])
        if !FileManager.default.fileExists(atPath: our_cache_dir) {
            do {
                try FileManager.default.createDirectory(
                    atPath: our_cache_dir, withIntermediateDirectories: true, attributes: nil)
            } catch {
                msc_debug_log("Error creating \(our_cache_dir): \(error)")
                return ""
            }
        }
        _msclib_html_dir = NSString.path(withComponents: [our_cache_dir, "html"])
        if FileManager.default.fileExists(atPath: _msclib_html_dir) {
            // empty it
            do {
                try FileManager.default.removeItem(atPath: _msclib_html_dir)
            } catch {
                msc_debug_log("Error clearing \(_msclib_html_dir): \(error)")
                _msclib_html_dir = ""
                return ""
            }
        }
        do {
            try FileManager.default.createDirectory(
                atPath: _msclib_html_dir, withIntermediateDirectories: false, attributes: nil)
        } catch {
            msc_debug_log("Error creating \(_msclib_html_dir): \(error)")
            return ""
        }
        
        // symlink or copy our static files dir
        if let resourcesPath = Bundle.main.resourcePath {
            let source_path = NSString.path(withComponents: [resourcesPath, "WebResources"])
            let dest_path = NSString.path(withComponents: [_msclib_html_dir, "static"])
            linkOrCopy(source_path, dest_path)
        }
        
        // symlink or copy the Managed Installs icons dir
        if let managed_install_dir = pref("ManagedInstallDir") as? String {
            let source_path = NSString.path(withComponents: [managed_install_dir, "icons"])
            let dest_path = NSString.path(withComponents: [_msclib_html_dir, "icons"])
            linkOrCopy(source_path, dest_path)
        }
        
        // unzip any custom client resources
        get_custom_resources()
        
        return _msclib_html_dir
    }
    return ""
}
