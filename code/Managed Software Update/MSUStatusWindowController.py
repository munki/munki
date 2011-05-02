# encoding: utf-8
#
#  MSUStatusWindowController.py
#
#
#  Created by Greg Neagle on 9/21/09.
#
# Copyright 2009-2011 Greg Neagle.
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
import socket
import objc
import munki
import FoundationPlist
from Foundation import *
from SystemConfiguration import SCDynamicStoreCopyConsoleUser
from AppKit import *
import PyObjCTools

debug = False

class NSPropertyListSerializationException(Exception):
    pass

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

    window = objc.IBOutlet()
    messageFld = objc.IBOutlet()
    detailFld = objc.IBOutlet()
    progressIndicator = objc.IBOutlet()
    stopBtn = objc.IBOutlet()
    imageFld = objc.IBOutlet()

    backdropWindow = objc.IBOutlet()
    backdropImageFld = objc.IBOutlet()

    stopBtnState = 0
    restartAlertDismissed = 0
    session_started = False
    session_connected = False


    @objc.IBAction
    def stopBtnClicked_(self, sender):
        if debug:
            NSLog(u"Stop button was clicked.")
        sender.setState_(1)
        self.stopBtnState = 1
        sender.setEnabled_(False)

    def startMunkiStatusSession(self):
        NSLog(u"Managed Software Update.app PID: %s" % os.getpid())
        consoleuser = munki.getconsoleuser()
        if consoleuser == None or consoleuser == u"loginwindow":
            if self.backdropWindow:
                self.backdropWindow.setCanBecomeVisibleWithoutLogin_(True)
                self.backdropWindow.setLevel_(NSStatusWindowLevel)
                screenRect = NSScreen.mainScreen().frame()
                self.backdropWindow.setFrame_display_(screenRect, True)
                if self.backdropImageFld:
                    bgImage = getLoginwindowPicture()
                    self.backdropImageFld.setImage_(bgImage)
                self.backdropWindow.orderFrontRegardless()

        if self.window:
            if consoleuser == None or consoleuser == u"loginwindow":
                # needed so the window can show over the loginwindow
                self.window.setCanBecomeVisibleWithoutLogin_(True)
                self.window.setLevel_(NSScreenSaverWindowLevel - 1)
            self.window.center()
            self.messageFld.setStringValue_(NSLocalizedString(u"Starting…", None))
            self.detailFld.setStringValue_(u"")
            self.stopBtn.setHidden_(False)
            self.stopBtn.setEnabled_(True)
            self.stopBtnState = 0
            if self.imageFld:
                theImage = NSImage.imageNamed_("Managed Software Update")
                self.imageFld.setImage_(theImage)
            if self.progressIndicator:
                self.progressIndicator.setMinValue_(0.0)
                self.progressIndicator.setMaxValue_(100.0)
                self.progressIndicator.setIndeterminate_(True)
                self.progressIndicator.setUsesThreadedAnimation_(True)
                self.progressIndicator.startAnimation_(self)
            self.window.orderFrontRegardless()
            # start our message processing thread
            NSThread.detachNewThreadSelector_toTarget_withObject_(
                                                        self.handleSocket,
                                                        self,
                                                        None)

            self.session_started = True
            #NSApp.activateIgnoringOtherApps_(True)


    def sessionStarted(self):
        return self.session_started

    def handleSocket(self):
        # Autorelease pool for memory management
        pool = NSAutoreleasePool.alloc().init()

        socketSessionResult = 0

        socketpath = "/tmp/com.googlecode.munki.munkistatus.%s" % os.getpid()
        try:
            os.remove(socketpath)
        except OSError:
            pass
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(socketpath)
        s.listen(1)
        s.settimeout(30)
        try:
            conn, addr = s.accept()
            # reset the timeout on the connected socket
            conn.settimeout(None)
            self.session_connected = True
            if debug:
                NSLog(u"Socket connection established.")
            buffer = ''
            keepLooping = True
            while keepLooping:
                data = conn.recv(1024)
                if not data:
                    # socket connection was closed, we should terminate.
                    NSLog(u"Socket connection closed without QUIT message.")
                    socketSessionResult = -1
                    break
                if debug:
                    NSLog(repr(data))
                buffer = buffer + data
                # do we have at least one return character?
                if buffer.count('\n'):
                    lines = buffer.splitlines(True)
                    buffer = ''
                    for line in lines:
                        if line.endswith('\n'):
                            command = line.decode('UTF-8').rstrip('\n')
                            if debug:
                                NSLog(u"Socket received command: %s" % command)
                            if command.startswith(u"QUIT: "):
                                keepLooping = False
                                socketSessionResult = 0
                                break
                            response = self.processSocketMsg_(command)
                            if response:
                                conn.send(response)
                        else:
                            buffer = line
                            break

            conn.close()
        except socket.timeout:
            NSLog("Socket timed out before connection.")
            socketSessionResult = -2
        except socket.error, errcode:
            NSLog("Socket error: %s." % errcode)
            socketSessionResult = -1
        try:
            os.remove(socketpath)
        except OSError:
            pass

        self.window.orderOut_(self)
        self.session_started = False
        self.session_connected = False
        #NSApp.delegate().munkiStatusSessionEnded_(socketSessionResult)
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
                self.socketEnded_,socketSessionResult, NO)

        # Clean up autorelease pool
        del pool

    def socketEnded_(self, socketSessionResult):
        NSApp.delegate().munkiStatusSessionEnded_(socketSessionResult)		

    def processSocketMsg_(self, message):
        if message.startswith(u"ACTIVATE: "):
            NSApp.activateIgnoringOtherApps_(True)
            return ""
        if message.startswith(u"HIDE: "):
            self.window.orderOut_(self)
            return ""
        if message.startswith(u"SHOW: "):
            self.window.orderFront_(self)
            return ""
        if message.startswith(u"TITLE: "):
            self.window.setTitle_(NSLocalizedString(message[7:], None))
            return ""
        if message.startswith(u"MESSAGE: "):
            self.messageFld.setStringValue_(
                                NSLocalizedString(message[9:], None))
            return ""
        if message.startswith(u"DETAIL: "):
            self.detailFld.setStringValue_(message[8:])
            return ""
        if message.startswith(u"PERCENT: "):
            self.setPercentageDone(message[9:])
            return ""
        if message.startswith(u"GETSTOPBUTTONSTATE: "):
            return "%s\n" % self.stopBtnState
        if message.startswith(u"HIDESTOPBUTTON: "):
            self.stopBtn.setHidden_(True)
            return ""
        if message.startswith(u"SHOWSTOPBUTTON: "):
            self.stopBtn.setHidden_(False)
            return ""
        if message.startswith(u"ENABLESTOPBUTTON: "):
            self.stopBtn.setEnabled_(True)
            return ""
        if message.startswith(u"DISABLESTOPBUTTON: "):
            self.stopBtn.setEnabled_(False)
            return ""
        if message.startswith(u"RESTARTALERT: "):
            self.doRestartAlert()
            while 1:
                if self.restartAlertDismissed:
                    break
            return "1\n"

        return ""

    def setPercentageDone(self, percent):
        if float(percent) < 0:
            if not self.progressIndicator.isIndeterminate():
                self.progressIndicator.setIndeterminate_(True)
                self.progressIndicator.startAnimation_(self)
        else:
            if self.progressIndicator.isIndeterminate():
                self.progressIndicator.stopAnimation_(self)
                self.progressIndicator.setIndeterminate_(False)
            self.progressIndicator.setDoubleValue_(float(percent))

    @PyObjCTools.AppHelper.endSheetMethod
    def alertDidEnd_returnCode_contextInfo_(self, alert, returncode, contextinfo):
        self.restartAlertDismissed = 1

    def doRestartAlert(self):
        self.restartAlertDismissed = 0
        alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(
            NSLocalizedString(u"Restart Required", None), 
            NSLocalizedString(u"Restart", None), 
            objc.nil, 
            objc.nil, 
            NSLocalizedString(u"Software installed or removed requires a restart. You will have a chance to save open documents.", None))
        alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(
            self.window, self, self.alertDidEnd_returnCode_contextInfo_, objc.nil)

