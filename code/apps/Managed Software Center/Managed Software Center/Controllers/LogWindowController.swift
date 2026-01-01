//
//  LogWindowController.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 6/26/25.
//  Copyright © 2025-2026 The Munki Project. All rights reserved.
//

import Cocoa

class LogWindowController: NSWindowController {
    
    @IBOutlet weak var logViewController: LogViewController!
    
    override func windowDidLoad() {
        super.windowDidLoad()
        var windowRect = NSScreen.main!.frame
        windowRect.origin.x = 100.0
        windowRect.origin.y = 200.0
        windowRect.size.width -= 200.0
        windowRect.size.height -= 300.0
        window?.setFrame(windowRect, display: false)
        window?.makeKeyAndOrderFront(self)
        logViewController.initializeView()
    }
    
}
