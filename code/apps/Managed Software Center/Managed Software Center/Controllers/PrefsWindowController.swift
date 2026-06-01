//
//  PrefsWindowController.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 5/5/26.
//  Copyright © 2026 The Munki Project. All rights reserved.
//

import Cocoa

class PrefsWindowController: NSWindowController, NSWindowDelegate {
    
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

    // read preferences and set up the window to reflect them
    override func awakeFromNib() {
        super.awakeFromNib()
        let useNotificationTimes = UserDefaults.standard.bool(forKey: "UseNotificationTimes")
        updateNotificationTimesCheckbox.state = useNotificationTimes ? .on : .off
        if useNotificationTimes {
            timeRangeSelector.isHidden = false
        }
        var allowedHoursStart = munkiPref("MSCAllowedNotificationWindowStart") as? Int ?? 0
        allowedHoursStart = min(max(allowedHoursStart, 0), 23)
        var allowedHoursEnd = munkiPref("MSCAllowedNotificationWindowEnd") as? Int ?? 24
        allowedHoursEnd = min(max(allowedHoursEnd, 0), 24)
        timeRangeSelector.setAllowedHours(start: allowedHoursStart, end: allowedHoursEnd)
        let notificationHours = UserDefaults.standard.array(forKey: "NotificationHours") as? [Int] ?? []
        timeRangeSelector.setSelectedHours(notificationHours)
    }

    func windowWillClose(_ notification: Notification) {
        let useNotificationTimes = updateNotificationTimesCheckbox.state.rawValue == 1
        let notificationHours = timeRangeSelector.selectedHoursList()
        UserDefaults.standard.set(useNotificationTimes, forKey: "UseNotificationTimes")
        UserDefaults.standard.set(notificationHours, forKey: "NotificationHours")
    }
}
