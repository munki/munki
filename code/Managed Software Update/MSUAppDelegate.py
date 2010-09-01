#
#  MSUAppDelegate.py
#  Managed Software Update
#
#  Created by Greg Neagle on 2/10/10.
#  Copyright 2009-2010 Greg Neagle.
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

def getconsoleuser():
    from SystemConfiguration import SCDynamicStoreCopyConsoleUser
    cfuser = SCDynamicStoreCopyConsoleUser( None, None, None )
    return cfuser[0]


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
        
        runmode = NSUserDefaults.standardUserDefaults().stringForKey_("mode") or \
                  os.environ.get("ManagedSoftwareUpdateMode")
        if runmode:
            self.runmode = runmode
            NSLog("Runmode: %s" % runmode)
                    
        consoleuser = getconsoleuser()
        if consoleuser == None or consoleuser == u"loginwindow":
            # Status Window only
            NSMenu.setMenuBarVisible_(NO)
            self.munkiStatusController.startMunkiStatusSession()
        elif self.runmode == "MunkiStatus":
            self.munkiStatusController.startMunkiStatusSession()
        else:
            # display updates if available; if no available updates
            # trigger an update check
            if not self._listofupdates:
                self.getAvailableUpdates()
            if self._listofupdates:
                self.buildUpdateTableData()
                self.mainWindowController.theWindow.makeKeyAndOrderFront_(self)
                NSApp.requestUserAttention_(NSCriticalRequest)
                if self._optionalInstalls:
                    self.buildOptionalInstallsData()
            else:
                # no updates available. Should we check for some?
                self.checkForUpdates()
    
    def munkiStatusSessionEnded_(self, socketSessionResult):
        consoleuser = getconsoleuser()
        if self.runmode == "MunkiStatus" or consoleuser == None or consoleuser == u"loginwindow":
            # Status Window only, so we should just quit
            NSApp.terminate_(self)
            
        alertMessageText = "Update check failed"
        if self.managedsoftwareupdate_task == "installwithnologout":
            alertMessageText = "Install session failed"
            
        if socketSessionResult == -1:
            # connection was dropped unexpectedly
            self.mainWindowController.theWindow.makeKeyAndOrderFront_(self)
            alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(alertMessageText, u"Quit", objc.nil, objc.nil, "There is a configuration problem with the managed software installer. The process ended unexpectedly. Contact your systems administrator.")
            alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(self.mainWindowController.theWindow, self, self.quitAlertDidEnd_returnCode_contextInfo_, objc.nil)
            return
  
        elif socketSessionResult == -2:
            # socket timed out before connection
            self.mainWindowController.theWindow.makeKeyAndOrderFront_(self)
            alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(alertMessageText, u"Quit", objc.nil, objc.nil, "There is a configuration problem with the managed software installer. Could not start the process. Contact your systems administrator.")
            alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(self.mainWindowController.theWindow, self, self.quitAlertDidEnd_returnCode_contextInfo_, objc.nil)
            return
            
        if self.managedsoftwareupdate_task == "installwithnologout":
            # we're done.
            NSApp.terminate_(self)
            
        elif self.managedsoftwareupdate_task == "manualcheck":
            self.managedsoftwareupdate_task = None
            self._listofupdates = []
            self.getAvailableUpdates()
            self.buildUpdateTableData()
            if self._optionalInstalls:
                self.buildOptionalInstallsData()
            self.mainWindowController.theWindow.makeKeyAndOrderFront_(self)
            if self._listofupdates:
                return
            # no list of updates; let's check the LastCheckResult for more info
            prefs = munki.getManagedInstallsPrefs()
            lastCheckResult = prefs.get("LastCheckResult")
            if lastCheckResult == 0:
                self.noUpdatesAlert()
            elif lastCheckResult == 1:
                NSApp.requestUserAttention_(NSCriticalRequest)
            elif lastCheckResult == -1:
                alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(u"Cannot check for updates", u"Quit", objc.nil, objc.nil, "Managed Software Update cannot contact the update server at this time.\nIf this situtation continues, contact your systems administrator.")
                alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(self.mainWindowController.theWindow, self, self.quitAlertDidEnd_returnCode_contextInfo_, objc.nil)
            elif lastCheckResult == -2:
                alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(u"Cannot check for updates", u"Quit", objc.nil, objc.nil, "Managed Software Update failed its preflight check.\nTry again later.")
                alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(self.mainWindowController.theWindow, self, self.quitAlertDidEnd_returnCode_contextInfo_, objc.nil)

    def noUpdatesAlert(self):               
        if self._optionalInstalls:
            alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(u"Your software is up to date.", u"Quit", u"Optional software...", objc.nil, "There is no new software for your computer at this time.")
            alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(self.mainWindowController.theWindow, self, self.quitAlertDidEnd_returnCode_contextInfo_, objc.nil) 
        else:
            alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(u"Your software is up to date.", u"Quit", objc.nil, objc.nil, "There is no new software for your computer at this time.")
            alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(self.mainWindowController.theWindow, self, self.quitAlertDidEnd_returnCode_contextInfo_, objc.nil) 
     
    
    def checkForUpdates(self):
        # kick off an update check
        self.mainWindowController.theWindow.orderOut_(self)
        result = munki.startUpdateCheck()
        if result == 0:
            self.managedsoftwareupdate_task = "manualcheck"
            self.munkiStatusController.window.makeKeyAndOrderFront_(self)
            self.munkiStatusController.startMunkiStatusSession()
        else:
            self.mainWindowController.theWindow.makeKeyAndOrderFront_(self)
            alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(u"Update check failed", u"Quit", objc.nil, objc.nil, "There is a configuration problem with the managed software installer. Could not start the update check process. Contact your systems administrator.")
            alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(self.mainWindowController.theWindow, self, self.quitAlertDidEnd_returnCode_contextInfo_, objc.nil)
    
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
                        if display_name in item:
                            item["display_name"] = item["display_name"] + " (will be removed)"
                        elif name in item:
                            item["display_name"] = item["name"] + " (will be removed)"
                        updatelist.append(item)
                if not showRemovalDetail:
                    row = {}
                    row["display_name"] = "Software removals"
                    row["version"] = ""
                    row["description"] = "Scheduled removal of managed software."
                    if restartNeeded:
                        row["RestartAction"] = "RequireRestart"
                    updatelist.append(row)
        
        if updatelist:
            self._listofupdates = updatelist
            self.update_view_controller.updateNowBtn.setEnabled_(YES)
            self.getOptionalInstalls()
        else:
            appleupdates = munki.getAppleUpdates()
            if appleupdates:
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
            will_be_state = objc.NO
            if item.get("installed") or item.get("will_be_installed"):
                will_be_state = objc.YES
            if item.get("will_be_removed"):
                will_be_state = objc.NO
            row['managed'] = (item['name'] in selfserve_installs)
            row['original_managed'] = (item['name'] in selfserve_installs)
            row['itemname'] = item['name']
            row['name'] = item.get("display_name") or item['name']
            row['version'] = munki.trimVersionString(item.get("version_to_install"),3)
            row['description'] = item.get("description","")
            row['size'] = munki.humanReadable(item.get("installer_item_size",0))
            if row['installed']:
                if item.get("needs_update"):
                    status = "Update available"
                else:
                    row['size'] = "-"
                    status = "Installed"
                if item.get("will_be_removed"):
                    status = "Will be removed"
                elif not item.get('uninstallable'):
                    status = "Not removable"
                    row['enabled'] = objc.NO
            else:
                status = "Not installed"
                if item.get("will_be_installed"):
                    status = "Will be installed"
                elif item.get("note"):
                    # some reason we can't install
                    status = item.get("note")
                    row['enabled'] = objc.NO
            row['status'] = status
            row['original_status'] = status
            row_dict = NSMutableDictionary.dictionaryWithDictionary_(row)
            table.append(row_dict)
            
        if table:
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
            row['version'] = munki.trimVersionString(item.get("version_to_install"),3)
            if item.get("installer_item_size"):
                row['size'] = munki.humanReadable(item.get("installer_item_size"))
            else:
                row['size'] = ""
            row['description'] = item.get("description","")
            row_dict = NSDictionary.dictionaryWithDictionary_(row)
            table.append(row_dict)
            
        self.update_view_controller.setUpdatelist_(table)
        self.update_view_controller.tableView.deselectAll_(self)
        if self.restart_required:
            self.update_view_controller.restartInfoFld.setStringValue_(u"Restart will be required.")
            self.update_view_controller.restartImageFld.setImage_(self._restartImage)
        elif self.logout_required:
            self.update_view_controller.restartInfoFld.setStringValue_(u"Logout will be required.")
            self.update_view_controller.restartImageFld.setImage_(self._logoutImage)
        

    def confirmInstallUpdates(self):
        if self.mainWindowController.theWindow.isVisible() == objc.NO:
            return
        if len(munki.currentGUIusers()) > 1:
            alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(u"Other users logged in", u"Cancel", objc.nil, objc.nil, "There are other users logged into this computer.\nUpdating now could cause other users to lose their work.\n\nPlease try again later after the other users have logged out.")
            alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(self.mainWindowController.theWindow, self, self.multipleUserAlertDidEnd_returnCode_contextInfo_, objc.nil) 
        elif self.restart_required:
            alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(u"Restart Required", u"Log out and update", u"Cancel", objc.nil, "A restart is required after updating. Log out and update now?")
            alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(self.mainWindowController.theWindow, self, self.logoutAlertDidEnd_returnCode_contextInfo_, objc.nil) 
        elif self.logout_required or munki.installRequiresLogout():
            alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(u"Logout Required", u"Log out and update", u"Cancel", objc.nil, "A logout is required before updating. Log out and update now?")
            alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(self.mainWindowController.theWindow, self, self.logoutAlertDidEnd_returnCode_contextInfo_, objc.nil)
        else:
            alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(u"Logout Recommended", u"Log out and update", u"Cancel", u"Update without logging out", "A logout is recommended before updating. Log out and update now?")
            alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(self.mainWindowController.theWindow, self, self.logoutAlertDidEnd_returnCode_contextInfo_, objc.nil) 

    
    def installSessionErrorAlert(self):
        alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(u"Cannot start installation session", u"Quit", objc.nil, objc.nil, "There is a configuration problem with the managed software installer. Could not start the install session. Contact your systems administrator.")
        alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(self.mainWindowController.theWindow, self, self.quitAlertDidEnd_returnCode_contextInfo_, objc.nil) 

                                
    @PyObjCTools.AppHelper.endSheetMethod
    def logoutAlertDidEnd_returnCode_contextInfo_(self, alert, returncode, contextinfo):
        if returncode == 0:
            NSLog("User cancelled")
        elif returncode == 1:
            NSLog("User chose to log out")
            result = munki.logoutAndUpdate()
            if result:
                self.installSessionErrorAlert()
        elif returncode == -1:
            NSLog("User chose to update without logging out")
            result = munki.justUpdate()
            if result:
                self.installSessionErrorAlert() 
            else:
                self.managedsoftwareupdate_task = "installwithnologout"
                self.mainWindowController.theWindow.orderOut_(self)
                self.munkiStatusController.window.makeKeyAndOrderFront_(self)
                self.munkiStatusController.startMunkiStatusSession()
                

    @PyObjCTools.AppHelper.endSheetMethod
    def multipleUserAlertDidEnd_returnCode_contextInfo_(self, alert, returncode, contextinfo):
        pass
                 
    @PyObjCTools.AppHelper.endSheetMethod
    def quitAlertDidEnd_returnCode_contextInfo_(self, alert, returncode, contextinfo):
        if returncode == 1:
            NSApp.terminate_(self)
        else:
            self.update_view_controller.optionalSoftwareBtn.setHidden_(NO)
            self.buildOptionalInstallsData()
            self.mainWindowController.theTabView.selectNextTabViewItem_(self)
            
        

