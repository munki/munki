//
//  power.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 7/16/18.
//  Copyright © 2018-2026 The Munki Project. All rights reserved.
//

import Foundation
import IOKit.ps

func onACPower() -> Bool {
    // Returns a boolean to indicate if the machine is on AC power
    let snapshot = IOPSCopyPowerSourcesInfo().takeRetainedValue()
    let powerSource = IOPSGetProvidingPowerSourceType(snapshot).takeRetainedValue()
    return powerSource as String == kIOPSACPowerValue
}

func onBatteryPower() -> Bool {
    // Returns a boolean to indicate if the machine is on battery power
    let snapshot = IOPSCopyPowerSourcesInfo().takeRetainedValue()
    let powerSource = IOPSGetProvidingPowerSourceType(snapshot).takeRetainedValue()
    return powerSource as String == kIOPSBatteryPowerValue
}

func getBatteryPercentage() -> Int {
    // Returns battery charge percentage (0-100)
    let snapshot = IOPSCopyPowerSourcesInfo().takeRetainedValue()
    let sources = IOPSCopyPowerSourcesList(snapshot).takeRetainedValue() as Array
    for source in sources {
        if let description = IOPSGetPowerSourceDescription(snapshot, source).takeUnretainedValue() as? [String: Any] {
            if description["Type"] as? String == kIOPSInternalBatteryType {
                return description[kIOPSCurrentCapacityKey] as? Int ?? 0
            }
        }
    }
    return 0
}
