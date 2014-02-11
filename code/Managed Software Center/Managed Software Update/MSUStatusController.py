# encoding: utf-8
#
# MSUStatusController.py
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
import time
import munki
import FoundationPlist
from Foundation import *
from AppKit import *
import PyObjCTools

debug = False

class MSUStatusController(NSObject):
    '''
    Handles status messages from managedsoftwareupdate
    '''

    session_started = False
    session_connected = False
    
    statusWindowController = IBOutlet()
    
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
    
    def startMunkiStatusSession(self):
        self.statusWindowController.initStatusSession()
        self.registerForNotifications()
        self.session_started = True
            
    def cleanUpStatusSession(self):
        self.session_started = False
        self.unregisterForNotifications()
        self.statusWindowController.cleanUpStatusSession()
    
    def sessionStarted(self):
        return self.session_started

    def socketEnded_(self, socketSessionResult):
        # clean up if needed
        self.cleanUpStatusSession()
        # tell the app the update session is done
        NSApp.delegate().munkiStatusSessionEnded_(socketSessionResult)
        
    def updateStatus_(self, notification):
        info = notification.userInfo()
        if 'message' in info:
            statusWindowController.setMessage_(info['message'])
        if 'detail' in info:
            statusWindowController.setDetail_(info['detail'])
        if 'percent' in info:
            statusWindowController.setPercentageDone_(info['percent'])
        command = info.get('command')
        if command == 'activate':
            statusWindowController.window.orderFrontRegardless()
        elif command == 'hideStopButton':
            statusWindowController.hideStopButton()
        elif command == 'showStopButton':
            statusWindowController.showStopButton()
        elif command == 'disableStopButton':
            statusWindowController.disableStopButton()
        elif command == 'enableStopButton':
            statusWindowController.enableStopButton()
        elif command == 'showRestartAlert':
            statusWindowController.doRestartAlert()
        elif command == 'quit':
            self.cleanUpStatusSession()
