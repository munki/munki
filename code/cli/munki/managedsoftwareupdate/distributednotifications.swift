//
//  distributednotifications.swift
//  munki
//
//  Created by Greg Neagle on 8/28/24.
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

func sendDistributedNotification(_ name: NSNotification.Name, userInfo: PlistDict? = nil) {
    // Sends a NSDistributedNotification
    let dnc = DistributedNotificationCenter.default()
    dnc.postNotificationName(
        name,
        object: nil,
        userInfo: userInfo,
        options: [.deliverImmediately, .postToAllSessions]
    )
}

func sendUpdateNotification() {
    // Sends an update notification via NSDistributedNotificationCenter
    // Managed Software Center.app and MunkiStatus.app register to receive these
    // events.
    let name = NSNotification.Name(rawValue: "com.googlecode.munki.managedsoftwareupdate.updateschanged")
    let userInfo = ["pid": ProcessInfo().processIdentifier]
    sendDistributedNotification(name, userInfo: userInfo)
}

func sendDockUpdateNotification() {
    // Sends an update notification via NSDistributedNotificationCenter
    // Managed Software Center.app's dock tile plugin registers to receive these
    // events.
    let name = NSNotification.Name(rawValue: "com.googlecode.munki.managedsoftwareupdate.dock.updateschanged")
    let userInfo = ["pid": ProcessInfo().processIdentifier]
    sendDistributedNotification(name, userInfo: userInfo)
}

func sendStartNotification() {
    // Sends a start notification via NSDistributedNotificationCenter
    let name = NSNotification.Name(rawValue: "com.googlecode.munki.managedsoftwareupdate.started")
    let userInfo = ["pid": ProcessInfo().processIdentifier]
    sendDistributedNotification(name, userInfo: userInfo)
}

func sendEndedNotification() {
    // Sends an ended notification via NSDistributedNotificationCenter
    let name = NSNotification.Name(rawValue: "com.googlecode.munki.managedsoftwareupdate.ended")
    let userInfo = ["pid": ProcessInfo().processIdentifier]
    sendDistributedNotification(name, userInfo: userInfo)
}
