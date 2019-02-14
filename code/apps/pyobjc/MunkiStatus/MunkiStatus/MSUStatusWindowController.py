# encoding: utf-8
#
# MSUStatusWindowController.py
# MunkiStatus
#
# Copyright 2009-2019 Greg Neagle.
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
'''Controller for the main status window'''

from objc import YES, NO, IBAction, IBOutlet, nil
from PyObjCTools import AppHelper

import os

import munki
import FoundationPlist

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


# lots of camelCase names, following Cocoa convention
# pylint: disable=invalid-name

debug = False

def getLoginwindowPicture():
    '''Returns the image behind the loginwindow (in < 10.7)'''
    desktopPicturePath = ''
    loginwindowPrefsPath = "/Library/Preferences/com.apple.loginwindow.plist"
    if os.path.exists(loginwindowPrefsPath):
        loginwindowPrefs = FoundationPlist.readPlist(loginwindowPrefsPath)
        if loginwindowPrefs:
            desktopPicturePath = loginwindowPrefs.get('DesktopPicture', '')
            if desktopPicturePath:
                if os.path.exists(desktopPicturePath):
                    theImage = NSImage.alloc().initWithContentsOfFile_(
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
    '''Controls the status window.'''

    # since this subclasses NSObject,
    # it doesn't have a Python __init__method
    # pylint: disable=no-init

    window = IBOutlet()
    logWindow = IBOutlet()
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
    timeout_counter = 0
    saw_process = False
    managedsoftwareupdate_pid = None
    window_level = NSScreenSaverWindowLevel - 1


    @IBAction
    def stopBtnClicked_(self, sender):
        '''Called when stop button is clicked in the status window'''
        if debug:
            NSLog(u"Stop button was clicked.")
        sender.setState_(1)
        self.stopBtnState = 1
        sender.setEnabled_(False)
        # send a notification that stop button was clicked
        STOP_REQUEST_FLAG = ('/private/tmp/com.googlecode.munki.'
                             'managedsoftwareupdate.stop_requested')
        if not os.path.exists(STOP_REQUEST_FLAG):
            open(STOP_REQUEST_FLAG, 'w').close()

    def registerForNotifications(self):
        '''Register for notification messages'''
        dnc = NSDistributedNotificationCenter.defaultCenter()
        dnc.addObserver_selector_name_object_suspensionBehavior_(
            self,
            self.updateStatus_,
            'com.googlecode.munki.managedsoftwareupdate.statusUpdate',
            None,
            NSNotificationSuspensionBehaviorDeliverImmediately)
        dnc.addObserver_selector_name_object_suspensionBehavior_(
            self,
            self.managedsoftwareupdateStarted_,
            'com.googlecode.munki.managedsoftwareupdate.started',
            None,
            NSNotificationSuspensionBehaviorDeliverImmediately)
        dnc.addObserver_selector_name_object_suspensionBehavior_(
            self,
            self.managedsoftwareupdateEnded_,
            'com.googlecode.munki.managedsoftwareupdate.ended',
            None,
            NSNotificationSuspensionBehaviorDeliverImmediately)
        self.receiving_notifications = True

    def unregisterForNotifications(self):
        '''Tell the DistributedNotificationCenter to stop sending us
        notifications'''
        NSDistributedNotificationCenter.defaultCenter().removeObserver_(self)
        # set self.receiving_notifications to False so our process monitoring
        # thread will exit
        self.receiving_notifications = False

    def managedsoftwareupdateStarted_(self, notification):
        '''Called when we get a
        com.googlecode.munki.managedsoftwareupdate.started notification'''
        if 'pid' in notification.userInfo():
            self.managedsoftwareupdate_pid = notification.userInfo()['pid']
            NSLog('managedsoftwareupdate pid %s started'
                  % self.managedsoftwareupdate_pid)

    def managedsoftwareupdateEnded_(self, notification):
        '''Called when we get a
        com.googlecode.munki.managedsoftwareupdate.ended notification'''
        NSLog('managedsoftwareupdate pid %s ended'
              % notification.userInfo().get('pid'))

    def haveElCapPolicyBanner(self):
        '''Returns True if we are running El Cap or later and there is
        a loginwindow PolicyBanner in place'''
        # Get our Darwin major version
        darwin_vers = int(os.uname()[2].split('.')[0])
        if darwin_vers > 14:
            for test_file in ['/Library/Security/PolicyBanner.txt',
                              '/Library/Security/PolicyBanner.rtf',
                              '/Library/Security/PolicyBanner.rtfd']:
                if os.path.exists(test_file):
                    return True
        return False

    def setWindowLevel(self):
        '''Sets our NSWindowLevel. Works around issues with the loginwindow
        PolicyBanner in 10.11+ Some code based on earlier work by Pepijn
        Bruienne'''
        # bump our NSWindowLevel if we have a PolicyBanner in ElCap+
        if self.haveElCapPolicyBanner():
            NSLog('El Capitan+ loginwindow PolicyBanner found')
            self.window_level = NSScreenSaverWindowLevel

    def initStatusSession(self):
        '''Initialize our status session'''
        self.setWindowLevel()
        consoleuser = munki.getconsoleuser()
        if consoleuser == None or consoleuser == u"loginwindow":
            self.displayBackdropWindow()
            # needed so the window can show over the loginwindow
            self.window.setCanBecomeVisibleWithoutLogin_(True)
            self.window.setLevel_(self.window_level)

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
        self.timer = (NSTimer.
            scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                5.0, self, self.checkProcess, None, YES))

    def checkProcess(self):
        '''Monitors managedsoftwareupdate process for failure to start
        or unexpected exit, so we're not waiting around forever if
        managedsoftwareupdate isn't running.'''
        PYTHON_SCRIPT_NAME = 'managedsoftwareupdate'
        NEVER_STARTED = -2
        UNEXPECTEDLY_QUIT = -1

        NSLog('checkProcess timer fired')

        if self.window_level == NSScreenSaverWindowLevel:
            # we're at the loginwindow, there is a PolicyBanner, and we're
            # running under 10.11+. Make sure we're in the front.
            NSApp.activateIgnoringOtherApps_(YES)
            if not self.logWindow.isVisible():
                self.window.makeKeyAndOrderFront_(self)

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
        '''Called if the status session fails'''
        NSLog('statusSessionFailed: %s' % sessionResult)
        self.cleanUpStatusSession()
        NSApp.terminate_(self)

    def cleanUpStatusSession(self):
        '''Clean things up before we exit'''
        self.unregisterForNotifications()
        if self.backdropWindow and self.backdropWindow.isVisible():
            self.backdropWindow.orderOut_(self)
        self.window.orderOut_(self)
        # clean up timer
        if self.timer:
            self.timer.invalidate()
            self.timer = None

    def configureAndDisplayBackdropWindow_(self, window):
        '''Sets all our configuration options for our masking windows'''
        window.setCanBecomeVisibleWithoutLogin_(True)
        if self.haveElCapPolicyBanner():
            self.backdropWindow.setLevel_(self.window_level)
        else:
            self.backdropWindow.setLevel_(self.window_level - 1)
        translucentColor = NSColor.blackColor().colorWithAlphaComponent_(0.35)
        window.setBackgroundColor_(translucentColor)
        window.setOpaque_(False)
        window.setIgnoresMouseEvents_(False)
        window.setAlphaValue_(0.0)
        window.orderFrontRegardless()
        window.animator().setAlphaValue_(1.0)

    def displayBackdropWindow(self):
        '''Draw a window that covers the login UI'''
        self.backdropWindow.setCanBecomeVisibleWithoutLogin_(True)
        if self.haveElCapPolicyBanner():
            self.backdropWindow.setLevel_(self.window_level)
        else:
            self.backdropWindow.setLevel_(self.window_level - 1)
        screenRect = NSScreen.mainScreen().frame()
        self.backdropWindow.setFrame_display_(screenRect, True)

        darwin_vers = int(os.uname()[2].split('.')[0])
        if darwin_vers < 11:
            if self.backdropImageFld:
                bgImage = getLoginwindowPicture()
                self.backdropImageFld.setImage_(bgImage)
                self.backdropWindow.orderFrontRegardless()
        else:
            # Lion+
            # draw transparent/translucent windows to prevent interaction
            # with the login UI
            self.backdropImageFld.setHidden_(True)
            self.configureAndDisplayBackdropWindow_(self.backdropWindow)
            # are there any other screens?
            for screen in NSScreen.screens():
                if screen != NSScreen.mainScreen():
                    # create another masking window for this secondary screen
                    window_rect = screen.frame()
                    window_rect.origin = NSPoint(0.0, 0.0)
                    child_window = NSWindow.alloc(
                        ).initWithContentRect_styleMask_backing_defer_screen_(
                            window_rect,
                            NSBorderlessWindowMask, NSBackingStoreBuffered,
                            NO, screen)
                    self.configureAndDisplayBackdropWindow_(child_window)
                    if self.haveElCapPolicyBanner():
                        self.backdropWindow.addChildWindow_ordered_(
                            child_window, NSWindowAbove)

        if self.haveElCapPolicyBanner():
            # preserve the relative ordering of the backdrop window and the
            # status window IOW, clicking the backdrop window will not bring it
            # in front of the status window
            self.backdropWindow.addChildWindow_ordered_(
                self.window, NSWindowAbove)


    def updateStatus_(self, notification):
        '''Called when we get a
        com.googlecode.munki.managedsoftwareupdate.statusUpdate notification;
        update our status display with information from the notification'''

        if self.window_level == NSScreenSaverWindowLevel:
            # we're at the loginwindow, there is a PolicyBanner, and we're
            # running under 10.11+. Make sure we're in the front.
            NSApp.activateIgnoringOtherApps_(YES)
            if not self.logWindow.isVisible():
                self.window.makeKeyAndOrderFront_(self)

        self.got_status_update = True
        info = notification.userInfo()
        # explicitly get keys from info object; PyObjC in Mountain Lion
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
            NSApp.activateIgnoringOtherApps_(YES)
            self.window.orderFrontRegardless()
        elif command == 'showRestartAlert':
            # clean up timer
            if self.timer:
                self.timer.invalidate()
                self.timer = None
            self.doRestartAlert()
        elif command == 'quit':
            self.cleanUpStatusSession()
            NSApp.terminate_(self)

    def setPercentageDone_(self, percent):
        '''Set progress indicator to display percent done'''
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
        '''Called when restart alert is dismissed'''
        # we don't use the returncode or contextinfo arguments
        # pylint: disable=unused-argument
        self.restartAlertDismissed = 1
        munki.restartNow()

    def doRestartAlert(self):
        '''Display a restart alert'''
        self.restartAlertDismissed = 0
        # pylint: disable=line-too-long
        nsa = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(
            NSLocalizedString(u"Restart Required", None),
            NSLocalizedString(u"Restart", None),
            nil,
            nil,
            NSLocalizedString(
                u"Software installed or removed requires a restart. "
                "You will have a chance to save open documents.", None))
        # pylint: enable=line-too-long
        nsa.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(
            self.window, self, self.restartAlertDidEnd_returnCode_contextInfo_,
            nil)

    def setMessage_(self, messageText):
        '''Set the main status message'''
        messageText = NSBundle.mainBundle().localizedStringForKey_value_table_(
            messageText, messageText, None)
        self.messageFld.setStringValue_(messageText)

    def setDetail_(self, detailText):
        '''Set the status detail text'''
        detailText = NSBundle.mainBundle().localizedStringForKey_value_table_(
            detailText, detailText, None)
        self.detailFld.setStringValue_(detailText)

    def getStopBtnState(self):
        '''Return True if the stop button was clicked; False otherwise'''
        return self.stopBtnState

    def hideStopButton(self):
        '''Hide the stop button'''
        self.stopBtn.setHidden_(True)

    def showStopButton(self):
        '''Show the stop button'''
        self.stopBtn.setHidden_(False)

    def enableStopButton(self):
        '''Enable the stop button'''
        self.stopBtn.setEnabled_(True)

    def disableStopButton(self):
        '''Disable the stop button'''
        self.stopBtn.setEnabled_(False)

    def getRestartAlertDismissed(self):
        '''Return True if the restart alert was dismissed; False otherwise'''
        return self.restartAlertDismissed


def more_localized_strings():
    '''Some strings that are sent to us from managedsoftwareupdate. By putting
    them here, the localize.py script will add them to the
    en.lproj/Localizable.strings file so localizers will be able to discover
    them'''
    dummy = NSLocalizedString(u"Starting...", "managedsoftwareupdate message")
    dummy = NSLocalizedString(u"Finishing...", "managedsoftwareupdate message")
    dummy = NSLocalizedString(
        u"Performing preflight tasks...", "managedsoftwareupdate message")
    dummy = NSLocalizedString(
        u"Performing postflight tasks...", "managedsoftwareupdate message")

    dummy = NSLocalizedString(
        u"Checking for available updates...", "managedsoftwareupdate message")
    dummy = NSLocalizedString(
        u"Checking for additional changes...", "managedsoftwareupdate message")
    dummy = NSLocalizedString(
        u"Software installed or removed requires a restart.",
        "managedsoftwareupdate message")
    dummy = NSLocalizedString(
        u"Waiting for network...", "managedsoftwareupdate message")
    dummy = NSLocalizedString(u"Done.", "managedsoftwareupdate message")

    dummy = NSLocalizedString(
        u"Retrieving list of software for this machine...",
        "managedsoftwareupdate message")
    dummy = NSLocalizedString(
        u"Verifying package integrity...", "managedsoftwareupdate message")

    dummy = NSLocalizedString(
        u"The software was successfully installed.",
        "managedsoftwareupdate message")

    dummy = NSLocalizedString(
        u"Gathering information on installed packages",
        "managedsoftwareupdate message")
    dummy = NSLocalizedString(
        u"Determining which filesystem items to remove",
        "managedsoftwareupdate message")
    dummy = NSLocalizedString(
        u"Removing receipt info", "managedsoftwareupdate message")
    dummy = NSLocalizedString(
        u"Nothing to remove.", "managedsoftwareupdate message")
    dummy = NSLocalizedString(
        u"Package removal complete.", "managedsoftwareupdate message")

    # apple update messages
    dummy = NSLocalizedString(
        u"Checking for available Apple Software Updates...",
        "managedsoftwareupdate message")
    dummy = NSLocalizedString(
        u"Checking Apple Software Update catalog...",
        "managedsoftwareupdate message")
    dummy = NSLocalizedString(
        u"Downloading available Apple Software Updates...",
        "managedsoftwareupdate message")
    dummy = NSLocalizedString(
        u"Installing available Apple Software Updates...",
        "managedsoftwareupdate message")

    # Adobe install/uninstall messages
    dummy = NSLocalizedString(
        u"Running Adobe Setup", "managedsoftwareupdate message")
    dummy = NSLocalizedString(
        u"Running Adobe Uninstall", "managedsoftwareupdate message")
    dummy = NSLocalizedString(
        u"Starting Adobe installer...", "managedsoftwareupdate message")
    dummy = NSLocalizedString(
        u"Running Adobe Patch Installer", "managedsoftwareupdate message")

    # macOS install/upgrade messages
    dummy = NSLocalizedString(
        u"Starting macOS upgrade...", "managedsoftwareupdate message")
    dummy = NSLocalizedString(
        u"Preparing to run macOS Installer...", "managedsoftwareupdate message")
    dummy = NSLocalizedString(
        u"System will restart and begin upgrade of macOS.",
        "managedsoftwareupdate message")
