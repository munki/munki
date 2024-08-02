//
//  main.swift
//  app_usage_monitor
//
//  Created by Greg Neagle on 8/1/24.
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

import AppKit
import Foundation

enum AppUsageClientError: Error {
    case socketError(code: UNIXDomainSocketClientErrorCode, description: String)
    case taskError(description: String)
}

class AppUsageClient {
    // handles communication with appusaged daemon

    let APPUSAGED_SOCKET = "/var/run/appusaged"
    let socket = UNIXDomainSocketClient()

    func connect() throws {
        // Connect to appusaged
        socket.connect(to: APPUSAGED_SOCKET)
        if socket.errCode != .noError {
            throw AppUsageClientError.socketError(
                code: socket.errCode,
                description: "Failed to connect to \(APPUSAGED_SOCKET)"
            )
        }
    }

    func sendRequest(_ request: PlistDict) throws -> String {
        // Send a request to appusaged
        let requestStr = try plistToString(request)
        socket.write(requestStr)
        if socket.errCode != .noError {
            throw AppUsageClientError.socketError(
                code: socket.errCode,
                description: "Failed to write to \(APPUSAGED_SOCKET)"
            )
        }
        let reply = socket.read(timeout: 1)
        if reply.isEmpty {
            return "ERROR:No reply"
        }
        return reply.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    func disconnect() {
        // Disconnect from appusaged
        socket.close()
    }

    func process(_ request: PlistDict) throws -> String {
        // Send a request and return the result
        try connect()
        let result = try sendRequest(request)
        disconnect()
        return result
    }
}

class NotificationHandler: NSObject {
    // A subclass of NSObject to handle workspace notifications

    let usage = AppUsageClient()
    let wsNotificationCenter = NSWorkspace.shared.notificationCenter
    let distributedNotificationCenter = DistributedNotificationCenter.default()

    override init() {
        super.init()
        wsNotificationCenter.addObserver(
            self,
            selector: #selector(didLaunchApplicationNotification(_:)),
            name: NSWorkspace.didLaunchApplicationNotification,
            object: nil
        )
        wsNotificationCenter.addObserver(
            self,
            selector: #selector(didActivateApplicationNotification(_:)),
            name: NSWorkspace.didActivateApplicationNotification,
            object: nil
        )
        wsNotificationCenter.addObserver(
            self,
            selector: #selector(didTerminateApplicationNotification(_:)),
            name: NSWorkspace.didTerminateApplicationNotification,
            object: nil
        )
        wsNotificationCenter.addObserver(
            self,
            selector: #selector(requestedItemForInstall(_:)),
            name: NSNotification.Name("com.googlecode.munki.managedsoftwareupdate.installrequest"),
            object: nil
        )
    }

    deinit {
        // Unregister for all the notifications we registered for
        wsNotificationCenter.removeObserver(self)
        distributedNotificationCenter.removeObserver(self)
    }

    func getInfoDictForApp(_ appObject: NSRunningApplication) -> [String: String] {
        // Returns a dict with info about an application.
        // Args:
        //     appObject: NSRunningApplication object
        // Returns:
        //     appDict: ["bundle_id": str,
        //               "path": str,
        //               "version": str]
        var bundleID = ""
        var appPath = ""
        var appVersion = "0"

        if let url = appObject.bundleURL {
            appPath = url.path()
        }
        if let _bundleID = appObject.bundleIdentifier {
            bundleID = _bundleID
        } else if !appPath.isEmpty {
            // use the base filename
            bundleID = (appPath as NSString).lastPathComponent
        }
        if !appPath.isEmpty {
            // try to get the version from the bundle's plist
            if let appInfoPlist = NSDictionary(
                contentsOfFile: (appPath as NSString).appendingPathComponent("Contents/Info.plist")) as? PlistDict
            {
                appVersion = appInfoPlist["CFBundleShortVersionString"] as? String ?? appInfoPlist["CFBundleVersion"] as? String ?? "0"
            }
        }
        return ["bundle_id": bundleID,
                "path": appPath,
                "version": appVersion]
    }

    func process(event: String, notification: NSNotification) {
        if let appObject = notification.userInfo?["NSWorkspaceApplicationKey"] as? NSRunningApplication {
            let appDict = getInfoDictForApp(appObject)
            let _ = try? usage.process(
                ["event": event,
                 "app_dict": appDict]
            )
        }
    }

    @objc func didLaunchApplicationNotification(_ notification: NSNotification) {
        // Handle NSWorkspaceDidLaunchApplicationNotification
        process(event: "launch", notification: notification)
    }

    @objc func didActivateApplicationNotification(_ notification: NSNotification) {
        // Handle NSWorkspaceDidActivateApplicationNotification
        process(event: "activate", notification: notification)
    }

    @objc func didTerminateApplicationNotification(_ notification: NSNotification) {
        // Handle NSWorkspaceDidTerminateApplicationNotification
        process(event: "quit", notification: notification)
    }

    @objc func requestedItemForInstall(_ notification: NSNotification) {
        // Handle com.googlecode.munki.managedsoftwareupdate.installrequest
        if let installInfo = notification.userInfo as? [String: String] {
            let _ = try? usage.process(
                ["event": installInfo["event"] ?? "unknown",
                 "name": installInfo["name"] ?? "unknown",
                 "version": installInfo["version"] ?? "unknown"]
            )
        }
    }
}

func main() {
    // Initialize our handler object and let NSWorkspace's notification center
    // know we are interested in notifications
    let notificationHandler = NotificationHandler()

    while true {
        // listen for notifications forever
        // give time to the runloop so we can actually get notifications
        RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.1))
    }
}

// run it!
main()
