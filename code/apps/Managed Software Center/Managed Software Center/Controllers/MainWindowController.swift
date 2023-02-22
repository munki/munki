//
//  MainWindowController.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 6/29/18.
//  Copyright © 2018-2023 The Munki Project. All rights reserved.
//

import Cocoa
import WebKit


class MainWindowController: NSWindowController, NSWindowDelegate, WKNavigationDelegate, WKScriptMessageHandler {
    
    var _alertedUserToOutstandingUpdates = false
    var _update_in_progress = false
    var managedsoftwareupdate_task = ""
    var cached_self_service = SelfService()
    var alert_controller = MSCAlertController()
    var htmlDir = ""
    var wkContentController = WKUserContentController()
    
    let sidebar_items = [
        ["title": "Software", "icon": "AllItemsTemplate"],
        ["title": "Categories", "icon": "toolbarCategoriesTemplate"],
        ["title": "My Items", "icon": "MyStuffTemplate"],
        ["title": "Updates", "icon": "updatesTemplate"]
    ]
    
    // status properties
    var _status_title = ""
    var stop_requested = false
    var user_warned_about_extra_updates = false
    var forceFrontmost = false
    
    var backdropWindows: [NSWindow] = []
    
    // Cocoa UI binding properties
    
    @IBOutlet weak var navigateBackButton: NSButton!
    @IBOutlet weak var progressSpinner: NSProgressIndicator!
    
    @IBOutlet weak var searchField: NSSearchField!
    
    @IBOutlet weak var sidebar: NSOutlineView!
    
    @IBOutlet weak var fullSidebar: NSVisualEffectView!
    
    @IBOutlet weak var navigateBackMenuItem: NSMenuItem!
    @IBOutlet weak var findMenuItem: NSMenuItem!
    @IBOutlet weak var softwareMenuItem: NSMenuItem!
    @IBOutlet weak var categoriesMenuItem: NSMenuItem!
    @IBOutlet weak var myItemsMenuItem: NSMenuItem!
    @IBOutlet weak var updatesMenuItem: NSMenuItem!
    @IBOutlet weak var reloadPageMenuItem: NSMenuItem!
    
    @IBOutlet weak var webViewContainer: NSView!
    @IBOutlet weak var webViewPlaceholder: NSView!
    var webView: WKWebView!

    override func windowDidLoad() {
        super.windowDidLoad()
    }

    @objc private func onItemClicked() {
        if 0 ... sidebar_items.count ~= sidebar.clickedRow {
                clearSearchField()
                switch sidebar.clickedRow {
                    case 0:
                        loadAllSoftwarePage(self)
                    case 1:
                        loadCategoriesPage(self)
                    case 2:
                        loadMyItemsPage(self)
                    case 3:
                        loadUpdatesPage(self)
                    default:
                        loadUpdatesPage(self)
            }
        }
    }
    
    func appShouldTerminate() -> NSApplication.TerminateReply {
        // called by app delegate
        // when it receives applicationShouldTerminate:
        if getUpdateCount() == 0 {
            // no pending updates
            return .terminateNow
        }
        if !shouldFilterAppleUpdates() && appleUpdatesMustBeDoneWithSystemPreferences() {
            if shouldAggressivelyNotifyAboutAppleUpdates(days: 2) {
                if !currentPageIsUpdatesPage() {
                    loadUpdatesPage(self)
                }
                alert_controller.alertToAppleUpdates()
                setFilterAppleUpdates(true)
                return .terminateCancel
            }
        }
        if currentPageIsUpdatesPage() {
            if (!thereAreUpdatesToBeForcedSoon() && !shouldAggressivelyNotifyAboutMunkiUpdates()) {
                // We're already at the updates view, so user is aware of the
                // pending updates, so OK to just terminate
                // (unless there are some updates to be forced soon)
                return .terminateNow
            }
            if _alertedUserToOutstandingUpdates {
                if (thereAreUpdatesToBeForcedSoon() || shouldAggressivelyNotifyAboutMunkiUpdates()) {
                    // user keeps avoiding; let's try at next logout or restart
                    writeInstallAtStartupFlagFile(skipAppleUpdates: false)
                }
                return .terminateNow
            }
        }
        // we have pending updates and we have not yet warned the user
        // about them
        alert_controller.alertToPendingUpdates(self)
        return .terminateCancel
    }
    
    func currentPageIsUpdatesPage() -> Bool {
        // return true if current tab selected is Updates
        return sidebar.selectedRow == 3
    }

    func newTranslucentWindow(screen: NSScreen) -> NSWindow {
        // makes a translucent masking window we use to prevent interaction with
        // other apps
        var windowRect = screen.frame
        windowRect.origin = NSMakePoint(0.0, 0.0)
        let thisWindow = NSWindow(
            contentRect: windowRect,
            styleMask: .borderless,
            backing: .buffered,
            defer: false,
            screen: screen
        )
        thisWindow.level = .normal
        thisWindow.backgroundColor = NSColor.black.withAlphaComponent(0.50)
        thisWindow.isOpaque = false
        thisWindow.ignoresMouseEvents = false
        thisWindow.alphaValue = 0.0
        thisWindow.orderFrontRegardless()
        thisWindow.animator().alphaValue = 1.0
        return thisWindow
    }
    
    func displayBackdropWindows() {
        for screen in NSScreen.screens {
            let newWindow = newTranslucentWindow(screen: screen)
            // add to our backdropWindows array so a reference stays around
            backdropWindows.append(newWindow)
        }
    }
    
    func makeUsUnobnoxious() {
        // reverse all the obnoxious changes
        msc_log("msc", "end_obnoxious_mode")
        
        // remove obnoxious presentation options
        NSApp.presentationOptions = NSApp.currentSystemPresentationOptions.subtracting(
            NSApplication.PresentationOptions([.hideDock, .disableHideApplication, .disableProcessSwitching, .disableForceQuit]))
        
        for window in self.backdropWindows {
            window.orderOut(self)
        }
        if let window = self.window {
            window.collectionBehavior = .fullScreenPrimary
            // turn .closable, .miniaturizable, .resizable back on
            let addedStyleMask : NSWindow.StyleMask = [.closable, .miniaturizable, .resizable]
            window.styleMask = window.styleMask.union(addedStyleMask)
            window.level = .normal
        }
        self.forceFrontmost = false
        // enable/disable controls as needed
        determineIfUpdateOnlyWindowOrUpdateAndOptionalWindowMode()
        reloadPageMenuItem.isEnabled = true
    }
    
    func makeUsObnoxious() {
        // makes this app and window impossible(?)/difficult to ignore
        msc_log("msc", "start_obnoxious_mode")
        
        // make sure we're frontmost
        NSApp.activate(ignoringOtherApps: true)
        
        // make it very difficult to switch away from this app
        NSApp.presentationOptions = NSApp.currentSystemPresentationOptions.union(
            NSApplication.PresentationOptions([.hideDock, .disableHideApplication, .disableProcessSwitching, .disableForceQuit]))
        
        // alter some window properties to make the window harder to ignore
        if let window = self.window {
            window.center()
            window.collectionBehavior = .fullScreenNone
            window.styleMask = window.styleMask.subtracting(
                NSWindow.StyleMask([.miniaturizable, .resizable]))
            window.level = .floating
        }
        
        // disable all of the other controls
        updatesOnlyWindowMode()
        reloadPageMenuItem.isEnabled = false
        loadUpdatesPage(self)
        
        // set flag to cause us to always be brought to front
        self.forceFrontmost = true
        
        // create translucent windows to mask all other apps
        displayBackdropWindows()
    }
    
    func weShouldBeObnoxious() -> Bool {
        // returns a Bool to let us know if we should enter obnoxiousMode
        if thereAreUpdatesToBeForcedSoon() {
            return true
        }
        if shouldAggressivelyNotifyAboutMunkiUpdates() {
            return true
        }
        if shouldAggressivelyNotifyAboutAppleUpdates() {
            if userIsAdmin() || !userMustBeAdminToInstallAppleUpdates() {
                // only be obnoxious if the user can actually _do_ something
                return true
            }
        }
        return false
    }
    
    func updatesOnlyWindowMode() {
        findMenuItem.isHidden = true
        softwareMenuItem.isHidden = true
        categoriesMenuItem.isHidden = true
        myItemsMenuItem.isHidden = true
        updatesMenuItem.isHidden = true
        fullSidebar.isHidden = true
        webViewContainer.frame.origin.x = -1
        webViewContainer.frame.size.width = self.window!.frame.width
        navigateBackButton.frame.origin.x = 90
        // adjusts window controls on newer OSs
        if #available(macOS 10.13, *) {
            let customToolbar = NSToolbar()
            customToolbar.showsBaselineSeparator = false
            self.window?.titleVisibility = .hidden
            self.window?.toolbar = customToolbar
        }
        loadUpdatesPage(self)
    }
    
    func updatesAndOptionalWindowMode() {
        findMenuItem.isHidden = false
        softwareMenuItem.isHidden = false
        categoriesMenuItem.isHidden = false
        myItemsMenuItem.isHidden = false
        updatesMenuItem.isHidden = false
        fullSidebar.isHidden = false
        webViewContainer.frame.origin.x = 220
        navigateBackButton.frame.origin.x = 17
        webViewContainer.frame.size.width = self.window!.frame.width - fullSidebar.frame.width
        // adjusts window controls on newer OSs
        if #available(macOS 10.13, *) {
            let customToolbar = NSToolbar()
            customToolbar.showsBaselineSeparator = false
            self.window?.titleVisibility = .hidden
            self.window?.toolbar = customToolbar
        }
    }
    
    func moveDirectlyToUpdatesPageIfNeeded() {
        if getUpdateCount() > 0 || !getProblemItems().isEmpty {
            loadUpdatesPage(self)
        }
    }
    
    func determineIfUpdateOnlyWindowOrUpdateAndOptionalWindowMode() {
        // if we have no optional_items set MSC to show updates only
        // if updates available go right to update screen
        if optionalInstallsExist() {
            updatesAndOptionalWindowMode()
            moveDirectlyToUpdatesPageIfNeeded()
        } else {
            updatesOnlyWindowMode()
        }
    }
    
    
    func loadInitialView() {
        // Called by app delegate from applicationDidFinishLaunching:
        if optionalInstallsExist() {
            loadAllSoftwarePage(self)
        } else {
            loadUpdatesPage(self)
        }
        determineIfUpdateOnlyWindowOrUpdateAndOptionalWindowMode()
        cached_self_service = SelfService()
    }

    func toolBarItemIsHighlighted(_ item: NSToolbarItem) -> Bool {
        if let button = item.view as? NSButton {
            return (button.state == .on)
        }
        return false
    }

    func setHighlightFor(item: NSToolbarItem, doHighlight: Bool) {
        if let button = item.view as? NSButton {
            button.state = (doHighlight ? .on : .off)
        }
    }
    
    func highlightToolbarButtons(_ nameToHighlight: String) {
        for (index, item) in sidebar_items.enumerated() {
            if nameToHighlight == item["title"] {
                sidebar.selectRowIndexes(IndexSet(integer: index), byExtendingSelection: false)
            }
        }
    }
    
    func clearSearchField() {
        self.searchField.stringValue = ""
    }
    
    
    func munkiStatusSessionEnded(withStatus sessionResult: Int, errorMessage: String) {
        // Called by StatusController when a Munki session ends
        msc_debug_log("MunkiStatus session ended: \(sessionResult)")
        if !errorMessage.isEmpty {
            msc_debug_log("MunkiStatus session error message: \(errorMessage)")
        }
        msc_debug_log("MunkiStatus session type: \(managedsoftwareupdate_task)")
        let tasktype = managedsoftwareupdate_task
        managedsoftwareupdate_task = ""
        _update_in_progress = false
        
        // The managedsoftwareupdate run will have changed state preferences
        // in ManagedInstalls.plist. Load the new values.
        reloadPrefs()
        if tasktype ==  "" {
            // probably a background session, but not one initiated by the user here
            resetAndReload()
            return
        }
        let lastCheckResult = pref("LastCheckResult") as? Int ?? 0
        if sessionResult != 0 || lastCheckResult < 0 {
            var alertMessageText = NSLocalizedString(
                "Update check failed", comment: "Update Check Failed title")
            var detailText = ""
            if tasktype == "installwithnologout" {
                msc_log("MSC", "cant_update", msg: "Install session failed")
                alertMessageText = NSLocalizedString(
                    "Install session failed", comment: "Install Session Failed title")
            }
            if sessionResult == -1 {
                // connection was dropped unexpectedly
                msc_log("MSC", "cant_update", msg: "unexpected process end")
                detailText = NSLocalizedString(
                    ("There is a configuration problem with the managed " +
                     "software installer. The process ended unexpectedly. " +
                     "Contact your systems administrator."),
                    comment: "Unexpected Session End message")
            } else if sessionResult == -2 {
                // session never started
                msc_log("MSC", "cant_update", msg: "process did not start")
                detailText = NSLocalizedString(
                    ("There is a configuration problem with the managed " +
                     "software installer. Could not start the process. " +
                     "Contact your systems administrator."),
                    comment: "Could Not Start Session message")
            } else if lastCheckResult == -1 {
                // server not reachable
                msc_log("MSC", "cant_update", msg: "cannot contact server")
                detailText = NSLocalizedString(
                    ("Managed Software Center cannot contact the update " +
                     "server at this time.\n" +
                     "Try again later. If this situation continues, " +
                     "contact your systems administrator."),
                    comment: "Cannot Contact Server detail")
            } else if lastCheckResult == -2 {
                // preflight failed
                msc_log("MSC", "cant_update", msg: "failed preflight")
                detailText = NSLocalizedString(
                    ("Managed Software Center cannot check for updates now.\n" +
                     "Try again later. If this situation continues, " +
                     "contact your systems administrator."),
                    comment: "Failed Preflight Check detail")
            }
            if !errorMessage.isEmpty {
                detailText = "\(detailText)\n\n\(errorMessage)"
            }
            // show the alert sheet
            if let thisWindow = self.window {
                thisWindow.makeKeyAndOrderFront(self)
                if let attachedSheet = thisWindow.attachedSheet {
                    // there's an existing sheet open; close it first
                    thisWindow.endSheet(attachedSheet)
                }
            }
            let alert = NSAlert()
            alert.messageText = alertMessageText
            alert.informativeText = detailText
            alert.addButton(withTitle: NSLocalizedString("OK", comment:"OK button title"))
            alert.beginSheetModal(for: self.window!, completionHandler: { (modalResponse) -> Void in
                self.resetAndReload()
            })
            return
        }
        if tasktype == "checktheninstall" {
            clearMunkiItemsCache()
            // possibly check again if choices have changed
            updateNow()
            return
        }
        
        // all done checking and/or installing: display results
        resetAndReload()
        
        if updateCheckNeeded() {
            // more stuff pending? Let's do it...
            updateNow()
        }
    }
            
    func resetAndReload() {
        // Clear cached values, reload from disk. Display any changes.
        // Typically called soon after a managedsoftwareupdate session completes
        msc_debug_log("resetAndReload method called")
        // need to clear out cached data
        clearMunkiItemsCache()
        // recache SelfService choices
        cached_self_service = SelfService()
        // copy any new custom client resources
        get_custom_resources()
        // pending updates may have changed
        _alertedUserToOutstandingUpdates = false
        // enable/disable controls as needed
        determineIfUpdateOnlyWindowOrUpdateAndOptionalWindowMode()
        // what page are we currently viewing?
        let page_url = webView.url
        let filename = page_url?.lastPathComponent ?? ""
        let name = (filename as NSString).deletingPathExtension
        let key = name.components(separatedBy: "-")[0]
        switch key {
        case "detail", "updatedetail":
            // item detail page; just rebuild and reload it
            load_page(filename)
        case "category", "filter", "developer":
            // optional item list page
            updateListPage()
        case "categories":
            // categories page
            updateCategoriesPage()
        case "myitems":
            // my items page
            updateMyItemsPage()
        case "updates":
            // updates page; just rebuild and reload it
            load_page("updates.html")
            if !shouldAggressivelyNotifyAboutMunkiUpdates() {
                _alertedUserToOutstandingUpdates = true
            }
        default:
            // should never get here
            msc_debug_log("Unexpected value for page name: \(filename)")
        }
        // update count might have changed
        displayUpdateCount()
    }
    
    // Begin NSWindowDelegate methods
    
    func windowShouldClose(_ sender: NSWindow) -> Bool {
        // NSWindowDelegate method called when user closes a window
        // for us, closing the main window should be the same as quitting
        NSApp.terminate(self)
        return false
    }
    
    func windowDidBecomeMain(_ notification: Notification) {
        // Our window was activated, make sure controls enabled as needed
        sidebar.action = #selector(onItemClicked)
    }
    
    func windowDidResignMain(_ notification: Notification) {
        // Our window was deactivated, make sure controls enabled as needed
    }
    
    // End NSWindowDelegate methods
    
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
    
    func addJSmessageHandlers() {
        // define messages JavaScript can send us
        wkContentController.add(self, name: "openExternalLink")
        wkContentController.add(self, name: "installButtonClicked")
        wkContentController.add(self, name: "myItemsButtonClicked")
        wkContentController.add(self, name: "actionButtonClicked")
        wkContentController.add(self, name: "changeSelectedCategory")
        wkContentController.add(self, name: "updateOptionalInstallButtonClicked")
        wkContentController.add(self, name: "updateOptionalInstallButtonFinishAction")
    }

    func insertWebView() {
        // replace our webview placeholder with the real one
        if let superview = webViewPlaceholder?.superview {
            // define webview configuration
            let webConfiguration = WKWebViewConfiguration()
            addJSmessageHandlers()
            webConfiguration.userContentController = wkContentController
            webConfiguration.preferences.javaScriptEnabled = true
            webConfiguration.preferences.javaEnabled = false
            if UserDefaults.standard.bool(forKey: "developerExtrasEnabled") {
                webConfiguration.preferences.setValue(true, forKey: "developerExtrasEnabled")
            }
            // init our webview
            let replacementWebView = MSCWebView(frame: webViewPlaceholder.frame, configuration: webConfiguration)
            replacementWebView.autoresizingMask = webViewPlaceholder.autoresizingMask
            //replacementWebView.translatesAutoresizingMaskIntoConstraints = false  // we'll add them later, by hand
            replacementWebView.allowsBackForwardNavigationGestures = false
            if #available(OSX 10.12, *) {
                replacementWebView.setValue(false, forKey: "drawsBackground")
            }
            // replace the placeholder in the window view with the real webview
            superview.replaceSubview(webViewPlaceholder, with: replacementWebView)
            webView = replacementWebView
        }
    }
    
    override func awakeFromNib() {
        // Stuff we need to initialize when we start
        super.awakeFromNib()
        insertWebView()
        webView.navigationDelegate = self
        setNoPageCache()
        alert_controller = MSCAlertController()
        alert_controller.window = self.window
        htmlDir = html_dir()
        registerForNotifications()
    }
    
    func registerForNotifications() {
        // register for notification messages
        let nc = DistributedNotificationCenter.default()
        // register for notification if user switches to/from Dark Mode
        nc.addObserver(self,
                       selector: #selector(self.interfaceThemeChanged(_:)),
                       name: NSNotification.Name(
                        rawValue: "AppleInterfaceThemeChangedNotification"),
                       object: nil,
                       suspensionBehavior: .deliverImmediately)
        // register for notification if available updates change
        nc.addObserver(self,
                       selector: #selector(self.updateAvailableUpdates(_:)),
                       name: NSNotification.Name(
                            rawValue: "com.googlecode.munki.managedsoftwareupdate.updateschanged"),
                       object: nil,
                       suspensionBehavior: .deliverImmediately)
        //register for notification to display a logout warning
        // from the logouthelper
        nc.addObserver(self,
                       selector: #selector(self.forcedLogoutWarning(_:)),
                       name: NSNotification.Name(
                            rawValue: "com.googlecode.munki.ManagedSoftwareUpdate.logoutwarn"),
                       object: nil,
                       suspensionBehavior: .deliverImmediately)
    }
    
    @objc func interfaceThemeChanged(_ notification: Notification) {
        // Called when user switches to/from Dark Mode
        let interface_theme = interfaceTheme()
        // call JavaScript in the webview to update the appearance CSS
        webView.evaluateJavaScript("changeAppearanceModeTo('\(interface_theme)')")
    }
    
    @objc func updateAvailableUpdates(_ notification: Notification) {
        // If a Munki session is not in progress (that we know of) and
        // we get a updateschanged notification, resetAndReload
        msc_debug_log("Managed Software Center got update notification")
        if !_update_in_progress {
            resetAndReload()
        }
    }
    
    @objc func forcedLogoutWarning(_ notification: Notification) {
        // Received a logout warning from the logouthelper for an
        // upcoming forced install
        msc_debug_log("Managed Software Center got forced logout warning")
        // got a notification of an upcoming forced install
        // switch to updates view, then display alert
        loadUpdatesPage(self)
        alert_controller.forcedLogoutWarning(notification)
    }
    
    @objc func checkForUpdates(suppress_apple_update_check: Bool = false) {
        // start an update check session
        if _update_in_progress {
            return
        }
        do {
            try startUpdateCheck(suppress_apple_update_check)
        } catch {
            munkiStatusSessionEnded(withStatus: -2, errorMessage: "\(error)")
            return
        }
        _update_in_progress = true
        //setFilterAppleUpdates(false)
        //setFilterStagedOSUpdate(false)
        displayUpdateCount()
        managedsoftwareupdate_task = "manualcheck"
        if let status_controller = (NSApp.delegate as? AppDelegate)?.statusController {
            status_controller.startMunkiStatusSession()
        }
        markRequestedItemsAsProcessing()
    }
    
    @objc func checkForUpdatesSkippingAppleUpdates() {
        checkForUpdates(suppress_apple_update_check: true)
    }
    
    @IBAction func reloadPage(_ sender: Any) {
        // User selected Reload page menu item. Reload the page and kick off an updatecheck
        msc_log("user", "reload_page_menu_item_selected")
        setFilterAppleUpdates(false)
        setFilterStagedOSUpdate(false)
        checkForUpdates()
        URLCache.shared.removeAllCachedResponses()
        webView.reload(sender)
    }
    
    func kickOffInstallSession() {
        // start an update install/removal session
        
        // check for need to logout, restart, firmware warnings
        // warn about blocking applications, etc...
        // then start an update session
        if updatesRequireRestart() || updatesRequireLogout() {
            if !currentPageIsUpdatesPage() {
                // switch to updates view
                loadUpdatesPage(self)
            } else {
                // we're already displaying the available updates
                _alertedUserToOutstandingUpdates = true
            }
            // warn about need to logout or restart
            alert_controller.confirmUpdatesAndInstall()
        } else {
            if alert_controller.alertedToBlockingAppsRunning() {
                loadUpdatesPage(self)
                return
            }
            if alert_controller.alertedToRunningOnBatteryAndCancelled() {
                loadUpdatesPage(self)
                return
            }
            if alert_controller.alertedToNotVolumeOwner() {
                clearMunkiItemsCache()
                setFilterStagedOSUpdate(true)
                setFilterAppleUpdates(false)
                loadUpdatesPage(self)
                return
            }
            if alert_controller.alertedToStagedOSUpgradeAndCancelled() {
                clearMunkiItemsCache()
                setFilterStagedOSUpdate(true)
                setFilterAppleUpdates(false)
                loadUpdatesPage(self)
                return
            }
            managedsoftwareupdate_task = ""
            msc_log("user", "install_without_logout")
            _update_in_progress = true
            displayUpdateCount()
            if let status_controller = (NSApp.delegate as? AppDelegate)?.statusController {
                status_controller._status_message = NSLocalizedString(
                    "Updating...", comment: "Updating message")
            }
            do {
                try justUpdate()
            } catch {
                msc_debug_log("Error starting install session: \(error)")
                munkiStatusSessionEnded(withStatus: -2, errorMessage: "\(error)")
            }
            managedsoftwareupdate_task = "installwithnologout"
            if let status_controller = (NSApp.delegate as? AppDelegate)?.statusController {
                status_controller.startMunkiStatusSession()
            }
            markPendingItemsAsInstalling()
        }
    }
    
    func markPendingItemsAsInstalling() {
        // While an install/removal session is happening, mark optional items
        // that are being installed/removed with the appropriate status
        msc_debug_log("marking pendingItems as installing")
        let install_info = getInstallInfo()
        let managed_installs = install_info["managed_installs"] as? [PlistDict] ?? [PlistDict]()
        let removals = install_info["removals"] as? [PlistDict] ?? [PlistDict]()
        let items_to_be_installed_names = managed_installs.filter(
            {$0["name"] != nil}).map({$0["name"] as! String})
        let items_to_be_removed_names = removals.filter(
            {$0["name"] != nil}).map({$0["name"] as! String})
        for name in items_to_be_installed_names {
            // remove names for user selections since we are installing
            user_install_selections.remove(name)
        }
        for name in items_to_be_removed_names {
            // remove names for user selections since we are removing
            user_removal_selections.remove(name)
        }
        for item in getOptionalInstallItems() {
            var new_status = ""
            if let name = item["name"] as? String {
                if items_to_be_installed_names.contains(name) {
                    msc_debug_log("Setting status for \(name) to \"installing\"")
                    new_status = "installing"
                } else if items_to_be_removed_names.contains(name) {
                    msc_debug_log("Setting status for \(name) to \"removing\"")
                    new_status = "removing"
                }
            }
            if !new_status.isEmpty {
                item["status"] = new_status
                updateDOMforOptionalItem(item)
            }
        }
    }
    
    func markRequestedItemsAsProcessing() {
        // When an update check session is happening, mark optional items
        // that have been requested as processing
        msc_debug_log("marking requested items as processing")
        for item in getOptionalInstallItems() {
            var new_status = ""
            let name = item["name"] as? String ?? ""
            if item["status"] as? String == "install-requested" {
                msc_debug_log("Setting status for \(name) to \"downloading\"")
                new_status = "downloading"
            } else if item["status"] as? String == "removal-requested" {
                msc_debug_log("Setting status for \(name) to \"preparing-removal\"")
                new_status = "preparing-removal"
            }
            if !new_status.isEmpty {
                item["status"] = new_status
                updateDOMforOptionalItem(item)
            }
        }
    }
    
    func updateNow() {
        /* If user has added to/removed from the list of things to be updated,
         run a check session. If there are no more changes, proceed to an update
         installation session if items to be installed/removed are exclusively
         those selected by the user in this session */
        if stop_requested {
            // reset the flag
            stop_requested = false
            resetAndReload()
            return
        }
        if updateCheckNeeded() {
            // any item status changes that require an update check?
            msc_debug_log("updateCheck needed")
            msc_log("user", "check_then_install_without_logout")
            // since we are just checking for changed self-service items
            // we can suppress the Apple update check
            _update_in_progress = true
            displayUpdateCount()
            do {
                try startUpdateCheck(true)
            } catch {
                msc_debug_log("Error starting check-then-install session: \(error)")
                munkiStatusSessionEnded(withStatus: -2, errorMessage: "\(error)")
                return
            }
            managedsoftwareupdate_task = "checktheninstall"
            if let status_controller = (NSApp.delegate as? AppDelegate)?.statusController {
                status_controller.startMunkiStatusSession()
            }
            markRequestedItemsAsProcessing()
        } else if !_alertedUserToOutstandingUpdates && updatesContainNonUserSelectedItems() {
            // current list of updates contains some not explicitly chosen by
            // the user
            msc_debug_log("updateCheck not needed, items require user approval")
            _update_in_progress = false
            displayUpdateCount()
            loadUpdatesPage(self)
            alert_controller.alertToExtraUpdates()
        } else {
            msc_debug_log("updateCheck not needed")
            _alertedUserToOutstandingUpdates = false
            _status_title = NSLocalizedString(
                "Update in progress.",
                comment: "Update In Progress primary text") + ".."
            kickOffInstallSession()
            makeUsUnobnoxious()
        }
    }
    
    func getUpdateCount() -> Int {
        // Get the count of effective updates
        if _update_in_progress {
            return 0
        }
        return getEffectiveUpdateList().count
    }
    
    func displayUpdateCount() {
        // Display the update count as a badge in the window toolbar
        // and as an icon badge in the Dock
        let updateCount = getUpdateCount()
        
        var cellView:MSCTableCellView?

        if let view = self.sidebar.rowView(atRow: 3, makeIfNecessary: false) {
            cellView = view.view(atColumn: 0) as? MSCTableCellView
        }

        if updateCount > 0 {
            NSApp.dockTile.badgeLabel = String(updateCount)
            cellView?.badge.title = String(updateCount)
            cellView?.badge.isHidden = false
        } else {
            NSApp.dockTile.badgeLabel = nil
            cellView?.badge.isHidden = true
        }
    }
    
    func updateMyItemsPage() {
        // Update the "My Items" page with current data.
        // Modifies the DOM to avoid ugly browser refresh
        let myitems_rows = buildMyItemsRows()
        setInnerHTML(myitems_rows, elementID: "my_items_rows")
    }
    
    func updateCategoriesPage() {
        // Update the Categories page with current data.
        // Modifies the DOM to avoid ugly browser refresh
        let items_html = buildCategoryItemsHTML()
        setInnerHTML(items_html, elementID: "optional_installs_items")
    }
    
    func updateListPage() {
        // Update the optional items list page with current data.
        // Modifies the DOM to avoid ugly browser refresh
        let page_url = webView.url
        let filename = page_url?.lastPathComponent ?? ""
        let name = ((filename as NSString).deletingPathExtension) as String
        let components = name.split(separator: "-", maxSplits: 1, omittingEmptySubsequences: false)
        let key = String(components[0])
        let value = String(components.count > 1 ? components[1] : "")
        var category = ""
        var our_filter = ""
        var developer = ""
        if key == "category" {
             if value != "all" {
                category = value
             }
        } else if key == "filter" {
            our_filter = value
        } else if key == "developer" {
            developer = value
        } else {
            msc_debug_log("updateListPage unexpected error: current page filename is \(filename)")
            return
        }
        msc_debug_log("updating software list page with " +
                      "category: '\(category)', developer: '\(developer)', " +
                      "filter: '\(our_filter)'")
        let items_html = buildListPageItemsHTML(
            category: category, developer: developer, filter: our_filter)
        setInnerHTML(items_html, elementID: "optional_installs_items")
    }
    
    func load_page(_ url_fragment: String) {
        // Tells the WebView to load the appropriate page
        msc_debug_log("load_page request for \(url_fragment)")
        
        let html_file = NSString.path(withComponents: [htmlDir, url_fragment])
        let request = URLRequest(url: URL(fileURLWithPath: html_file),
                                 cachePolicy: .reloadIgnoringLocalCacheData,
                                 timeoutInterval: TimeInterval(10.0))
        webView.load(request)
        if url_fragment == "updates.html" {
            // clear all earlier update notifications
            removeAllDeliveredNotifications()
            // record that the user has been presented pending updates
            if !_update_in_progress && !shouldAggressivelyNotifyAboutMunkiUpdates() && !thereAreUpdatesToBeForcedSoon() {
                _alertedUserToOutstandingUpdates = true
            }
        }
    }
    
    func removeAllDeliveredNotifications() {
        // calls munki-notifier to remove all delivered notifications
        // we can't remove them directly since we didn't actually post them
        // so we can't use
        // NSUserNotificationCenter.default.removeAllDeliveredNotifications()
        let munkiNotifierPath = Bundle.main.path(forResource: "munki-notifier", ofType: "app")
        if let munkiNotifierPath = munkiNotifierPath {
            NSLog("munki-notifier path: %@", munkiNotifierPath as String)
            let command = "/usr/bin/open"
            let args = ["-a", munkiNotifierPath, "--args", "-clear"]
            _ = exec(command, args: args)
        }
    }
    
    func handleMunkiURL(_ url: URL) {
        // Display page associated with munki:// url
        NSLog("Handling URL: %@", url.absoluteString)
        guard url.scheme == "munki" else {
            msc_debug_log("URL \(url) has unsupported scheme")
            return
        }
        guard let host = url.host else {
            msc_debug_log("URL \(url) has invalid format")
            return
        }
        var filename = unquote(host)
        // append ".html" if absent
        if !(filename.hasSuffix(".html")) {
            filename += ".html"
        }
        // if the user has minimized the main window, deminiaturize it
        if let window = self.window {
            if window.isMiniaturized {
                window.deminiaturize(self)
            }
        }
        // try to build and load the page
        if filename == "notify.html" {
            //resetAndReload()
            load_page("updates.html")
            if !_update_in_progress && getUpdateCount() > 0 {
                // we're notifying about pending updates. We might need to be obnoxious about it
                if let window = self.window {
                    // don't let people move the window mostly off-screen so
                    // they can ignore it
                    window.center()
                }
                if weShouldBeObnoxious() {
                    NSLog("%@", "Entering obnoxious mode")
                    makeUsObnoxious()
                }
            }
        } else {
            load_page(filename)
        }
    }

    func setNoPageCache() {
        /* We disable the back/forward page cache because
         we generate each page dynamically; we want things
         that are changed in one page view to be reflected
         immediately in all page views */
        // TO-DO: figure this out for WKWebView
        /*let identifier = "com.googlecode.munki.ManagedSoftwareCenter"
        if let prefs = WebPreferences(identifier: identifier) {
            prefs.usesPageCache = false
            webView.preferencesIdentifier = identifier
        }*/
    }
    
    func clearCache() {
        if #available(OSX 10.10, *) {
            let os_vers = OperatingSystemVersion(majorVersion: 10, minorVersion: 11, patchVersion: 0)
            if ProcessInfo().isOperatingSystemAtLeast(os_vers) {
                let cacheDataTypes = Set([WKWebsiteDataTypeDiskCache, WKWebsiteDataTypeMemoryCache])
                let dateFrom = Date.init(timeIntervalSince1970: 0)
                WKWebsiteDataStore.default().removeData(ofTypes: cacheDataTypes, modifiedSince: dateFrom, completionHandler: {})
                return
            }
        }
        // Fallback on earlier versions
        URLCache.shared.removeAllCachedResponses()
    }

    // WKNavigationDelegateMethods
    
    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if let url = navigationAction.request.url {
            msc_debug_log("Got load request for \(url)")
            if navigationAction.targetFrame == nil {
                // new window target
                // open link in default browser instead of in our app's WebView
                NSWorkspace.shared.open(url)
                decisionHandler(.cancel)
                return
            }
        }
        if let url = navigationAction.request.url, let scheme = url.scheme {
            msc_debug_log("Got URL scheme: \(scheme)")
            if scheme == "munki" {
                handleMunkiURL(url)
                decisionHandler(.cancel)
                return
            }
            if scheme == "mailto" || scheme == "http" || scheme == "https" {
                // open link in default mail client since WKWebView doesn't
                // forward these links natively
                NSWorkspace.shared.open(url)
                decisionHandler(.cancel)
                return
            }
            if url.scheme == "file" {
                // if this is a MSC page, generate it!
                if url.deletingLastPathComponent().path == htmlDir {
                    let filename = url.lastPathComponent
                    do {
                        try buildPage(filename)
                    } catch {
                        msc_debug_log(
                            "Could not build page for \(filename): \(error)")
                    }
                }
            }
        }
        decisionHandler(.allow)
    }
    
    func webView(_ webView: WKWebView,
                 decidePolicyFor navigationResponse: WKNavigationResponse,
                 decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        if !(navigationResponse.canShowMIMEType) {
            if let url = navigationResponse.response.url {
                // open link in default browser instead of in our app's WebView
                NSWorkspace.shared.open(url)
                decisionHandler(.cancel)
                return
            }
        }
        decisionHandler(.allow)
    }
    
    func webView(_ webView: WKWebView,
                 didStartProvisionalNavigation navigation: WKNavigation!) {
        // Animate progress spinner while we load a page and highlight the
        // proper toolbar button
        progressSpinner.startAnimation(self)
        if let main_url = webView.url {
            let pagename = main_url.lastPathComponent
            msc_debug_log("Requested pagename is \(pagename)")
            if (pagename == "category-all.html" ||
                pagename.hasPrefix("detail-") ||
                pagename.hasPrefix("filter-") ||
                pagename.hasPrefix("developer-")) {
                highlightToolbarButtons("Software")
            } else if pagename == "categories.html" || pagename.hasPrefix("category-") {
                highlightToolbarButtons("Categories")
            } else if pagename == "myitems.html" {
                highlightToolbarButtons("My Items")
            } else if pagename == "updates.html" || pagename.hasPrefix("updatedetail-") {
                highlightToolbarButtons("Updates")
            } else {
                // no idea what type of item it is
                highlightToolbarButtons("")
            }
        }
    }
    
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        // react to end of displaying a new page
        progressSpinner.stopAnimation(self)
        clearCache()
        let allowNavigateBack = webView.canGoBack
        let page_url = webView.url
        let filename = page_url?.lastPathComponent ?? ""
        let onMainPage = (
            ["category-all.html", "categories.html", "myitems.html", "updates.html"].contains(filename))
        navigateBackButton.isHidden = !allowNavigateBack || onMainPage
        navigateBackMenuItem.isEnabled = (allowNavigateBack && !onMainPage)
    }
    
    func webView(_ webView: WKWebView,
                 didFail navigation: WKNavigation!,
                 withError error: Error) {
        // Stop progress spinner and log error
        progressSpinner.stopAnimation(self)
        msc_debug_log("Committed load error: \(error)")
    }
    
    func webView(_ webView: WKWebView,
                 didFailProvisionalNavigation navigation: WKNavigation!,
                 withError error: Error) {
        // Stop progress spinner and log
        progressSpinner.stopAnimation(self)
        msc_debug_log("Provisional load error: \(error)")
        do {
            let files = try FileManager.default.contentsOfDirectory(atPath: htmlDir)
            msc_debug_log("Files in html_dir: \(files)")
        } catch {
            // ignore
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
    
    func displayPreInstallUninstallAlert(_ alert: PlistDict, action: @escaping (String)->Void, item: String) {
        // Display an alert sheet before processing item install/upgrade
        // or uninstall
        let defaultAlertTitle = NSLocalizedString(
            "Attention", comment:"Pre Install Uninstall Upgrade Alert Title")
        let defaultAlertDetail = NSLocalizedString(
            "Some conditions apply to this software. " +
            "Please contact your administrator for more details",
            comment: "Pre Install Uninstall Upgrade Alert Detail")
        let defaultOKLabel = NSLocalizedString(
            "OK", comment: "OK button title")
        let defaultCancelLabel = NSLocalizedString(
            "Cancel", comment: "Cancel button title/short action text")
        
        let alertTitle = alert["alert_title"] as? String ?? defaultAlertTitle
        let alertDetail = alert["alert_detail"] as? String ?? defaultAlertDetail
        let OKLabel = alert["ok_label"] as? String ?? defaultOKLabel
        let cancelLabel = alert["cancel_label"] as? String ?? defaultCancelLabel
        
        // show the alert sheet
        self.window?.makeKeyAndOrderFront(self)
        let alert = NSAlert()
        alert.messageText = alertTitle
        alert.informativeText = alertDetail
        alert.addButton(withTitle: cancelLabel)
        alert.addButton(withTitle: OKLabel)
        alert.beginSheetModal(for: self.window!,
                              completionHandler: ({ (modalResponse) -> Void in
            if modalResponse == .alertFirstButtonReturn {
                // default is to cancel!
                msc_log("user", "alert_canceled")
            } else if modalResponse == .alertSecondButtonReturn {
                msc_log("user", "alert_accepted")
                // run our completion function
                action(item)
            }
        }))
    }
    
    func actionButtonPerformAction(_ item_name: String) {
        // Perform the action requested when clicking the action button
        // in the list or detail view
        if let item = optionalItem(forName: item_name) {
            let prior_status = item["status"] as? String ?? ""
            if !update_status_for_item(item) {
                // there was a problem, can't continue
                return
            }
            let current_status = item["status"] as? String ?? ""
            //msc_log("user", "action_button_\(current_status)", item_name)
            displayUpdateCount()
            updateDOMforOptionalItem(item)
            
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
        } else {
            msc_debug_log(
                "User clicked Install/Upgrade/Removal/Cancel button " +
                "in the list or detail view")
            msc_debug_log("Can't find item: \(item_name)")
            return
        }
    }
    
    func update_status_for_item(_ item: OptionalItem) -> Bool {
        /* Attempts to update an item's status; displays an error dialog
         if SelfServeManifest is not writable.
         Returns a boolean to indicate success */
        if item.update_status() {
            return true
        } else {
            let errMsg = "Could not update \(WRITEABLE_SELF_SERVICE_MANIFEST_PATH)"
            msc_debug_log(errMsg)
            let alertTitle = NSLocalizedString(
                "System configuration problem",
                comment: "System configuration problem alert title")
            let alertDetail = NSLocalizedString(
                "A systems configuration issue is preventing Managed Software " +
                "Center from operating correctly. The reported issue is: ",
                comment: "System configuration problem alert detail") + "\n" + errMsg
            let alert = NSAlert()
            alert.messageText = alertTitle
            alert.informativeText = alertDetail
            alert.addButton(withTitle: NSLocalizedString("OK", comment: "OK button title"))
            alert.runModal()
            return false
        }
    }
    
    func updateOptionalInstallButtonFinishAction(_ item_name: String) {
        // Perform the required action when a user clicks
        // the cancel or add button in the updates list
        msc_debug_log("Called updateOptionalInstallButtonFinishAction for \(item_name)")
        guard let item = optionalItem(forName: item_name) else {
            msc_debug_log(
                "Unexpected error: Can't find item for \(item_name)")
            return
        }
        
        // remove row for this item from its current table
        webView.evaluateJavaScript("removeElementByID('\(item_name)_update_item')")
        
        // update item status
        if !update_status_for_item(item) {
            // there was a problem, can't continue
            msc_debug_log(
                "Unexpected error: Can't update status of \(item_name)")
            return
        }
        
        let current_status = item["status"] as? String ?? ""
        msc_log("user", "optional_install_\(current_status)", msg: item_name)
        if pythonishBool(item["needs_update"]) {
            // make some new HTML for the updated item
            let item_template = getTemplate("update_item_template.html")
            item["added_class"] = "added"
            let item_html = item_template.substitute(item)
            if ["install-requested",
                    "update-will-be-installed", "installed"].contains(current_status) {
                // add the node to the updates-to-install table
                addToInnerHTML(item_html, elementID: "updates-to-install-table")
            }
            if current_status == "update-available" {
                // add the node to the other-updates table
                addToInnerHTML(item_html, elementID: "other-updates-table")
            }
        }
        
        // might need to toggle visibility of other updates div
        // find any optional installs with status update available
        let other_updates = getOptionalInstallItems().filter(
            { ($0["status"] as? String ?? "") == "update-available" }
        )
        if other_updates.isEmpty {
            webView.evaluateJavaScript("document.getElementById('other-updates').classList.add('hidden')")
        } else {
            webView.evaluateJavaScript("document.getElementById('other-updates').classList.remove('hidden')")
        }
        
        // update the updates-to-install header to reflect the new list of
        // updates to install
        setInnerText(updateCountMessage(getUpdateCount()), elementID: "update-count-string")
        setInnerText(getWarningText(shouldFilterAppleUpdates()), elementID: "update-warning-text")
    
        // update text of Install All button
        setInnerText(getInstallAllButtonTextForCount(getUpdateCount()), elementID: "install-all-button-text")
        
        // update count badges
        displayUpdateCount()
        
        if updateCheckNeeded() {
            // check for updates after a short delay so UI changes visually
            // complete first
            self.perform(#selector(self.checkForUpdatesSkippingAppleUpdates), with: nil, afterDelay: 1.0)
        }
    }

    func updateDOMforOptionalItem(_ item: OptionalItem) {
        // Update displayed status of an item
        let item_name = item["name"] as? String ?? ""
        msc_debug_log("Called updateDOMforOptionalItem for \(item_name)")
        let btn_id = "\(item_name)_action_button_text"
        let status_line_id = "\(item_name)_status_text"
        
        webView.evaluateJavaScript("document.getElementById('\(btn_id)').className")  { (result, error) in
            msc_debug_log("result: \(result ?? "<none>") error: \(String(describing: error))")
            if error == nil {
                var btn_classes = (result as? String ?? "").components(separatedBy: " ")
                // filter out status class
                btn_classes = btn_classes.filter(
                    { ["msc-button-inner", "large", "small", "install-updates"].contains($0) }
                )
                if let item_status = item["status"] as? String {
                    btn_classes.append(item_status)
                    let btnClassName = btn_classes.joined(separator: " ")
                    self.webView.evaluateJavaScript("document.getElementById('\(btn_id)').className = '\(btnClassName)'")
                    self.webView.evaluateJavaScript("document.getElementById('\(status_line_id)').className = '\(item_status)'")
                }
                if btn_classes.contains("install-updates") {
                    //(btn as! DOMHTMLElement).innerText = item["myitem_action_text"] as? String ?? ""
                    self.setInnerText(item["myitem_action_text"] as? String ?? "", elementID: btn_id)
                } else if btn_classes.contains("long_action_text") {
                    //(btn as! DOMHTMLElement).innerText = item["long_action_text"] as? String ?? ""
                    self.setInnerText(item["long_action_text"] as? String ?? "", elementID: btn_id)
                } else {
                    //(btn as! DOMHTMLElement).innerText = item["short_action_text"] as? String ?? ""
                    self.setInnerText(item["short_action_text"] as? String ?? "", elementID: btn_id)
                }
                // use innerHTML instead of innerText because sometimes the status
                // text contains html, like '<span class="warning">Some warning</span>'
                self.setInnerHTML(item["status_text"] as? String ?? "", elementID: "\(item_name)_status_text_span")
            }
        }
    }
    
    func changeSelectedCategory(_ category: String) {
        // this method is called from JavaScript when the user
        // changes the category selected in the sidebar popup
        let all_categories_label = NSLocalizedString(
            "All Categories", comment: "AllCategoriesLabel")
        let featured_label = NSLocalizedString("Featured", comment: "FeaturedLabel")
        if [all_categories_label, featured_label].contains(category) {
            load_page("category-all.html")
        } else {
            load_page("category-\(category).html")
        }
    }
    
    // some Cocoa UI bindings
    @IBAction func showHelp(_ sender: Any) {
        if let helpURL = pref("HelpURL") as? String {
            if let finalURL = URL(string: helpURL) {
                NSWorkspace.shared.open(finalURL)
            }
        } else {
            let alertTitle = NSLocalizedString("Help", comment: "No help alert title")
            let alertDetail = NSLocalizedString(
                "Help isn't available for Managed Software Center.",
                comment: "No help alert detail")
            let alert = NSAlert()
            alert.messageText = alertTitle
            alert.informativeText = alertDetail
            alert.addButton(withTitle: NSLocalizedString("OK", comment: "OK button title"))
            alert.runModal()
        }
    }
    
    @IBAction func navigateBackBtnClicked(_ sender: Any) {
        clearSearchField()
        // Handle WebView back button
        webView.goBack(self)
        /*let page_url = webView.url
        let filename = page_url?.lastPathComponent ?? ""
        navigateBackButton.isHidden = !filename.hasPrefix("detail-")*/
    }
    
    @IBAction func navigateForwardBtnClicked(_ sender: Any) {
        // Handle WebView forward button
        clearSearchField()
        webView.goForward(self)
    }
    
    @IBAction func loadAllSoftwarePage(_ sender: Any) {
        // Called by Navigate menu item
        clearSearchField()
        load_page("category-all.html")
    }
    
    @IBAction func loadCategoriesPage(_ sender: Any) {
        // Called by Navigate menu item
        clearSearchField()
        load_page("categories.html")
    }
    
    @IBAction func loadMyItemsPage(_ sender: Any) {
        // Called by Navigate menu item'''
        clearSearchField()
        load_page("myitems.html")
    }
    
    @IBAction func loadUpdatesPage(_ sender: Any) {
        // Called by Navigate menu item'''
        clearSearchField()
        load_page("updates.html")
    }
    
    @IBAction func searchFilterChanged(_ sender: Any) {
        // User changed the search field
        let filterString = searchField.stringValue.lowercased()
        if !filterString.isEmpty {
            msc_debug_log("Search filter is: \(filterString)")
            load_page("filter-\(filterString).html")
        }
    }
}

extension MainWindowController: NSOutlineViewDataSource {
    // Number of items in the sidebar
    func outlineView(_ outlineView: NSOutlineView, numberOfChildrenOfItem item: Any?) -> Int {
        return sidebar_items.count
    }
    
    // Items to be added to sidebar
    func outlineView(_ outlineView: NSOutlineView, child index: Int, ofItem item: Any?) -> Any {
        return sidebar_items[index]
    }
    
    // Whether rows are expandable by an arrow
    func outlineView(_ outlineView: NSOutlineView, isItemExpandable item: Any) -> Bool {
        return false
    }
    
    func outlineView(_ outlineView: NSOutlineView, rowViewForItem item: Any) -> NSTableRowView? {
        return MSCTableRowView(frame: NSZeroRect);
    }
    
    func outlineView(_ outlineView: NSOutlineView, didAdd rowView: NSTableRowView, forRow row: Int) {
        rowView.selectionHighlightStyle = .regular
    }
}

extension MainWindowController: NSOutlineViewDelegate {
    
    func outlineView(_ outlineView: NSOutlineView, viewFor tableColumn: NSTableColumn?, item: Any) -> NSView? {
        var view: MSCTableCellView?
        let itemDict = item as? [String: String]
        if let title = itemDict?["title"], let icon = itemDict?["icon"] {
            view = outlineView.makeView(withIdentifier: NSUserInterfaceItemIdentifier(rawValue: "ItemCell"), owner: self) as? MSCTableCellView
            if let textField = view?.title {
                textField.stringValue = title.localized(withComment: "\(title) label")
            }
            if let imageView = view?.imgView {
                imageView.image = NSImage(named: NSImage.Name(icon))?.tint(color: .secondaryLabelColor)
            }
        }
        return view
    }
}

extension NSImage {
    func tint(color: NSColor) -> NSImage {
        guard !self.isTemplate else { return self }
        
        let image = self.copy() as! NSImage
        image.lockFocus()
        
        color.set()
        
        let imageRect = NSRect(origin: NSZeroPoint, size: image.size)
        imageRect.fill(using: .sourceAtop)
        
        image.unlockFocus()
        image.isTemplate = false
        
        return image
    }
}

extension String {
    func localized(withComment comment: String? = nil) -> String {
        return NSLocalizedString(self, comment: comment ?? "")
    }
}
