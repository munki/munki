//
//  MSCAlertController.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 7/15/18.
//  Copyright © 2018-2026 The Munki Project. All rights reserved.
//

import Cocoa

class MSCAlertController: NSObject {
    // An object that handles some of our alerts, if for no other reason
    // than to move a giant bunch of ugly code out of the WindowController
    
    var window: NSWindow? // our parent window
    var timers: [Timer] = []
    var quitButton: NSButton?
    var haveOpenedSysPrefsSUPane = false
    
    func handlePossibleAuthRestart() {
        // Ask for and store a password for auth restart if needed/possible
        if !haveOpenedSysPrefsSUPane && updatesRequireRestart() && verifyUser(NSUserName()) && !verifyRecoveryKeyPresent() {
            // FV is on and user is in list of FV users, so they can
            // authrestart, and we do not have a stored FV recovery
            // key/password. So we should prompt the user for a password
            // we can use for fdesetup authrestart
            if let passwordAlertController = (NSApp.delegate as? AppDelegate)?.passwordAlertController {
                passwordAlertController.promptForPasswordForAuthRestart()
            }
        }
    }
    
    func forcedLogoutWarning(_ notification: Notification) {
        // Display a forced logout warning
        guard let mainWindow = window else {
            msc_debug_log("Could not get main window in forcedLogoutWarning")
            return
        }
        NSApp.activate(ignoringOtherApps: true)
        var logoutTime: Date? = nil
        if let info = notification.userInfo {
            logoutTime = info["logout_time"] as? Date
        } else if thereAreUpdatesToBeForcedSoon() {
            logoutTime = earliestForceInstallDate()
        }
        if logoutTime == nil {
            return
        }
        let timeUntilLogout = Int(logoutTime!.timeIntervalSinceNow / 60)
        var infoText = ""
        let moreText = NSLocalizedString(
            "All pending updates will be installed. Unsaved work will be lost." +
            "\nYou may avoid the forced logout by logging out now.",
            comment: "Forced Logout warning detail")
        if timeUntilLogout > 55 {
            msc_log("user", "forced_logout_warning_initial")
            let formatString = NSLocalizedString(
                "A logout will be forced at approximately %@.",
                comment: "Logout warning string when logout is an hour or more away") as NSString
            let deadlineStr = stringFromDate(logoutTime!)
            infoText = NSString(format: formatString, deadlineStr) as String + "\n" + moreText
        } else if timeUntilLogout > 0 {
            msc_log("user", "forced_logout_warning_\(timeUntilLogout)")
            let formatString = NSLocalizedString(
                "A logout will be forced in less than %@ minutes.",
                comment: "Logout warning string when logout is in < 60 minutes") as NSString
            infoText = NSString(format: formatString, NSNumber.init(value: timeUntilLogout)) as String + "\n" + moreText
        } else {
            msc_log("user", "forced_logout_warning_final")
            infoText = NSLocalizedString(
                "A logout will be forced in less than a minute.\n" +
                "All pending updates will be installed. Unsaved work will be lost.",
                comment: "Logout warning string when logout is in less than a minute")
        }
        if let attachedSheet = mainWindow.attachedSheet {
            // there's an existing sheet open; close it first
            //NSApp.endSheet(attachedSheet)
            mainWindow.endSheet(attachedSheet)
        }
        let alert = NSAlert()
        alert.messageText =  NSLocalizedString(
            "Forced Logout for Mandatory Install", comment: "Forced Logout title text")
        alert.informativeText = infoText
        let ok_btn_title = NSLocalizedString("OK", comment: "OK button title")
        let logout_btn_title = NSLocalizedString(
            "Log out and update now", comment: "Logout and Update Now button text")
        if timeUntilLogout > 5 {
            // Display OK and Logout buttons
            alert.addButton(withTitle: ok_btn_title)
            alert.addButton(withTitle: logout_btn_title)
            alert.beginSheetModal(for: mainWindow, completionHandler: { (modalResponse) -> Void in
                if modalResponse == .alertSecondButtonReturn {
                    // clicked logout button
                    msc_log("user", "install_with_logout")
                    self.handlePossibleAuthRestart()
                    do {
                        try logoutAndUpdate()
                    } catch {
                        self.installSessionErrorAlert("\(error)")
                    }
                } else {
                    // dismissed or closed or ignored
                    msc_log("user", "dismissed_forced_logout_warning")
                }
            })
        } else {
            // less than 5 minutes until forced logout -- only button says "Logout"
            alert.addButton(withTitle: logout_btn_title)
            alert.beginSheetModal(for: mainWindow, completionHandler: { (modalResponse) -> Void in
                if modalResponse == .alertFirstButtonReturn {
                    // checking for the only button seems odd, but the modal can end
                    // because we called mainWindow.endSheet(attachedSheet)
                    // and we don't want to try to log out in that case
                    msc_log("user", "install_with_logout")
                    self.handlePossibleAuthRestart()
                    do {
                        try logoutAndUpdate()
                    } catch {
                        self.installSessionErrorAlert("\(error)")
                    }
                }
            })
        }
    }
    
    func alertToAppleUpdates() {
        // Notify user of pending Apple updates
        guard let mainWindow = window else {
            msc_debug_log("Could not get main window in alertToAppleUpdates")
            return
        }
        let alert = NSAlert()
        alert.messageText = NSLocalizedString(
            "Important Apple Updates", comment: "Apple Software Updates Pending title")
        alert.addButton(withTitle: NSLocalizedString("Install now", comment: "Install now button title"))
        alert.addButton(withTitle: NSLocalizedString(
            "Skip these updates", comment: "Skip Apple updates button title"))
        let su_icon_file = "/System/Library/PreferencePanes/SoftwareUpdate.prefPane/Contents/Resources/SoftwareUpdate.icns"
        if let suIcon = NSImage.init(contentsOfFile: su_icon_file) {
            alert.icon = suIcon
        }
        if !userIsAdmin() && userMustBeAdminToInstallAppleUpdates() {
            // tell user they cannot install the updates
            msc_log("user", "apple_updates_user_cannot_install")
            alert.informativeText = NSLocalizedString(
                "Your administrator has restricted installation of these updates. Contact your administrator for assistance.",
                comment: "Apple Software Updates Unable detail")
            // disable install now button
            alert.buttons[0].isEnabled = false
        } else {
            // prompt user to install using System Preferences
            msc_log("user", "apple_updates_pending")
            alert.informativeText = NSLocalizedString(
                "You must install these updates using Software Update in System Preferences.",
                comment: "Apple Software Updates Pending detail")
            if shouldAggressivelyNotifyAboutAppleUpdates() {
                // disable the skip button
                alert.buttons[1].isEnabled = false
            }
        }
        alert.beginSheetModal(for: mainWindow, completionHandler: { (modalResponse) -> Void in
            self.appleUpdateAlertEnded(for: alert, withResponse: modalResponse)
        })
    }
    
    func appleUpdateAlertEnded(for alert: NSAlert, withResponse modalResponse: NSApplication.ModalResponse) {
        // Called when Apple update alert ends
        if modalResponse == .alertFirstButtonReturn {
            msc_log("user", "agreed_apple_updates")
            // make sure this alert panel is gone before we proceed
            alert.window.orderOut(self)
            let appDelegate = NSApp.delegate! as! AppDelegate
            appDelegate.mainWindowController.forceFrontmost = false
            appDelegate.backdropOnlyMode = true
            if let mainWindow = window {
                mainWindow.level = .normal
            }
            let timer1 = Timer.scheduledTimer(timeInterval: 0.1,
                                              target: self,
                                              selector: #selector(self.openSoftwareUpdate),
                                              userInfo: nil,
                                              repeats: false)
            timers.append(timer1)
            let timer2 = Timer.scheduledTimer(timeInterval: 1.5,
                                              target: self,
                                              selector: #selector(self.closeMainWindow),
                                              userInfo: nil,
                                              repeats: false)
            timers.append(timer2)
            let timer3 = Timer.scheduledTimer(timeInterval: 14.5,
                                              target: self,
                                              selector: #selector(self.removeBlurredBackground),
                                              userInfo: nil,
                                              repeats: false)
            timers.append(timer3)
            // wait 15 seconds, then quit
            let timer4 = Timer.scheduledTimer(timeInterval: 15.0,
                                              target: NSApp as Any,
                                              selector: #selector(NSApp.terminate),
                                              userInfo: self,
                                              repeats: false)
            timers.append(timer4)
        } else {
            // cancelled
            msc_log("user", "deferred_apple_updates")
            alert.window.orderOut(self)
            setFilterAppleUpdates(true)
            clearMunkiItemsCache()
            if let mainWindowController = (NSApp.delegate! as! AppDelegate).mainWindowController {
                mainWindowController.load_page("updates.html")
                mainWindowController.displayUpdateCount()
                if shouldAggressivelyNotifyAboutMunkiUpdates() {
                    mainWindowController._alertedUserToOutstandingUpdates = false
                }
            }
        }
    }
    
    @objc func openSoftwareUpdate() {
        // object method to call openSoftwareUpdatePrefsPane function
        if let mainWindowController = (NSApp.delegate! as! AppDelegate).mainWindowController,
           let blurredBackground = mainWindowController.blurredBackground
        {
            // lower the level of our blur windows so the Software Update
            // pane can appear in front
            blurredBackground.lowerWindowLevels()
        }
        openSoftwareUpdatePrefsPane()
        self.haveOpenedSysPrefsSUPane = true
    }
    
    @objc func closeMainWindow() {
        // closes the main window, duh
        if let mainWindow = window {
            mainWindow.orderOut(self)
        }
    }
    
    @objc func removeBlurredBackground() {
        // removes the blurred background so other apps can be accessed
        if (NSApp.delegate! as! AppDelegate).mainWindowController.blurredBackground != nil {
            (NSApp.delegate! as! AppDelegate).mainWindowController.blurredBackground = nil
        }
    }


    func alertToExtraUpdates() {
        // Notify user of additional pending updates
        msc_log("user", "extra_updates_pending")
        guard let mainWindow = window else {
            msc_debug_log("Could not get main window in alertToExtraUpdates")
            return
        }
        let alert = NSAlert()
        alert.messageText = NSLocalizedString(
            "Additional Pending Updates", comment: "Additional Pending Updates title")
        alert.informativeText = NSLocalizedString(
            "There are additional pending updates to install or remove.",
            comment: "Additional Pending Updates detail")
        alert.addButton(withTitle: NSLocalizedString("OK", comment: "OK button title"))
        alert.beginSheetModal(for: mainWindow, completionHandler: { (modalResponse) -> Void in
            // do nothing
        })
    }
    
    func confirmUpdatesAndInstall() {
        // Make sure it's OK to proceed with installing if logout or restart is
        // required
        guard let mainWindow = window else {
            msc_debug_log("Could not get main window in confirmUpdatesAndInstall")
            return
        }
        if alertedToMultipleUsers() {
            return
        } else if updatesRequireRestart() {
            let alert = NSAlert()
            alert.messageText = NSLocalizedString(
                "Restart Required", comment: "Restart Required title")
            alert.informativeText = NSLocalizedString(
                "A restart is required after updating. Log " +
                "out and update now?", comment: "Restart Required detail")
            alert.addButton(withTitle: NSLocalizedString(
                "Log out and update", comment: "Log out and Update button text"))
            alert.addButton(withTitle: NSLocalizedString(
                "Cancel", comment: "Cancel button title/short action text"))
           alert.beginSheetModal(for: mainWindow, completionHandler: { (modalResponse) -> Void in
                self.logoutAlertEnded(for: alert, withResponse: modalResponse)
            })
        } else if updatesRequireLogout() || installRequiresLogout() {
            let alert = NSAlert()
            alert.messageText = NSLocalizedString(
                "Logout Required", comment: "Logout Required title")
            alert.informativeText = NSLocalizedString(
                "A logout is required before updating. Log " +
                "out and update now?", comment: "Logout Required detail")
            alert.addButton(withTitle: NSLocalizedString(
                "Log out and update", comment: "Log out and Update button text"))
            alert.addButton(withTitle: NSLocalizedString(
                "Cancel", comment: "Cancel button title/short action text"))
            alert.beginSheetModal(for: mainWindow, completionHandler: { (modalResponse) -> Void in
                self.logoutAlertEnded(for: alert, withResponse: modalResponse)
            })
        } else {
            // we shouldn't have been invoked if neither a restart or logout was
            // required
            msc_debug_log(
                "confirmUpdatesAndInstall was called but no restart or logout was needed")
        }
    }
    
    func logoutAlertEnded(for alert: NSAlert, withResponse modalResponse: NSApplication.ModalResponse) {
        // Called when logout alert ends
        if modalResponse == .alertFirstButtonReturn {
            // make sure this alert panel is gone before we proceed, which
            // might involve opening another alert sheet
            alert.window.orderOut(self)
            if alertedToFirmwareUpdatesAndCancelled() {
                msc_log("user", "alerted_to_firmware_updates_and_cancelled")
                return
            } else if alertedToRunningOnBatteryAndCancelled() {
                msc_log("user", "alerted_on_battery_power_and_cancelled")
                return
            }
            msc_log("user", "install_with_logout")
            handlePossibleAuthRestart()
            do {
                try logoutAndUpdate()
            } catch {
                installSessionErrorAlert("\(error)")
            }
        } else {
            msc_log("user", "cancelled")
        }
    }
    
    func installSessionErrorAlert(_ errorMessage: String) {
        // Something has gone wrong and we can't trigger an install at logout
        msc_log("user", "install_session_failed")
        guard let mainWindow = window else {
            msc_debug_log("Could not get main window in installSessionErrorAlert")
            return
        }
        let alert = NSAlert()
        alert.messageText = NSLocalizedString(
            "Install session failed", comment: "Install Session Failed title")
        var detailText = NSLocalizedString(
            "There is a configuration problem with the managed software " +
                "installer. Could not start the process. Contact your systems " +
            "administrator.", comment: "Could Not Start Session message")
        if !errorMessage.isEmpty {
            detailText = "\(detailText)\n\n\(errorMessage)"
        }
        alert.informativeText = detailText
        alert.addButton(withTitle: NSLocalizedString("OK", comment: "OK button title"))
        alert.beginSheetModal(for: mainWindow, completionHandler: { (modalResponse) -> Void in
            // do nothing
        })
    }
    
    func alertedToMultipleUsers() -> Bool {
        // Returns true if there are multiple GUI logins; alerts as a side
        // effect
        if currentGUIusers().count > 1 {
            guard let mainWindow = window else {
                msc_debug_log("Could not get main window in alertedToMultipleUsers")
                return false
            }
            msc_log("MSC", "multiple_gui_users_update_cancelled")
            let alert = NSAlert()
            alert.messageText = NSLocalizedString(
                "Other users logged in", comment: "Other Users Logged In title")
            alert.informativeText = NSLocalizedString(
                "There are other users logged into this computer.\n" +
                "Updating now could cause other users to lose their " +
                "work.\n\nPlease try again later after the other users " +
                "have logged out.", comment: "Other Users Logged In detail")
            alert.addButton(withTitle: NSLocalizedString(
                "Cancel", comment: "Cancel button title/short action text"))
            alert.beginSheetModal(for: mainWindow, completionHandler: { (modalResponse) -> Void in
                // do nothing
            })
            return true
        } else {
            return false
        }
    }
    
    func alertedToNotVolumeOwner() -> Bool {
        // Returns true if we're launching a staged OS installer and the current
        // GUI user is not a volume owner; alerts as a side effect
        if updateListContainsStagedOSUpdate() && isAppleSilicon() && !currentUserIsVolumeOwner() {
            guard let mainWindow = window else {
                msc_debug_log("Could not get main window in alertedToNotVolumeOwner")
                return false
            }
            msc_log("MSC", "staged_os_installer_not_volume_owner_update_cancelled")
            let alert = NSAlert()
            alert.messageText = NSLocalizedString(
                "Cannot upgrade macOS", comment: "Not volume owner title")
            alert.informativeText = NSLocalizedString(
                "Your user account is not an owner of the current startup volume.\n" +
                "You cannot upgrade macOS at this time.\n\n" +
                "Contact your systems administrator.",
                comment: "Not volume owner detail")
            alert.addButton(withTitle: NSLocalizedString(
                "Cancel", comment: "Cancel button title/short action text"))
            alert.beginSheetModal(for: mainWindow, completionHandler: { (modalResponse) -> Void in
                // do nothing
            })
            return true
        }
        return false
    }
    
    func alertedToStagedOSUpgradeAndCancelled() -> Bool {
        // Returns true if there is staged macOS upgrade and the user
        // declines to install it
        
        if (shouldFilterStagedOSUpdate() || !updateListContainsStagedOSUpdate()) {
            return false
        }
        if (getEffectiveUpdateList().count > 1 || getAppleUpdates().count > 0) {
            let alert = NSAlert()
            alert.messageText = NSLocalizedString(
                "macOS install pending",
                comment: "macOS Install Pending text")
            alert.informativeText = NSLocalizedString(
                "A macOS install is pending. This install may take some " +
                "time. Other pending items will be installed later.\n\n" +
                "Continue with the install?",
                comment:"macOS Install Pending detail")
            alert.addButton(withTitle: NSLocalizedString(
                "Continue", comment: "Continue button text"))
            alert.addButton(withTitle: NSLocalizedString(
                "Cancel", comment: "Cancel button title/short action text"))
            // making UI consistent with Apple Software Update...
            // set Cancel button to be activated by return key
            alert.buttons[1].keyEquivalent = "\r"
            // set Continue button to be activated by Escape key
            alert.buttons[0].keyEquivalent = "\u{1B}"
            msc_log("MSC", "alert_to_macos_install")
            let response = alert.runModal()
            if response == .alertSecondButtonReturn {
                // user clicked Cancel
                return true
            }
        }
        return false
    }
    
    func alertedToBlockingAppsRunning() -> Bool {
        // Returns true if blocking_apps are running; alerts as a side-effect
        guard let mainWindow = window else {
            msc_debug_log("Could not get main window in alertedToBlockingAppsRunning")
            return false
        }
        var apps_to_check = [String]()
        for update_item in getUpdateList() {
            if let blocking_apps = update_item["blocking_applications"] as? [String] {
                apps_to_check += blocking_apps
            } else if let installs_items = update_item["installs"] as? [PlistDict] {
                let installs_apps = installs_items.filter(
                    { ($0["type"] as? String ?? "" == "application" &&
                        !($0["path"] as? String ?? "").isEmpty) }).map(
                            { ($0["path"] as? NSString ?? "").lastPathComponent })
                apps_to_check += installs_apps
            }
        }
        let running_apps = getRunningBlockingApps(apps_to_check)
        if running_apps.isEmpty {
            return false
        }
        guard let currentUser = getconsoleuser() else {
            return false
        }
        let other_users_apps = running_apps.filter(
            { $0["user"] ?? "" != currentUser }).map(
                { $0["display_name"] ?? "" })
        let my_apps = running_apps.filter(
            { $0["user"] ?? "" == currentUser }).map(
                { $0["display_name"] ?? "" })
        //  msc_log("MSC", "conflicting_apps", ','.join(other_users_apps + my_apps))
        let alert = NSAlert()
        if !other_users_apps.isEmpty {
            alert.messageText = NSLocalizedString(
                "Applications in use by others",
                comment: "Other Users Blocking Apps Running title")
            let formatString = NSLocalizedString(
                "Other logged in users are using the following " +
                "applications. Try updating later when they are no longer " +
                "in use:\n\n%@",
                comment: "Other Users Blocking Apps Running detail")
            alert.informativeText = String(
                format: formatString, Array(Set(other_users_apps)).joined(separator: "\n"))
        } else {
            alert.messageText = NSLocalizedString(
                "Conflicting applications running",
                comment: "Blocking Apps Running title")
            let formatString = NSLocalizedString(
                "You must quit the following applications before " +
                "proceeding with installation or removal:\n\n%@",
                comment: "Blocking Apps Running detail")
            alert.informativeText = String(
                format: formatString, Array(Set(my_apps)).joined(separator: "\n"))
        }
        alert.addButton(withTitle: NSLocalizedString("OK", comment: "OK button title"))
        alert.beginSheetModal(for: mainWindow, completionHandler: { (modalResponse) -> Void in
            // do nothing
        })
        return true
    }
    
    func getFirmwareAlertInfo() -> [[String: String]] {
        // Get detail about a firmware update
        var info = [[String: String]]()
        for update_item in getUpdateList() {
            if let firmware_alert_text = update_item["firmware_alert_text"] as? String {
                var info_item = [String: String]()
                info_item["name"] = update_item["display_name"] as? String ?? update_item["name"] as? String ?? "Firmware Update"
                if firmware_alert_text == "_DEFAULT_FIRMWARE_ALERT_TEXT_" {
                    info_item["alert_text"] = NSLocalizedString(
                        "Firmware will be updated on your computer. " +
                        "Your computer's power cord must be connected " +
                        "and plugged into a working power source. " +
                        "It may take several minutes for the update to " +
                        "complete. Do not disturb or shut off the power " +
                        "on your computer during this update.",
                        comment: "Firmware Alert Default detail")
                } else {
                    info_item["alert_text"] = firmware_alert_text
                }
                info.append(info_item)
            }
        }
        return info
    }
    
    func alertedToFirmwareUpdatesAndCancelled() -> Bool {
        // Returns true if we have one or more firmware updates and
        // the user clicks the Cancel button
        let firmware_alert_info = getFirmwareAlertInfo()
        if firmware_alert_info.isEmpty {
            return false
        }
        let on_battery_power = onBatteryPower()
        for item in firmware_alert_info {
            let alert = NSAlert()
            alert.messageText = item["name"] ?? "Firmware Update"
            var alert_text = ""
            if on_battery_power {
                alert_text = NSLocalizedString(
                    "Your computer is not connected to a power source.",
                    comment: "No Power Source Warning text")
                alert_text += "\n\n" + (item["alert_text"] ?? "")
            } else {
                alert_text = item["alert_text"] ?? ""
            }
            alert.informativeText = alert_text
            alert.addButton(withTitle: NSLocalizedString(
                "Continue", comment: "Continue button text"))
            alert.addButton(withTitle: NSLocalizedString(
                "Cancel", comment: "Cancel button title/short action text"))
            alert.alertStyle = .critical
            if on_battery_power {
                // set Cancel button to be activated by return key
                alert.buttons[1].keyEquivalent = "\r"
                // set Continue button to be activated by Escape key
                alert.buttons[0].keyEquivalent = "\u{1B}"
            }
            let response = alert.runModal()
            if response == .alertSecondButtonReturn {
                // user clicked Cancel
                return true
            }
        }
        return true
    }
    
    func alertedToRunningOnBatteryAndCancelled() -> Bool {
        // Returns true if we are running on battery with less
        // than 50% power and user clicks the Cancel button
        if onBatteryPower() && getBatteryPercentage() < 50 {
            let alert = NSAlert()
            alert.messageText = NSLocalizedString(
                "Your computer is not connected to a power source.",
                comment: "No Power Source Warning text")
            alert.informativeText = NSLocalizedString(
                "For best results, you should connect your computer to a " +
                "power source before updating. Are you sure you want to " +
                "continue the update?", comment:"No Power Source Warning detail")
            alert.addButton(withTitle: NSLocalizedString(
                "Continue", comment: "Continue button text"))
            alert.addButton(withTitle: NSLocalizedString(
                "Cancel", comment: "Cancel button title/short action text"))
            // making UI consistent with Apple Software Update...
            // set Cancel button to be activated by return key
            alert.buttons[1].keyEquivalent = "\r"
            // set Continue button to be activated by Escape key
            alert.buttons[0].keyEquivalent = "\u{1B}"
            msc_log("MSC", "alert_on_battery_power")
            let response = alert.runModal()
            if response == .alertSecondButtonReturn {
                // user clicked Cancel
                return true
            }
        }
        return false
    }
    
    func alertToPendingUpdates(_ mwc: MainWindowController) {
        // Alert user to pending updates before quitting the application
        mwc._alertedUserToOutstandingUpdates = true
        // show the updates
        mwc.loadUpdatesPage(self)
        var alertTitle = ""
        var alertDetail = ""
        if thereAreUpdatesToBeForcedSoon() {
            alertTitle = NSLocalizedString("Mandatory Updates Pending",
                                           comment: "Mandatory Updates Pending text")
            if let deadline = earliestForceInstallDate() {
                let time_til_logout = deadline.timeIntervalSinceNow
                if time_til_logout > 0 {
                    let deadline_str = stringFromDate(deadline)
                    let formatString = NSLocalizedString(
                        ("One or more updates must be installed by %@. A logout " +
                          "may be forced if you wait too long to update."),
                        comment: "Mandatory Updates Pending detail")
                    alertDetail = String(format: formatString, deadline_str)
                } else {
                    alertDetail = NSLocalizedString(
                        ("One or more mandatory updates are overdue for " +
                         "installation. A logout will be forced soon."),
                        comment: "Mandatory Updates Imminent detail")
                }
            }
        } else {
            alertTitle = NSLocalizedString(
                "Pending updates", comment: "Pending Updates alert title")
            alertDetail = NSLocalizedString(
                "There are pending updates for this computer.",
                comment: "Pending Updates alert detail text")
        }
        let alert = NSAlert()
        alert.messageText = alertTitle
        alert.informativeText = alertDetail
        var quitButton = NSApplication.ModalResponse.alertFirstButtonReturn
        var updateButton = NSApplication.ModalResponse.alertSecondButtonReturn
        if !shouldAggressivelyNotifyAboutMunkiUpdates() && !thereAreUpdatesToBeForcedSoon() {
            alert.addButton(withTitle: NSLocalizedString("Quit", comment: "Quit button title"))
            alert.addButton(withTitle: NSLocalizedString("Update now", comment: "Update Now button title"))
        } else {
            // add the buttons in the opposite order so "Update now" is the default/primary
            alert.addButton(withTitle: NSLocalizedString("Update now", comment: "Update Now button title"))
            alert.addButton(withTitle: NSLocalizedString("Quit", comment: "Quit button title"))
            // initially disable the Quit button
            self.quitButton = alert.buttons[1]
            alert.buttons[1].isEnabled = false
            let timer1 = Timer.scheduledTimer(timeInterval: 5.0,
                                              target: self,
                                              selector: #selector(self.activateQuitButton),
                                              userInfo: nil,
                                              repeats: false)
            timers.append(timer1)
            updateButton = NSApplication.ModalResponse.alertFirstButtonReturn
            quitButton = NSApplication.ModalResponse.alertSecondButtonReturn
        }
        alert.beginSheetModal(for: self.window!, completionHandler: { (modalResponse) -> Void in
            if modalResponse == quitButton {
                msc_log("user", "quit")
                NSApp.terminate(self)
            } else if modalResponse == updateButton {
                msc_log("user", "install_now_clicked")
                // make sure this alert panel is gone before we proceed
                // which might involve opening another alert sheet
                alert.window.orderOut(self)
                // invalidate any timers
                for timer in self.timers {
                    timer.invalidate()
                }
                // initiate the updates
                mwc.updateNow()
                mwc.loadUpdatesPage(self)
            }
        })
    }
    
    @objc func activateQuitButton() {
        if let button = self.quitButton {
            button.isEnabled = true
        } else {
            NSLog("%@", "could not get the alert button reference")
        }
    }

}
