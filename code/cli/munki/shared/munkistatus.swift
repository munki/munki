//
//  munkistatus.swift
//  munki
//
//  Created by Greg Neagle on 8/6/24.
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

/// a Singleton class that contains our current status for display
class MunkiStatusInfo {
    static let shared = MunkiStatusInfo()

    var status: PlistDict

    private init() {
        status = [
            "message": "",
            "detail": "",
            "percent": -1,
            "stop_button_visible": true,
            "stop_button_enabled": true,
            "command": "",
            "pid": ProcessInfo.processInfo.processIdentifier,
        ]
    }
}

/// Uses launchd KeepAlive path so it launches from a launchd agent
/// in the correct context.
/// This is more complicated to set up, but makes Apple (and launchservices) happier.
/// There needs to be a launch agent that is triggered when the launchfile is created;
/// and that launch agent then runs MunkiStatus.app.
/// Note: this only works at the loginwindow, since the LaunchAgent is only
/// loaded at the loginwindow.
func munkiStatusLaunch() {
    let launchfile = "/var/run/com.googlecode.munki.MunkiStatus"
    if FileManager.default.createFile(atPath: launchfile, contents: nil) {
        usleep(1_000_000)
        try? FileManager.default.removeItem(atPath: launchfile)
    } else {
        printStderr("Couldn't create launchpath \(launchfile)")
    }
}

/// Post a status notification
func postStatusNotification() {
    let NOTIFICATION_NAME = "com.googlecode.munki.managedsoftwareupdate.statusUpdate"
    let dnc = DistributedNotificationCenter.default()
    dnc.postNotificationName(
        NSNotification.Name(rawValue: NOTIFICATION_NAME),
        object: nil,
        userInfo: MunkiStatusInfo.shared.status,
        options: [.deliverImmediately, .postToAllSessions]
    )
}

/// Sets the status message.
func munkiStatusMessage(_ text: String) {
    MunkiStatusInfo.shared.status["message"] = text
    postStatusNotification()
}

/// Sets the detail text.
func munkiStatusDetail(_ text: String) {
    MunkiStatusInfo.shared.status["detail"] = text
    postStatusNotification()
}

func munkiStatusPercent(_ percentage: Int) {
    MunkiStatusInfo.shared.status["percent"] = percentage
    postStatusNotification()
}

/// Sets the progress indicator to 0-100 percent done.
/// If you pass a negative number, the progress indicator
/// is shown as an indeterminate indicator.
func munkiStatusHideStopButton() {
    // Tells MunkiStatus/MSC to hide the stop button.
    MunkiStatusInfo.shared.status["stop_button_visible"] = false
    postStatusNotification()
}

/// Tells MunkiStatus/MSC to show the stop button.
func munkiStatusShowStopButton() {
    MunkiStatusInfo.shared.status["stop_button_visible"] = true
    postStatusNotification()
}

/// Tells MunkiStatus/MSC to disable the stop button.
func munkiStatusDisableStopButton() {
    MunkiStatusInfo.shared.status["stop_button_enabled"] = false
    postStatusNotification()
}

/// Tells MunkiStatus/MSC to enable the stop button.
func munkiStatusEnableStopButton() {
    MunkiStatusInfo.shared.status["stop_button_enabled"] = true
    postStatusNotification()
}

/// Tells MunkiStatus to bring its window to the front
func munkiStatusActivate() {
    MunkiStatusInfo.shared.status["command"] = "activate"
    postStatusNotification()
    // commands should be cleared after they are sent
    MunkiStatusInfo.shared.status["command"] = ""
}

/// Tells MunkiStatus to quit
func munkiStatusQuit() {
    MunkiStatusInfo.shared.status["command"] = "quit"
    postStatusNotification()
    // commands should be cleared after they are sent
    MunkiStatusInfo.shared.status["command"] = ""
}

/// Tells MunkiStatus to display a restart alert
func munkiStatusRestartAlert() {
    MunkiStatusInfo.shared.status["command"] = "showRestartAlert"
    postStatusNotification()
    // commands should be cleared after they are sent
    MunkiStatusInfo.shared.status["command"] = ""
}
