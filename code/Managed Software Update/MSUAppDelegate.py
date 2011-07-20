#
#  MSUAppDelegate.py
#  Managed Software Update
#
#  Created by Greg Neagle on 2/10/10.
#  Copyright 2009-2011 Greg Neagle.
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

from Foundation import *
from AppKit import *
from objc import YES, NO
import os
import munki
import PyObjCTools

munki.setupLogging()

class MSUAppDelegate(NSObject):

    munkiStatusController = objc.IBOutlet()
    mainWindowController = objc.IBOutlet()

    update_view_controller = objc.IBOutlet()
    update_array_controller = objc.IBOutlet()

    optional_view_controller = objc.IBOutlet()
    optional_array_controller = objc.IBOutlet()

    _emptyImage = NSImage.imageNamed_("Empty.png")
    _restartImage = NSImage.imageNamed_("RestartReq.tif")
    _logoutImage = NSImage.imageNamed_("LogOutReq.tif")
    _listofupdates = []
    _optionalInstalls = []

    restart_required = False
    logout_required = False
    runmode = "Normal"
    managedsoftwareupdate_task = None

    def applicationDidFinishLaunching_(self, sender):
        NSLog(u"Managed Software Update finished launching.")
        munki.log("MSU", "launched")

        runmode = NSUserDefaults.standardUserDefaults().stringForKey_("mode") or \
                  os.environ.get("ManagedSoftwareUpdateMode")
        if runmode:
            self.runmode = runmode
            NSLog("Runmode: %s" % runmode)

        # Prevent automatic relaunching at login on Lion 
        if NSApp.respondsToSelector_('disableRelaunchOnLogin'):
            NSApp.disableRelaunchOnLogin()

        consoleuser = munki.getconsoleuser()
        if consoleuser == None or consoleuser == u"loginwindow":
            # Status Window only
            NSMenu.setMenuBarVisible_(NO)
            self.munkiStatusController.startMunkiStatusSession()
        elif self.runmode == "MunkiStatus":
            self.munkiStatusController.startMunkiStatusSession()
        else:
            # user may have launched the app manually, or it may have
            # been launched by /usr/local/munki/managedsoftwareupdate
            # to display available updates
            lastcheck = NSDate.dateWithString_(munki.pref('LastCheckDate'))
            if not lastcheck or lastcheck.timeIntervalSinceNow() < -60:
                # it's been more than a minute since the last check
                self.checkForUpdates()
                return
            # do we have existing updates to display?
            if not self._listofupdates:
                self.getAvailableUpdates()
            if self._listofupdates:
                self.displayUpdatesWindow()
            else:
                # no updates available. Should we check for some?
                self.checkForUpdates()

    def displayUpdatesWindow(self):
        self.buildUpdateTableData()
        if self._optionalInstalls:
            self.buildOptionalInstallsData()
        self.mainWindowController.theWindow.makeKeyAndOrderFront_(self)
        NSApp.requestUserAttention_(NSCriticalRequest)

    def munkiStatusSessionEnded_(self, socketSessionResult):
        consoleuser = munki.getconsoleuser()
        if (self.runmode == "MunkiStatus" or consoleuser == None
            or consoleuser == u"loginwindow"):
            # Status Window only, so we should just quit
            munki.log("MSU", "exit_munkistatus")
            NSApp.terminate_(self)

        # The managedsoftwareupdate run will have changed state preferences
        # in ManagedInstalls.plist. Load the new values.
        munki.reload_prefs()

        alertMessageText = NSLocalizedString(u"Update check failed", None)
        if self.managedsoftwareupdate_task == "installwithnologout":
            alertMessageText = NSLocalizedString(u"Install session failed", None)

        if socketSessionResult == -1:
            # connection was dropped unexpectedly
            self.mainWindowController.theWindow.makeKeyAndOrderFront_(self)
            alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(
                alertMessageText,
                NSLocalizedString(u"Quit", None),
                objc.nil,
                objc.nil,
                NSLocalizedString(u"There is a configuration problem with the managed software installer. The process ended unexpectedly. Contact your systems administrator.", None))
            alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(
                self.mainWindowController.theWindow, self, self.quitAlertDidEnd_returnCode_contextInfo_, objc.nil)
            return

        elif socketSessionResult == -2:
            # socket timed out before connection
            self.mainWindowController.theWindow.makeKeyAndOrderFront_(self)
            alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(
                alertMessageText,
                NSLocalizedString(u"Quit", None),
                objc.nil,
                objc.nil,
                NSLocalizedString(u"There is a configuration problem with the managed software installer. Could not start the process. Contact your systems administrator.", None))
            alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(
                self.mainWindowController.theWindow, self, self.quitAlertDidEnd_returnCode_contextInfo_, objc.nil)
            return

        if self.managedsoftwareupdate_task == "installwithnologout":
            # we're done.
            munki.log("MSU", "exit_installwithnologout")
            NSApp.terminate_(self)

        elif self.managedsoftwareupdate_task == "manualcheck":
            self.managedsoftwareupdate_task = None
            self._listofupdates = []
            self.getAvailableUpdates()
            #NSLog(u"Building table of available updates.")
            self.buildUpdateTableData()
            if self._optionalInstalls:
                #NSLog(u"Building table of optional software.")
                self.buildOptionalInstallsData()
            #NSLog(u"Showing main window.")
            self.mainWindowController.theWindow.makeKeyAndOrderFront_(self)
            #NSLog(u"Main window was made key and ordered front")
            if self._listofupdates:
                return
            # no list of updates; let's check the LastCheckResult for more info
            lastCheckResult = munki.pref("LastCheckResult")
            if lastCheckResult == 0:
                munki.log("MSU", "no_updates")
                self.noUpdatesAlert()
            elif lastCheckResult == 1:
                NSApp.requestUserAttention_(NSCriticalRequest)
            elif lastCheckResult == -1:
                munki.log("MSU", "cant_update", "cannot contact server")
                alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(
                    NSLocalizedString(u"Cannot check for updates", None),
                    NSLocalizedString(u"Quit", None),
                    objc.nil,
                    objc.nil,
                    NSLocalizedString(u"Managed Software Update cannot contact the update server at this time.\nIf this situation continues, contact your systems administrator.", None))
                alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(
                    self.mainWindowController.theWindow, self, self.quitAlertDidEnd_returnCode_contextInfo_, objc.nil)
            elif lastCheckResult == -2:
                munki.log("MSU", "cant_update", "failed preflight")
                alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(
                    NSLocalizedString(u"Cannot check for updates", None),
                    NSLocalizedString(u"Quit",  None),
                    objc.nil,
                    objc.nil,
                    NSLocalizedString(u"Managed Software Update failed its preflight check.\nTry again later.", None))
                alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(
                    self.mainWindowController.theWindow, self, self.quitAlertDidEnd_returnCode_contextInfo_, objc.nil)

    def noUpdatesAlert(self):
        if self._optionalInstalls:
            alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(
                NSLocalizedString(u"Your software is up to date.", None),
                NSLocalizedString(u"Quit", None),
                NSLocalizedString(u"Optional software...", None),
                objc.nil,
                NSLocalizedString(u"There is no new software for your computer at this time.", None))
            alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(
                self.mainWindowController.theWindow, self, self.quitAlertDidEnd_returnCode_contextInfo_, objc.nil)
        else:
            alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(
                NSLocalizedString(u"Your software is up to date.", None),
                NSLocalizedString(u"Quit", None),
                objc.nil,
                objc.nil,
                NSLocalizedString(u"There is no new software for your computer at this time.", None))
            alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(
                self.mainWindowController.theWindow, self, self.quitAlertDidEnd_returnCode_contextInfo_, objc.nil)


    def checkForUpdates(self):
        # kick off an update check

        # close main window
        self.mainWindowController.theWindow.orderOut_(self)
        # clear data structures
        self._listofupdates = []
        self._optionalInstalls = []
        self.update_view_controller.tableView.deselectAll_(self)
        self.update_view_controller.setUpdatelist_([])
        self.optional_view_controller.tableView.deselectAll_(self)
        self.optional_view_controller.setOptionallist_([])

        # attempt to start the update check
        result = munki.startUpdateCheck()
        if result == 0:
            self.managedsoftwareupdate_task = "manualcheck"
            self.munkiStatusController.window.makeKeyAndOrderFront_(self)
            self.munkiStatusController.startMunkiStatusSession()
        else:
            self.mainWindowController.theWindow.makeKeyAndOrderFront_(self)
            alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(
                NSLocalizedString(u"Update check failed", None),
                NSLocalizedString(u"Quit", None),
                objc.nil,
                objc.nil,
                NSLocalizedString(u"There is a configuration problem with the managed software installer. Could not start the update check process. Contact your systems administrator.", None))
            alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(
                self.mainWindowController.theWindow, self, self.quitAlertDidEnd_returnCode_contextInfo_, objc.nil)

    def applicationDidBecomeActive_(self, sender):
        pass


    def getOptionalInstalls(self):
        optionalInstalls = []
        installinfo = munki.getInstallInfo()
        if installinfo:
            optionalInstalls = installinfo.get("optional_installs", [])
        if optionalInstalls:
            self._optionalInstalls = optionalInstalls
            self.update_view_controller.optionalSoftwareBtn.setHidden_(NO)
        else:
            self.update_view_controller.optionalSoftwareBtn.setHidden_(YES)


    def enableUpdateNowBtn_(self, enable):
        self.update_view_controller.updateNowBtn.setEnabled_(enable)


    def getAvailableUpdates(self):
        updatelist = []
        installinfo = munki.getInstallInfo()
        if installinfo:
            updatelist = installinfo.get("managed_installs", [])
            if installinfo.get("removals"):
                removallist = installinfo.get("removals")
                restartNeeded = False
                showRemovalDetail = munki.getRemovalDetailPrefs()
                for item in removallist:
                    if item.get("RestartAction") == "RequireRestart" or item.get("RestartAction") == "RecommendRestart":
                        restartNeeded = True
                    if showRemovalDetail:
                        item["display_name"] = ((item.get("display_name") or item.get("name", ""))
                                                + NSLocalizedString(u" (will be removed)", None))
                        item["description"] = NSLocalizedString(u"This item will be removed.", None)
                        updatelist.append(item)
                if not showRemovalDetail:
                    row = {}
                    row["display_name"] = NSLocalizedString(u"Software removals", None)
                    row["version"] = ""
                    row["description"] = NSLocalizedString(u"Scheduled removal of managed software.", None)
                    if restartNeeded:
                        row["RestartAction"] = "RequireRestart"
                    updatelist.append(row)

        if updatelist:
            self._listofupdates = updatelist
            self.enableUpdateNowBtn_(YES)
            #self.performSelector_withObject_afterDelay_("enableUpdateNowBtn:", YES, 4)
            self.getOptionalInstalls()
        else:
            appleupdates = munki.getAppleUpdates()
            if appleupdates:
                munki.log("MSU", "appleupdates")
                self._listofupdates = appleupdates.get("AppleUpdates", [])
                self.update_view_controller.updateNowBtn.setEnabled_(YES)
                self.update_view_controller.optionalSoftwareBtn.setHidden_(YES)
            else:
                self.update_view_controller.updateNowBtn.setEnabled_(NO)
                self.getOptionalInstalls()


    def buildOptionalInstallsData(self):
        table = []
        selfservedata = munki.readSelfServiceManifest()
        selfserve_installs = selfservedata.get('managed_installs',[])
        selfserve_uninstalls = selfservedata.get('managed_uninstalls',[])

        for item in self._optionalInstalls:
            row = {}
            row['enabled'] = objc.YES
            # current install state
            row['installed'] = item.get("installed", objc.NO)
            # user desired state
            row['managed'] = (item['name'] in selfserve_installs)
            row['original_managed'] = (item['name'] in selfserve_installs)
            row['itemname'] = item['name']
            row['name'] = item.get("display_name") or item['name']
            row['version'] = munki.trimVersionString(item.get("version_to_install"))
            row['description'] = item.get("description", "")
            if item.get("installer_item_size"):
                row['size'] = munki.humanReadable(item.get("installer_item_size"))
            elif item.get("installed_size"):
                row['size'] = munki.humanReadable(item.get("installed_size"))
            else:
                row['size'] = ""

            if row['installed']:
                if item.get("needs_update"):
                    status = NSLocalizedString(u"Update available", None)
                else:
                    row['size'] = "-"
                    status = NSLocalizedString(u"Installed", None)
                if item.get("will_be_removed"):
                    status = NSLocalizedString(u"Will be removed", None)
                elif not item.get('uninstallable'):
                    status = NSLocalizedString(u"Not removable", None)
                    row['enabled'] = objc.NO
            else:
                status = "Not installed"
                if item.get("will_be_installed"):
                    status = NSLocalizedString(u"Will be installed", None)
                elif item.get("note"):
                    # some reason we can't install
                    status = item.get("note")
                    row['enabled'] = objc.NO
            row['status'] = status
            row['original_status'] = status
            row_dict = NSMutableDictionary.dictionaryWithDictionary_(row)
            table.append(row_dict)

        self.optional_view_controller.setOptionallist_(table)
        self.optional_view_controller.tableView.deselectAll_(self)


    def addOrRemoveOptionalSoftware(self):
        # record any requested changes in installed/removal state
        # then kick off an update check
        optional_install_choices = {}
        optional_install_choices['managed_installs'] = []
        optional_install_choices['managed_uninstalls'] = []
        for row in self.optional_array_controller.arrangedObjects():
            if row['managed']:
                # user selected for install
                optional_install_choices['managed_installs'].append(row['itemname'])
            elif row['original_managed']:
                # was managed, but user deselected it; we should remove it if possible
                optional_install_choices['managed_uninstalls'].append(row['itemname'])
        munki.writeSelfServiceManifest(optional_install_choices)
        self.checkForUpdates()


    def buildUpdateTableData(self):
        table = []
        self.restart_required = False
        self.logout_required = False
        for item in self._listofupdates:
            row = {}
            if item.get("RestartAction") == "RequireRestart" or item.get("RestartAction") == "RecommendRestart":
                row['image'] = self._restartImage
                self.restart_required = True
            elif item.get("RestartAction") == "RequireLogout" or item.get("RestartAction") == "RecommendLogout":
                row['image'] = self._logoutImage
                self.logout_required = True
            else:
                row['image'] = self._emptyImage
            row['name'] = item.get("display_name") or item.get("name","")
            row['version'] = munki.trimVersionString(item.get("version_to_install"))
            if item.get("installer_item_size"):
                row['size'] = munki.humanReadable(item.get("installer_item_size"))
            elif item.get("installed_size"):
                row['size'] = munki.humanReadable(item.get("installed_size"))
            else:
                row['size'] = ""
            row['description'] = item.get("description","")
            row_dict = NSDictionary.dictionaryWithDictionary_(row)
            table.append(row_dict)

        self.update_view_controller.setUpdatelist_(table)
        self.update_view_controller.tableView.deselectAll_(self)
        if self.restart_required:
            self.update_view_controller.restartInfoFld.setStringValue_(
                NSLocalizedString(u"Restart will be required.", None))
            self.update_view_controller.restartImageFld.setImage_(self._restartImage)
        elif self.logout_required:
            self.update_view_controller.restartInfoFld.setStringValue_(
                NSLocalizedString(u"Logout will be required.", None))
            self.update_view_controller.restartImageFld.setImage_(self._logoutImage)


    def confirmInstallUpdates(self):
        if self.mainWindowController.theWindow.isVisible() == objc.NO:
            return
        if len(munki.currentGUIusers()) > 1:
            alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(
                NSLocalizedString(u"Other users logged in", None),
                NSLocalizedString(u"Cancel", None),
                objc.nil,
                objc.nil,
                NSLocalizedString("There are other users logged into this computer.\nUpdating now could cause other users to lose their work.\n\nPlease try again later after the other users have logged out.", None))
            alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(
                self.mainWindowController.theWindow, self, self.multipleUserAlertDidEnd_returnCode_contextInfo_, objc.nil)
        elif self.restart_required:
            alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(
                NSLocalizedString(u"Restart Required", None),
                NSLocalizedString(u"Log out and update", None),
                NSLocalizedString(u"Cancel", None),
                objc.nil,
                NSLocalizedString(u"A restart is required after updating. Please be patient as there may be a short delay at the login window. Log out and update now?", None))
            alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(
                self.mainWindowController.theWindow, self, self.logoutAlertDidEnd_returnCode_contextInfo_, objc.nil)
        elif self.logout_required or munki.installRequiresLogout():
            alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(
                NSLocalizedString(u"Logout Required", None),
                NSLocalizedString(u"Log out and update", None),
                NSLocalizedString(u"Cancel", None),
                objc.nil,
                NSLocalizedString(u"A logout is required before updating. Please be patient as there may be a short delay at the login window. Log out and update now?", None))
            alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(
                self.mainWindowController.theWindow, self, self.logoutAlertDidEnd_returnCode_contextInfo_, objc.nil)
        else:
            alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(
                NSLocalizedString(u"Logout Recommended", None),
                NSLocalizedString(u"Log out and update", None),
                NSLocalizedString(u"Cancel", None),
                NSLocalizedString(u"Update without logging out", None),
                NSLocalizedString(u"A logout is recommended before updating. Please be patient as there may be a short delay at the login window. Log out and update now?", None))
            alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(
                self.mainWindowController.theWindow, self, self.logoutAlertDidEnd_returnCode_contextInfo_, objc.nil)


    def alertIfBlockingAppsRunning(self):
        apps_to_check = []
        for update_item in self._listofupdates:
            if 'blocking_applications' in update_item:
                apps_to_check.extend(update_item['blocking_applications'])
            else:
                apps_to_check.extend([os.path.basename(item.get('path'))
                                     for item in update_item.get('installs', [])
                                     if item['type'] == 'application'])

        running_apps = munki.getRunningBlockingApps(apps_to_check)
        if running_apps:
            alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(
                    NSLocalizedString(u"Conflicting applications running", None),
                    NSLocalizedString(u"OK", None),
                    objc.nil,
                    objc.nil,
                    NSLocalizedString(u"You must quit the following applications before proceeding with installation:\n\n%s", None) % '\n'.join(running_apps))
            munki.log("MSU", "conflicting_apps", ','.join(running_apps))
            alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(
                self.mainWindowController.theWindow, self, self.blockingAppsRunningAlertDidEnd_returnCode_contextInfo_, objc.nil)
            return True
        else:
            return False

    def installSessionErrorAlert(self):
        alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(
                NSLocalizedString(u"Cannot start installation session", None),
                NSLocalizedString(u"Quit", None),
                objc.nil,
                objc.nil,
                NSLocalizedString(u"There is a configuration problem with the managed software installer. Could not start the install session. Contact your systems administrator.", None))
        munki.log("MSU", "cannot_start")
        alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(
            self.mainWindowController.theWindow, self, self.quitAlertDidEnd_returnCode_contextInfo_, objc.nil)


    @PyObjCTools.AppHelper.endSheetMethod
    def logoutAlertDidEnd_returnCode_contextInfo_(self, alert, returncode, contextinfo):
        if returncode == 0:
            NSLog("User cancelled")
            munki.log("user", "cancelled")
        elif returncode == 1:
            NSLog("User chose to log out")
            munki.log("user", "install_with_logout")
            result = munki.logoutAndUpdate()
            if result:
                self.installSessionErrorAlert()
        elif returncode == -1:
            # dismiss the alert sheet now because we might display
            # another alert
            alert.window().orderOut_(self)
            if self.alertIfBlockingAppsRunning():
                pass
            else:
                NSLog("User chose to update without logging out")
                munki.log("user", "install_without_logout")
                result = munki.justUpdate()
                if result:
                    self.installSessionErrorAlert()
                else:
                    self.managedsoftwareupdate_task = "installwithnologout"
                    self.mainWindowController.theWindow.orderOut_(self)
                    self.munkiStatusController.window.makeKeyAndOrderFront_(self)
                    self.munkiStatusController.startMunkiStatusSession()

    @PyObjCTools.AppHelper.endSheetMethod
    def blockingAppsRunningAlertDidEnd_returnCode_contextInfo_(self, alert, returncode, contextinfo):
        pass

    @PyObjCTools.AppHelper.endSheetMethod
    def multipleUserAlertDidEnd_returnCode_contextInfo_(self, alert, returncode, contextinfo):
        pass

    @PyObjCTools.AppHelper.endSheetMethod
    def quitAlertDidEnd_returnCode_contextInfo_(self, alert, returncode, contextinfo):
        if returncode == 1:
            munki.log("user", "quit")
            NSApp.terminate_(self)
        else:
            munki.log("user", "view_optional_software")
            self.update_view_controller.optionalSoftwareBtn.setHidden_(NO)
            self.buildOptionalInstallsData()
            self.mainWindowController.theTabView.selectNextTabViewItem_(self)



