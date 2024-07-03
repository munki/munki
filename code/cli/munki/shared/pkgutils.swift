//
//  pkgutils.swift
//  munki
//
//  Created by Greg Neagle on 7/2/24.
//

import Foundation

func getPkgRestartInfo(_ pkgpath: String) -> PlistDict {
    var installerinfo = PlistDict()
    let results = runCLI(
        "/usr/sbin/installer",
        arguments: ["-query", "RestartAction",
                   "-pkg", pkgpath,
                   "-plist"]
    )
    if results.exitcode != 0 {
        displayError("installer -query for \(pkgpath) failed: \(results.error)")
        return installerinfo
    }
    let (pliststr, _) = parseFirstPlist(fromString: results.output)
    if !pliststr.isEmpty {
        if let plist = try? readPlistFromString(pliststr) as? PlistDict {
            if let restartAction = plist["RestartAction"] as? String {
                if restartAction != "None" {
                    installerinfo["RestartAction"] = restartAction
                }
            }
        }
    }
    return installerinfo
}


func getVersionString(plist: PlistDict, key: String = "") -> String {
    // Gets a version string from the plist.
    //
    // If a key is explicitly specified, the string value of that key is returned
    // without modification, or an empty string if the key does not exist or the value
    // is not a string.
    //
    // If key is not specified:
    // if there's a valid CFBundleShortVersionString, returns that.
    // else if there's a CFBundleVersion, returns that
    // else returns an empty string.
    
    if !key.isEmpty {
        return plist[key] as? String ?? ""
    }
    for aKey in ["CFBundleShortVersionString", "CFBundleVersion"] {
        if let version = plist[aKey] as? String {
            return version
        }
    }
    return ""
}

// MARK: bundle functions

func getBundleInfo(_ bundlepath: String) -> PlistDict? {
    // Returns Info.plist data if available for bundle at bundlepath
    var infopath = (bundlepath as NSString).appendingPathComponent("Contents/Info.plist")
    let filemanager = FileManager.default
    if !filemanager.fileExists(atPath: infopath) {
        infopath = (bundlepath as NSString).appendingPathComponent("Resources/Info.plist")
    }
    if filemanager.fileExists(atPath: infopath) {
        return try? readPlist(infopath) as? PlistDict
    }
    return nil
}


func getAppBundleExecutable(_ bundlepath: String) -> String {
    // Returns path to the actual executable in an app bundle or empty string
    var executableName = (bundlepath as NSString).lastPathComponent
    executableName = (executableName as NSString).deletingPathExtension
    if let plist = getBundleInfo(bundlepath) {
        if let cfBundleExecutable = plist["CFBundleExecutable"] as? String {
            executableName = cfBundleExecutable
        } else if let cfBundleName = plist["CFBundleName"] as? String {
            executableName = cfBundleName
        }
    }
    var executablePath = (bundlepath as NSString).appendingPathComponent("Contents/MacOS")
    executablePath = (executablePath as NSString).appendingPathComponent(executableName)
    if FileManager.default.fileExists(atPath: executablePath) {
        return executablePath
    }
    return ""
}


func parseInfoFileText(_ text: String) -> [String:String] {
    var info = [String:String]()
    for line in text.components(separatedBy: .newlines) {
        let parts = line.components(separatedBy: .whitespaces)
        if parts.count > 1 {
            let key = parts[0]
            let value = parts[1...].joined(separator: " ")
            info[key] = value
        }
    }
    return info
}


func parseInfoFile(_ infofilepath: String) -> PlistDict {
    // parses an ancient data format in old bundle-style packages
    // and returns a PlistDict
    if let filedata = NSData(contentsOfFile: infofilepath) {
        if let filetext = String(data: filedata as Data, encoding: .macOSRoman) {
            return parseInfoFileText(filetext)
        } else if let filetext = String(data: filedata as Data, encoding: .utf8) {
            return parseInfoFileText(filetext)
        }
    }
    return PlistDict()
}


func getBundleVersion(_ bundlepath: String, key: String = "") -> String {
    // Returns version number from a bundle.
    // Some extra code to deal with very old-style bundle packages
    //
    // Specify key to use a specific key in the Info.plist for the version string.
    
    if let plist = getBundleInfo(bundlepath) {
        let versionstring = getVersionString(plist: plist, key: key)
        if !versionstring.isEmpty {
            return versionstring
        }
    }
    // no version number in Info.plist. Maybe old-style package?
    let infopath = (bundlepath as NSString).appendingPathComponent("Contents/Resources/English.lproj")
    if isDir(infopath) {
        let filemanager = FileManager.default
        if let dirlist = try? filemanager.contentsOfDirectory(atPath: infopath) {
            for item in dirlist {
                if item.hasSuffix(".info") {
                    let infofile = (infopath as NSString).appendingPathComponent(item)
                    let info = parseInfoFile(infofile)
                    if let version = info["Version"] as? String {
                        return version
                    }
                }
            }
        }
    }
    return "0.0.0.0.0"
}

// MARK: dist file functions
