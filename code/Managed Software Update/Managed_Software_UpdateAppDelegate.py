#
#  Managed_Software_UpdateAppDelegate.py
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
import munki
import PyObjCTools

class Managed_Software_UpdateAppDelegate(NSObject):

    window_controller = objc.IBOutlet()
    array_controller = objc.IBOutlet()

    _emptyImage = NSImage.imageNamed_("Empty.png")
    _restartImage = NSImage.imageNamed_("RestartReq.tif")
    _logoutImage = NSImage.imageNamed_("LogOutReq.tif")
    _listofupdates = []
    
    restart_required = False
    logout_required = False

    
    def applicationDidFinishLaunching_(self, sender):
        pass
                
    def applicationDidBecomeActive_(self, sender):
        # display updates if available; if no available updates
        # trigger an update check
        if not self._listofupdates:
            self.getAvailableUpdates()
        if self._listofupdates:
            self.buildTableData()
            self.window_controller.theWindow.makeKeyAndOrderFront_(self)
        else:
            # no updates available. Should we check for some?
            result = munki.checkForUpdates()
            if result == 0:
                self.window_controller.theWindow.makeKeyAndOrderFront_(self)
                alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(u"Your software is up to date.", u"Quit", objc.nil, objc.nil, "There is no new software for your computer at this time.")
                alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(self.window_controller.theWindow, self, self.quitAlertDidEnd_returnCode_contextInfo_, objc.nil) 
            elif result == -1:
                self.window_controller.theWindow.makeKeyAndOrderFront_(self)
                alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(u"Cannot check for updates", u"Quit", objc.nil, objc.nil, "Managed Software Update cannot contact the update server at this time.\nIf this situtation continues, contact your systems administrator.")
                alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(self.window_controller.theWindow, self, self.quitAlertDidEnd_returnCode_contextInfo_, objc.nil)
            elif result == -2:
                self.window_controller.theWindow.makeKeyAndOrderFront_(self)
                alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(u"Update check failed", u"Quit", objc.nil, objc.nil, "There is a configuration problem with the managed software installer. Could not start the update check process. Contact your systems administrator.")
                alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(self.window_controller.theWindow, self, self.quitAlertDidEnd_returnCode_contextInfo_, objc.nil)
                
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
        else:
            appleupdates = munki.getAppleUpdates()
            if appleupdates:
                self._listofupdates = appleupdates.get("AppleUpdates", [])
        
                
    def buildTableData(self):
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
            row['description'] = item.get("description","")
            row_dict = NSDictionary.dictionaryWithDictionary_(row)
            table.append(row_dict)
            
        self.window_controller.setUpdatelist_(table)
        self.window_controller.tableView.deselectAll_(self)
        if self.restart_required:
            self.window_controller.restartInfoFld.setStringValue_(u"Restart will be required.")
            self.window_controller.restartImageFld.setImage_(self._restartImage)
        elif self.logout_required:
            self.window_controller.restartInfoFld.setStringValue_(u"Logout will be required.")
            self.window_controller.restartImageFld.setImage_(self._logoutImage)
        

            
    def tableViewSelectionDidChange_(self, sender):
        if self.array_controller.selectedObjects():
            row = self.array_controller.selectedObjects()[0]
            self.window_controller.descriptionView.mainFrame().loadHTMLString_baseURL_(row.get("description",""), None)
        else:
            self.window_controller.descriptionView.mainFrame().loadHTMLString_baseURL_(u"", None)
            
            
    def confirmInstallUpdates(self):
        if len(munki.currentGUIusers()) > 1:
            alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(u"Other users logged in", u"Cancel", objc.nil, objc.nil, "There are other users logged into this computer.\nUpdating now could cause other users to lose their work.\n\nPlease try again later after the other users have logged out.")
            alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(self.window_controller.theWindow, self, self.multipleUserAlertDidEnd_returnCode_contextInfo_, objc.nil) 
        elif self.restart_required:
            alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(u"Restart Required", u"Log out and update", u"Cancel", objc.nil, "A restart is required after updating. Log out and update now?")
            alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(self.window_controller.theWindow, self, self.logoutAlertDidEnd_returnCode_contextInfo_, objc.nil) 
        elif self.logout_required or munki.installRequiresLogout():
            alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(u"Logout Required", u"Log out and update", u"Cancel", objc.nil, "A logout is required before updating. Log out and update now?")
            alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(self.window_controller.theWindow, self, self.logoutAlertDidEnd_returnCode_contextInfo_, objc.nil)
        else:
            alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(u"Logout Recommended", u"Log out and update", u"Cancel", u"Update without logging out", "A logout is recommended before updating. Log out and update now?")
            alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(self.window_controller.theWindow, self, self.logoutAlertDidEnd_returnCode_contextInfo_, objc.nil) 

    
    def installSessionErrorAlert(self):
        alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(u"Cannot start installation session", u"Quit", objc.nil, objc.nil, "There is a configuration problem with the managed software installer. Could not start the install session. Contact your systems administrator.")
        alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(self.window_controller.theWindow, self, self.quitAlertDidEnd_returnCode_contextInfo_, objc.nil) 

                                
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
                NSApp.terminate_(self)

    @PyObjCTools.AppHelper.endSheetMethod
    def multipleUserAlertDidEnd_returnCode_contextInfo_(self, alert, returncode, contextinfo):
        pass
                 
    @PyObjCTools.AppHelper.endSheetMethod
    def quitAlertDidEnd_returnCode_contextInfo_(self, alert, returncode, contextinfo):
        NSApp.terminate_(self)

