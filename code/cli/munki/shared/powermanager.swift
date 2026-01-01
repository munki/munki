//
//  powermanager.swift
//  munki
//
//  Created by Greg Neagle on 8/6/24.
//
//  Copyright 2024-2026 The Munki Project. All rights reserved.
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

/// Returns the current power source
func getPowerSource() -> String? {
    guard
        let powerSourcesInfo = IOPSCopyPowerSourcesInfo()?.takeRetainedValue(),
        let powerSource = IOPSGetProvidingPowerSourceType(powerSourcesInfo)?.takeRetainedValue()
    else {
        return nil
    }
    return powerSource as String
}

/// Returns a boolean to indicate if the machine is on AC power
func onACPower() -> Bool {
    return getPowerSource() == kIOPMACPowerKey
}

/// Returns a boolean to indicate if the machine is on battery power
func onBatteryPower() -> Bool {
    return getPowerSource() == kIOPMBatteryPowerKey
}

/// Returns battery charge percentage
func getBatteryPercentage() -> Int {
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

/// Determine if this Mac has a power source of 'InternalBattery'
func hasInternalBattery() -> Bool {
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

/// Get the current PowerManager assertions. Returns a dictionary.
func getPMAssertions() -> [String: [String]] {
    var assertions = [String: [String]]()
    var assertionsByProcess: Unmanaged<CFDictionary>?
    if IOPMCopyAssertionsByProcess(&assertionsByProcess) == kIOReturnSuccess,
       let assertionsByProcess
    {
        let cfd = assertionsByProcess.takeUnretainedValue()
        let d = cfd as! [CFNumber: [[String: Any]]]
        for aList in d.values {
            for item in aList {
                if let processName = item["Process Name"] as? String,
                   let assertionType = item["AssertionTrueType"] as? String
                {
                    if assertions[processName] == nil {
                        assertions[processName] = [assertionType]
                    } else {
                        assertions[processName] = assertions[processName]! + [assertionType]
                    }
                }
            }
        }
    }
    return assertions
}

// MARK: no sleep assertions

/// Uses IOKit functions to prevent sleep.
func assertIOPM(name: CFString, reason: CFString) -> IOPMAssertionID? {
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

/// Uses IOKit functions to prevent idle sleep.
func assertNoIdleSleep(reason: String) -> IOPMAssertionID? {
    let kIOPMAssertPreventUserIdleSystemSleep = "PreventUserIdleSystemSleep" as CFString
    return assertIOPM(name: kIOPMAssertPreventUserIdleSystemSleep, reason: reason as CFString)
}

/// Uses IOKit functions to prevent display sleep.
func assertNoDisplaySleep(reason: String) -> IOPMAssertionID? {
    let kIOPMAssertPreventUserDisplaySystemSleep = "PreventUserDisplaySystemSleep" as CFString
    return assertIOPM(name: kIOPMAssertPreventUserDisplaySystemSleep, reason: reason as CFString)
}

/// Clears a sleep assertion if any
func removeNoSleepAssertion(_ id: IOPMAssertionID?) {
    if let id {
        IOPMAssertionRelease(id)
    }
}

/// A simple object that prevents idle sleep and automagically
/// removes the assertion when the object goes out of scope or is deleted
class Caffeinator {
    var assertionID: IOPMAssertionID?

    init(reason: String = "") {
        DisplayAndLog.main.info("Preventing idle sleep")
        assertionID = assertNoIdleSleep(reason: reason)
    }

    deinit {
        DisplayAndLog.main.info("Allowing idle sleep")
        removeNoSleepAssertion(assertionID)
    }
}
