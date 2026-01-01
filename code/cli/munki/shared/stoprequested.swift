//
//  stoprequested.swift
//  munki
//
//  Created by Greg Neagle on 8/7/24.
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

/// Returns true if requested a stop (generally by clicking a cancel or stop button in the GUI)
func stopRequested() -> Bool {
    class StopRequested {
        // an elaborate way to avoid a naked global variable
        static let shared = StopRequested()

        var stopRequested = false

        private init() {
            //
        }
    }
    if StopRequested.shared.stopRequested {
        return true
    }
    let stopRequestFlag = "/private/tmp/com.googlecode.munki.managedsoftwareupdate.stop_requested"
    if pathExists(stopRequestFlag) {
        StopRequested.shared.stopRequested = true
        DisplayAndLog.main.info("### User stopped session ###")
        try? FileManager.default.removeItem(atPath: stopRequestFlag)
        return true
    }
    return false
}
