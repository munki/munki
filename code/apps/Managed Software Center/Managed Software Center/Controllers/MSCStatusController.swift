//
//  MSCStatusController.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 7/11/18.
//  Copyright © 2018-2026 The Munki Project. All rights reserved.
//

import Cocoa
import WebKit

class MSCStatusController: NSObject {
    
    @IBOutlet weak var statusWindowController: MainWindowController!
    
    // Handles status messages from managedsoftwareupdate
    var session_started = false
    var got_status_update = false
    var timer: Timer? = nil
    
    var _status_restartAlertDismissed = false
    var _status_stopBtnDisabled = false
    var _status_stopBtnHidden = false
    var _status_stopBtnState = 0
    var _status_message = ""
    var _status_detail = ""
    var _status_percent = -1.0
    var _status_stopBtnPressed = false
    var receiving_notifications = false
    var timeout_counter = 0
    var saw_process = false
    
    func registerForNotifications() {
        // Register for notification messages
        let center = DistributedNotificationCenter.default()
        center.addObserver(self,
                           selector: #selector(self.updateStatus),
                           name: NSNotification.Name(
                                rawValue: "com.googlecode.munki.managedsoftwareupdate.statusUpdate"),
                           object: nil,
                           suspensionBehavior: .deliverImmediately)
        receiving_notifications = true
    }
    
    func unregisterForNotifications() {
        // Tell the DistributedNotificationCenter to stop sending us notifications
        DistributedNotificationCenter.default().removeObserver(self)
        // set self.receiving_notifications to False so our process monitoring
        // thread will exit
        receiving_notifications = false
    }
    
    func startMunkiStatusSession() {
        // Initialize things for monitoring a managedsoftwareupdate session
        initStatusSession()
        session_started = true
        // start our process monitor timer so we can be notified about
        // process failure
        timeout_counter = 6
        saw_process = false
        timer = Timer.scheduledTimer(timeInterval: 5.0,
                                     target: self,
                                     selector: #selector(self.checkProcess),
                                     userInfo: nil,
                                     repeats: true)
    }
    
    @objc func checkProcess() {
        // Monitors managedsoftwareupdate process for failure to start
        // or unexpected exit, so we're not waiting around forever if
        // managedsoftwareupdate isn't running.
        let NEVER_STARTED = -2
        let UNEXPECTEDLY_QUIT = -1
        if !session_started {
            return
        }
        if got_status_update {
            // we got a status update since we last checked; no need to
            // check the process table
            timeout_counter = 6
            saw_process = true
            // clear the flag so we have to get another status update
            got_status_update = false
        } else if managedsoftwareupdateInstanceRunning() {
            timeout_counter = 6
            saw_process = true
        } else {
            msc_debug_log("managedsoftwareupdate not running...")
            timeout_counter -= 1
        }
        if timeout_counter == 0 {
            msc_debug_log("Timed out waiting for managedsoftwareupdate.")
            if saw_process {
                sessionEnded(UNEXPECTEDLY_QUIT)
            } else {
                sessionEnded(NEVER_STARTED)
            }
        }
    }
    
    func sessionStarted() -> Bool {
        // Accessor method
        return session_started
    }
    
    func sessionEnded(_ result: Int) {
        // clean up after a managedsoftwareupdate session ends
        if let uTimer = timer {
            uTimer.invalidate()
            timer = nil
        }
        cleanUpStatusSession()
        // tell the window controller the update session is done
        statusWindowController.munkiStatusSessionEnded(withStatus: result, errorMessage: "")
    }
    
    @objc func updateStatus(_ notification: NSNotification) {
        // Got update status notification from managedsoftwareupdate
        msc_debug_log("Got munkistatus update notification")
        got_status_update = true
        guard let info = notification.userInfo as? [String: Any] else {
            msc_debug_log("No userInfo in notification")
            return
        }
        msc_debug_log("\(info)")
        if let message = info["message"] as? String {
            setMessage(message)
        }
        if let detail = info["detail"] as? String {
            setDetail(detail)
        }
        if let percent = info["percent"] {
            setPercentageDone(percent)
        }
        if let stop_button_visible = info["stop_button_visible"] as? Bool {
            if stop_button_visible {
                showStopButton()
            } else {
                hideStopButton()
            }
        }
        if let stop_button_enabled = info["stop_button_enabled"] as? Bool {
            if stop_button_enabled {
                enableStopButton()
            } else {
                disableStopButton()
            }
        }
        let command = info["command"] as? String ?? ""
        if !session_started && !["showRestartAlert", "quit"].contains(command) {
            // we got a status message but we didn't start the session
            // so switch to the right mode
            startMunkiStatusSession()
        }
        if !command.isEmpty {
            msc_debug_log("Received command: \(command)")
        }
        if command == "activate" {
            // do nothing
        } else if command == "showRestartAlert" {
            if session_started {
                sessionEnded(0)
            }
            doRestartAlert()
        } else if command == "quit" {
            sessionEnded(0)
        }
    }
    
    // required status methods

    func initStatusSession() {
        // Initialize the main window for update status
        statusWindowController._update_in_progress = true
        statusWindowController.displayUpdatesProgressSpinner(true)
        if statusWindowController.currentPageIsUpdatesPage() {
            //statusWindowController.makeUsUnobnoxious()
            statusWindowController.load_page("updates.html")
            statusWindowController.displayUpdateCount()
        }
    }
    
    func cleanUpStatusSession() {
        // Clean up after status session ends
        session_started = false
        // stop the progress spinner in the sidebar
        statusWindowController.displayUpdatesProgressSpinner(false)
        // reset all our status variables
        statusWindowController._update_in_progress = false
        _status_stopBtnDisabled = false
        _status_stopBtnHidden = false
        _status_stopBtnState = 0
        _status_message = ""
        _status_detail = ""
        _status_percent = -1.0
    }
    
    func doRestartAlert() {
        // Display a restart alert -- some item just installed or removed
        // requires a restart
        msc_log("MSC", "restart_required")
        _status_restartAlertDismissed = false
        let alert = NSAlert()
        alert.messageText = NSLocalizedString("Restart Required", comment: "Restart Required title")
        alert.informativeText = NSLocalizedString(
            "Software installed or removed requires a restart. You will have a chance to save open documents.",
            comment:"Restart Required alert detail")
        alert.addButton(withTitle: NSLocalizedString("Restart", comment:"Restart button title"))
        alert.beginSheetModal(for: statusWindowController.window!) { (_) in
            msc_log("MSC", "restart_confirmed")
            self._status_restartAlertDismissed = true
            restartNow()
        }
    }

    func setPercentageDone(_ percentish: Any?) {
        // Display percentage done
        var percent = -1.0
        // TO-DO: there's got to be a more elegant way of doing this
        if percentish != nil {
            if percentish! is String {
                percent = Double(percentish! as! String) ?? -1.0
            } else if percentish! is Double {
                percent = percentish! as! Double
            }
        }
        if percent > 100.0 {
            percent = 100.0
        }
        _status_percent = percent
        // tell JavaScript to update the percentage done
        msc_debug_log("Calling JavaScript updateProgress")
        statusWindowController.webView.evaluateJavaScript("updateProgress(\(percent))")
    }

    func setMessage(_ text: String) {
        // Display main status message
        var messageText = Bundle.main.localizedString(forKey: text, value: text, table: nil)
        _status_message = messageText
        if messageText.isEmpty {
            messageText = "&nbsp;"
        }
        statusWindowController.setInnerHTML(messageText, elementID: "primary-status-text")
    }
    
    func setDetail(_ text: String) {
        // Display status detail
        var detailText = Bundle.main.localizedString(forKey: text, value: text, table: nil)
        _status_detail = detailText
        if detailText.isEmpty {
            detailText = "&nbsp;"
        }
        statusWindowController.setInnerHTML(detailText, elementID: "secondary-status-text")
    }

    func getStopButtonState() -> Bool {
        // Get the state (pressed or not) of the stop button
        // Returns true if pressed; false if not
        return _status_stopBtnPressed
    }
    
    func hideStopButton() {
        // Hide the stop button
        if _status_stopBtnPressed {
            // if the button is pressed, don't hide it
            return
        }
        _status_stopBtnHidden = true
        statusWindowController.webView.evaluateJavaScript("hideStopButton()")
    }
    
    func showStopButton() {
        // Show the stop button
        if _status_stopBtnPressed {
            // if the button is pressed, just exit
            return
        }
        _status_stopBtnHidden = false
        statusWindowController.webView.evaluateJavaScript("showStopButton()")
    }
    
    func disableStopButton() {
        // Disable the stop button
        if _status_stopBtnPressed {
            // if the button is pressed, just exit
            return
        }
        _status_stopBtnHidden = true
        statusWindowController.webView.evaluateJavaScript("disableStopButton()")
    }
    
    func enableStopButton() {
        // Enable the stop button
        if _status_stopBtnPressed {
            // if the button is pressed, just exit
            return
        }
        _status_stopBtnDisabled = false
        statusWindowController.webView.evaluateJavaScript("enableStopButton()")
    }
    
    func getRestartAlertDismissed() -> Bool {
        // Was the restart alert dismissed?'
        return _status_restartAlertDismissed
    }
    
    func morelocalizedstrings() {
        // Some strings that are sent to us from managedsoftwareupdate. By putting
        // them here, genstrings can add them to the Localizable.strings file
        // so localizers will be able to discover them
        
        var  _ = "" // we don't actually use these values at all
        
        // Munki messages
        _ = NSLocalizedString(
            "Starting...", comment: "managedsoftwareupdate message")
        _ = NSLocalizedString(
            "Finishing...", comment: "managedsoftwareupdate message")
        _ = NSLocalizedString(
            "Performing preflight tasks...", comment: "managedsoftwareupdate message")
        _ = NSLocalizedString(
            "Performing postflight tasks...", comment: "managedsoftwareupdate message")
        _ = NSLocalizedString(
            "Checking for available updates...", comment: "managedsoftwareupdate message")
        _ = NSLocalizedString(
            "Checking for additional changes...", comment: "managedsoftwareupdate message")
        _ = NSLocalizedString(
            "Software installed or removed requires a restart.",
            comment: "managedsoftwareupdate message")
        _ = NSLocalizedString(
            "Waiting for network...", comment: "managedsoftwareupdate message")
        _ = NSLocalizedString("Done.", comment: "managedsoftwareupdate message")
        _ = NSLocalizedString(
            "Retrieving list of software for this machine...",
            comment: "managedsoftwareupdate message")
        _ = NSLocalizedString(
            "Verifying package integrity...", comment: "managedsoftwareupdate message")
        _ = NSLocalizedString(
            "The software was successfully installed.",
            comment: "managedsoftwareupdate message")
        _ = NSLocalizedString(
            "Gathering information on installed packages",
            comment: "managedsoftwareupdate message")
        _ = NSLocalizedString(
            "Determining which filesystem items to remove",
            comment: "managedsoftwareupdate message")
        _ = NSLocalizedString(
            "Removing receipt info", comment: "managedsoftwareupdate message")
        _ = NSLocalizedString(
            "Nothing to remove.", comment: "managedsoftwareupdate message")
        _ = NSLocalizedString(
            "Package removal complete.", comment: "managedsoftwareupdate message")
        
        // apple update messages
        _ = NSLocalizedString(
            "Checking for available Apple Software Updates...",
            comment: "managedsoftwareupdate message")
        _ = NSLocalizedString(
            "Checking Apple Software Update catalog...",
            comment: "managedsoftwareupdate message")
        _ = NSLocalizedString(
            "Downloading available Apple Software Updates...",
            comment: "managedsoftwareupdate message")
        _ = NSLocalizedString(
            "Installing available Apple Software Updates...",
            comment: "managedsoftwareupdate message")
        
        // Adobe install/uninstall messages
        _ = NSLocalizedString(
            "Running Adobe Setup", comment: "managedsoftwareupdate message")
        _ = NSLocalizedString(
            "Running Adobe Uninstall", comment: "managedsoftwareupdate message")
        _ = NSLocalizedString(
            "Starting Adobe installer...", comment: "managedsoftwareupdate message")
        _ = NSLocalizedString(
            "Running Adobe Patch Installer", comment: "managedsoftwareupdate message")
        
        // macOS install/upgrade messages
        _ = NSLocalizedString(
            "Starting macOS upgrade...", comment: "managedsoftwareupdate message")
        _ = NSLocalizedString(
            "Preparing to run macOS Installer...", comment: "managedsoftwareupdate message")
        _ = NSLocalizedString(
            "System will restart and begin upgrade of macOS.",
            comment: "managedsoftwareupdate message")
    }

}
