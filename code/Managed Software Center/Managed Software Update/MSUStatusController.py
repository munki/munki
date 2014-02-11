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

    def sessionEnded_(self, result):
        # clean up if needed
        self.cleanUpStatusSession()
        # tell the app the update session is done
        NSApp.delegate().munkiStatusSessionEnded_(result)
        
    def updateStatus_(self, notification):
        info = notification.userInfo()
        if 'message' in info:
            self.statusWindowController.setMessage_(info['message'])
        if 'detail' in info:
            self.statusWindowController.setDetail_(info['detail'])
        if 'percent' in info:
            self.statusWindowController.setPercentageDone_(info['percent'])
        command = info.get('command')
        if command == 'activate':
            NSApp.activateIgnoringOtherApps_(YES) #? do we really want to do this?
            self.statusWindowController.window().orderFrontRegardless()
        elif command == 'hideStopButton':
            self.statusWindowController.hideStopButton()
        elif command == 'showStopButton':
            self.statusWindowController.showStopButton()
        elif command == 'disableStopButton':
            self.statusWindowController.disableStopButton()
        elif command == 'enableStopButton':
            self.statusWindowController.enableStopButton()
        elif command == 'showRestartAlert':
            self.statusWindowController.doRestartAlert()
        elif command == 'quit':
            self.sessionEnded_(0)
