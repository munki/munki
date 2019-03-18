# encoding: utf-8
#
#  MSCMainWindowController.py
#  Managed Software Center
#
#  Copyright 2013-2019 Greg Neagle.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os

import munki
import mschtml
import msclib
import msclog
import MunkiItems

from urlparse import urlparse

from AlertController import AlertController
from MSCBadgedTemplateImage import MSCBadgedTemplateImage

from objc import YES, NO, IBAction, IBOutlet, nil
from PyObjCTools import AppHelper

## pylint: disable=wildcard-import
## pylint: disable=unused-wildcard-import
## pylint: disable=redefined-builtin
#from Foundation import *
#from AppKit import *
## pylint: enable=redefined-builtin
## pylint: enable=wildcard-import

# pylint: disable=wildcard-import
from CocoaWrapper import *
# pylint: enable=wildcard-import

#from WebKit import *
from WebKit import WebView, WebPreferences

# Disable PyLint complaining about 'invalid' camelCase names
# pylint: disable=C0103


class MSCMainWindowController(NSWindowController):

    _alertedUserToOutstandingUpdates = False

    _update_in_progress = False
    managedsoftwareupdate_task = None
    _update_queue = set()

    # status vars
    _status_title = u''
    stop_requested = False
    user_warned_about_extra_updates = False
    html_dir = None
    alert_context_info = None
    cached_self_service = None
    alert_controller = None

    # Cocoa UI binding properties
    softwareToolbarButton = IBOutlet()
    categoriesToolbarButton = IBOutlet()
    myItemsToolbarButton = IBOutlet()
    updatesToolbarButton = IBOutlet()
    webView = IBOutlet()
    navigateBackBtn = IBOutlet()
    navigateForwardBtn = IBOutlet()
    progressSpinner = IBOutlet()
    searchField = IBOutlet()
    updateButtonCell = IBOutlet()
    windowMenuSeperatorItem = IBOutlet()
    fullScreenMenuItem = IBOutlet()
    findMenuItem = IBOutlet()
    softwareMenuItem = IBOutlet()
    categoriesMenuItem = IBOutlet()
    myItemsMenuItem = IBOutlet()

    def appShouldTerminate(self):
        '''called by app delegate
        when it receives applicationShouldTerminate:'''
        if self.getUpdateCount() == 0:
            # no pending updates
            return YES
        if (self.currentPageIsUpdatesPage()
                and not munki.thereAreUpdatesToBeForcedSoon()):
            # We're already at the updates view, so user is aware of the
            # pending updates, so OK to just terminate
            # (unless there are some updates to be forced soon)
            return YES
        if (self.currentPageIsUpdatesPage()
                and self._alertedUserToOutstandingUpdates):
            return YES
        # we have pending updates and we have not yet warned the user
        # about them
        self.alertToPendingUpdates()
        return NO

    def alertToPendingUpdates(self):
        '''Alert user to pending updates before quitting the application'''
        self._alertedUserToOutstandingUpdates = True
        # show the updates
        self.loadUpdatesPage_(self)
        if munki.thereAreUpdatesToBeForcedSoon():
            alertTitle = NSLocalizedString(u"Mandatory Updates Pending",
                                           u"Mandatory Updates Pending text")
            deadline = munki.earliestForceInstallDate()
            time_til_logout = deadline.timeIntervalSinceNow()
            if time_til_logout > 0:
                deadline_str = munki.stringFromDate(deadline)
                formatString = NSLocalizedString(
                    (u"One or more updates must be installed by %s. A logout "
                     "may be forced if you wait too long to update."),
                    u"Mandatory Updates Pending detail")
                alertDetail = formatString % deadline_str
            else:
                alertDetail = NSLocalizedString(
                    (u"One or more mandatory updates are overdue for "
                     "installation. A logout will be forced soon."),
                    u"Mandatory Updates Imminent detail")
        else:
            alertTitle = NSLocalizedString(
                u"Pending updates", u"Pending Updates alert title")
            alertDetail = NSLocalizedString(
                u"There are pending updates for this computer.",
                u"Pending Updates alert detail text")
        alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(
            alertTitle,
            NSLocalizedString(u"Quit", u"Quit button title"),
            nil,
            NSLocalizedString(u"Update now", u"Update Now button title"),
            u"%@", alertDetail)
        alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(
            self.window(), self,
            self.updateAlertDidEnd_returnCode_contextInfo_, nil)

    @AppHelper.endSheetMethod
    def updateAlertDidEnd_returnCode_contextInfo_(
            self, alert, returncode, contextinfo):
        '''Called when alert invoked by alertToPendingUpdates ends'''
        if returncode == NSAlertDefaultReturn:
            msclog.log("user", "quit")
            NSApp.terminate_(self)
        elif returncode == NSAlertOtherReturn:
            msclog.log("user", "install_now_clicked")
            # make sure this alert panel is gone before we proceed
            # which might involve opening another alert sheet
            alert.window().orderOut_(self)
            # initiate the updates
            self.updateNow()
            self.loadUpdatesPage_(self)

    def loadInitialView(self):
        '''Called by app delegate from applicationDidFinishLaunching:'''
        self.enableOrDisableSoftwareViewControls()
        optional_items = MunkiItems.getOptionalInstallItems()
        if not optional_items or self.getUpdateCount() or MunkiItems.getProblemItems():
            self.loadUpdatesPage_(self)
        else:
            self.loadAllSoftwarePage_(self)
        self.displayUpdateCount()
        self.cached_self_service = MunkiItems.SelfService()

    def highlightToolbarButtons_(self, nameToHighlight):
        '''Highlight/dim buttons in our toolbar'''
        self.softwareToolbarButton.setState_(nameToHighlight == "Software")
        self.categoriesToolbarButton.setState_(nameToHighlight == "Categories")
        self.myItemsToolbarButton.setState_(nameToHighlight == "My Items")
        self.updatesToolbarButton.setState_(nameToHighlight == "Updates")

    def enableOrDisableToolbarButtons_(self, enabled_state):
        '''Enable or disable buttons in our toolbar'''
        if self.window().isMainWindow() == NO:
            enabled_state = NO
            updates_button_state = NO
        else:
            updates_button_state = YES
        self.softwareToolbarButton.setEnabled_(enabled_state)
        self.categoriesToolbarButton.setEnabled_(enabled_state)
        self.myItemsToolbarButton.setEnabled_(enabled_state)
        self.updatesToolbarButton.setEnabled_(updates_button_state)

    def enableOrDisableSoftwareViewControls(self):
        '''Disable or enable the controls that let us view optional items'''
        optional_items = MunkiItems.getOptionalInstallItems()
        enabled_state = (len(optional_items) > 0)
        self.enableOrDisableToolbarButtons_(enabled_state)
        self.searchField.setEnabled_(enabled_state)
        self.findMenuItem.setEnabled_(enabled_state)
        self.softwareMenuItem.setEnabled_(enabled_state)
        self.softwareMenuItem.setEnabled_(enabled_state)
        self.categoriesMenuItem.setEnabled_(enabled_state)
        self.myItemsMenuItem.setEnabled_(enabled_state)

    def munkiStatusSessionEndedWithStatus_errorMessage_(self, sessionResult, errmsg):
        '''Called by StatusController when a Munki session ends'''
        msclog.debug_log(u"MunkiStatus session ended: %s" % sessionResult)
        msclog.debug_log(
            u"MunkiStatus session type: %s" % self.managedsoftwareupdate_task)
        tasktype = self.managedsoftwareupdate_task
        self.managedsoftwareupdate_task = None
        self._update_in_progress = False

        # The managedsoftwareupdate run will have changed state preferences
        # in ManagedInstalls.plist. Load the new values.
        munki.reload_prefs()
        lastCheckResult = munki.pref("LastCheckResult")
        if sessionResult != 0 or lastCheckResult < 0:
            OKButtonTitle = NSLocalizedString(u"OK", u"OK button title")
            alertMessageText = NSLocalizedString(
                u"Update check failed", u"Update Check Failed title")
            detailText = u""
            if tasktype == "installwithnologout":
                msclog.log("MSC", "cant_update", "Install session failed")
                alertMessageText = NSLocalizedString(
                    u"Install session failed", u"Install Session Failed title")

            if sessionResult == -1:
                # connection was dropped unexpectedly
                msclog.log("MSC", "cant_update", "unexpected process end")
                detailText = NSLocalizedString(
                    (u"There is a configuration problem with the managed "
                     "software installer. The process ended unexpectedly. "
                     "Contact your systems administrator."),
                    u"Unexpected Session End message")
            elif sessionResult == -2:
                # session never started
                msclog.log("MSC", "cant_update", "process did not start")
                detailText = NSLocalizedString(
                    (u"There is a configuration problem with the managed "
                     "software installer. Could not start the process. "
                     "Contact your systems administrator."),
                    u"Could Not Start Session message")
            elif lastCheckResult == -1:
                # server not reachable
                msclog.log("MSC", "cant_update", "cannot contact server")
                detailText = NSLocalizedString(
                    (u"Managed Software Center cannot contact the update "
                     "server at this time.\n"
                     "Try again later. If this situation continues, "
                     "contact your systems administrator."),
                    u"Cannot Contact Server detail")
            elif lastCheckResult == -2:
                # preflight failed
                msclog.log("MSU", "cant_update", "failed preflight")
                detailText = NSLocalizedString(
                    (u"Managed Software Center cannot check for updates now.\n"
                     "Try again later. If this situation continues, "
                     "contact your systems administrator."),
                    u"Failed Preflight Check detail")
            if errmsg:
                detailText += u"\n\n" + unicode(errmsg)
            # show the alert sheet
            self.window().makeKeyAndOrderFront_(self)
            alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(
                alertMessageText, OKButtonTitle, nil, nil, u"%@", detailText)
            alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(
                self.window(), self,
                self.munkiSessionErrorAlertDidEnd_returnCode_contextInfo_, nil)
            return

        if tasktype == 'checktheninstall':
            MunkiItems.reset()
            # possibly check again if choices have changed
            self.updateNow()
            return

        # all done checking and/or installing: display results
        self.resetAndReload()

        if MunkiItems.updateCheckNeeded():
            # more stuff pending? Let's do it...
            self.updateNow()

    @AppHelper.endSheetMethod
    def munkiSessionErrorAlertDidEnd_returnCode_contextInfo_(
            self, alert, returncode, contextinfo):
        '''Called when alert raised by munkiStatusSessionEnded ends'''
        self.resetAndReload()

    def resetAndReload(self):
        '''Clear cached values, reload from disk. Display any changes.
        Typically called soon after a Munki session completes'''
        msclog.debug_log('resetAndReload method called')
        # need to clear out cached data
        MunkiItems.reset()
        # recache SelfService choices
        self.cached_self_service = MunkiItems.SelfService()
        # copy any new custom client resources
        msclib.get_custom_resources()
        # pending updates may have changed
        self._alertedUserToOutstandingUpdates = False
        # enable/disable controls as needed
        self.enableOrDisableSoftwareViewControls()
        # what page are we currently viewing?
        page_url = self.webView.mainFrameURL()
        filename = NSURL.URLWithString_(page_url).lastPathComponent()
        name = os.path.splitext(filename)[0]
        key = name.partition('-')[0]
        if key == 'detail':
            # optional item detail page
            self.webView.reload_(self)
        if key in ['category', 'filter', 'developer']:
            # optional item list page
            self.updateListPage()
        if key == 'categories':
            # categories page
            self.updateCategoriesPage()
        if key == 'myitems':
            # my items page
            self.updateMyItemsPage()
        if key == 'updates':
            # updates page
            self.webView.reload_(self)
            self._alertedUserToOutstandingUpdates = True
        if key == 'updatedetail':
            # update detail page
            self.webView.reload_(self)
        # update count might have changed
        self.displayUpdateCount()

    def windowShouldClose_(self, sender):
        '''NSWindowDelegate method called when user closes a window'''
        # closing the main window should be the same as quitting
        NSApp.terminate_(self)
        return NO

    def windowDidBecomeMain_(self, notification):
        '''Our window was activated, make sure controls enabled as needed'''
        optional_items = MunkiItems.getOptionalInstallItems()
        enabled_state = (len(optional_items) > 0)
        self.enableOrDisableToolbarButtons_(enabled_state)

    def windowDidResignMain_(self, notification):
        '''Our window was deactivated, make sure controls enabled as needed'''
        self.enableOrDisableToolbarButtons_(NO)

    def configureFullScreenMenuItem(self):
        '''check to see if NSWindow's toggleFullScreen: selector is implemented.
        if so, unhide the menu items for going full screen'''
        if self.window().respondsToSelector_('toggleFullScreen:'):
            self.windowMenuSeperatorItem.setHidden_(False)
            self.fullScreenMenuItem.setHidden_(False)
            self.fullScreenMenuItem.setEnabled_(True)

    def awakeFromNib(self):
        '''Stuff we need to initialize when we start'''
        self.configureFullScreenMenuItem()
        self.webView.setDrawsBackground_(NO)
        self.webView.setUIDelegate_(self)
        self.webView.setFrameLoadDelegate_(self)
        self.webView.setResourceLoadDelegate_(self)
        self.webView.setPolicyDelegate_(self)
        self.setNoPageCache()
        self.alert_controller = AlertController.alloc().init()
        self.alert_controller.setWindow_(self.window())
        self.html_dir = msclib.html_dir()
        self.registerForNotifications()

    def registerForNotifications(self):
        '''register for notification messages'''
        notification_center = NSDistributedNotificationCenter.defaultCenter()
        # register for notification if user switches to/from Dark Mode
        notification_center.addObserver_selector_name_object_suspensionBehavior_(
            self,
            self.interfaceThemeChanged,
            'AppleInterfaceThemeChangedNotification',
            None,
            NSNotificationSuspensionBehaviorDeliverImmediately)

        # register for notification if available updates change
        notification_center.addObserver_selector_name_object_suspensionBehavior_(
            self,
            self.updateAvailableUpdates,
            'com.googlecode.munki.managedsoftwareupdate.updateschanged',
            None,
            NSNotificationSuspensionBehaviorDeliverImmediately)

        # register for notification to display a logout warning
        # from the logouthelper
        notification_center.addObserver_selector_name_object_suspensionBehavior_(
            self,
            self.forcedLogoutWarning,
            'com.googlecode.munki.ManagedSoftwareUpdate.logoutwarn',
            None,
            NSNotificationSuspensionBehaviorDeliverImmediately)
    
    def interfaceThemeChanged(self):
        '''Called when user switches to/from Dark Mode'''
        interface_style = mschtml.interfaceStyle()
        scriptObject = self.webView.windowScriptObject()
        args = [interface_style]
        # call JavaScript in the webview to update the appearance CSS
        scriptObject.callWebScriptMethod_withArguments_("changeAppearanceModeTo", args)

    def updateAvailableUpdates(self):
        '''If a Munki session is not in progress (that we know of) and
        we get a updateschanged notification, resetAndReload'''
        msclog.debug_log(u"Managed Software Center got update notification")
        if not self._update_in_progress:
            self.resetAndReload()

    def forcedLogoutWarning(self, notification_obj):
        '''Received a logout warning from the logouthelper for an
        upcoming forced install'''
        msclog.debug_log(u"Managed Software Center got forced logout warning")
        # got a notification of an upcoming forced install
        # switch to updates view, then display alert
        self.loadUpdatesPage_(self)
        self.alert_controller.forcedLogoutWarning(notification_obj)

    def checkForUpdates(self, suppress_apple_update_check=False):
        '''start an update check session'''
        # attempt to start the update check
        if self._update_in_progress:
            return
        try:
            munki.startUpdateCheck(suppress_apple_update_check)
        except munki.ProcessStartError, err:
            self.munkiStatusSessionEndedWithStatus_errorMessage_(-2, unicode(err))
            return

        self._update_in_progress = True
        self.displayUpdateCount()
        self.managedsoftwareupdate_task = "manualcheck"
        NSApp.delegate().statusController.startMunkiStatusSession()
        self.markRequestedItemsAsProcessing()


    @IBAction
    def reloadPage_(self, sender):
        '''User selected Reload page menu item. Reload the page and kick off an updatecheck'''
        msclog.log('user', 'reload_page_menu_item_selected')
        self.checkForUpdates()
        self.webView.reload_(sender)

    def kickOffInstallSession(self):
        '''start an update install/removal session'''
        # check for need to logout, restart, firmware warnings
        # warn about blocking applications, etc...
        # then start an update session
        if (MunkiItems.updatesRequireRestart()
                or MunkiItems.updatesRequireLogout()):
            # switch to updates view
            self.loadUpdatesPage_(self)
            # warn about need to logout or restart
            self.alert_controller.confirmUpdatesAndInstall()
        else:
            if self.alert_controller.alertedToBlockingAppsRunning():
                self.loadUpdatesPage_(self)
                return
            if self.alert_controller.alertedToRunningOnBatteryAndCancelled():
                self.loadUpdatesPage_(self)
                return
            self.managedsoftwareupdate_task = None
            msclog.log("user", "install_without_logout")
            self._update_in_progress = True
            self.displayUpdateCount()
            self.setStatusViewTitle_(
                NSLocalizedString(u"Updating...", u"Updating message"))
            try:
                munki.justUpdate()
            except munki.ProcessStartError, err:
                msclog.debug_log("Error starting install session: %s" % err)
                self.munkiStatusSessionEndedWithStatus_errorMessage_(-2, err)
            else:
                self.managedsoftwareupdate_task = "installwithnologout"
                NSApp.delegate().statusController.startMunkiStatusSession()
                self.markPendingItemsAsInstalling()

    def markPendingItemsAsInstalling(self):
        '''While an install/removal session is happening, mark optional items
        that are being installed/removed with the appropriate status'''
        msclog.debug_log('marking pendingItems as installing')
        install_info = munki.getInstallInfo()
        items_to_be_installed_names = [
            item['name'] for item in install_info.get('managed_installs', [])]
        items_to_be_removed_names = [
            item['name'] for item in install_info.get('removals', [])]

        for name in items_to_be_installed_names:
            # remove names for user selections since we are installing
            MunkiItems.user_install_selections.discard(name)

        for name in items_to_be_removed_names:
            # remove names for user selections since we are removing
            MunkiItems.user_removal_selections.discard(name)

        for item in MunkiItems.getOptionalInstallItems():
            new_status = None
            if item['name'] in items_to_be_installed_names:
                msclog.debug_log(
                    'Setting status for %s to "installing"' % item['name'])
                new_status = u'installing'
            elif item['name'] in items_to_be_removed_names:
                msclog.debug_log(
                    'Setting status for %s to "removing"' % item['name'])
                new_status = u'removing'
            if new_status:
                item['status'] = new_status
                self.updateDOMforOptionalItem(item)

    def markRequestedItemsAsProcessing(self):
        '''When an update check session is happening, mark optional items
           that have been requested as processing'''
        msclog.debug_log('marking requested items as processing')
        for item in MunkiItems.getOptionalInstallItems():
            new_status = None
            if item['status'] == 'install-requested':
                msclog.debug_log(
                    'Setting status for %s to "downloading"' % item['name'])
                new_status = u'downloading'
            elif item['status'] == 'removal-requested':
                msclog.debug_log(
                    'Setting status for %s to "preparing-removal"'
                    % item['name'])
                new_status = u'preparing-removal'
            if new_status:
                item['status'] = new_status
                self.updateDOMforOptionalItem(item)

    def updateNow(self):
        '''If user has added to/removed from the list of things to be updated,
        run a check session. If there are no more changes, proceed to an update
        installation session if items to be installed/removed are exclusively
        those selected by the user in this session'''
        if self.stop_requested:
            # reset the flag
            self.stop_requested = False
            self.resetAndReload()
            return
        if MunkiItems.updateCheckNeeded():
            # any item status changes that require an update check?
            msclog.debug_log('updateCheck needed')
            msclog.log("user", "check_then_install_without_logout")
            # since we are just checking for changed self-service items
            # we can suppress the Apple update check
            suppress_apple_update_check = True
            self._update_in_progress = True
            self.displayUpdateCount()
            try:
                munki.startUpdateCheck(suppress_apple_update_check)
            except munki.ProcessStartError, err:
                msclog.debug_log(
                    "Error starting check-then-install session: %s" % err)
                self.munkiStatusSessionEndedWithStatus_errorMessage_(-2, err)
            else:
                self.managedsoftwareupdate_task = "checktheninstall"
                NSApp.delegate().statusController.startMunkiStatusSession()
                self.markRequestedItemsAsProcessing()
        elif (not self._alertedUserToOutstandingUpdates
              and MunkiItems.updatesContainNonUserSelectedItems()):
            # current list of updates contains some not explicitly chosen by
            # the user
            msclog.debug_log(
                'updateCheck not needed, items require user approval')
            self._update_in_progress = False
            self.displayUpdateCount()
            self.loadUpdatesPage_(self)
            self.alert_controller.alertToExtraUpdates()
        else:
            msclog.debug_log('updateCheck not needed')
            self._alertedUserToOutstandingUpdates = False
            self.kickOffInstallSession()

    def getUpdateCount(self):
        '''Get the count of effective updates'''
        if self._update_in_progress:
            return 0
        return len(MunkiItems.getEffectiveUpdateList())

    def displayUpdateCount(self):
        '''Display the update count as a badge in the window toolbar
        and as an icon badge in the Dock'''
        updateCount = self.getUpdateCount()
        btn_image = MSCBadgedTemplateImage.imageNamed_withCount_(
            'updatesTemplate.pdf', updateCount)
        self.updateButtonCell.setImage_(btn_image)
        if updateCount not in [u'★', 0]:
            NSApp.dockTile().setBadgeLabel_(str(updateCount))
        else:
            NSApp.dockTile().setBadgeLabel_(None)

    def updateMyItemsPage(self):
        '''Update the "My Items" page with current data.
        Modifies the DOM to avoid ugly browser refresh'''
        myitems_rows = mschtml.build_myitems_rows()
        document = self.webView.mainFrameDocument()
        table_body_element = document.getElementById_('my_items_rows')
        table_body_element.setInnerHTML_(myitems_rows)

    def updateCategoriesPage(self):
        '''Update the Categories page with current data.
        Modifies the DOM to avoid ugly browser refresh'''
        items_html = mschtml.build_category_items_html()
        document = self.webView.mainFrameDocument()
        items_div_element = document.getElementById_('optional_installs_items')
        items_div_element.setInnerHTML_(items_html)

    def updateListPage(self):
        '''Update the optional items list page with current data.
        Modifies the DOM to avoid ugly browser refresh'''
        page_url = self.webView.mainFrameURL()
        filename = NSURL.URLWithString_(page_url).lastPathComponent()
        name = os.path.splitext(filename)[0]
        key, _, value = name.partition('-')
        category = None
        our_filter = None
        developer = None
        if key == 'category':
            if value != 'all':
                category = value
        elif key == 'filter':
            our_filter = value
        elif key == 'developer':
            developer = value
        else:
            msclog.debug_log(
                'updateListPage unexpected error: _current_page_filename is %s'
                % filename)
            return
        msclog.debug_log(
            'updating software list page with category: '
            '%s, developer; %s, filter: %s' % (category, developer, our_filter))
        items_html = mschtml.build_list_page_items_html(
            category=category, developer=developer, filter=our_filter)
        document = self.webView.mainFrameDocument()
        items_div_element = document.getElementById_('optional_installs_items')
        items_div_element.setInnerHTML_(items_html)

    def load_page(self, url_fragment):
        '''Tells the WebView to load the appropriate page'''
        msclog.debug_log('load_page request for %s' % url_fragment)
        html_file = os.path.join(self.html_dir, url_fragment)
        request = NSURLRequest.requestWithURL_cachePolicy_timeoutInterval_(
            NSURL.fileURLWithPath_(html_file),
            NSURLRequestReloadIgnoringLocalCacheData, 10)
        self.webView.mainFrame().loadRequest_(request)
        if url_fragment == 'updates.html':
            # clear all earlier update notifications
            NSUserNotificationCenter.defaultUserNotificationCenter(
                ).removeAllDeliveredNotifications()

    def setNoPageCache(self):
        '''We disable the back/forward page cache because
        we generate each page dynamically; we want things
        that are changed in one page view to be reflected
        immediately in all page views'''
        identifier = u'com.googlecode.munki.ManagedSoftwareCenter'
        prefs = WebPreferences.alloc().initWithIdentifier_(identifier)
        prefs.setUsesPageCache_(False)
        self.webView.setPreferencesIdentifier_(identifier)

##### WebView delegate methods #####

    def webView_decidePolicyForNewWindowAction_request_newFrameName_decisionListener_(
            self, sender, actionInformation, request, frameName, listener):
        '''open link in default browser instead of in our app's WebView'''
        listener.ignore()
        NSWorkspace.sharedWorkspace().openURL_(request.URL())

    def webView_decidePolicyForMIMEType_request_frame_decisionListener_(
            self, sender, mimetype, request, frame, listener):
        '''Decide whether to show or download content'''
        if WebView.canShowMIMEType_(mimetype):
            listener.use()
        else:
            # send the request to the user's default browser instead, where it
            # can display or download it
            listener.ignore()
            NSWorkspace.sharedWorkspace().openURL_(request.URL())

    def webView_resource_willSendRequest_redirectResponse_fromDataSource_(
            self, sender, identifier, request, redirectResponse, dataSource):
        '''By reacting to this delegate notification, we can build the page
        the WebView wants to load'''
        msclog.debug_log(
            'webView_resource_willSendRequest_redirectResponse_fromDataSource_')
        url = request.URL()
        msclog.debug_log('Got URL scheme: %s' % url.scheme())
        if url.scheme() == NSURLFileScheme:
            msclog.debug_log(u'Request path is %s' % url.path())
            if self.html_dir in url.path():
                msclog.debug_log(u'request for %s' % url.path())
                filename = unicode(url.lastPathComponent())
                if (filename.endswith(u'.html')
                        and (filename.startswith(u'detail-')
                             or filename.startswith(u'category-')
                             or filename.startswith(u'filter-')
                             or filename.startswith(u'developer-')
                             or filename.startswith(u'updatedetail-')
                             or filename == u'myitems.html'
                             or filename == u'updates.html'
                             or filename == u'categories.html')):
                    try:
                        mschtml.build_page(filename)
                    except BaseException, err:
                        msclog.debug_log(u'Could not build page for %s: %s'
                                         % (filename, err))
        return request

    def webView_didClearWindowObject_forFrame_(
            self, sender, windowScriptObject, frame):
        '''Configure webView to let JavaScript talk to this object.'''
        windowScriptObject.setValue_forKey_(self, 'AppController')

    def webView_didStartProvisionalLoadForFrame_(self, view, frame):
        '''Animate progress spinner while we load a page and highlight the
        proper toolbar button'''
        self.progressSpinner.startAnimation_(self)
        main_url = self.webView.mainFrameURL()
        parts = urlparse(main_url)
        pagename = os.path.basename(parts.path)
        msclog.debug_log('Requested pagename is %s' % pagename)
        if (pagename == 'category-all.html'
                or pagename.startswith('detail-')
                or pagename.startswith('filter-')
                or pagename.startswith('developer-')):
            self.highlightToolbarButtons_("Software")
        elif pagename == 'categories.html' or pagename.startswith('category-'):
            self.highlightToolbarButtons_("Categories")
        elif pagename == 'myitems.html':
            self.highlightToolbarButtons_("My Items")
        elif pagename == 'updates.html' or pagename.startswith('updatedetail-'):
            self.highlightToolbarButtons_("Updates")
        else:
            # no idea what type of item it is
            self.highlightToolbarButtons_(None)

    def webView_didFinishLoadForFrame_(self, view, frame):
        '''Stop progress spinner and update state of back/forward buttons'''
        self.progressSpinner.stopAnimation_(self)
        self.navigateBackBtn.setEnabled_(self.webView.canGoBack())
        self.navigateForwardBtn.setEnabled_(self.webView.canGoForward())

    def webView_didFailProvisionalLoadWithError_forFrame_(
            self, view, error, frame):
        '''Stop progress spinner and log'''
        self.progressSpinner.stopAnimation_(self)
        msclog.debug_log(u'Provisional load error: %s' % error)
        files = os.listdir(self.html_dir)
        msclog.debug_log('Files in html_dir: %s' % files)

    def webView_didFailLoadWithError_forFrame_(self, view, error, frame):
        '''Stop progress spinner and log error'''
        #TO-DO: display an error page?
        self.progressSpinner.stopAnimation_(self)
        msclog.debug_log('Committed load error: %s' % error)

    def isSelectorExcludedFromWebScript_(self, aSelector):
        '''Declare which methods can be called from JavaScript'''
        # For security, you must explicitly allow a selector to be called
        # from JavaScript.
        if aSelector in ['openExternalLink:',
                         'actionButtonClicked:',
                         'myItemsActionButtonClicked:',
                         'changeSelectedCategory:',
                         'installButtonClicked',
                         'updateOptionalInstallButtonClicked:',
                         'updateOptionalInstallButtonFinishAction:']:
            return NO # this selector is NOT _excluded_ from scripting
        return YES # disallow everything else

#### handling DOM UI elements ####

    def openExternalLink_(self, url):
        '''open a link in the default browser'''
        NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_(url))

    def installButtonClicked(self):
        '''this method is called from JavaScript when the user
        clicks the Install button in the Updates view'''
        if self._update_in_progress:
            # this is now a stop/cancel button
            msclog.log('user', 'cancel_updates')
            NSApp.delegate().statusController.disableStopButton()
            NSApp.delegate().statusController._status_stopBtnState = 1
            self.stop_requested = True
            # send a notification that stop button was clicked
            STOP_REQUEST_FLAG = (
                u'/private/tmp/'
                'com.googlecode.munki.managedsoftwareupdate.stop_requested')
            if not os.path.exists(STOP_REQUEST_FLAG):
                open(STOP_REQUEST_FLAG, 'w').close()

        elif self.getUpdateCount() == 0:
            # no updates, this button must say "Check Again"
            msclog.log('user', 'refresh_clicked')
            self.checkForUpdates()
        else:
            # must say "Update"
            # we're on the Updates page, so users can see all the pending/
            # outstanding updates
            self._alertedUserToOutstandingUpdates = True
            self.updateNow()

    def showUpdateProgressSpinner(self):
        '''This method is currently unused'''
        # update the status header on the updates page
        document = self.webView.mainFrameDocument()
        spinner = document.getElementById_('updates-progress-spinner')
        if spinner:
            spinner_classes = spinner.className().split(' ')
            if 'hidden' in spinner_classes:
                spinner_classes.remove('hidden')
                spinner.setClassName_(' '.join(spinner_classes))
        update_count_element = document.getElementById_('update-count-string')
        if update_count_element:
            update_count_element.setInnerText_(
                NSLocalizedString(u"Checking for updates...",
                                  u"Checking For Updates message"))
        warning_text_element = document.getElementById_('update-warning-text')
        if warning_text_element:
            warning_text_element.setInnerHTML_('')
        install_all_button = document.getElementById_('install-all-button-text')
        if install_all_button:
            install_all_button.setInnerText_(
                NSLocalizedString(u"Cancel",
                                  u"Cancel button title/short action text"))

        container_div = document.getElementById_('os-and-app-updates')
        if container_div:
            container_div_classes = container_div.className().split(' ')
            if not 'updating' in container_div_classes:
                container_div_classes.append('updating')
                container_div.setClassName_(' '.join(container_div_classes))

    def updateOptionalInstallButtonClicked_(self, item_name):
        '''this method is called from JavaScript when a user clicks
        the cancel or add button in the updates list'''
        item = MunkiItems.optionalItemForName_(item_name)
        if not item:
            msclog.debug_log(
                'Unexpected error: Can\'t find item for %s' % item_name)
            return
        if (item['status'] == 'update-available'
                and item.get('preupgrade_alert')):
            self.displayPreInstallUninstallAlert_Action_Item_(
                item['preupgrade_alert'],
                self.updateOptionalInstallButtonBeginAction_, item_name)
        else:
            self.updateOptionalInstallButtonBeginAction_(item_name)

    def updateOptionalInstallButtonBeginAction_(self, item_name):
        scriptObject = self.webView.windowScriptObject()
        args = [item_name]
        scriptObject.callWebScriptMethod_withArguments_(
            'fadeOutAndRemove', args)

    def update_status_for_item(self, item):
        '''Attempts to update an item's status; displays an error dialog
        if SelfServeManifest is not writable.
        Returns a boolean to indicate success'''
        try:
            item.update_status()
            return True
        except MunkiItems.SelfServiceError, err:
            msclog.debug_log(str(err))
            alertTitle = NSLocalizedString(
                u"System configuration problem", 
                u"System configuration problem alert title")
            alertDetail = NSLocalizedString(
                u"A systems configuration issue is preventing Managed Software "
                "Center from operating correctly. The reported issue is: ",
                u"System configuration problem alert detail")
            alertDetail = alertDetail + "\n" + str(err)
            alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(
                alertTitle,
                NSLocalizedString(u"OK", u"OK button title"),
                nil,
                nil,
                u"%@", alertDetail)
            result = alert.runModal()
            return False

    def updateOptionalInstallButtonFinishAction_(self, item_name):
        '''Perform the required action when a user clicks
        the cancel or add button in the updates list'''
        # TO-DO: better handling of all the possible "unexpected error"s
        document = self.webView.mainFrameDocument()
        item = MunkiItems.optionalItemForName_(item_name)
        if not item:
            msclog.debug_log(
                'Unexpected error: Can\'t find item for %s' % item_name)
            return
        update_table_row = document.getElementById_('%s_update_table_row'
                                                    % item_name)
        if not update_table_row:
            msclog.debug_log(
                'Unexpected error: Can\'t find table row for %s' % item_name)
            return
        # remove this row from its current table
        update_table_row.parentNode().removeChild_(update_table_row)

        previous_status = item['status']
        # update item status
        if not self.update_status_for_item(item):
            # there was a problem, can't continue
            return

        msclog.log('user', 'optional_install_' + item['status'], item_name)

        # do we need to add a new node to the other list?
        if item.get('needs_update'):
            # make some new HTML for the updated item
            managed_update_names = MunkiItems.getInstallInfo().get(
                'managed_updates', [])
            item_template = mschtml.get_template('update_row_template.html')
            item_html = item_template.safe_substitute(item)

            if item['status'] in ['install-requested',
                                  'update-will-be-installed', 'installed']:
                # add the node to the updates-to-install table
                table = document.getElementById_('updates-to-install-table')
            if item['status'] == 'update-available':
                # add the node to the other-updates table
                table = document.getElementById_('other-updates-table')
            if not table:
                msclog.debug_log(
                    'Unexpected error: could not find other-updates-table')
                return
            # this isn't the greatest way to add something to the DOM
            # but it works...
            table.setInnerHTML_(table.innerHTML() + item_html)

        # might need to toggle visibility of other updates div
        other_updates_div = document.getElementById_('other-updates')
        other_updates_div_classes = other_updates_div.className().split(' ')
        other_updates_table = document.getElementById_('other-updates-table')
        if other_updates_table.innerHTML().strip():
            if 'hidden' in other_updates_div_classes:
                other_updates_div_classes.remove('hidden')
                other_updates_div.setClassName_(
                    ' '.join(other_updates_div_classes))
        else:
            if not 'hidden' in other_updates_div_classes:
                other_updates_div_classes.append('hidden')
                other_updates_div.setClassName_(
                    ' '.join(other_updates_div_classes))

        # update the updates-to-install header to reflect the new list of
        # updates to install
        updateCount = self.getUpdateCount()
        update_count_message = msclib.updateCountMessage(updateCount)
        update_count_element = document.getElementById_('update-count-string')
        if update_count_element:
            update_count_element.setInnerText_(update_count_message)

        warning_text = mschtml.get_warning_text()
        warning_text_element = document.getElementById_('update-warning-text')
        if warning_text_element:
            warning_text_element.setInnerHTML_(warning_text)

        # update text of Install All button
        install_all_button_element = document.getElementById_(
            'install-all-button-text')
        if install_all_button_element:
            install_all_button_element.setInnerText_(
                msclib.getInstallAllButtonTextForCount(updateCount))

        # update count badges
        self.displayUpdateCount()

        if MunkiItems.updateCheckNeeded():
            # check for updates after a short delay so UI changes visually
            # complete first
            self.performSelector_withObject_afterDelay_(
                self.checkForUpdates, True, 1.0)

    def myItemsActionButtonClicked_(self, item_name):
        '''this method is called from JavaScript when the user clicks
        the Install/Remove/Cancel button in the My Items view'''
        item = MunkiItems.optionalItemForName_(item_name)
        if not item:
            msclog.debug_log(
                'Unexpected error: Can\'t find item for %s' % item_name)
            return
        if item['status'] == 'installed' and item.get('preuninstall_alert'):
            self.displayPreInstallUninstallAlert_Action_Item_(
                item['preuninstall_alert'],
                self.myItemsActionButtonPerformAction_, item_name)
        else:
            self.myItemsActionButtonPerformAction_(item_name)

    def myItemsActionButtonPerformAction_(self, item_name):
        '''perform action needed when user clicks
        the Install/Remove/Cancel button in the My Items view'''
        document = self.webView.mainFrameDocument()
        item = MunkiItems.optionalItemForName_(item_name)
        status_line = document.getElementById_('%s_status_text' % item_name)
        btn = document.getElementById_('%s_action_button_text' % item_name)
        if not item or not btn or not status_line:
            msclog.debug_log(
                'User clicked MyItems action button for %s' % item_name)
            msclog.debug_log('Unexpected error finding HTML elements')
            return
        prior_status = item['status']
        if not self.update_status_for_item(item):
            # there was a problem, can't continue
            return

        self.displayUpdateCount()
        if item['status'] == 'not-installed':
            # we removed item from list of things to install
            # now remove from display
            table_row = document.getElementById_(
                '%s_myitems_table_row' % item_name)
            if table_row:
                table_row.parentNode().removeChild_(table_row)
        else:
            btn.setInnerText_(item['myitem_action_text'])
            status_line.setInnerText_(item['status_text'])
            status_line.setClassName_('status %s' % item['status'])

        if item['status'] in ['install-requested', 'removal-requested']:
            self._alertedUserToOutstandingUpdates = False
            if not self._update_in_progress:
                self.updateNow()
        elif prior_status in ['will-be-installed', 'update-will-be-installed',
                              'will-be-removed']:
            # cancelled a pending install or removal; should run an updatecheck
            self.checkForUpdates(suppress_apple_update_check=True)

    def updateDOMforOptionalItem(self, item):
        '''Update displayed status of an item'''
        document = self.webView.mainFrameDocument()
        if not document:
            return
        status_line = document.getElementById_('%s_status_text' % item['name'])
        status_text_span = document.getElementById_(
            '%s_status_text_span' % item['name'])
        btn = document.getElementById_('%s_action_button_text' % item['name'])
        if not btn or not status_line:
            msclog.debug_log('ERROR in updateDOMforOptionalItem: '
                             'could not find items in DOM')
            return
        btn_classes = btn.className().split(' ')
        # filter out status class
        btn_classes = [class_name for class_name in btn_classes
                       if class_name in ['msc-button-inner', 'large', 'small',
                                         'install-updates']]
        btn_classes.append(item['status'])
        btn.setClassName_(' '.join(btn_classes))
        if 'install-updates' in btn_classes:
            btn.setInnerText_(item['myitem_action_text'])
        elif 'large' in btn_classes:
            btn.setInnerText_(item['long_action_text'])
        else:
            btn.setInnerText_(item['short_action_text'])
        if status_text_span:
            # use setInnerHTML_ instead of setInnerText_ because sometimes the status
            # text contains html, like '<span class="warning">Some warning</span>'
            status_text_span.setInnerHTML_(item['status_text'])
        status_line.setClassName_(item['status'])

    def actionButtonClicked_(self, item_name):
        '''this method is called from JavaScript when the user clicks
        the Install/Remove/Cancel button in the list or detail view'''

        item = MunkiItems.optionalItemForName_(item_name)
        if not item:
            msclog.debug_log(
                'User clicked Install/Remove/Upgrade/Cancel button in the list '
                'or detail view')
            msclog.debug_log('Can\'t find item: %s' % item_name)
            return

        showAlert = True
        if item['status'] == 'not-installed' and item.get('preinstall_alert'):
            self.displayPreInstallUninstallAlert_Action_Item_(
                item['preinstall_alert'],
                self.actionButtonPerformAction_, item_name)
        elif item['status'] == 'installed' and item.get('preuninstall_alert'):
            self.displayPreInstallUninstallAlert_Action_Item_(
                item['preuninstall_alert'],
                self.actionButtonPerformAction_, item_name)
        elif (item['status'] == 'update-available'
              and item.get('preupgrade_alert')):
            self.displayPreInstallUninstallAlert_Action_Item_(
                item['preupgrade_alert'],
                self.actionButtonPerformAction_, item_name)
        else:
            self.actionButtonPerformAction_(item_name)
            showAlert = False
        if showAlert:
            msclog.log("user", "show_alert")

    def displayPreInstallUninstallAlert_Action_Item_(
            self, alert_dict, action_selector, item_name):
        ''' Display an alert sheet before processing item install/upgrade
        or uninstall '''
        defaultAlertTitle = NSLocalizedString(
            u'Attention', u'Pre Install Uninstall Upgrade Alert Title')
        defaultAlertDetail = NSLocalizedString(
            u'Some conditions apply to this software. '
            'Please contact your administrator for more details',
            u'Pre Install Uninstall Upgrade Alert Detail')
        defaultOKLabel = NSLocalizedString(
            u'OK', u'Pre Install Uninstall Upgrade OK Label')
        defaultCancelLabel = NSLocalizedString(
            u'Cancel', u'Pre Install Uninstall Upgrade Cancel Label')

        alertTitle = alert_dict.get('alert_title') or defaultAlertTitle
        alertDetail = alert_dict.get('alert_detail', defaultAlertDetail)
        OKLabel = alert_dict.get('ok_label') or defaultOKLabel
        cancelLabel = alert_dict.get('cancel_label') or defaultCancelLabel

        self.alert_context_info = {'selector': action_selector,
                                   'item_name': item_name}

        # show the alert sheet
        self.window().makeKeyAndOrderFront_(self)
        alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(
            alertTitle,
            cancelLabel,
            OKLabel,
            nil,
            u"%@", alertDetail)
        alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(
            self.window(),
            self,
            self.actionAlertDidEnd_returnCode_contextInfo_,
            nil)

    def actionAlertDidEnd_returnCode_contextInfo_(
            self, alert, returncode, contextinfo):
        '''Called when alert invoked by actionButtonClicked_ ends'''
        alert.window().orderOut_(self)
        if returncode == NSAlertDefaultReturn:
            msclog.log("user", "alert_canceled")
        else:
            msclog.log("user", "alert_accepted")
            selector = self.alert_context_info.get('selector')
            item_name = self.alert_context_info.get('item_name')
            if selector and item_name:
                selector(item_name)

    def actionButtonPerformAction_(self, item_name):
        '''Perform the action requested when clicking the action button
        in the list or detail view'''
        item = MunkiItems.optionalItemForName_(item_name)
        if not item:
            msclog.debug_log(
                'User clicked Install/Upgrade/Removal/Cancel button '
                'in the list or detail view')
            msclog.debug_log('Can\'t find item: %s' % item_name)
            return

        prior_status = item['status']
        if not self.update_status_for_item(item):
            # there was a problem, can't continue
            return
        msclog.log('user', 'action_button_' + item['status'], item_name)

        self.displayUpdateCount()
        self.updateDOMforOptionalItem(item)

        if item['status'] in ['install-requested', 'removal-requested']:
            self._alertedUserToOutstandingUpdates = False
            if not self._update_in_progress:
                self.updateNow()
        elif prior_status in ['will-be-installed', 'update-will-be-installed',
                              'will-be-removed']:
            # cancelled a pending install or removal; should run an updatecheck
            self.checkForUpdates(suppress_apple_update_check=True)

    def changeSelectedCategory_(self, category):
        '''this method is called from JavaScript when the user
        changes the category selected in the sidebar popup'''
        all_categories_label = NSLocalizedString(
            u"All Categories", u"AllCategoriesLabel")
        featured_label = NSLocalizedString(u"Featured", u"FeaturedLabel")
        if category in [all_categories_label, featured_label]:
            category = u'all'
        self.load_page('category-%s.html' % category)

    def setStatusViewTitle_(self, title_text):
        '''When displaying status during a managedsoftwareupdate run, this
        method is used to display info where the update count message
        usually is'''
        document = self.webView.mainFrameDocument()
        self._status_title = title_text
        # we re-purpose the update count message for this
        update_count_element = document.getElementById_('update-count-string')
        if update_count_element:
            update_count_element.setInnerText_(title_text)

#### some Cocoa UI bindings #####

    @IBAction
    def showHelp_(self, sender):
        helpURL = munki.pref('HelpURL')
        if helpURL:
            NSWorkspace.sharedWorkspace().openURL_(
                NSURL.URLWithString_(helpURL))
        else:
            alertTitle = NSLocalizedString(u"Help", u"No help alert title")
            alertDetail = NSLocalizedString(
                u"Help isn't available for Managed Software Center.",
                u"No help alert detail")
            alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(
                alertTitle,
                NSLocalizedString(u"OK", u"OK button title"),
                nil,
                nil,
                u"%@", alertDetail)
            result = alert.runModal()

    @IBAction
    def navigateBackBtnClicked_(self, sender):
        '''Handle WebView back button'''
        self.webView.goBack_(self)

    @IBAction
    def navigateForwardBtnClicked_(self, sender):
        '''Handle WebView forward button'''
        self.webView.goForward_(self)

    @IBAction
    def loadAllSoftwarePage_(self, sender):
        '''Called by Navigate menu item'''
        self.load_page('category-all.html')

    @IBAction
    def loadCategoriesPage_(self, sender):
        '''Called by Navigate menu item'''
        self.load_page('categories.html')

    @IBAction
    def loadMyItemsPage_(self, sender):
        '''Called by Navigate menu item'''
        self.load_page('myitems.html')

    @IBAction
    def loadUpdatesPage_(self, sender):
        '''Called by Navigate menu item'''
        self.load_page('updates.html')
        self._alertedUserToOutstandingUpdates = True

    @IBAction
    def softwareToolbarButtonClicked_(self, sender):
        '''User clicked Software toolbar button'''
        self.loadAllSoftwarePage_(sender)

    @IBAction
    def categoriesToolbarButtonClicked_(self, sender):
        '''User clicked Categories toolbar button'''
        self.loadCategoriesPage_(sender)

    @IBAction
    def myItemsToolbarButtonClicked_(self, sender):
        '''User clicked My Items toolbar button'''
        self.loadMyItemsPage_(sender)

    @IBAction
    def updatesToolbarButtonClicked_(self, sender):
        '''User clicked Updates toolbar button'''
        self.loadUpdatesPage_(sender)

    @IBAction
    def searchFilterChanged_(self, sender):
        '''User changed the search field'''
        filterString = self.searchField.stringValue().lower()
        if filterString:
            msclog.debug_log('Search filter is: %s'
                             % repr(filterString.encode('utf-8')))
            self.load_page(u'filter-%s.html' % filterString)

    def currentPageIsUpdatesPage(self):
        '''return True if current tab selected is Updates'''
        return self.updatesToolbarButton.state() == NSOnState

    #def currentPageIsMyItemsPage(self):
    #    '''return True if current tab selected is My Items'''
    #    return (self.myItemsToolbarButton.state() == NSOnState)

    #def currentPageIsCategoriesPage(self):
    #    '''return True if current tab selected is Categories'''
    #    return (self.categoriesToolbarButton.state() == NSOnState)
