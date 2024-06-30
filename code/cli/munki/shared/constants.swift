//
//  constants.swift
//  munki
//
//  Created by Greg Neagle on 6/25/24.
//

import Foundation

// NOTE: it's very important that defined exit codes are never changed!
// Preflight exit codes
let EXIT_STATUS_PREFLIGHT_FAILURE = 1
// Client config exit codes.
let EXIT_STATUS_OBJC_MISSING = 100 // no longer relevant
let EXIT_STATUS_MUNKI_DIRS_FAILURE = 101
// Server connection exit codes.
let EXIT_STATUS_SERVER_UNAVAILABLE = 150
// User related exit codes.
let EXIT_STATUS_INVALID_PARAMETERS = 200
let EXIT_STATUS_ROOT_REQUIRED = 201

let BUNDLE_ID = "ManagedInstalls" as CFString
let DEFAULT_GUI_CACHE_AGE_SECS = 3600
let WRITEABLE_SELF_SERVICE_MANIFEST_PATH = "/Users/Shared/.SelfServeManifest"

let ADDITIONAL_HTTP_HEADERS_KEY = "AdditionalHttpHeaders"

let LOGINWINDOW = "/System/Library/CoreServices/loginwindow.app/Contents/MacOS/loginwindow"

let CHECKANDINSTALLATSTARTUPFLAG = "/Users/Shared/.com.googlecode.munki.checkandinstallatstartup"
let INSTALLATSTARTUPFLAG = "/Users/Shared/.com.googlecode.munki.installatstartup"
let INSTALLATLOGOUTFLAG = "/private/tmp/com.googlecode.munki.installatlogout"
let UPDATECHECKLAUNCHFILE = "/private/tmp/.com.googlecode.munki.updatecheck.launchd"
let INSTALLWITHOUTLOGOUTFILE = "/private/tmp/.com.googlecode.munki.managedinstall.launchd"

// postinstall actions
let POSTACTION_NONE = 0
let POSTACTION_LOGOUT = 1
let POSTACTION_RESTART = 2
let POSTACTION_SHUTDOWN = 4

typealias PlistDict = [String:Any]
