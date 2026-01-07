//
//  AppDelegate.swift
//  ManagedSoftwareCenter
//
//  Created by Greg Neagle on 5/27/18.
//  Copyright © 2018-2026 The Munki Project. All rights reserved.
//

import Cocoa
import UserNotifications

@NSApplicationMain
class AppDelegate: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate {

    @IBOutlet weak var mainWindowController: MainWindowController!
    @IBOutlet weak var statusController: MSCStatusController!
    @IBOutlet weak var passwordAlertController: MSCPasswordAlertController!
    
    var logWindowController: LogWindowController?
    
    var launchedViaURL = false
    var backdropOnlyMode = false
    
    @IBAction func showLogWindow(_ sender: Any) {
        if logWindowController == nil {
            logWindowController = LogWindowController(windowNibName: "LogWindow")
        }
        logWindowController!.showWindow(self)
    }
    
    @objc func openURL(_ event: NSAppleEventDescriptor, with replyEvent: NSAppleEventDescriptor) {
        let keyword = AEKeyword(keyDirectObject)
        let urlDescriptor = event.paramDescriptor(forKeyword: keyword)
        if let urlString = urlDescriptor?.stringValue {
            msc_log("MSC", "Called by external URL: \(urlString)")
            launchedViaURL = true
            if let url = URL(string: urlString) {
                mainWindowController.handleMunkiURL(url)
            } else {
                msc_debug_log("\(urlString) is not a valid URL")
                return
            }
        }
    }
    
    // MARK: NSApplicationDelegate methods
    
    func applicationSupportsSecureRestorableState(_ app: NSApplication) -> Bool {
        return true
    }
    
    func applicationDidFinishLaunching(_ aNotification: Notification) {
        // NSApplication delegate method called at launch
        NSLog("%@", "Finished launching")
        NSLog("Additional arguments: %@", CommandLine.arguments)

        if let info_dict = Bundle.main.infoDictionary {
            if let vers = info_dict["CFBundleShortVersionString"] as? String {
                //print(vers)
                msc_log("MSC", "launched", msg: "VER=\(vers)")
            }
        }
        
        // setup client logging
        setup_logging()
        
        if let userInfo = aNotification.userInfo {
            if userInfo["NSApplicationLaunchUserNotificationKey"] != nil {
                // we get this notification at launch because it's too early to have
                // declared ourself a NSUserNotificationCenterDelegate
                NSLog("%@", "Launched via Notification interaction")
                //userNotificationCenter(NSUserNotificationCenter.default, didActivate: ourNotification)
                launchedViaURL = true
            }
        }
        // Prevent automatic relaunching at login on Lion+
        if NSApp.responds(to: #selector(NSApplication.disableRelaunchOnLogin)) {
            NSApp.disableRelaunchOnLogin()
        }
         
        // have the statuscontroller register for its own notifications
        statusController.registerForNotifications()
        
        // we need to let UNUserNotificationCenter know we
        // support Dock icon badges
        let center = UNUserNotificationCenter.current()
        center.requestAuthorization(options: [.badge], completionHandler: { _, _ in return })
        
        // user may have launched the app manually, or it may have
        // been launched by /usr/local/munki/managedsoftwareupdate
        // to display available updates, or via a munki: URL
        if !launchedViaURL {
            var lastcheck = pref("LastCheckDate") as? Date ?? Date.distantPast
            if thereAreUpdatesToBeForcedSoon(hours: 2) {
                // skip the check and just display the updates
                // by pretending the lastcheck is now
                lastcheck = Date()
            }
            if shouldAggressivelyNotifyAboutAppleUpdates() || shouldAggressivelyNotifyAboutMunkiUpdates() {
                // skip the check and just display the updates
                // by pretending the lastcheck is now
                lastcheck = Date()
            }
            let max_cache_age = pref("CheckResultsCacheSeconds") as? Int ?? 0
            if lastcheck.timeIntervalSinceNow * -1 > TimeInterval(max_cache_age) {
                // check for updates if the last check is over the
                // configured manualcheck cache age max.
                mainWindowController.checkForUpdates()
            } else if updateCheckNeeded() {
                //check for updates if we have optional items selected for install
                // or removal that have not yet been processed
                mainWindowController.checkForUpdates()
            }
        }
        // load the initial view only if we are not already loading something else.
        // enables launching the app to a specific panel, eg. from URL handler
        if !mainWindowController.webView.isLoading {
            mainWindowController.loadInitialView()
        }
    }
    
    func applicationWillFinishLaunching(_ notification: Notification) {
        // Installs URL handler for calls outside the app eg. web clicks
        let manager = NSAppleEventManager.shared()
        manager.setEventHandler(self,
                                andSelector: #selector(self.openURL(_:with:)),
                                forEventClass: AEEventClass(kInternetEventClass),
                                andEventID: AEEventID(kAEGetURL))

        // set ourself as a delegate for UNUserNotificationCenter notifications
        UNUserNotificationCenter.current().delegate = self
    }
        
    func applicationDidResignActive(_ notification: Notification) {
        if self.mainWindowController.forceFrontmost == true {
            NSApp.activate(ignoringOtherApps: true)
        }
    }
    
    func applicationDidBecomeActive(_ notification: Notification) {
        if self.backdropOnlyMode == true {
            // (re)launch Software Update prefs pane
            openSoftwareUpdatePrefsPane()
        }
    }

    func applicationWillTerminate(_ aNotification: Notification) {
        // Insert code here to tear down your application
    }
    
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        // Called if user selects 'Quit' from menu
        return self.mainWindowController.appShouldTerminate()
    }

    // MARK: UNUserNotificationCenterDelegate methods
    
    func userNotificationCenter(_ center: UNUserNotificationCenter,
             willPresent notification: UNNotification,
             withCompletionHandler completionHandler:
                @escaping (UNNotificationPresentationOptions) -> Void) {
        msc_log("MSC", "\(#function) called")
        // This should only be called when we're in the foreground, therefore
        // we should not present the notification
        completionHandler([])
    }
    
    func userNotificationCenter(_ center: UNUserNotificationCenter,
                didReceive response: UNNotificationResponse,
                withCompletionHandler completionHandler:
                   @escaping () -> Void) {
        msc_log("MSC", "\(#function) called")
        let userInfo = response.notification.request.content.userInfo
        if userInfo["action"] as? String ?? "" == "open_url" {
            let urlString = userInfo["value"] as? String ?? "munki://updates"
            msc_log("MSC", "Got user notification to open \(urlString)")
            if let url = URL(string: urlString) {
                mainWindowController.handleMunkiURL(url)
            }
            // we don't need any other notifications hanging around
            center.removeAllDeliveredNotifications()
        } else {
            msc_log("MSC", "Got user notification with unrecognized userInfo")
        }
        // Always call the completion handler when done.
        completionHandler()
    }
    
}

