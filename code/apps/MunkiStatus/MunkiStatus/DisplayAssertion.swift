//
//  DisplayAssertion.swift
//  MunkiStatus
//
//  Created by Christopher A Grande on 5/9/25.
//  Copyright © 2025-2026 The Munki Project. All rights reserved.
//

import IOKit.pwr_mgt

var displaySleepAssertionID: IOPMAssertionID?

func createNoDisplaySleepAssertion() {
    let threshold = isAppleSilicon() ? 30 : 50
    if onACPower() || getBatteryPercentage() >= threshold {
        var assertionID: IOPMAssertionID = 0
        let reasonForActivity = "Prevent display sleep during Munki bootstrapping" as CFString
        
        let result = IOPMAssertionCreateWithName(kIOPMAssertionTypeNoDisplaySleep as CFString,
                                                 IOPMAssertionLevel(kIOPMAssertionLevelOn),
                                                 reasonForActivity,
                                                 &assertionID)
        if result == kIOReturnSuccess {
            displaySleepAssertionID = assertionID
            print("NoDisplaySleep assertion created with ID: \(assertionID)")
        } else {
            print("Failed to create NoDisplaySleep assertion. Error code: \(result)")
        }
    } else {
        print("Display sleep assertion not created, not enough battery power.")
    }
}

func releaseDisplaySleepAssertion() {
    guard let assertionID = displaySleepAssertionID else {
        print("No assertion to release.")
        return
    }

    let result = IOPMAssertionRelease(assertionID)

    if result == kIOReturnSuccess {
        print("NoDisplaySleep assertion released.")
        displaySleepAssertionID = nil
    } else {
        print("Failed to release NoDisplaySleep assertion. Error code: \(result)")
    }
}
