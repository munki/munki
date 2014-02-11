# encoding: utf-8
#
#  MSUAppDelegate.py
#  Managed Software Update
#
#  Copyright 2013-2014 Greg Neagle.
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

from objc import YES, NO, IBAction, IBOutlet, nil
import PyObjCTools
from Foundation import *
from AppKit import *

from MSUStatusController import MSUStatusController

import munki

class MSUAppDelegate(NSObject):
    
    mainWindowController = IBOutlet()
    statusController = IBOutlet()
    
    managedsoftwareupdate_task = None

    def applicationShouldTerminate_(self, sender):
        # called if user selects 'Quit' from menu
        return self.mainWindowController.appShouldTerminate()
    
    def applicationDidFinishLaunching_(self, sender):
        # Prevent automatic relaunching at login on Lion+
        if NSApp.respondsToSelector_('disableRelaunchOnLogin'):
            NSApp.disableRelaunchOnLogin()
        
        ver = NSBundle.mainBundle().infoDictionary().get('CFBundleShortVersionString')
        NSLog("MSU GUI version: %s" % ver)
        munki.log("MSU", "launched", "VER=%s" % ver)

        # register for notification messages so we can be told if available
        # updates change while we are open
        notification_center = NSDistributedNotificationCenter.defaultCenter()
        notification_center.addObserver_selector_name_object_suspensionBehavior_(
            self,
            self.updateAvailableUpdates,
            'com.googlecode.munki.ManagedSoftwareUpdate.update',
            None,
            NSNotificationSuspensionBehaviorDeliverImmediately)
                                                                                 
        # register for notification messages so we can be told to
        # display a logout warning
        notification_center = NSDistributedNotificationCenter.defaultCenter()
        notification_center.addObserver_selector_name_object_suspensionBehavior_(
            self,
            self.forcedLogoutWarning,
            'com.googlecode.munki.ManagedSoftwareUpdate.logoutwarn',
            None,
            NSNotificationSuspensionBehaviorDeliverImmediately)
            
        # user may have launched the app manually, or it may have
        # been launched by /usr/local/munki/managedsoftwareupdate
        # to display available updates
        if munki.thereAreUpdatesToBeForcedSoon(hours=2):
            # skip the check and just display the updates
            # by pretending the lastcheck is now
            lastcheck = NSDate.date()
        else:
            lastcheck = munki.pref('LastCheckDate')
        # if there is no lastcheck timestamp, check for updates.
        if not lastcheck:
            self.checkForUpdates()
        
        # otherwise, only check for updates if the last check is over the
        # configured manualcheck cache age max.
        max_cache_age = munki.pref('CheckResultsCacheSeconds')
        if lastcheck.timeIntervalSinceNow() * -1 > int(max_cache_age):
            self.checkForUpdates()
                         
        # just show the default initial view
        self.mainWindowController.loadInitialView()

    def updateAvailableUpdates(self):
        NSLog(u"Managed Software Update got update notification")
        if not self.mainWindowController._update_in_progress:
            self.mainWindowController.resetAndReload()

    def forcedLogoutWarning(self, notification_obj):
        NSLog(u"Managed Software Update got forced logout warning")
    
    def munkiStatusSessionEnded_(self, socketSessionResult):
        NSLog(u"MunkiStatus session ended: %s" % socketSessionResult)
        NSLog(u"MunkiStatus session type: %s" % self.managedsoftwareupdate_task)
        # tell the main window
        tasktype = self.managedsoftwareupdate_task
        self.managedsoftwareupdate_task = None
        self.mainWindowController.munkiTaskEnded_withResult_(
                            tasktype, socketSessionResult)

    def checkForUpdates(self, suppress_apple_update_check=False):
        # kick off an update check
        # attempt to start the update check
        #result = munki.startUpdateCheck(suppress_apple_update_check)
        result = 0
        if result == 0:
            self.managedsoftwareupdate_task = "manualcheck"
            self.statusController.startMunkiStatusSession()
        else:
            self.mainWindowController.theWindow.makeKeyAndOrderFront_(self)
            self.munkiStatusSessionEnded_(2)
