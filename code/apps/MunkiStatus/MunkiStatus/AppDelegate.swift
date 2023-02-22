//
//  AppDelegate.swift
//  MunkiStatus
//
//  Created by Greg Neagle on 5/18/18.
//  Copyright © 2018-2023 The Munki Project. All rights reserved.
//

import Cocoa

class AppDelegate: NSObject, NSApplicationDelegate {

    @IBOutlet weak var window: NSWindow!
    @IBOutlet weak var logWindow: NSWindow!
    
    var backdropWindows: [NSWindow] = []
    
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
            displayBackdropWindows()
        }
        // Prevent automatic relaunching at login on Lion+
        if NSApp.responds(to: #selector(NSApplication.disableRelaunchOnLogin)) {
            NSApp.disableRelaunchOnLogin()
        }
    }

    func applicationWillTerminate(_ aNotification: Notification) {
        // Insert code here to tear down your application
    }

    func newTranslucentWindow(screen: NSScreen) -> NSWindow {
        // makes a translucent masking window we use to prevent interaction with
        // the login window/login controls
        var windowRect = screen.frame
        windowRect.origin = NSMakePoint(0.0, 0.0)
        let thisWindow = NSWindow(
            contentRect: windowRect,
            styleMask: .borderless,
            backing: .buffered,
            defer: false,
            screen: screen
        )
        thisWindow.canBecomeVisibleWithoutLogin = true
        thisWindow.level = backdropWindowLevel
        thisWindow.backgroundColor = NSColor.black.withAlphaComponent(0.35)
        thisWindow.isOpaque = false
        thisWindow.ignoresMouseEvents = false
        thisWindow.alphaValue = 0.0
        thisWindow.orderFrontRegardless()
        thisWindow.animator().alphaValue = 1.0
        return thisWindow
    }
    
    func displayBackdropWindows() {
        for screen in NSScreen.screens {
            let newWindow = newTranslucentWindow(screen: screen)
            if haveElCapPolicyBanner {
                if backdropWindows.count > 1 {
                    backdropWindows[0].addChildWindow(newWindow, ordered: .below)
                }
            }
            // add to our backdropWindows array so a reference stays around
            backdropWindows.append(newWindow)
        }
        if haveElCapPolicyBanner {
            // status window and masking windows have the same NSWindowLevel, so keep status window above the backdrop
            backdropWindows[0].addChildWindow(window, ordered: .above)
        }
    }
}

