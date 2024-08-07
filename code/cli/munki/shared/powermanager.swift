//
//  powermanager.swift
//  munki
//
//  Created by Greg Neagle on 8/6/24.
//
//  Copyright 2024 Greg Neagle.
//
//  Licensed under the Apache License, Version 2.0 (the "License");
//  you may not use this file except in compliance with the License.
//  You may obtain a copy of the License at
//
//       https://www.apache.org/licenses/LICENSE-2.0
//
//  Unless required by applicable law or agreed to in writing, software
//  distributed under the License is distributed on an "AS IS" BASIS,
//  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
//  See the License for the specific language governing permissions and
//  limitations under the License.

import Foundation
import IOKit.ps
import IOKit.pwr_mgt

// The IOKit Power Source and Power Management APIs are not very Swift-friendly.
// This post https://forums.developer.apple.com/forums/thread/712711 helped with
// getting these relatively safe

func getPowerSource() -> String? {
    guard
        let powerSourcesInfo = IOPSCopyPowerSourcesInfo()?.takeRetainedValue(),
        let powerSource = IOPSGetProvidingPowerSourceType(powerSourcesInfo)?.takeRetainedValue()
    else {
        return nil
    }
    return powerSource as String
}

func onACPower() -> Bool {
    // Returns a boolean to indicate if the machine is on AC power
    return getPowerSource() == kIOPMACPowerKey
}

func onBatteryPower() -> Bool {
    // Returns a boolean to indicate if the machine is on battery power
    return getPowerSource() == kIOPMBatteryPowerKey
}

func getBatteryPercentage() -> Int {
    // Returns battery charge percentage
    guard
        let psi = IOPSCopyPowerSourcesInfo()?.takeRetainedValue(),
        let cf = IOPSCopyPowerSourcesList(psi)?.takeRetainedValue()
    else {
        return 0
    }
    let psl = cf as [CFTypeRef]
    for ps in psl {
        guard
            let cfd = IOPSGetPowerSourceDescription(psi, ps)?.takeUnretainedValue()
        else {
            return 0
        }
        let d = cfd as! [String: Any]
        guard
            let psTypeStr = d[kIOPSTypeKey] as? String
        else {
            return 0
        }
        if psTypeStr == "InternalBattery" {
            guard
                let psCapacity = d[kIOPSCurrentCapacityKey] as? Int
            else {
                return 0
            }
            return psCapacity
        }
    }
    return 0
}

func hasInternalBattery() -> Bool {
    // Determine if this Mac has a power source of 'InternalBattery'
    guard
        let psi = IOPSCopyPowerSourcesInfo()?.takeRetainedValue(),
        let cf = IOPSCopyPowerSourcesList(psi)?.takeRetainedValue()
    else {
        return false
    }
    let psl = cf as [CFTypeRef]
    for ps in psl {
        guard
            let cfd = IOPSGetPowerSourceDescription(psi, ps)?.takeUnretainedValue()
        else {
            return false
        }
        let d = cfd as! [String: Any]
        guard
            let psTypeStr = d[kIOPSTypeKey] as? String
        else {
            return false
        }
        if psTypeStr == "InternalBattery" {
            return true
        }
    }
    return false
}

// MARK: no sleep assertions

func assertIOPM(name: CFString, reason: CFString) -> IOPMAssertionID? {
    // Uses IOKit functions to prevent sleep.
    var assertionID = IOPMAssertionID(0)
    let success = IOPMAssertionCreateWithName(
        name,
        IOPMAssertionLevel(kIOPMAssertionLevelOn),
        reason,
        &assertionID
    )
    if success == kIOReturnSuccess {
        return assertionID
    }
    return nil
}

func assertNoIdleSleep(reason: String) -> IOPMAssertionID? {
    // Uses IOKit functions to prevent idle sleep.
    let kIOPMAssertPreventUserIdleSystemSleep = "PreventUserIdleSystemSleep" as CFString
    return assertIOPM(name: kIOPMAssertPreventUserIdleSystemSleep, reason: reason as CFString)
}

func assertNoDisplaySleep(reason: String) -> IOPMAssertionID? {
    // Uses IOKit functions to prevent idle sleep.
    let kIOPMAssertPreventUserDisplaySystemSleep = "PreventUserDisplaySystemSleep" as CFString
    return assertIOPM(name: kIOPMAssertPreventUserDisplaySystemSleep, reason: reason as CFString)
}

func removeNoSleepAssertion(_ id: IOPMAssertionID?) {
    if let id {
        IOPMAssertionRelease(id)
    }
}

class Caffeinator {
    // A simple object that prevents idle sleep and automagically
    // removes the assertion when the object goes out of scope or is deleted

    var assertionID: IOPMAssertionID?

    init(reason: String = "Munki is installing software") {
        displayInfo("Preventing idle sleep")
        assertionID = assertNoIdleSleep(reason: reason)
    }

    deinit {
        displayInfo("Allowing idle sleep")
        removeNoSleepAssertion(assertionID)
    }
}
