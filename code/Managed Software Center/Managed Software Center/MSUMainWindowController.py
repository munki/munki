#
#  MSUMainWindowController.py
#  Managed Software Center
#
#  Copyright 2013-2014 Greg Neagle.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os

from urllib import quote_plus, unquote_plus

import munki
import msuhtml
import msulib
import msulog
import FoundationPlist
import MSUBadgedTemplateImage
import MunkiItems

from AlertController import AlertController

from objc import YES, NO, IBAction, IBOutlet, nil
from PyObjCTools import AppHelper
from Foundation import *
from AppKit import *
from WebKit import *

class MSUMainWindowController(NSWindowController):
    
    _alertedUserToOutstandingUpdates = False
    
    _update_in_progress = False
    _update_queue = set()
    
    # status vars
    _status_title = ''
        
    _current_page_filename = None
    
    html_dir = None
    
    tabControl = IBOutlet()
    webView = IBOutlet()
    navigationBtn = IBOutlet()
    progressSpinner = IBOutlet()
    searchField = IBOutlet()
    updateButtonCell = IBOutlet()
    windowMenuSeperatorItem = IBOutlet()
    fullScreenMenuItem = IBOutlet()
    
    def appShouldTerminate(self):
        # save any changes to SelfServe choices
        selectedCell = self.tabControl.selectedCell()
        if selectedCell and selectedCell.tag() == 4:
            # We're already at the updates view, so user is aware of the
            # pending updates, so OK to just terminate.
            return YES
        if not self._alertedUserToOutstandingUpdates and self.getUpdateCount():
            # we have pending updates and we have not yet warned the user
            # about them
            self.alertToPendingUpdates()
            return NO
        return YES

    def alertToPendingUpdates(self):
        self._alertedUserToOutstandingUpdates = True
        alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(
            NSLocalizedString(u"Pending updates", u'PendingUpdatesAlertTitle'),
            NSLocalizedString(u"Quit", u'QuitButtonTitle'),
            NSLocalizedString(u"Show updates", u'ShowUpdatesButtonTitle'),
            NSLocalizedString(u"Update now", u'UpdateNowButtonTitle'),
            NSLocalizedString(u"There are pending updates for this computer.",
                              u'PendingUpdatesAlertDetailText'))
        alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(
            self.window(), self,
            self.updateAlertDidEnd_returnCode_contextInfo_, objc.nil)
    
    @AppHelper.endSheetMethod
    def updateAlertDidEnd_returnCode_contextInfo_(
                                   self, alert, returncode, contextinfo):
        self._currentAlert = None
        if returncode == NSAlertDefaultReturn:
            msulog.log("user", "quit")
            NSApp.terminate_(self)
        elif returncode == NSAlertAlternateReturn:
            msulog.log("user", "view_updates_page")
            self.loadUpdatesPage_(self)
        elif returncode == NSAlertOtherReturn:
            msulog.log("user", "install_now_clicked")
            # initiate the updates
            self.updateNow()
            self.loadUpdatesPage_(self)

    def window_willPositionSheet_usingRect_(self, window, sheet, rect):
        # move the anchor point of our sheets to below our toolbar
        # (or really, to the top of the web view)
        webViewRect = self.webView.frame()
        return NSMakeRect(webViewRect.origin.x, webViewRect.origin.y + webViewRect.size.height,
                          webViewRect.size.width, 0)

    def loadInitialView(self):
        if MunkiItems.getEffectiveUpdateList():
            self.loadUpdatesPage_(self)
        else:
            self.loadAllSoftwarePage_(self)
        self.displayUpdateCount()

    @AppHelper.endSheetMethod
    def munkiSessionErrorAlertDidEnd_returnCode_contextInfo_(
                                        self, alert, returncode, contextinfo):
        self.resetAndReload()
    
    def munkiTaskEnded_withResult_(self, tasktype, sessionResult):
        self._update_in_progress = False
        
        # The managedsoftwareupdate run will have changed state preferences
        # in ManagedInstalls.plist. Load the new values.
        munki.reload_prefs()
        lastCheckResult = munki.pref("LastCheckResult")
        if sessionResult != 0 or lastCheckResult < 0:
            OKButtonTitle = NSLocalizedString(u"OK", u'OKButtonTitle')
            alertMessageText = NSLocalizedString(u"Update check failed", u'UpdateCheckFailedTitle')
            if tasktype == "installwithnologout":
                alertMessageText = NSLocalizedString(
                                        u"Install session failed", u'InstallSessionFailedTitle')

            if sessionResult == -1:
                # connection was dropped unexpectedly
                msulog.log("MSC", "cant_update", "unexpected process end")
                detailText = NSLocalizedString(
                    (u"There is a configuration problem with the managed software installer. "
                      "The process ended unexpectedly. Contact your systems administrator."),
                     u'UnexpectedSessionEndMessage')
            elif sessionResult == -2:
                # session never started
                msulog.log("MSC", "cant_update", "process did not start")
                detailText = NSLocalizedString(
                    (u"There is a configuration problem with the managed software installer. "
                      "Could not start the process. Contact your systems administrator."),
                     u'CouldNotStartSessionMessage')
            elif lastCheckResult == -1:
                # server not reachable
                msulog.log("MSC", "cant_update", "cannot contact server")
                detailText = NSLocalizedString(
                    (u"Managed Software Center cannot contact the update server at this time.\n"
                      "Try again later. If this situation continues, "
                      "contact your systems administrator."), u'CannotContactServerDetail')
            elif lastCheckResult == -2:
                # preflight failed
                msulog.log("MSU", "cant_update", "failed preflight")
                detailText = NSLocalizedString(
                    (u"Managed Software Center cannot check for updates now.\n"
                      "Try again later. If this situation continues, "
                      "contact your systems administrator."), u'FailedPreflightCheckDetail')
            # show the alert sheet
            self.window().makeKeyAndOrderFront_(self)
            alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(
                alertMessageText, OKButtonTitle, nil, nil, detailText)
            alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(
                self.window(), self,
                self.munkiSessionErrorAlertDidEnd_returnCode_contextInfo_, nil)
            return
        
        if tasktype == 'checktheninstall':
            MunkiItems.reset()
            # possibly check again if choices have changed
            self.updateNow()
            return

        if lastCheckResult == 1:
            # there are some updates to install; are we expected to install them now?
            # done checking; now try to install...
            #self.kickOffUpdateSession()
            #return
            pass

        # all done checking and/or installing: display results
        self.resetAndReload()
        if self._update_queue:
            # more stuff pending? Let's do it
            self._update_queue.clear()
            self.updateNow()

    def resetAndReload(self):
        NSLog('resetAndReload method called')
        # need to clear out cached data
        MunkiItems.reset()
        self._alertedUserToOutstandingUpdates = False
        # what page are we currently viewing?
        filename = self._current_page_filename
        name = os.path.splitext(filename)[0]
        key, p, quoted_value = name.partition('-')
        value = unquote_plus(quoted_value)
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
        # closing the main window should be the same as quitting
        NSApp.terminate_(self)
        return NO

    def configureFullScreenMenuItem(self):
        # check to see if NSWindow's toggleFullScreen: selector is implemented.
        # if so, unhide the menu items for going full screen
        if self.window().respondsToSelector_('toggleFullScreen:'):
            self.windowMenuSeperatorItem.setHidden_(False)
            self.fullScreenMenuItem.setHidden_(False)
            self.fullScreenMenuItem.setEnabled_(True)

    def awakeFromNib(self):
        self.configureFullScreenMenuItem()
        self.webView.setDrawsBackground_(NO)
        self.webView.setUIDelegate_(self)
        self.webView.setFrameLoadDelegate_(self)
        self.webView.setResourceLoadDelegate_(self)
        self.webView.setPolicyDelegate_(self)
        self.setNoPageCache()
        self.alert_controller = AlertController.alloc().init()
        self.alert_controller.setWindow_(self.window())
        self.html_dir = msulib.html_dir()
    
    def forcedLogoutWarning(self, notification_obj):
        # got a notification of an upcoming forced install
        # switch to updates view, then display alert
        self.loadUpdatesPage_(self)
        self.alert_controller.forcedLogoutWarning(notification_obj)
    
    def kickOffUpdateSession(self):
        # TO-DO: check for need to logout, restart, firmware warnings
        # warn about blocking applications, etc...
        if MunkiItems.updatesRequireRestart() or MunkiItems.updatesRequireLogout():
            self.alert_controller.confirmUpdatesAndInstall()
        else:
            if self.alert_controller.alertedToBlockingAppsRunning():
                # do nothing
                return
            if self.alert_controller.alertedToRunningOnBatteryAndCancelled():
                # do nothing
                return
            NSApp.delegate().managedsoftwareupdate_task = None
            msulog.log("user", "install_without_logout")
            self._update_in_progress = True
            self.displayUpdateCount()
            self.setStatusViewTitle_(NSLocalizedString(
                u'Updating...', u'UpdatingMessage').encode('utf-8'))
            result = munki.justUpdate()
            if result:
                NSLog("Error starting install session: %s" % result)
                NSApp.delegate().munkiStatusSessionEnded_(2)
            else:
                NSApp.delegate().managedsoftwareupdate_task = "installwithnologout"
                NSApp.delegate().statusController.startMunkiStatusSession()
                self.markPendingItemsAsInstalling()

    def markPendingItemsAsInstalling(self):
        install_info = munki.getInstallInfo()
        items_to_be_installed_names = [item['name']
                                       for item in install_info.get('managed_installs', [])]
        items_to_be_removed_names = [item['name']
                                     for item in install_info.get('removals', [])]
        
        for item in MunkiItems.getOptionalInstallItems():
            new_status = None
            if item['name'] in items_to_be_installed_names:
                NSLog('Setting status for %s to "installing"' % item['name'])
                new_status =  'installing'
            elif item['name'] in items_to_be_removed_names:
                NSLog('Setting status for %s to "removing"' % item['name'])
                new_status = 'removing'
            if new_status:
                item['status'] = new_status
                self.updateDOMforOptionalItem(item)

    def updateNow(self):
        if not MunkiItems.allOptionalChoicesProcessed():
            NSLog('selfService choices changed')
            msulog.log("user", "check_then_install_without_logout")
            # since we are just checking for changed self-service items
            # we can suppress the Apple update check
            suppress_apple_update_check = True
            self._update_in_progress = True
            self.displayUpdateCount()
            result = munki.startUpdateCheck(suppress_apple_update_check)
            result = 0
            if result:
                NSLog("Error starting check-then-install session: %s" % result)
                NSApp.delegate().munkiStatusSessionEnded_(2)
            else:
                NSApp.delegate().managedsoftwareupdate_task = "checktheninstall"
                NSApp.delegate().statusController.startMunkiStatusSession()
        else:
            NSLog('selfService choices unchanged')
            self.kickOffUpdateSession()

    def getUpdateCount(self):
        if self._update_in_progress:
            return 0
        return len(MunkiItems.getEffectiveUpdateList())

    def displayUpdateCount(self):
        updateCount = self.getUpdateCount()
        btn_image = MSUBadgedTemplateImage.imageNamed_withCount_(
                        'toolbarUpdatesTemplate.png', updateCount)
        self.updateButtonCell.setImage_(btn_image)
        if updateCount:
            NSApp.dockTile().setBadgeLabel_(str(updateCount))
        else:
            NSApp.dockTile().setBadgeLabel_(None)
    
    def updateMyItemsPage(self):
        '''Modifies the DOM to avoid ugly browser refresh'''
        myitems_rows = msuhtml.build_myitems_rows()
        document = self.webView.mainFrameDocument()
        table_body_element = document.getElementById_('my_items_rows')
        table_body_element.setInnerHTML_(myitems_rows)

    def updateCategoriesPage(self):
        '''Modifies DOM on currently displayed page to avoid nasty page refresh'''
        items_html = msulib.build_category_items_html()
        document = self.webView.mainFrameDocument()
        items_div_element = document.getElementById_('optional_installs_items')
        items_div_element.setInnerHTML_(items_html)

    def updateListPage(self):
        '''Modifies DOM on currently displayed page to avoid nasty page refresh'''
        filename = self._current_page_filename
        if not filename:
            NSLog('updateListPage unexpected error: no _current_page_filename')
            return
        name = os.path.splitext(filename)[0]
        key, p, quoted_value = name.partition('-')
        category = None
        filter = None
        developer = None
        value = unquote_plus(quoted_value)
        if key == 'category':
            if value != 'all':
                category = value
        elif key == 'filter':
            filter = value
        elif key == 'developer':
            developer = value
        else:
            NSLog('updateListPage unexpected error: _current_page_filename is %s' %
                  filename)
            return
        NSLog('updating with category: %s, developer; %s, filter: %s' %
              (category, developer, filter))
        items_html = msuhtml.build_list_page_items_html(
                            category=category, developer=developer, filter=filter)
        document = self.webView.mainFrameDocument()
        items_div_element = document.getElementById_('optional_installs_items')
        items_div_element.setInnerHTML_(items_html)

    def load_page(self, url_fragment):
        html_file = os.path.join(self.html_dir, url_fragment)
        request = NSURLRequest.requestWithURL_cachePolicy_timeoutInterval_(
            NSURL.fileURLWithPath_(html_file), NSURLRequestReloadIgnoringLocalCacheData, 10)
        self.webView.mainFrame().loadRequest_(request)

    def setNoPageCache(self):
        # We disable the back/forward page cache because
        # we generate each page dynamically; we want things
        # that are changed in one page view to be reflected
        # immediately in all page views
        identifier = 'com.googlecode.munki.ManagedSoftwareCenter'
        prefs = WebPreferences.alloc().initWithIdentifier_(identifier)
        prefs.setUsesPageCache_(False)
        self.webView.setPreferencesIdentifier_(identifier)

##### WebView delegate methods #####

    def webView_decidePolicyForNewWindowAction_request_newFrameName_decisionListener_(
            self, webView, actionInformation, request, frameName, listener):
        # open link in default browser
        listener.ignore()
        NSWorkspace.sharedWorkspace().openURL_(request.URL())

    def webView_resource_willSendRequest_redirectResponse_fromDataSource_(
            self, sender, identifier, request, redirectResponse, dataSource):
        url = request.URL()
        if url.scheme() == 'file' and os.path.join(self.html_dir) in url.path():
            #NSLog(u'Got request for local file: %@', url.path())
            filename = url.lastPathComponent()
            if (filename.endswith('.html')
                and (filename.startswith('detail-')
                     or filename.startswith('category-')
                     or filename.startswith('filter-')
                     or filename.startswith('developer-')
                     or filename.startswith('updatedetail-')
                     or filename == 'myitems.html'
                     or filename == 'updates.html'
                     or filename == 'categories.html')):
                try:
                    msuhtml.build_page(filename)
                except Exception, e:
                    NSLog('%@', e)
                if filename == 'category-all.html':
                    self.tabControl.selectCellWithTag_(1)
                elif filename == 'categories.html':
                    self.tabControl.selectCellWithTag_(2)
                elif filename == 'myitems.html':
                    self.tabControl.selectCellWithTag_(3)
                elif filename == 'updates.html':
                    self.tabControl.selectCellWithTag_(4)
                else:
                    self.tabControl.deselectAllCells()
                # store the filename
                self._current_page_filename = filename

        return request

    def webView_didClearWindowObject_forFrame_(self, sender, windowScriptObject, frame):
        # Configure webView to let JavaScript talk to this object.
        self.windowScriptObject = windowScriptObject
        windowScriptObject.setValue_forKey_(self, 'AppController')

    def webView_didStartProvisionalLoadForFrame_(self, view, frame):
        self.progressSpinner.startAnimation_(self)

    def webView_didFinishLoadForFrame_(self, view, frame):
        self.progressSpinner.stopAnimation_(self)
        self.navigationBtn.setEnabled_forSegment_(self.webView.canGoBack(), 0)
        self.navigationBtn.setEnabled_forSegment_(self.webView.canGoForward(), 1)

    def webView_didFailProvisionalLoadWithError_forFrame_(self, view, error, frame):
        self.progressSpinner.stopAnimation_(self)
        NSLog(u'Provisional load error: %@', error)

    def webView_didFailLoadWithError_forFrame_(self, view, error, frame):
        self.progressSpinner.stopAnimation_(self)
        NSLog('Committed load error: %@', error)

    def isSelectorExcludedFromWebScript_(self, aSelector):
        # For security, you must explicitly allow a selector to be called from JavaScript.
        if aSelector in ['actionButtonClicked:',
                         'myItemsActionButtonClicked:',
                         'changeSelectedCategory:',
                         'installButtonClicked',
                         'updateOptionalInstallButtonClicked:']:
            return NO # this selector is NOT _excluded_ from scripting, so it can be called.
        return YES # disallow everything else

#### handling DOM UI elements ####

    def installButtonClicked(self):
        # this method is called from JavaScript when the user
        # clicks the Install All button in the Updates view
        if self._update_in_progress:
            # this is now a stop/cancel button
            NSApp.delegate().statusController.disableStopButton()
            NSApp.delegate().statusController._status_stopBtnState =  1
            # send a notification that stop button was clicked
            STOP_REQUEST_FLAG = '/private/tmp/com.googlecode.munki.managedsoftwareupdate.stop_requested'
            if not os.path.exists(STOP_REQUEST_FLAG):
                open(STOP_REQUEST_FLAG, 'w').close()

        elif self.getUpdateCount() == 0:
            # no updates, this button must say "Check Again"
            self._update_in_progress = True
            self.loadUpdatesPage_(self)
            self.displayUpdateCount()
            NSApp.delegate().checkForUpdates()
        else:
            # must say "Update"
            self.updateNow()
            self.loadUpdatesPage_(self)
    
    def showUpdateProgressSpinner(self):
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
                NSLocalizedString(u'Checking for updates...',
                                  u'CheckingForUpdatesMessage')).encode('utf-8')
        warning_text_element = document.getElementById_('update-warning-text')
        if warning_text_element:
            warning_text_element.setInnerHTML_('')
        install_all_button = document.getElementById_('install-all-button-text')
        if install_all_button:
            install_all_button.setInnerText_(
                NSLocalizedString(u'Cancel', u'CancelButtonText')).encode('utf-8')
            #btn_classes = install_all_button.className().split(' ')
            #if not 'checking' in btn_classes:
            #    btn_classes.append('checking')
            #    install_all_button.setClassName_(' '.join(btn_classes))
        # hide cancel/add buttons
        container_div = document.getElementById_('os-and-app-updates')
        if container_div:
            container_div_classes = container_div.className().split(' ')
            if not 'updating' in container_div_classes:
                container_div_classes.append('updating')
                container_div.setClassName_(' '.join(container_div_classes))

    def updateOptionalInstallButtonClicked_(self, item_name):
        # this method is called from JavaScript when a user clicks
        # the cancel or add button in the updates list
        # TO-DO: better handling of all the "unexpected error"s
        document = self.webView.mainFrameDocument()
        item = MunkiItems.optionalItemForName_(item_name)
        if not item:
            NSLog('Unexpected error')
            return
        update_table_row = document.getElementById_('%s_update_table_row' % item_name)
        if not update_table_row:
            NSLog('Unexpected error')
            return
        # remove this row from its current table
        node = update_table_row.parentNode().removeChild_(update_table_row)

        # update item status
        item.update_status()

        # do we need to add a new node to the other list?
        if item.get('needs_update'):
            # make some new HTML for the updated item
            managed_update_names = munki.getInstallInfo().get('managed_updates', [])
            item_template = msulib.get_template('update_row_template.html')
            item_html = item_template.safe_substitute(item)

            if item['status'] in ['update-will-be-installed', 'installed']:
                # add the node to the updates-to-install table
                table = document.getElementById_('updates-to-install-table')
            if item['status'] == 'update-available':
                # add the node to the other-updates table
                table = document.getElementById_('other-updates-table')
            if not table:
                NSLog('Unexpected error')
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
                other_updates_div.setClassName_(' '.join(other_updates_div_classes))
        else:
            if not 'hidden' in other_updates_div_classes:
                other_updates_div_classes.append('hidden')
                other_updates_div.setClassName_(' '.join(other_updates_div_classes))

        # update the updates-to-install header to reflect the new list of updates to install
        updateCount = self.getUpdateCount()
        update_count_message = msulib.updateCountMessage(updateCount)
        update_count_element = document.getElementById_('update-count-string')
        if update_count_element:
            update_count_element.setInnerText_(update_count_message)

        warning_text = self.get_warning_text()
        warning_text_element = document.getElementById_('update-warning-text')
        if warning_text_element:
            warning_text_element.setInnerHTML_(warning_text)

        # update text of Install All button
        install_all_button_element = document.getElementById_('install-all-button-text')
        if install_all_button_element:
            install_all_button_element.setInnerText_(
                msulib.getInstallAllButtonTextForCount(updateCount))

        # update count badges
        self.displayUpdateCount()

    def myItemsActionButtonClicked_(self, item_name):
        # this method is called from JavaScript when the user clicks
        # the Install/Removel/Cancel button in the My Items view
        document = self.webView.mainFrameDocument()
        item = MunkiItems.optionalItemForName_(item_name)
        status_line = document.getElementById_('%s_status_text' % item_name)
        btn = document.getElementById_('%s_action_button_text' % item_name)
        if not item or not btn or not status_line:
            NSLog('Unexpected error')
            return
        item.update_status()
        self.displayUpdateCount()
        if item['status'] == 'not-installed':
            # we removed item from list of things to install
            # now remove from display
            table_row = document.getElementById_('%s_myitems_table_row' % item_name)
            if table_row:
                node = table_row.parentNode().removeChild_(table_row)
        else:
            btn.setInnerText_(item['myitem_action_text'])
            status_line.setInnerText_(item['status_text'])
            status_line.setClassName_('status %s' % item['status'])
            if not self._update_in_progress:
                if item['status'] in ['will-be-installed', 'update-will-be-installed',
                                      'will-be-removed']:
                    self.updateNow()

    def updateDOMforOptionalItem(self, item):
        document = self.webView.mainFrameDocument()
        status_line = document.getElementById_('%s_status_text' % item['name'])
        btn = document.getElementById_('%s_action_button_text' % item['name'])
        if not btn or not status_line:
            return
        btn_classes = btn.className().split(' ')
        # filter out status class
        btn_classes = [class_name for class_name in btn_classes
                       if class_name in ['msu-button-inner', 'large', 'small', 'install-updates']]
        btn_classes.append(item['status'])
        btn.setClassName_(' '.join(btn_classes))
        if 'install-updates' in btn_classes:
            btn.setInnerText_(item['myitem_action_text'])
        elif 'large' in btn_classes:
            btn.setInnerText_(item['long_action_text'])
        else:
            btn.setInnerText_(item['short_action_text'])
        status_line.setInnerText_(item['status_text'])
        status_line.setClassName_(item['status'])

    def actionButtonClicked_(self, item_name):
        # this method is called from JavaScript when the user clicks
        # the Install/Removel/Cancel button in the list or detail view
        item = MunkiItems.optionalItemForName_(item_name)
        if not item:
            NSLog('Can\'t find item: %s' % item_name)
            return
        item.update_status()
        self.displayUpdateCount()
        self.updateDOMforOptionalItem(item)
        if not self._update_in_progress:
            if item['status'] in ['will-be-installed', 'update-will-be-installed', 'will-be-removed']:
                self.updateNow()
        else:
            if item['status'] in ['will-be-installed', 'update-will-be-installed', 'will-be-removed']:
                self._update_queue.add(item['name'])
            else:
                self._update_queue.discard(item['name'])

    def changeSelectedCategory_(self, category):
        # this method is called from JavaScript when the user
        # changes the category selected in the sidebar popup
        if category == 'All Categories':
            category = 'all'
        self.load_page('category-%s.html' % quote_plus(category))

    def setStatusViewTitle_(self, title_text):
        document = self.webView.mainFrameDocument()
        # we re-purpose the update count message for this
        update_count_element = document.getElementById_('update-count-string')
        if update_count_element:
            update_count_element.setInnerText_(title_text)

    @IBAction
    def navigationBtnClicked_(self, sender):
        segment = sender.selectedSegment()
        if segment == 0:
            self.webView.goBack_(self)
        if segment == 1:
            self.webView.goForward_(self)

    @IBAction
    def loadAllSoftwarePage_(self, sender):
        self.load_page('category-all.html')

    @IBAction
    def loadCategoriesPage_(self, sender):
        self.load_page('categories.html')

    @IBAction
    def loadMyItemsPage_(self, sender):
        self.load_page('myitems.html')

    @IBAction
    def loadUpdatesPage_(self, sender):
        self.load_page('updates.html')

    @IBAction
    def tabControlClicked_(self, sender):
        selectedCell = sender.selectedCell()
        if selectedCell:
            tag = selectedCell.tag()
            if tag == 1:
                self.loadAllSoftwarePage_(sender)
            if tag == 2:
                self.loadCategoriesPage_(sender)
            if tag == 3:
                self.loadMyItemsPage_(sender)
            if tag == 4:
                self.loadUpdatesPage_(sender)

    @IBAction
    def searchFilterChanged_(self, sender):
        filterString = self.searchField.stringValue().lower()
        if filterString:
            self.load_page('filter-%s.html' % quote_plus(filterString))

    def currentPageIsUpdatesPage(self):
        '''return True if current tab selected is updates'''
        selectedCell = self.tabControl.selectedCell()
        return (selectedCell is not None and selectedCell.tag() == 4)
    
    def currentPageIsMyItemsPage(self):
        '''return True if current tab selected is updates'''
        selectedCell = self.tabControl.selectedCell()
        return (selectedCell is not None and selectedCell.tag() == 3)

    def currentPageIsCategoriesPage(self):
        '''return True if current tab selected is updates'''
        selectedCell = self.tabControl.selectedCell()
        return (selectedCell is not None and selectedCell.tag() == 2)