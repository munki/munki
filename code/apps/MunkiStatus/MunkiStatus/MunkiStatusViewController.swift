//
//  MunkiStatusViewController.swift
//  MunkiStatus
//
//  Created by Greg Neagle on 5/18/18.
//  Copyright © 2018-2026 The Munki Project. All rights reserved.
//

import Cocoa

class MunkiStatusViewController: NSViewController {

    @IBOutlet weak var messageField: NSTextField!
    @IBOutlet weak var detailField: NSTextField!
    @IBOutlet weak var progressBar: NSProgressIndicator!
    @IBOutlet weak var stopButton: NSButton!
    
    var receivingNotifications = false
    var restartAlertDismissed = false
    var gotStatusUpdate = false
    var timeoutCounter = 6
    var sawProcess = false
    var timer: Timer? = nil
    
    let STOP_REQUEST_FLAG = "/private/tmp/com.googlecode.munki.managedsoftwareupdate.stop_requested"
    
    override func viewDidLoad() {
        if #available(OSX 10.10, *) {
            super.viewDidLoad()
        } else {
            // Fallback on earlier versions
        }
        // Do view setup here.
        if atLoginWindow() {
            view.window?.canBecomeVisibleWithoutLogin = true
            view.window?.level = statusWindowLevel
        }
        messageField.stringValue =
            NSLocalizedString("Starting...", comment: "managedsoftwareupdate message")
        progressBar.isIndeterminate = true
        progressBar.usesThreadedAnimation = true
        progressBar.startAnimation(self)
        registerForNotifications()
        view.window?.orderFrontRegardless()
        timer = Timer.scheduledTimer(timeInterval: 5.0,
                                     target: self,
                                     selector: #selector(self.checkProcess),
                                     userInfo: nil,
                                     repeats: true)
    }
    
    @IBAction func stopButtonClicked(_ sender: Any) {
        // Deactivate the Stop button and write a flag file
        // to tell managedsoftwareupdate to stop
        stopButton.state = NSControl.StateValue.on
        stopButton.isEnabled = false
        FileManager.default.createFile(atPath: STOP_REQUEST_FLAG, contents: nil, attributes: nil)
    }
    
    func cleanUpStatusSession() {
        // Clean up before we exit
        unregisterForNotifications()
        if timer != nil {
            timer!.invalidate()
            timer = nil
        }
    }
    
    func statusSessionFailed(_ sessionResult: String) {
        print("status session failed: \(sessionResult)")
        cleanUpStatusSession()
        NSApp.terminate(self)
    }
    
   
    @objc func checkProcess() {
        // Monitors managedsoftwareupdate process for failure to start
        // or unexpected exit, so we're not waiting around forever if
        // managedsoftwareupdate isn't running.
        
        print("checkProcess timer fired")
        
        if (haveElCapPolicyBanner && atLoginWindow()) {
            // we're at the loginwindow, there is a PolicyBanner, and we're
            // running under 10.11+. Make sure we're in the front.
            NSApp.activate(ignoringOtherApps: true)
        }
        
        if gotStatusUpdate {
            // we got a status update since we last checked; no need to
            // check the process table
            timeoutCounter = 6
            sawProcess = true
            // clear the flag so we have to get another status update
            gotStatusUpdate = false
        } else if managedsoftwareupdateInstanceRunning() {
            print("managedsoftwareupdate is running")
            timeoutCounter = 6
            sawProcess = true
        } else {
            print("managedsoftwareupdate is NOT running")
            timeoutCounter -= 1
        }
        if timeoutCounter == 0 {
            if sawProcess {
                statusSessionFailed("process unexpectedly quit")
            } else {
                statusSessionFailed("process never started")
            }
        }
    }
    
    func setPercentageDone(_ percentish: Any?) {
        // Set progress indicator to display percent done
        var percent = -1.0
        // TO-DO: there's got to be a more elegant way of doing this
        if percentish != nil {
            if percentish! is String {
                percent = Double(percentish! as! String) ?? -1.0
            } else if percentish! is Double {
                percent = percentish! as! Double
            }
        }
        if percent < 0.0 {
            if !(progressBar.isIndeterminate) {
                progressBar.isIndeterminate = true
                progressBar.startAnimation(self)
            }
        } else {
            if progressBar.isIndeterminate {
                progressBar.stopAnimation(self)
                progressBar.isIndeterminate = false
            }
            progressBar.doubleValue = percent
        }
    }

    func doRestartAlert() {
        let a = NSAlert()
        a.messageText = NSLocalizedString("Restart Required", comment: "")
        a.informativeText = NSLocalizedString(
            "Software installed or removed requires a restart. You will have a chance to save open documents.",
            comment: "")
        a.addButton(withTitle: NSLocalizedString("Restart", comment: ""))
        
        a.beginSheetModal(for: self.view.window!, completionHandler: { (modalResponse) -> Void in
            if modalResponse == .alertFirstButtonReturn {
                self.restartAlertDismissed = true
                //munkiRestartNow()
            }
        })
    }
    
    func getLocalizedText(_ text: String) -> String {
        return Bundle.main.localizedString(forKey: text, value: text, table: nil)
    }
    
    @objc func updateStatus(_ notification: Notification) {
        // Called when we get a
        // com.googlecode.munki.managedsoftwareupdate.statusUpdate notification;
        // update our status display with information from the notification
        gotStatusUpdate = true
        let info = notification.userInfo
        if info == nil {
            return
        }
        
        if (info!.keys.contains("message")) {
            if let message = info!["message"] as? String {
                messageField.stringValue = getLocalizedText(message)
            }
        }
        if (info!.keys.contains("detail")) {
            if let detail = info!["detail"] as? String {
                detailField.stringValue = getLocalizedText(detail)
            }
        }
        if (info!.keys.contains("percent")) {
            setPercentageDone(info!["percent"])
        }
        if stopButton.state == NSControl.StateValue.off {
            if (info!.keys.contains("stop_button_visible")) {
                if let visible = info!["stop_button_visible"] as? Bool {
                    stopButton.isHidden = !(visible)
                }
            }
            if (info!.keys.contains("stop_button_enabled")) {
                if let enabled = info!["stop_button_enabled"] as? Bool {
                    stopButton.isEnabled = enabled
                }
            }
        }
        if (info!.keys.contains("command")) {
            if let command = info!["command"] as? String {
                if command == "activate" {
                    NSApp.activate(ignoringOtherApps: true)
                    view.window?.orderFrontRegardless()
                } else if command == "showRestartAlert" {
                    // clean up timer
                    if timer != nil {
                        timer!.invalidate()
                        timer = nil
                    }
                    doRestartAlert()
                } else if command == "quit" {
                    cleanUpStatusSession()
                    NSApp.terminate(self)
                }
            }
        }
    }
    
    func registerForNotifications() {
        // Register for notification messages
        let dnc = DistributedNotificationCenter.default()
        dnc.addObserver(
            self,
            selector: #selector(self.updateStatus(_:)),
            name: NSNotification.Name(rawValue: "com.googlecode.munki.managedsoftwareupdate.statusUpdate"),
            object: nil,
            suspensionBehavior: .deliverImmediately)
        
        receivingNotifications = true
    }
    
    func unregisterForNotifications() {
        // Tell the DistributedNotificationCenter to stop sending us notifications
        DistributedNotificationCenter.default.removeObserver(self)
        // set self.receiving_notifications to False so our process monitoring
        // thread will exit
        receivingNotifications = false
    }
    
}
