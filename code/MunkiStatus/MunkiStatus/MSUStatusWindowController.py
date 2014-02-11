# encoding: utf-8
#
#  MSUStatusWindowController.py
#
#
#  Created by Greg Neagle on 9/21/09.
#
# Copyright 2009-2014 Greg Neagle.
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


from objc import YES, NO, IBAction, IBOutlet, nil
from PyObjCTools import AppHelper

import os
import munki
import FoundationPlist
from Foundation import *
from AppKit import *
from SystemConfiguration import SCDynamicStoreCopyConsoleUser

debug = False

def getLoginwindowPicture():
    desktopPicturePath = ''
    loginwindowPrefsPath = "/Library/Preferences/com.apple.loginwindow.plist"
    if os.path.exists(loginwindowPrefsPath):
        loginwindowPrefs = FoundationPlist.readPlist(loginwindowPrefsPath)
        if loginwindowPrefs:
            desktopPicturePath = loginwindowPrefs.get('DesktopPicture', '')
            if desktopPicturePath:
                if os.path.exists(desktopPicturePath):
                    theImage = \
                        NSImage.alloc().initWithContentsOfFile_(
                            desktopPicturePath)
                    if theImage:
                        return theImage
                return NSImage.imageNamed_("Solid Aqua Blue")
    theImage = NSImage.alloc().initWithContentsOfFile_(
                        "/System/Library/CoreServices/DefaultDesktop.jpg")
    if theImage:
        return theImage
    else:
        return NSImage.imageNamed_("Solid Aqua Blue")
        

class MSUStatusWindowController(NSObject):
    '''
    Controls the status window. This was formerly part of a
    seperate application known as MunkiStatus.app
    '''

    window = IBOutlet()
    messageFld = IBOutlet()
    detailFld = IBOutlet()
    progressIndicator = IBOutlet()
    stopBtn = IBOutlet()
    imageFld = IBOutlet()

    backdropWindow = IBOutlet()
    backdropImageFld = IBOutlet()

    stopBtnState = 0
    restartAlertDismissed = 0

    @IBAction
    def stopBtnClicked_(self, sender):
        if debug:
            NSLog(u"Stop button was clicked.")
        sender.setState_(1)
        self.stopBtnState = 1
        sender.setEnabled_(False)
        # send a notification that stop button was clicked
        notification_center = NSDistributedNotificationCenter.defaultCenter()
        notification_center.postNotificationName_object_userInfo_options_(
            'com.googlecode.munki.MunkiStatus.stopButtonClicked',
            None,
            None,
            NSNotificationDeliverImmediately + NSNotificationPostToAllSessions)
    
    def registerForNotifications(self):
        '''Register for notification messages'''
        notification_center = NSDistributedNotificationCenter.defaultCenter()
        notification_center.addObserver_selector_name_object_suspensionBehavior_(
            self,
            self.updateStatus_,
            'com.googlecode.munki.managedsoftwareupdate.statusUpdate',
            None,
            NSNotificationSuspensionBehaviorDeliverImmediately)
    
    def unregisterForNotifications(self):
        '''Tell the DistributedNotificationCenter to stop sending us notifications'''
        NSDistributedNotificationCenter.defaultCenter().removeObserver_(self)

    def initStatusSession(self):
        consoleuser = munki.getconsoleuser()
        if consoleuser == None or consoleuser == u"loginwindow":
            self.displayBackdropWindow()

        if self.window:
            if consoleuser == None or consoleuser == u"loginwindow":
                # needed so the window can show over the loginwindow
                self.window.setCanBecomeVisibleWithoutLogin_(True)
                self.window.setLevel_(NSScreenSaverWindowLevel - 1)
            self.window.center()
            self.messageFld.setStringValue_(
                NSLocalizedString(u"Starting…", None))
            self.detailFld.setStringValue_(u"")
            self.stopBtn.setHidden_(False)
            self.stopBtn.setEnabled_(True)
            self.stopBtnState = 0
            if self.imageFld:
                theImage = NSImage.imageNamed_("MunkiStatus")
                self.imageFld.setImage_(theImage)
            if self.progressIndicator:
                self.progressIndicator.setMinValue_(0.0)
                self.progressIndicator.setMaxValue_(100.0)
                self.progressIndicator.setIndeterminate_(True)
                self.progressIndicator.setUsesThreadedAnimation_(True)
                self.progressIndicator.startAnimation_(self)
            self.window.orderFrontRegardless()
            self.registerForNotifications()
            
    def cleanUpStatusSession(self):
        self.unregisterForNotifications()
        if self.backdropWindow and self.backdropWindow.isVisible():
            self.backdropWindow.orderOut_(self)
        self.window.orderOut_(self)
                
    def displayBackdropWindow(self):
        if self.backdropWindow:
            self.backdropWindow.setCanBecomeVisibleWithoutLogin_(True)
            self.backdropWindow.setLevel_(NSStatusWindowLevel)
            screenRect = NSScreen.mainScreen().frame()
            self.backdropWindow.setFrame_display_(screenRect, True)
            
            darwin_vers = int(os.uname()[2].split('.')[0])
            if darwin_vers < 11:
                if self.backdropImageFld:
                    bgImage = getLoginwindowPicture()
                    self.backdropImageFld.setImage_(bgImage)
                    self.backdropWindow.orderFrontRegardless()
            else:
                self.backdropImageFld.setHidden_(True)
                translucentColor = \
                    NSColor.blackColor().colorWithAlphaComponent_(0.35)
                self.backdropWindow.setBackgroundColor_(translucentColor)
                self.backdropWindow.setOpaque_(False)
                self.backdropWindow.setIgnoresMouseEvents_(False)
                self.backdropWindow.setAlphaValue_(0.0)
                self.backdropWindow.orderFrontRegardless()
                self.backdropWindow.animator().setAlphaValue_(1.0)

    def updateStatus_(self, notification):
        info = notification.userInfo()
        if 'message' in info:
            self.setMessage_(info['message'])
        if 'detail' in info:
            self.setDetail_(info['detail'])
        if 'percent' in info:
            self.setPercentageDone_(info['percent'])
        command = info.get('command')
        if command == 'activate':
            self.window.orderFrontRegardless()
        elif command == 'hideStopButton':
            self.hideStopButton()
        elif command == 'showStopButton':
            self.showStopButton()
        elif command == 'disableStopButton':
            self.disableStopButton()
        elif command == 'enableStopButton':
            self.enableStopButton()
        elif command == 'showRestartAlert':
            self.doRestartAlert()
        elif command == 'quit':
            self.cleanUpStatusSession()
            NSApp.terminate_(self)

    def setPercentageDone_(self, percent):
        if float(percent) < 0:
            if not self.progressIndicator.isIndeterminate():
                self.progressIndicator.setIndeterminate_(True)
                self.progressIndicator.startAnimation_(self)
        else:
            if self.progressIndicator.isIndeterminate():
                self.progressIndicator.stopAnimation_(self)
                self.progressIndicator.setIndeterminate_(False)
            self.progressIndicator.setDoubleValue_(float(percent))

    @AppHelper.endSheetMethod
    def restartAlertDidEnd_returnCode_contextInfo_(
                                        self, alert, returncode, contextinfo):
        self.restartAlertDismissed = 1
        munki.restartNow()

    def doRestartAlert(self):
        self.restartAlertDismissed = 0
        alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(
            NSLocalizedString(u"Restart Required", None),
            NSLocalizedString(u"Restart", None),
            nil,
            nil,
            NSLocalizedString(
                u"Software installed or removed requires a restart. "
                "You will have a chance to save open documents.", None))
        alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(
            self.window, self, self.restartAlertDidEnd_returnCode_contextInfo_, nil)

    def setMessage_(self, messageText):
        self.messageFld.setStringValue_(messageText)

    def setDetail_(self, detailText):
        self.detailFld.setStringValue_(detailText)

    def getStopBtnState(self):
        return self.stopBtnState

    def hideStopButton(self):
        self.stopBtn.setHidden_(True)

    def showStopButton(self):
        self.stopBtn.setHidden_(False)

    def enableStopButton(self):
        self.stopBtn.setEnabled_(True)

    def disableStopButton(self):
        self.stopBtn.setEnabled_(False)

    def getRestartAlertDismissed(self):
        return self.restartAlertDismissed

