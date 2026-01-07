//
//  MainWindowController+NSWindowDelegate.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 6/28/25.
//  Copyright © 2025-2026 The Munki Project. All rights reserved.
//

import Cocoa

extension MainWindowController: NSWindowDelegate {
    
    func windowShouldClose(_ sender: NSWindow) -> Bool {
        // NSWindowDelegate method called when user closes a window
        // for us, closing the main window should be the same as quitting
        NSApp.terminate(self)
        return false
    }
    
    func windowDidBecomeMain(_ notification: Notification) {
        // Our window was activated, make sure controls enabled as needed
        sidebarList.action = #selector(self.sidebarItemClicked)
    }
    
    func windowDidResignMain(_ notification: Notification) {
        // Our window was deactivated, make sure controls enabled as needed
    }

    func windowDidBecomeKey(_ notification: Notification) {
        // If we just became key, enforce obnoxious mode if required.
        if _obnoxiousNotificationMode {
            makeUsObnoxious()
        }
    }
}
