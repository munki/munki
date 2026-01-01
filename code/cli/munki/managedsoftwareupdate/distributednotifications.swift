//
//  distributednotifications.swift
//  munki
//
//  Created by Greg Neagle on 8/28/24.
//  Copyright 2024-2026 The Munki Project.
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

/// Sends a NSDistributedNotification
func sendDistributedNotification(_ name: NSNotification.Name, userInfo: PlistDict? = nil) {
    let dnc = DistributedNotificationCenter.default()
    dnc.postNotificationName(
        name,
        object: nil,
        userInfo: userInfo,
        options: [.deliverImmediately, .postToAllSessions]
    )
}

/// Sends an update notification via NSDistributedNotificationCenter
/// Managed Software Center.app and MunkiStatus.app register to receive these events.
func sendUpdateNotification() {
    let name = NSNotification.Name(rawValue: "com.googlecode.munki.managedsoftwareupdate.updateschanged")
    let userInfo = ["pid": ProcessInfo().processIdentifier]
    sendDistributedNotification(name, userInfo: userInfo)
}

/// Sends an update notification via NSDistributedNotificationCenter
/// Managed Software Center.app's dock tile plugin registers to receive these events.
func sendDockUpdateNotification() {
    let name = NSNotification.Name(rawValue: "com.googlecode.munki.managedsoftwareupdate.dock.updateschanged")
    let userInfo = ["pid": ProcessInfo().processIdentifier]
    sendDistributedNotification(name, userInfo: userInfo)
}

/// Sends a start notification via NSDistributedNotificationCenter
func sendStartNotification() {
    let name = NSNotification.Name(rawValue: "com.googlecode.munki.managedsoftwareupdate.started")
    let userInfo = ["pid": ProcessInfo().processIdentifier]
    sendDistributedNotification(name, userInfo: userInfo)
}

/// Sends an ended notification via NSDistributedNotificationCenter
func sendEndedNotification() {
    let name = NSNotification.Name(rawValue: "com.googlecode.munki.managedsoftwareupdate.ended")
    let userInfo = ["pid": ProcessInfo().processIdentifier]
    sendDistributedNotification(name, userInfo: userInfo)
}
