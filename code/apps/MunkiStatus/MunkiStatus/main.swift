//
//  main.swift
//  MunkiStatus
//
//  Created by Greg Neagle on 8/27/19.
//  Copyright © 2019-2026 The Munki Project. All rights reserved.
//

import Cocoa

// On Catalina, LaunchAgents run under "LimitLoadToSessionType : LoginWindow" on
// boot seem to be run before a CGSession is setup. Wait until the session is
// available before handing execution over to NSApplicationMain().
// Thanks to Tom Bergin for this insight.
while CGSessionCopyCurrentDictionary() == nil {
    print("Waiting for a CGSession...")
    usleep(500000)
}

_ = NSApplicationMain(CommandLine.argc, CommandLine.unsafeArgv)
