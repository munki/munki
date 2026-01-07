//
//  MainWindowController+WKScriptMessageHandler.swift
//  Managed Software Center
//
//  Created by admin on 6/28/25.
//  Copyright © 2025-2026 The Munki Project. All rights reserved.
//

import Cocoa
import WebKit

extension MainWindowController: WKScriptMessageHandler {
    
    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        // react to messages set to us by JavaScript
        print("Got message from JavaScript: \(message.name)")
        if message.name == "installButtonClicked" {
            installButtonClicked()
        }
        if message.name == "myItemsButtonClicked" {
            if let item_name = message.body as? String {
                myItemsActionButtonClicked(item_name)
            }
        }
        if message.name == "actionButtonClicked" {
            if let item_name = message.body as? String {
                actionButtonClicked(item_name)
            }
        }
        if message.name == "changeSelectedCategory" {
            if let category_name = message.body as? String {
                changeSelectedCategory(category_name)
            }
        }
        if message.name == "updateOptionalInstallButtonClicked" {
            if let item_name = message.body as? String {
                updateOptionalInstallButtonClicked(item_name)
            }
        }
        if message.name == "updateOptionalInstallButtonFinishAction" {
            if let item_name = message.body as? String {
                updateOptionalInstallButtonFinishAction(item_name)
            }
        }
        if message.name == "openExternalLink" {
            if let link = message.body as? String {
                openExternalLink(link)
            }
        }
    }
    
    // JavaScript integration
    
    // handling DOM UI elements
    
    func setInnerHTML(_ htmlString: String, elementID: String) {
        if let rawData = htmlString.data(using: .utf8) {
            let encodedData = rawData.base64EncodedString()
            webView.evaluateJavaScript("setInnerHTMLforElementID('\(elementID)', '\(encodedData)')")
        }
    }
    
    func addToInnerHTML(_ htmlString: String, elementID: String) {
        if let rawData = htmlString.data(using: .utf8) {
            let encodedData = rawData.base64EncodedString()
            webView.evaluateJavaScript("addToInnerHTMLforElementID('\(elementID)', '\(encodedData)')")
        }
    }
    
    func setInnerText(_ textString: String, elementID: String) {
        if let rawData = textString.data(using: .utf8) {
            let encodedData = rawData.base64EncodedString()
            webView.evaluateJavaScript("setInnerTextforElementID('\(elementID)', '\(encodedData)')")
        }
    }
    
    func openExternalLink(_ url: String) {
        // open a link in the default browser
        msc_debug_log("External link request: \(url)")
        if let real_url = URL(string: url) {
            NSWorkspace.shared.open(real_url)
        }
    }
    
    func installButtonClicked() {
        // this method is called from JavaScript when the user
        // clicks the Install button in the Updates view
        if _update_in_progress {
            // this is now a stop/cancel button
            msc_log("user", "cancel_updates")
            if let status_controller = (NSApp.delegate as? AppDelegate)?.statusController {
                status_controller.disableStopButton()
                status_controller._status_stopBtnState = 1
            }
            stop_requested = true
            // send a notification that stop button was clicked
            let stop_request_flag_file = "/private/tmp/com.googlecode.munki.managedsoftwareupdate.stop_requested"
            if !FileManager.default.fileExists(atPath: stop_request_flag_file) {
                FileManager.default.createFile(atPath: stop_request_flag_file, contents: nil, attributes: nil)
            }
        } else if getUpdateCount() == 0 {
            // no updates, the button must say "Check Again"
            msc_log("user", "refresh_clicked")
            checkForUpdates()
        } else {
            // button must say "Update"
            // we're on the Updates page, so users can see all the pending/
            // outstanding updates
            _alertedUserToOutstandingUpdates = true
            if !shouldFilterAppleUpdates() && appleUpdatesMustBeDoneWithSystemPreferences() {
                // if there are pending Apple updates, alert the user to
                // install via System Preferences
                alert_controller.alertToAppleUpdates()
                setFilterAppleUpdates(true)
            } else {
                updateNow()
            }
        }
    }
    
   func updateOptionalInstallButtonClicked(_ item_name: String) {
        // this method is called from JavaScript when a user clicks
        // the cancel or add button in the updates list
        if let item = optionalItem(forName: item_name) {
            if (item["status"] as? String ?? "" == "update-available" &&
                    item["preupgrade_alert"] != nil) {
                displayPreInstallUninstallAlert(item["preupgrade_alert"] as? PlistDict ?? PlistDict(),
                                                action: updateOptionalInstallButtonBeginAction,
                                                item: item_name)
            } else {
                updateOptionalInstallButtonBeginAction(item_name)
            }
        } else {
            msc_debug_log("Unexpected error: Can't find item for \(item_name)")
        }
    }
    
    func updateOptionalInstallButtonBeginAction(_ item_name: String) {
        webView.evaluateJavaScript("fadeOutAndRemove('\(item_name)')")
    }
    
    func myItemsActionButtonClicked(_ item_name: String) {
        // this method is called from JavaScript when the user clicks
        // the Install/Remove/Cancel button in the My Items view
        if let item = optionalItem(forName: item_name) {
            if (item["status"] as? String ?? "" == "installed" &&
                    item["preuninstall_alert"] != nil) {
                displayPreInstallUninstallAlert(item["preuninstall_alert"] as? PlistDict ?? PlistDict(),
                                                action: myItemsActionButtonPerformAction,
                                                item: item_name)
            } else {
                myItemsActionButtonPerformAction(item_name)
            }
        } else {
            msc_debug_log("Unexpected error: Can't find item for \(item_name)")
        }
    }
    
    func myItemsActionButtonPerformAction(_ item_name: String) {
        // perform action needed when user clicks
        // the Install/Remove/Cancel button in the My Items view
        guard let item = optionalItem(forName: item_name) else {
            msc_debug_log(
                "User clicked MyItems action button for \(item_name)")
            msc_debug_log("Could not find item for \(item_name)")
            return
        }
        let prior_status = item["status"] as? String ?? ""
        if !update_status_for_item(item) {
            // there was a problem, can't continue
            return
        }
        displayUpdateCount()
        let current_status = item["status"] as? String ?? ""
        if current_status == "not-installed" {
            // we removed item from list of things to install
            // now remove from display
            webView.evaluateJavaScript("removeElementByID('\(item_name)_myitems_table_row')")
        } else {
            setInnerHTML(item["myitem_action_text"] as? String ?? "", elementID: "\(item_name)_action_button_text")
            setInnerHTML(item["myitem_status_text"] as? String ?? "", elementID: "\(item_name)_status_text")
            webView.evaluateJavaScript("document.getElementById('\(item_name)_status_text')).className = 'status \(current_status)'")
        }
        if ["install-requested", "removal-requested"].contains(current_status) {
            _alertedUserToOutstandingUpdates = false
            if !_update_in_progress {
                updateNow()
            }
        } else if ["staged-os-installer",
                   "will-be-installed",
                   "update-will-be-installed",
                   "will-be-removed"].contains(prior_status) {
            // cancelled a pending install or removal; should run an updatecheck
            checkForUpdates(suppress_apple_update_check: true)
        }
    }
    
    func actionButtonClicked(_ item_name: String) {
        // this method is called from JavaScript when the user clicks
        // the Install/Remove/Cancel button in the list or detail view
        if let item = optionalItem(forName: item_name) {
            var showAlert = true
            let status = item["status"] as? String ?? ""
            if status == "not-installed" && item["preinstall_alert"] != nil {
                displayPreInstallUninstallAlert(item["preinstall_alert"] as? PlistDict ?? PlistDict(),
                                                action: actionButtonPerformAction,
                                                item: item_name)
            } else if status == "installed" && item["preuninstall_alert"] != nil {
                displayPreInstallUninstallAlert(item["preuninstall_alert"] as? PlistDict ?? PlistDict(),
                                                action: actionButtonPerformAction,
                                                item: item_name)
            } else if status == "update-available" && item["preupgrade_alert"] != nil {
                displayPreInstallUninstallAlert(item["preupgrade_alert"] as? PlistDict ?? PlistDict(),
                                                action: actionButtonPerformAction,
                                                item: item_name)
            } else {
                actionButtonPerformAction(item_name)
                showAlert = false
            }
            if showAlert {
                msc_log("user", "show_alert")
            }
        } else {
            msc_debug_log(
                "User clicked Install/Remove/Upgrade/Cancel button in the list " +
                "or detail view")
            msc_debug_log("Unexpected error: Can't find item for \(item_name)")
        }
    }

}
