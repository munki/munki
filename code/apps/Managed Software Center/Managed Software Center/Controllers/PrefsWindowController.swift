//
//  PrefsWindowController.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 5/5/26.
//  Copyright © 2026 The Munki Project. All rights reserved.
//

import Cocoa

class PrefsWindowController: NSWindowController {
    @IBOutlet weak var timeRangeSelectorContainingView: NSView!
    @IBOutlet var timeRangeSelectorController: TimeRangeSelectorViewController!

    override func windowDidLoad() {
        super.windowDidLoad()
        window?.makeKeyAndOrderFront(self)
        timeRangeSelectorController.startTime = 9
        timeRangeSelectorController.endTime = 17
    }
}
