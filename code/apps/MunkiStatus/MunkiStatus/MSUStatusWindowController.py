# encoding: utf-8
#
# MSUStatusWindowController.py
# MunkiStatus
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
import time
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
    got_status_update = False
    receiving_notifications = False
    timer = None

    @IBAction
    def stopBtnClicked_(self, sender):
        if debug:
            NSLog(u"Stop button was clicked.")
        sender.setState_(1)
        self.stopBtnState = 1
        sender.setEnabled_(False)
        # send a notification that stop button was clicked
        STOP_REQUEST_FLAG = '/private/tmp/com.googlecode.munki.managedsoftwareupdate.stop_requested'
        if not os.path.exists(STOP_REQUEST_FLAG):
            open(STOP_REQUEST_FLAG, 'w').close()
    
    def registerForNotifications(self):
        '''Register for notification messages'''
        notification_center = NSDistributedNotificationCenter.defaultCenter()
        notification_center.addObserver_selector_name_object_suspensionBehavior_(
            self,
            self.updateStatus_,
            'com.googlecode.munki.managedsoftwareupdate.statusUpdate',
            None,
            NSNotificationSuspensionBehaviorDeliverImmediately)
        notification_center.addObserver_selector_name_object_suspensionBehavior_(
            self,
            self.managedsoftwareupdateStarted_,
            'com.googlecode.munki.managedsoftwareupdate.started',
            None,
            NSNotificationSuspensionBehaviorDeliverImmediately)
        notification_center.addObserver_selector_name_object_suspensionBehavior_(
            self,
            self.managedsoftwareupdateEnded_,
            'com.googlecode.munki.managedsoftwareupdate.ended',
            None,
            NSNotificationSuspensionBehaviorDeliverImmediately)
        self.receiving_notifications = True
    
    def unregisterForNotifications(self):
        '''Tell the DistributedNotificationCenter to stop sending us notifications'''
        NSDistributedNotificationCenter.defaultCenter().removeObserver_(self)
        # set self.receiving_notifications to False so our process monitoring
        # thread will exit
        self.receiving_notifications = False
    
    def managedsoftwareupdateStarted_(self, notification):
        if 'pid' in notification.userInfo():
            self.managedsoftwareupdate_pid = notification.userInfo()['pid']
            NSLog('managedsoftwareupdate pid %s started' % self.managedsoftwareupdate_pid)

    def managedsoftwareupdateEnded_(self, notification):
        NSLog('managedsoftwareupdate pid %s ended' % notification.userInfo().get('pid'))

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
            # start our process monitor timer so we can be notified about
            # process failure
            self.timeout_counter = 6
            self.saw_process = False
            self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                                                          5.0, self, self.checkProcess_, None, YES)
            
    def checkProcess_(self, timer):
        '''Monitors managedsoftwareupdate process for failure to start
        or unexpected exit, so we're not waiting around forever if
        managedsoftwareupdate isn't running.'''
        PYTHON_SCRIPT_NAME = 'managedsoftwareupdate'
        NEVER_STARTED = -2
        UNEXPECTEDLY_QUIT = -1
        
        NSLog('checkProcess timer fired')
        
        if self.got_status_update:
            # we got a status update since we last checked; no need to
            # check the process table
            self.timeout_counter = 6
            self.saw_process = True
            # clear the flag so we have to get another status update
            self.got_status_update = False
        elif munki.pythonScriptRunning(PYTHON_SCRIPT_NAME):
            self.timeout_counter = 6
            self.saw_process = True
        else:
            NSLog('managedsoftwareupdate not running...')
            self.timeout_counter -= 1
        if self.timeout_counter == 0:
            NSLog('Timed out waiting for managedsoftwareupdate.')
            if self.saw_process:
                self.statusSessionFailed_(UNEXPECTEDLY_QUIT)
            else:
                self.statusSessionFailed_(NEVER_STARTED)

    def statusSessionFailed_(self, sessionResult):
        NSLog('statusSessionFailed: %s' % sessionResult)
        self.cleanUpStatusSession()
        NSApp.terminate_(self)

    def cleanUpStatusSession(self):
        self.unregisterForNotifications()
        if self.backdropWindow and self.backdropWindow.isVisible():
            self.backdropWindow.orderOut_(self)
        self.window.orderOut_(self)
        # clean up timer
        if self.timer:
            self.timer.invalidate()
            self.timer = None

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
        self.got_status_update = True
        info = notification.userInfo()
        # explictly get keys from info object; PyObjC in Mountain Lion
        # seems to need this
        info_keys = info.keys()
        if 'message' in info_keys:
            self.setMessage_(info['message'])
        if 'detail' in info_keys:
            self.setDetail_(info['detail'])
        if 'percent' in info_keys:
            self.setPercentageDone_(info['percent'])
        if self.stopBtnState == 0 and 'stop_button_visible' in info_keys:
            if info['stop_button_visible']:
                self.showStopButton()
            else:
                self.hideStopButton()
        if self.stopBtnState == 0 and 'stop_button_enabled' in info_keys:
            if info['stop_button_enabled']:
                self.enableStopButton()
            else:
                self.disableStopButton()
    
        command = info.get('command')
        if command == 'activate':
            self.window.orderFrontRegardless()
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
        self.messageFld.setStringValue_(NSLocalizedString(messageText, None))

    def setDetail_(self, detailText):
        self.detailFld.setStringValue_(NSLocalizedString(detailText, None))

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


def more_localized_strings():
    '''Some strings that are sent to us from managedsoftwareupdate. By putting them here,
    the localize.py script will add them to the en.lproj/Localizable.strings file so localizers
    will be able to discover them'''
    foo = NSLocalizedString(u"Starting...", "managedsoftwareupdate message")
    foo = NSLocalizedString(u"Finishing...", "managedsoftwareupdate message")
    foo = NSLocalizedString(u"Checking for available updates...", "managedsoftwareupdate message")
    foo = NSLocalizedString(u"Checking for additional changes...", "managedsoftwareupdate message")
    foo = NSLocalizedString(u"Software installed or removed requires a restart.",
                            "managedsoftwareupdate message")
    foo = NSLocalizedString(u"Waiting for network...", "managedsoftwareupdate message")
    foo = NSLocalizedString(u"Done.", "managedsoftwareupdate message")

    foo = NSLocalizedString(u"Retrieving list of software for this machine...",
                            "managedsoftwareupdate message")
    foo = NSLocalizedString(u"Verifying package integrity...", "managedsoftwareupdate message")

    foo = NSLocalizedString(u"The software was successfully installed.",
                            "managedsoftwareupdate message")

    foo = NSLocalizedString(u"Gathering information on installed packages",
                            "managedsoftwareupdate message")
    foo = NSLocalizedString(u"Determining which filesystem items to remove",
                            "managedsoftwareupdate message")
    foo = NSLocalizedString(u"Removing receipt info",
                            "managedsoftwareupdate message")
    foo = NSLocalizedString(u"Nothing to remove.", "managedsoftwareupdate message")
    foo = NSLocalizedString(u"Package removal complete.", "managedsoftwareupdate message")

    foo = NSLocalizedString(u"Checking for available Apple Software Updates...",
                            "managedsoftwareupdate message")
    foo = NSLocalizedString(u"Checking Apple Software Update catalog...",
                            "managedsoftwareupdate message")
    foo = NSLocalizedString(u"Downloading available Apple Software Updates...",
                            "managedsoftwareupdate message")
    foo = NSLocalizedString(u"Installing available Apple Software Updates...",
                            "managedsoftwareupdate message")

    foo = NSLocalizedString(u"Running Adobe Setup", "managedsoftwareupdate message")
    foo = NSLocalizedString(u"Running Adobe Uninstall", "managedsoftwareupdate message")
    foo = NSLocalizedString(u"Starting Adobe installer...", "managedsoftwareupdate message")
    foo = NSLocalizedString(u"Running Adobe Patch Installer", "managedsoftwareupdate message")
