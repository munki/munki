#
#  MSController.py
#  MunkiStatus
#
#
#  Created by Greg Neagle on 9/21/09.
#
# Copyright 2009 Greg Neagle.
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
from Foundation import *
from SystemConfiguration import SCDynamicStoreCopyConsoleUser
from AppKit import *
import PyObjCTools

debug = False

class NSPropertyListSerializationException(Exception):
    pass

def readPlist(filepath):
    """
    Read a .plist file from filepath.  Return the unpacked root object
    (which usually is a dictionary).
    """
    plistData = NSData.dataWithContentsOfFile_(filepath)
    dataObject, plistFormat, error = NSPropertyListSerialization.propertyListFromData_mutabilityOption_format_errorDescription_(plistData, NSPropertyListMutableContainers, None, None)
    if error:
        raise NSPropertyListSerializationException(error)
    else:
        return dataObject
        
        
def getLoginwindowPicture():
    desktopPicturePath = ''
    loginwindowPrefsPath = "/Library/Preferences/com.apple.loginwindow.plist"
    if os.path.exists(loginwindowPrefsPath):
        loginwindowPrefs = readPlist(loginwindowPrefsPath)
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
    
                
def getconsoleuser():
    cfuser = SCDynamicStoreCopyConsoleUser( None, None, None )
    return cfuser[0]
    
    
class MSController(NSObject):
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
    
    @objc.IBAction
    def stopBtnClicked_(self, sender):
        if debug: 
            NSLog(u"Stop button was clicked.")
        sender.setState_(1)
        self.stopBtnState = 1
        sender.setEnabled_(False)
    
    def awakeFromNib(self):
        NSLog(u"MunkiStatus.app PID: %s" % os.getpid())
        if getconsoleuser() == None:
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
            # needed so the window can show over the loginwindow
            self.window.setCanBecomeVisibleWithoutLogin_(True)
            if getconsoleuser() == None:
                self.window.setLevel_(NSScreenSaverWindowLevel - 1)
            self.window.center()
            self.window.setTitle_(u"Managed Software Update")
            self.window.orderFrontRegardless()
            if self.imageFld:
                theImage = NSImage.imageNamed_("MunkiStatus")
                self.imageFld.setImage_(theImage)
            #if self.messageFld:
            #    self.messageFld.setStringValue_(u"Working...")
            #if self.detailFld:
            #    self.detailFld.setStringValue_(u"")
            if self.progressIndicator:
                self.progressIndicator.setMinValue_(0.0)
                self.progressIndicator.setMaxValue_(100.0)
                self.progressIndicator.setIndeterminate_(True)
                self.progressIndicator.setUsesThreadedAnimation_(True)
                self.progressIndicator.startAnimation_(self)
        
            NSThread.detachNewThreadSelector_toTarget_withObject_(
                                                            self.handleSocket, 
                                                            self, 
                                                            None)
            NSApp.activateIgnoringOtherApps_(True)
            
    def handleSocket(self):        
        # Autorelease pool for memory management
        pool = NSAutoreleasePool.alloc().init()
        
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        socketpath = "/tmp/com.googlecode.munki.munkistatus.%s" % os.getpid()
        try:
            os.remove(socketpath)
        except OSError:
            pass
        s.bind(socketpath)
        s.listen(1)
        conn, addr = s.accept()
        if debug:
            NSLog(u"Connection established.")
        buffer = ''
        keepLooping = True
        while keepLooping:
            data = conn.recv(1024)
            if not data:
                # socket connection was closed, we should terminate.
                NSLog(u"Connection closed without QUIT message.")
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
                            NSLog(u"Received command: %s" % command)
                        if command.startswith(u"QUIT: "):
                            keepLooping = False
                            break
                        response = self.processSocketMsg(command)
                        if response:
                            conn.send(response)
                    else:
                        buffer = line
                        break
            
        conn.close()
        try:
            os.remove(socketpath)
        except OSError:
            pass
        NSApp.terminate_(self)
        
        # Clean up autorelease pool
        del pool
        
    def processSocketMsg(self, message):
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
            self.window.setTitle_(message[7:])
            return ""
        if message.startswith(u"MESSAGE: "):
            self.messageFld.setStringValue_(message[9:])
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
        alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(u"Restart Required", u"Restart", objc.nil, objc.nil, "Software installed or removed requires a restart. You will have a chance to save open documents.")
        alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(self.window, self, self.alertDidEnd_returnCode_contextInfo_, objc.nil) 
        