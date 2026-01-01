//
//  MainWindowController.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 6/29/18.
//  Copyright © 2018-2025 The Munki Project. All rights reserved.
//

import Cocoa
import WebKit

struct SidebarItem {
    let title: String
    let icon: String
    let page: String
}

class MainWindowController: NSWindowController {
    var mainWindowConfigurationComplete = false
    var _alertedUserToOutstandingUpdates = false
    var _update_in_progress = false
    var _obnoxiousNotificationMode = false
    var managedsoftwareupdate_task = ""
    var cached_self_service = SelfService()
    var alert_controller = MSCAlertController()
    var htmlDir = ""
    var wkContentController = WKUserContentController()

    lazy var sidebar_items: [SidebarItem] = getSidebarItems()
    
    // status properties
    var _status_title = ""
    var stop_requested = false
    var user_warned_about_extra_updates = false
    var forceFrontmost = false
    
    // Cocoa UI binding properties
    @IBOutlet weak var sidebarViewController: SidebarViewController!
    @IBOutlet weak var mainContentViewController: MainContentViewController!
    @IBOutlet weak var toolbar: NSToolbar!
    @IBOutlet weak var searchField: NSSearchField!
    @IBOutlet weak var sidebarList: NSOutlineView!
    @IBOutlet weak var navigateBackMenuItem: NSMenuItem!
    @IBOutlet weak var findMenuItem: NSMenuItem!
    @IBOutlet weak var reloadPageMenuItem: NSMenuItem!
    @IBOutlet weak var navigateMenu: NSMenuItem!
    
    @IBOutlet weak var webViewPlaceholder: NSView!
    var webView: WKWebView!
    
    var blurredBackground: BackgroundBlurrer?
    
    var pageLoadProgress: NSProgressIndicator?
    var navigateBackButton: NSToolbarItem?
    
    // Dangerous convenience alias so you can access the NSSplitViewController and manipulate it later on
    private var splitViewController: MainSplitViewController! {
        get { return contentViewController as? MainSplitViewController }
        set { contentViewController = newValue }
    }
    
    // number of items in the Navigate menu that aren't dynamic
    let navigateMenuStaticItemCount = 4

    func setupSplitView() {
        let originalFrame = window?.frame ?? .zero
        let splitViewController = MainSplitViewController()

        let sidebarItem = NSSplitViewItem(sidebarWithViewController: sidebarViewController)
        if !optionalInstallsExist() {
            sidebarItem.isCollapsed = true
        }
        splitViewController.addSplitViewItem(sidebarItem)
        
        let mainContentItem = NSSplitViewItem(viewController: mainContentViewController)
        // TODO: remove this after Xcode 26 ships and if/when require Xcode 26+ to build
        // we use this stupid condition because PermissionKit was introduced in the macOS 26 SDK
        // and there's no other straightforward way to do conditional compilation based on SDK
        // availability
        #if canImport(PermissionKit)
        if #available(macOS 26.0, *) {
            mainContentItem.automaticallyAdjustsSafeAreaInsets = true
        }
        #endif
        splitViewController.addSplitViewItem(mainContentItem)
        self.splitViewController = splitViewController
        // TODO: remove this hack. (Adding sidebar causes the window to expand, this resets it)
        if let window, originalFrame != .zero {
            window.setFrame(originalFrame, display: true)
        }
    }
    
    func updateNavigationMenu(_ sidebarItems: [SidebarItem]) {
        if let navigateMenu = navigateMenu.submenu {
            // remove any previously-added items
            
            let itemCount = navigateMenu.items.count
            if itemCount > navigateMenuStaticItemCount {
                navigateMenu.items.removeLast(itemCount - navigateMenuStaticItemCount)
            }
            // add an item for each sidebar item
            var index = 1
            for sidebarItem in sidebarItems {
                let key = index < 10 ? String(index) : ""
                let menuItem = NSMenuItem(
                    title: sidebarItem.title.localized(withComment: "\(sidebarItem.title) label"),
                    action: #selector(navigationMenuItemClicked),
                    keyEquivalent: key
                )
                if #available(macOS 26.0, *) {
                    if let image = NSImage(named: NSImage.Name(sidebarItem.icon))?.copy() as? NSImage {
                        // we make a copy since we're resizing it and this same image is
                        // used in the sidebar (and we don't want it to be the same size
                        // both places)
                        image.isTemplate = true
                        let fontsize = NSFont.menuFont(ofSize: 0.0).pointSize
                        image.size.height = fontsize
                        image.size.width = fontsize
                        menuItem.image = image
                    } else if let image = NSImage(systemSymbolName: sidebarItem.icon, accessibilityDescription: nil) {
                        menuItem.image = image
                    }
                }
                navigateMenu.items.append(menuItem)
                index += 1
            }
        }
    }
    
    /// Returns true if the sidebar items only refer to munki:// pages
    func sidebarItemsContainOnlyMunkiPages() -> Bool {
        for item in sidebar_items {
            if !item.page.hasPrefix("munki://") {
                return false
            }
        }
        return true
    }
    
    /// Returns a custom sidebar configuration, if any
    /// First attempts to read the config from preferences
    /// Then attempts to read the config from custom client resources
    /// Falls back to the default.
    func getCustomSidebarConfig() -> [[String: Any]] {
        if #available(macOS 11.0, *) {
            // enable custom sidebar items if 11.0 or later
            // because SF Symbols only supported on 11.0 or later
            //
            // try preferences (includes managed prefs)
            if let sidebarConfig = pref("CustomSidebarItems") as? [[String: Any]] {
                return sidebarConfig
            }
            // try custom client resources
            let customSidebarConfigPath = NSString.path(withComponents: [html_dir(), "custom/sidebar.plist"])
            if FileManager.default.fileExists(atPath: customSidebarConfigPath) {
                if let plist = try? readPlist(customSidebarConfigPath) as? [String: Any] {
                    if let sidebarConfig = plist["CustomSidebarItems"] as? [[String: Any]] {
                        return sidebarConfig
                    }
                } else {
                    // TODO: log error reading plist
                }
            }
        }
        // default (standard) sidebar
        return [
            ["title": "Software",
             "icon": "AllItemsTemplate",
             "page": MunkiURL.software.rawValue
            ],
            ["title": "Categories",
             "icon": "CategoriesTemplate",
             "page": MunkiURL.categories.rawValue
            ],
            ["title": "My Items",
             "icon": "MyStuffTemplate",
             "page": MunkiURL.myItems.rawValue
            ],
            ["title": "Updates",
             "icon": "UpdatesTemplate",
             "page": MunkiURL.updates.rawValue
            ],
        ]
    }
    
    /// Given a set of language identifiers, return the preferred identifier based on the user's current preferred languages
    func preferredLocalizationIdentifier(from identifiers: [String]) -> String? {
        let preferredLanguages = NSLocale.preferredLanguages
        for language in preferredLanguages {
            // just do a simple match
            if identifiers.contains(language) {
                return language
            } else if let languageWithoutRegionCode = language.split(separator: "-").first {
                // now look for matches without region code
                if identifiers.contains(String(languageWithoutRegionCode)) {
                    return String(languageWithoutRegionCode)
                } else {
                    // finally, if needed, match items with same language but different region
                    for identifier in identifiers {
                        if identifier.hasPrefix(String(languageWithoutRegionCode) + "-") {
                            return identifier
                        }
                    }
                }
            }
        }
        // didn't find any matches at all
        return nil
    }
    
    func getSidebarItems() -> [SidebarItem] {
        // enable custom sidebar items if 11.0 or later
        // because SF Symbols only supported on 11.0 or later
        var sidebarItems: [SidebarItem] = []
        let configItems = getCustomSidebarConfig()
        for item in configItems {
            guard let title = item["title"] as? String,
                  let icon = item["icon"] as? String,
                  let page = item["page"] as? String else {
                continue
            }
            
            var finalTitle = title
            var finalPage = page
            if let localizedStrings = item["localized_strings"] as? [String: Any] {
                
                let availableLanguages = Array(localizedStrings.keys)
                if let preferredLanguage = preferredLocalizationIdentifier(from: availableLanguages),
                   let languageDict = localizedStrings[preferredLanguage] as? [String: String]
                {
                    finalTitle = languageDict["title"] ?? title
                    finalPage = languageDict["page"] ?? page
                }
            }
            
            sidebarItems.append(SidebarItem(
                title: finalTitle,
                icon: icon,
                page: finalPage
            ))
        }
        // update Navigate menu to reflect the sidebar contents
        updateNavigationMenu(sidebarItems)
        return sidebarItems
    }
    
    func loadSidebarItemPage(_ page: String) {
        if page.hasPrefix("munki://") {
            if let url = URL(string: page) {
                handleMunkiURL(url)
            } else {
                msc_debug_log("Could not parse sidebar item page URL \(page)")
            }
        } else {
            load_page(page)
        }
    }
    
    @objc func navigationMenuItemClicked(_ sender: NSMenuItem) {
        let itemTitle = sender.title
        for (index, item) in sidebar_items.enumerated() {
            if item.title == itemTitle {
                clearSearchField()
                highlightSidebarItemByIndex(index)
                loadSidebarItemPage(item.page)
                break
            }
        }
    }

    @objc func sidebarItemClicked() {
        let row = sidebarList.clickedRow
        guard row >= 0 && row < sidebar_items.count else { return }
        clearSearchField()
        let item = sidebar_items[row]
        loadSidebarItemPage(item.page)
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
        let row = sidebarList.selectedRow
        guard row >= 0, row < sidebar_items.count else { return false }
        return sidebar_items[row].page == MunkiURL.updates.rawValue
    }
    
    func blurBackground() {
        blurredBackground = BackgroundBlurrer()
        if let window = self.window {
            window.level = NSWindow.Level(rawValue: Int(CGWindowLevelForKey(.maximumWindow) + 1))
        }
    }
    
    func makeUsUnobnoxious() {
        // reverse all the obnoxious changes
        msc_log("MSC", "end_obnoxious_mode")
        
        // remove obnoxious presentation options
        NSApp.presentationOptions = NSApp.currentSystemPresentationOptions.subtracting(
            NSApplication.PresentationOptions([.hideDock, .disableHideApplication, .disableProcessSwitching, .disableForceQuit]))
        
        // remove blurred background
        blurredBackground = nil

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
        msc_log("MSC", "start_obnoxious_mode")
        
        // make sure we're frontmost
        NSApp.activate(ignoringOtherApps: true)
        
        // If the window is not on the active space, force a space switch.
        // Return early, before locking down the presentation options. This will let the run loop spin, allowing
        // the space switch to occur. When the window becomes key, `makeUsObnoxious` will be called again.
        // On the second invocation, the window will be on the active space and this block will be skipped.
        if let window = self.window {
            if (!window.isOnActiveSpace) {
                NSApp.activate(ignoringOtherApps: true)
                window.orderFrontRegardless()
                return
            }
        }
        
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
        updatesOnlyWindowMode(hideSidebarRegardless: true)
        reloadPageMenuItem.isEnabled = false
        loadUpdatesPage(self)
        
        // set flag to cause us to always be brought to front
        self.forceFrontmost = true
        
        // blur everything behind the MSC window
        blurBackground()

        // seems redundant, but ensures the window is visible
        // in front of the blurred background even if it was minimized
        // previously
        self.showWindow(self)
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
    
    func hideMunkiNavigateMenuItems(_ shouldHide: Bool) {
        guard let menuItems = navigateMenu.submenu?.items else { return }
        if menuItems.count <= navigateMenuStaticItemCount { return }
        for (i, item) in sidebar_items.enumerated() {
            if item.page.hasPrefix("munki://") {
                menuItems[i + navigateMenuStaticItemCount].isHidden = shouldHide
            }
        }
    }
    
    func updatesOnlyWindowMode(hideSidebarRegardless: Bool = false) {
        findMenuItem.isHidden = true
        if hideSidebarRegardless || sidebarItemsContainOnlyMunkiPages() {
            hideMunkiNavigateMenuItems(true)
            // ensure sidebar is collapsed
            guard let firstSplitView = splitViewController.splitViewItems.first else { return }
            if !firstSplitView.animator().isCollapsed {
                firstSplitView.animator().isCollapsed = true
            }
        } else {
            // if there are non-munki:// items in the sidebar,
            // make sure the sidebar is visible
            hideMunkiNavigateMenuItems(false)
            // ensure sidebar is visible
            guard let firstSplitView = splitViewController.splitViewItems.first else { return }
            if firstSplitView.animator().isCollapsed {
                firstSplitView.animator().isCollapsed = false
            }
        }
        loadUpdatesPage(self)
    }
    
    func updatesAndOptionalWindowMode() {
        findMenuItem.isHidden = false
        hideMunkiNavigateMenuItems(false)
        // ensure sidebar is visible
        guard let firstSplitView = splitViewController.splitViewItems.first else { return }
        if firstSplitView.animator().isCollapsed {
            firstSplitView.animator().isCollapsed = false
        }
    }
    
    func shouldMoveToUpdatesPage() -> Bool {
        return getUpdateCount() > 0 || !getProblemItems().isEmpty
    }
    
    func determineIfUpdateOnlyWindowOrUpdateAndOptionalWindowMode() {
        // if we have no optional_items set MSC to show updates only
        // if updates available go right to update screen
        if optionalInstallsExist() {
            updatesAndOptionalWindowMode()
            if shouldMoveToUpdatesPage() {
                loadUpdatesPage(self)
            }
        } else {
            updatesOnlyWindowMode()
        }
    }
    
    func loadInitialView() {
        // Called by app delegate from applicationDidFinishLaunching:
        if optionalInstallsExist() {
            updatesAndOptionalWindowMode()
            if shouldMoveToUpdatesPage() {
                loadUpdatesPage(self)
                displayUpdateCount()
            } else {
                // load the page for the first sidebar item
                let item = sidebar_items[0]
                loadSidebarItemPage(item.page)

            }
        } else {
            updatesOnlyWindowMode()
        }
        cached_self_service = SelfService()
    }
    
    /// Selects the sidebar item by index
    func highlightSidebarItemByIndex(_ index: Int) {
        sidebarList.selectRowIndexes(IndexSet(integer: index), byExtendingSelection: false)
    }
    
    /// Selects the sidebar item with a matching page URL
    func highlightSidebarItemByPage(_ page: String) {
        for (index, item) in sidebar_items.enumerated() {
            if page == item.page {
                sidebarList.selectRowIndexes(IndexSet(integer: index), byExtendingSelection: false)
                return
            }
        }
        // didn't find a matching item -- select nothing
        sidebarList.deselectAll(self)
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
            if _obnoxiousNotificationMode {
                if weShouldBeObnoxious() {
                    makeUsObnoxious()
                } else {
                    _obnoxiousNotificationMode = false
                    makeUsUnobnoxious()
                }
            }
        default:
            // should never get here
            msc_debug_log("Unexpected value for page name: \(filename)")
        }
        // update count might have changed
        displayUpdateCount()
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
            
            // this and its replacement WKWebpagePreferences.allowsContentJavaScript
            // default to true. webConfiguration.preferences.javaScriptEnabled is deprecated,
            // So the easiest thing to do is just not call it or its replacement
            //webConfiguration.preferences.javaScriptEnabled = true
            // webConfiguration.preferences.javaEnabled is deprecated as of macOS 10.15,
            // and Java is no longer supported, so again, just don't set it
            //webConfiguration.preferences.javaEnabled = false
            
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
            replacementWebView.translatesAutoresizingMaskIntoConstraints = false
            /*
            // TODO: remove this when Xcode 26 ships and we require it to build
            // we use this stupid condition because PermissionKit was introduced in the macOS 26 SDK
            // and there's no other straightforward way to do conditional compilation based on SDK
            // availability
            #if canImport(PermissionKit)
            if #available(macOS 26.0, *) {
                // replace the placeholder in the window view with
                // a background extension view containing the webview
                let backgroundExtensionView = NSBackgroundExtensionView()
                backgroundExtensionView.frame = superview.frame
                backgroundExtensionView.automaticallyPlacesContentView = false
                backgroundExtensionView.contentView = replacementWebView
                backgroundExtensionView.translatesAutoresizingMaskIntoConstraints = false
                superview.replaceSubview(webViewPlaceholder, with: backgroundExtensionView)
                NSLayoutConstraint.activate([
                    backgroundExtensionView.leadingAnchor.constraint(equalTo: superview.leadingAnchor),
                    backgroundExtensionView.trailingAnchor.constraint(equalTo: superview.trailingAnchor),
                    backgroundExtensionView.topAnchor.constraint(equalTo: superview.topAnchor),
                    backgroundExtensionView.bottomAnchor.constraint(equalTo: superview.bottomAnchor)
                ])
            } else {
                // replace the placeholder in the window view with the real webview
                superview.replaceSubview(webViewPlaceholder, with: replacementWebView)
            }
            #else
            */
            // replace the placeholder in the window view with the real webview
            superview.replaceSubview(webViewPlaceholder, with: replacementWebView)
            //#endif
            webView = replacementWebView
            if #available(macOS 11.0, *) {
                let safeGuide = superview.safeAreaLayoutGuide
                NSLayoutConstraint.activate([
                    webView.leadingAnchor.constraint(equalTo: safeGuide.leadingAnchor),
                    webView.trailingAnchor.constraint(equalTo: safeGuide.trailingAnchor),
                    webView.topAnchor.constraint(equalTo: superview.topAnchor),
                    webView.bottomAnchor.constraint(equalTo: superview.bottomAnchor)
                ])
            } else {
                // Fallback on earlier versions
                NSLayoutConstraint.activate([
                    webView.leadingAnchor.constraint(equalTo: superview.leadingAnchor),
                    webView.trailingAnchor.constraint(equalTo: superview.trailingAnchor),
                    webView.topAnchor.constraint(equalTo: superview.topAnchor),
                    webView.bottomAnchor.constraint(equalTo: superview.bottomAnchor)
                ])
            }
            
            webView.navigationDelegate = self
        }
    }
    
    override func awakeFromNib() {
        // Stuff we need to initialize when we start
        super.awakeFromNib()
        if !mainWindowConfigurationComplete {
            // this is a bit of a hack since awakeFromNib gets called several times
            // but we only want this part of the config to run once
            mainWindowConfigurationComplete = true
            setupSplitView()
            insertWebView()
            setNoPageCache()
            alert_controller = MSCAlertController()
            alert_controller.window = self.window
            htmlDir = html_dir()
            registerForNotifications()
        }
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
        _alertedUserToOutstandingUpdates = true
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
            _obnoxiousNotificationMode = false
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
    
    func updatesSidebarItemView() -> MSCTableCellView? {
        for (i, item) in sidebar_items.enumerated() {
            if munkiURL(from: item.page) == MunkiURL.updates.rawValue {
                if let view = self.sidebarList.rowView(atRow: i, makeIfNecessary: false) {
                    return view.view(atColumn: 0) as? MSCTableCellView
                }
            }
        }
        return nil
    }
    
    func displayUpdateCount() {
        // Display the update count as a badge in the sidebar
        // and as an icon badge in the Dock
        let updateCount = getUpdateCount()
        
        let cellView = updatesSidebarItemView()

        if updateCount > 0 {
            NSApp.dockTile.badgeLabel = String(updateCount)
            cellView?.badge.title = String(updateCount)
            cellView?.badge.isHidden = false
        } else {
            NSApp.dockTile.badgeLabel = nil
            cellView?.badge.isHidden = true
        }
    }
    
    func displayUpdatesProgressSpinner(_ shouldDisplay: Bool) {
        // check if update sidebar item available
        guard let cellView = updatesSidebarItemView() else {
            return
        }
        if shouldDisplay {
            cellView.badge.isHidden = true
            cellView.spinner.startAnimation(self)
        } else {
            cellView.spinner.stopAnimation(self)
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
        var request: URLRequest
        
        if let components = URLComponents(string: url_fragment),
           ["https", "http"].contains(components.scheme)
        {
            // url_fragment is http:// or https:// URL
            request = URLRequest(
                url: URL(string: url_fragment)!,
                cachePolicy: .reloadIgnoringLocalCacheData,
                timeoutInterval: TimeInterval(10.0)
            )
        } else {
            // url_fragment is just a path (or filename)
            let baseURL = URL(fileURLWithPath: htmlDir).standardizedFileURL
            let requestURL = baseURL.appendingPathComponent(url_fragment).standardizedFileURL
            
            let baseComponents = baseURL.pathComponents
            let requestComponents = requestURL.pathComponents
            
            guard requestComponents.starts(with: baseComponents) else {
                msc_debug_log("Attempt to access file outside htmlDir: \(url_fragment)")
                // since error.html doesn't exist, this ends up triggering buildItemNotFoundPage()
                let errorURL = baseURL.appendingPathComponent("error.html")
                webView.load(URLRequest(url: errorURL))
                return
            }
            
            request = URLRequest(
                url: requestURL,
                cachePolicy: .reloadIgnoringLocalCacheData,
                timeoutInterval: 10.0
            )
        }

        webView.load(request)
        
        if url_fragment == "updates.html" {
            if !_update_in_progress && NSApp.isActive {
                // clear all earlier update notifications
                removeAllDeliveredNotifications()
            }
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
        let munkiNotifierPath = Bundle.main.bundlePath + "/Contents/Helpers/munki-notifier.app"
        if FileManager.default.fileExists(atPath: munkiNotifierPath) {
            NSLog("munki-notifier path: %@", munkiNotifierPath as String)
            // now make sure it's not already running
            let executablePath = munkiNotifierPath + "/Contents/MacOS/munki-notifier"
            let procs = getRunningProcessesWithUsers()
            for proc in procs {
                if proc["pathname"] == executablePath && proc["user"] == NSUserName() {
                    // munki-notifier is already running as this user
                    return
                }
            }
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
                    _obnoxiousNotificationMode = true
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
    
    // MARK: IBActions
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
    
    @IBAction func reloadPage(_ sender: Any) {
        // User selected Reload page menu item. Reload the page and kick off an updatecheck
        msc_log("user", "reload_page_menu_item_selected")
        setFilterAppleUpdates(false)
        setFilterStagedOSUpdate(false)
        checkForUpdates()
        URLCache.shared.removeAllCachedResponses()
        webView.reload(sender)
    }
    
}
