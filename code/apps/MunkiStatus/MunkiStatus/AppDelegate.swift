//
//  AppDelegate.swift
//  MunkiStatus
//
//  Created by Greg Neagle on 5/18/18.
//  Copyright © 2018-2025 The Munki Project. All rights reserved.
//

import Cocoa

class AppDelegate: NSObject, NSApplicationDelegate {

    @IBOutlet weak var window: NSWindow!
    @IBOutlet weak var logWindow: NSWindow!
    
    var blurredBackground: BackgroundBlurrer?
    
    func applicationWillFinishLaunching(_ aNotification: Notification) {
        if atLoginWindow() {
            // don't show menu bar
            NSMenu.setMenuBarVisible(false)
            // make sure we're active
            NSApp.activate(ignoringOtherApps: true)
        }
    }

    func applicationDidFinishLaunching(_ aNotification: Notification) {
        // draw our loginwindow masking windows if needed
        if atLoginWindow() {
            blurBackground()
        }
        // Prevent automatic relaunching at login on Lion+
        if NSApp.responds(to: #selector(NSApplication.disableRelaunchOnLogin)) {
            NSApp.disableRelaunchOnLogin()
        }
    }

    func applicationWillTerminate(_ aNotification: Notification) {
        // Insert code here to tear down your application
    }
    
    func blurBackground() {
        blurredBackground = BackgroundBlurrer()
    }
}

