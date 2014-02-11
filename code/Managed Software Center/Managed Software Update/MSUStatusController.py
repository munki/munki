# encoding: utf-8
#
#  MSUStatusController.py
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
import os
import socket
import time
import munki
import FoundationPlist
from Foundation import *
from SystemConfiguration import SCDynamicStoreCopyConsoleUser
from AppKit import *
import PyObjCTools

debug = False

class MSUStatusController(NSObject):
    '''
    Controls the status window. This was formerly part of a
    seperate application known as MunkiStatus.app
    '''

    session_started = False
    session_connected = False
    
    statusWindowController = IBOutlet()
    
    def startMunkiStatusSession(self):
        self.statusWindowController.initStatusSession()
        # start our message processing thread
        NSThread.detachNewThreadSelector_toTarget_withObject_(
            self.handleSocket, self, None)
        self.session_started = True
            
    def cleanUpStatusSession(self):
        self.statusWindowController.cleanUpStatusSession()
    
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
            a_buffer = ''
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
                a_buffer = a_buffer + data
                # do we have at least one return character?
                if a_buffer.count('\n'):
                    lines = a_buffer.splitlines(True)
                    a_buffer = ''
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
                            a_buffer = line
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

        self.session_started = False
        self.session_connected = False
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
                self.socketEnded_,socketSessionResult, NO)

        # Clean up autorelease pool
        del pool

    def socketEnded_(self, socketSessionResult):
        # clean up if needed
        self.cleanUpStatusSession()
        # tell the app the update session is done
        NSApp.delegate().munkiStatusSessionEnded_(socketSessionResult)
        
    def processSocketMsg_(self, message):
        if message.startswith(u"ACTIVATE: "):
            NSApp.activateIgnoringOtherApps_(True)
            self.statusWindowController.window().orderFront_(self)
            return ""
        if message.startswith(u"HIDE: "):
            self.statusWindowController.window().orderOut_(self)
            return ""
        if message.startswith(u"SHOW: "):
            self.statusWindowController.window().orderFront_(self)
            return ""
        if message.startswith(u"TITLE: "):
            self.statusWindowController.window().setTitle_(NSLocalizedString(message[7:], None))
            return ""
        if message.startswith(u"MESSAGE: "):
            self.statusWindowController.performSelectorOnMainThread_withObject_waitUntilDone_(
                'setMessage:',
                NSLocalizedString(message[9:], None),
                NO)
            return ""
        if message.startswith(u"DETAIL: "):
            self.statusWindowController.performSelectorOnMainThread_withObject_waitUntilDone_(
                'setDetail:',
                NSLocalizedString(message[8:], None),
                NO)
            return ""
        if message.startswith(u"PERCENT: "):
            self.statusWindowController.performSelectorOnMainThread_withObject_waitUntilDone_(
                'setPercentageDone:',
                message[9:],
                NO)
            return ""
        if message.startswith(u"GETSTOPBUTTONSTATE: "):
            return "%s\n" % self.statusWindowController.getStopBtnState()
        if message.startswith(u"HIDESTOPBUTTON: "):
            self.statusWindowController.performSelectorOnMainThread_withObject_waitUntilDone_(
                'hideStopButton',
                nil,
                NO)
            return ""
        if message.startswith(u"SHOWSTOPBUTTON: "):
            self.statusWindowController.performSelectorOnMainThread_withObject_waitUntilDone_(
                'showStopButton',
                nil,
                NO)
            return ""
        if message.startswith(u"ENABLESTOPBUTTON: "):
            self.statusWindowController.performSelectorOnMainThread_withObject_waitUntilDone_(
                'enableStopButton',
                nil,
                NO)
            return ""
        if message.startswith(u"DISABLESTOPBUTTON: "):
            self.statusWindowController.performSelectorOnMainThread_withObject_waitUntilDone_(
                'disableStopButton',
                nil,
                NO)
            return ""
        if message.startswith(u"RESTARTALERT: "):
            self.statusWindowController.performSelectorOnMainThread_withObject_waitUntilDone_(
                'doRestartAlert',
                nil,
                NO)
            while 1:
                if self.statusWindowController.getRestartAlertDismissed():
                    break
                time.sleep(.25)  # slow a potential busy loop.
            return "1\n"

        return ""
