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
    got_status_update = False

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
        self.receiving_notifications = True

    def unregisterForNotifications(self):
        '''Tell the DistributedNotificationCenter to stop sending us notifications'''
        NSDistributedNotificationCenter.defaultCenter().removeObserver_(self)
        # set self.receiving_notifications to False so our process monitoring
        # thread will exit
        self.receiving_notifications = False
    
    def startMunkiStatusSession(self):
        self.statusWindowController.initStatusSession()
        #self.registerForNotifications()
        self.session_started = True
        # start our process monitor thread so we can be notified about
        # process failure
        NSThread.detachNewThreadSelector_toTarget_withObject_(
                                                self.monitorProcess, self, None)
            
    def cleanUpStatusSession(self):
        self.session_started = False
        #self.unregisterForNotifications()
        self.statusWindowController.cleanUpStatusSession()
    
    def monitorProcess(self):
        '''Monitors managedsoftwareupdate process for failure to start
        or unexpected exit, so we're not waiting around forever if
        managedsoftwareupdate isn't running.'''
        PYTHON_SCRIPT_NAME = 'managedsoftwareupdate'
        NEVER_STARTED = -2
        UNEXPECTEDLY_QUIT = -1
        
        timeout_counter = 6
        saw_process = False
        
        # Autorelease pool for memory management
        pool = NSAutoreleasePool.alloc().init()
        while self.session_started:
            if self.got_status_update:
                # we got a status update since we last checked; no need to
                # check the process table
                timeout_counter = 6
                saw_process = True
                # clear the flag so we have to get another status update
                self.got_status_update = False
            elif munki.pythonScriptRunning(PYTHON_SCRIPT_NAME):
                timeout_counter = 6
                saw_process = True
            else:
                NSLog('No managedsoftwareupdate running...')
                timeout_counter -= 1
            if timeout_counter == 0:
                NSLog('Timed out waiting for managedsoftwareupdate.')
                if saw_process:
                    sessionResult = UNEXPECTEDLY_QUIT
                else:
                    sessionResult = NEVER_STARTED
                self.performSelectorOnMainThread_withObject_waitUntilDone_(
                                            self.sessionEnded_, sessionResult, NO)
                break
            time.sleep(5)
        
        # Clean up autorelease pool
        del pool
    
    def sessionStarted(self):
        return self.session_started

    def sessionEnded_(self, result):
        # clean up if needed
        self.cleanUpStatusSession()
        # tell the app the update session is done
        NSApp.delegate().munkiStatusSessionEnded_(result)
        
    def updateStatus_(self, notification):
        if not self.session_started:
            # we got a status message but we didn't start the session
            # so switch to the right mode
            self.startMunkiStatusSession()
        info = notification.userInfo()
        if 'message' in info:
            self.statusWindowController.setMessage_(info['message'])
        if 'detail' in info:
            self.statusWindowController.setDetail_(info['detail'])
        if 'percent' in info:
            self.statusWindowController.setPercentageDone_(info['percent'])
        if 'stop_button_visible' in info:
            if info['stop_button_visible']:
                self.statusWindowController.showStopButton()
            else:
                self.statusWindowController.hideStopButton()
        if 'stop_button_enabled' in info:
            if info['stop_button_enabled']:
                self.statusWindowController.enableStopButton()
            else:
                self.statusWindowController.disableStopButton()
        command = info.get('command')
        if command == 'activate':
            NSApp.activateIgnoringOtherApps_(YES) #? do we really want to do this?
            self.statusWindowController.window().orderFrontRegardless()
        elif command == 'showRestartAlert':
            self.statusWindowController.doRestartAlert()
        elif command == 'quit':
            self.sessionEnded_(0)
