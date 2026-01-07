//
//  msclog.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 6/6/18.
//  Copyright © 2018-2026 The Munki Project. All rights reserved.
//

import Foundation

let MSULOGDIR = "/Users/Shared/.com.googlecode.munki.ManagedSoftwareUpdate.logs"
// TO-DO: eliminate these global vars
var MSULOGFILE = ""
var MSULOGENABLED = false
var MSUDEBUGLOGENABLED = false

func is_safe_to_use(_ pathname: String) -> Bool {
    // Returns true if we can open this file and it is a regular file owned by us
    // mostly C functions since this a port from Python
    var safe = false
    if !(FileManager.default.fileExists(atPath: pathname)) {
        if FileManager.default.createFile(atPath: pathname, contents: nil, attributes: [FileAttributeKey.posixPermissions: 0o0600]) == false {
            NSLog("Could not create %@", pathname)
            return false
        }
    }
    pathname.withCString(){
        let fref = open($0, O_RDWR | O_CREAT | O_NOFOLLOW, 0x0600)
        if fref != 1 {
            var st = stat()
            var fstat_result : Int32 = 0
            withUnsafeMutablePointer(to: &st){
                fstat_result = fstat(fref, $0)
            }
            if fstat_result == 0 {
                safe = ((st.st_mode & S_IFREG) != 0) && (st.st_uid == getuid())
            }
        }
        close(fref)
    }
    return safe
}

func setup_logging() {
    if pythonishBool(pref("MSUDebugLogEnabled")) {
        MSUDEBUGLOGENABLED = true
    }
    if pythonishBool(pref("MSULogEnabled")) {
        MSULOGENABLED = true
    }
    if !(MSULOGENABLED) {
        return
    }

    let username = NSUserName()
    if !(FileManager.default.fileExists(atPath: MSULOGDIR)) {
        do {
            try FileManager.default.createDirectory(atPath: MSULOGDIR, withIntermediateDirectories: true, attributes: [FileAttributeKey.posixPermissions: 0o1777])
        } catch {
            NSLog("Could not create %@: %@", MSULOGDIR, "\(error)")
            return
        }
    }
    var pathIsDir = ObjCBool(false)
    let msuLogDirExists = FileManager.default.fileExists(atPath: MSULOGDIR, isDirectory: &pathIsDir)
    if !msuLogDirExists {
        NSLog("%@ doesn't exist.", MSULOGDIR)
        return
    } else if pathIsDir.boolValue == false {
        NSLog("%@ is not a directory", MSULOGDIR)
        return
    }
    // try to set our preferred permissions
    do {
        try FileManager.default.setAttributes([FileAttributeKey.posixPermissions: 0o1777], ofItemAtPath: MSULOGDIR)
    } catch {
        // do nothing
    }
    // find a safe log file to write to for this user
    var filename = NSString.path(withComponents: [MSULOGDIR, "\(username).log"])
    //make sure we can write to this; that it's owned by us, and not writable by group or other
    for _ in 0..<10 {
        if is_safe_to_use(filename) {
            MSULOGFILE = filename
            NSLog("Using file %@ for user-level logging", filename)
            return
        }
        NSLog("Not safe to use %@ for logging", filename)
        filename = NSString.path(withComponents: [MSULOGDIR, "\(username)_\(arc4random()).log"])
    }
    NSLog("Could not set up user-level logging for %@", username)
}

func msc_log(_ source: String, _ event: String, msg: String = "") {
    // Log an event from a source.
    if MSULOGFILE != "" {
        let datestamp = NSDate().timeIntervalSince1970
        let logString = "\(datestamp) \(source): \(event)  \(msg)\n"
        if let logData = logString.data(using: String.Encoding.utf8) {
            if let fh = FileHandle(forUpdatingAtPath: MSULOGFILE) {
                let _ = fh.seekToEndOfFile()
                fh.write(logData)
            }
        }
    }
}

func msc_debug_log(_ logMessage: String) {
    // Log to Apple System Log facility and also to MSU log if configured
    NSLog("%@", logMessage)
    msc_log("MSC", "debug", msg: logMessage)
}
