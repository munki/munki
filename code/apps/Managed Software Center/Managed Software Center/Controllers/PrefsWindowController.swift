//
//  PrefsWindowController.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 5/5/26.
//  Copyright © 2026 The Munki Project. All rights reserved.
//

import Cocoa

class PrefsWindowController: NSWindowController, NSWindowDelegate {
    @IBOutlet var timeRangeSelectorController: TimeRangeSelectorViewController!

    @IBOutlet weak var timeRangeSelector: TimeRangeSelectorView!
    @IBOutlet weak var updateNotificationTimesCheckbox: NSButton!

    @IBAction func didClickUpdateNotificationTimesCheckbox(_ sender: Any) {
        if updateNotificationTimesCheckbox.state.rawValue == 1 {
            timeRangeSelector.isHidden = false
        } else {
            timeRangeSelector.isHidden = true
        }
    }

    override func windowDidLoad() {
        super.windowDidLoad()
        window?.delegate = self
        window?.makeKeyAndOrderFront(self)
    }

    func windowWillClose(_ notification: Notification) {
        print(timeRangeSelector.selectedHoursList())
    }
}
