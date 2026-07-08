//
//  PrefsWindowController.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 5/5/26.
//  Copyright © 2026 The Munki Project. All rights reserved.
//

import Cocoa

class PrefsWindowController: NSWindowController, NSWindowDelegate {

    @IBOutlet weak var hoursSelector: HoursSelector!
    @IBOutlet weak var updateNotificationTimesCheckbox: NSButton!

    private var allowedHoursStart = 0
    private var allowedHoursEnd = 24
    private var displayedHours = [Int]()

    @IBAction func didClickUpdateNotificationTimesCheckbox(_ sender: Any) {
        if updateNotificationTimesCheckbox.state.rawValue == 1 {
            hoursSelector.isHidden = false
            hoursSelector.isEnabled = true
        } else {
            hoursSelector.isHidden = true
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
            hoursSelector.isHidden = false
            hoursSelector.isEnabled = true
        }
        allowedHoursStart = munkiPref("MSCAllowedNotificationWindowStart") as? Int ?? 0
        allowedHoursStart = min(max(allowedHoursStart, 0), 23)
        allowedHoursEnd = munkiPref("MSCAllowedNotificationWindowEnd") as? Int ?? 24
        allowedHoursEnd = min(max(allowedHoursEnd, 0), 24)
        setAllowedHours(start: allowedHoursStart, end: allowedHoursEnd)
        let notificationHours = UserDefaults.standard.array(forKey: "NotificationHours") as? [Int] ?? []
        setSelectedHours(notificationHours)

        // make sure prefs window name matches the name of the menu item
        // (Settings or Preferences or localized name)
        if let appDelegate = NSApp.delegate as? AppDelegate {
            let prefsName = appDelegate.preferencesMenuItem.title
            if prefsName.hasSuffix("…") {
                window?.title = String(prefsName.dropLast(1))
            } else {
                window?.title = prefsName
            }
        }

        // use localized strings from Localizable.strings instead
        // of having to generate a bunch of PrefsWindows.strings files
        updateNotificationTimesCheckbox.title = NSLocalizedString(
            "Restrict update notifications to selected hours",
            comment: "Restrict update notifications checkbox label"
        )
    }

    func windowWillClose(_ notification: Notification) {
        let useNotificationTimes = updateNotificationTimesCheckbox.state.rawValue == 1
        let notificationHours = selectedHoursList()
        UserDefaults.standard.set(useNotificationTimes, forKey: "UseNotificationTimes")
        UserDefaults.standard.set(notificationHours, forKey: "NotificationHours")
    }

    // MARK: - Helper Methods for Hour <-> Index Conversion

    /// Detect if user wants time in 24 hour format
    private func is24hourTime() -> Bool {
        let formatter = DateFormatter()
        formatter.locale = Locale.current
        formatter.setLocalizedDateFormatFromTemplate("j")
        return formatter.dateFormat?.contains("a") == false
    }

    /// Returns a compact string for hour labels
    private func labelHour(_ hour: Int) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale.current
        let using24hTime = is24hourTime()
        if using24hTime {
            formatter.dateFormat = "HH"
        } else {
            formatter.dateFormat = "h"
        }

        var components = DateComponents()
        components.hour = hour
        components.minute = 0

        let calendar = Calendar.current
        guard let date = calendar.date(from: components) else {
            return "\(hour)"
        }
        var formattedStr = formatter.string(from: date)
        if !using24hTime {
            // append an 'a' for AM and a 'p' for PM to "12"
            if hour == 0 || (hour < 12 && hour == allowedHoursStart) {
                formattedStr += "a"
            }
            if hour == 12 || (hour > 12 && hour == allowedHoursStart) {
                formattedStr += "p"
            }
        }
        return formattedStr
    }

    /// Check if hour is within the start and end range (handles ranges that cross midnight)
    private func hourWithinRange(_ hour: Int, start: Int, end: Int) -> Bool {
        if start < end {
            return hour >= start && hour < end
        }
        return hour >= start || hour < end
    }

    /// Set the allowed hour range and update the selector
    func setAllowedHours(start: Int, end: Int) {
        // Validate start (0-23)
        if start < 0 || start > 23 {
            allowedHoursStart = 0
        } else {
            allowedHoursStart = start
        }
        // Validate end (0-24)
        if end < 0 || end > 24 {
            allowedHoursEnd = 24
        } else {
            allowedHoursEnd = end
        }
        // If start and end are the same, allow all 24 hours
        if allowedHoursStart == allowedHoursEnd {
            allowedHoursStart = 0
            allowedHoursEnd = 24
        }

        // Build the hours array
        if allowedHoursStart < allowedHoursEnd {
            // Normal range
            displayedHours = Array(allowedHoursStart ..< allowedHoursEnd)
        } else {
            // Range crosses midnight
            displayedHours = Array(allowedHoursStart ... 23)
            displayedHours += Array(0 ..< allowedHoursEnd)
        }

        // Generate labels for each hour
        hoursSelector.cellLabels = displayedHours.map { labelHour($0) }
    }

    /// Set the selected hours
    func setSelectedHours(_ hours: [Int]) {
        let validHours = hours.filter {
            hourWithinRange($0, start: allowedHoursStart, end: allowedHoursEnd)
        }

        if validHours.isEmpty {
            // Select all hours within the allowed range
            let allIndices = Set(0 ..< displayedHours.count)
            hoursSelector.setSelectedIndices(allIndices)
        } else {
            // Convert hours to indices
            var indices = Set<Int>()
            for hour in validHours {
                if let index = displayedHours.firstIndex(of: hour) {
                    indices.insert(index)
                }
            }
            hoursSelector.setSelectedIndices(indices)
        }
    }

    /// Get the list of selected hours
    func selectedHoursList() -> [Int] {
        let selectedIndices = hoursSelector.selectedIndicesList()
        return selectedIndices.map { displayedHours[$0] }
    }
}
