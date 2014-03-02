# encoding: utf-8
#
#  MSUAppDelegate.py
#  Managed Software Center
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
import msulog

class MSUAppDelegate(NSObject):
    
    mainWindowController = IBOutlet()
    statusController = IBOutlet()

    def applicationShouldTerminate_(self, sender):
        # called if user selects 'Quit' from menu
        return self.mainWindowController.appShouldTerminate()
    
    def applicationDidFinishLaunching_(self, sender):
        # Prevent automatic relaunching at login on Lion+
        if NSApp.respondsToSelector_('disableRelaunchOnLogin'):
            NSApp.disableRelaunchOnLogin()
        
        ver = NSBundle.mainBundle().infoDictionary().get('CFBundleShortVersionString')
        NSLog("MSC GUI version: %s" % ver)
        msulog.log("MSC", "launched", "VER=%s" % ver)
        
        # setup client logging
        msulog.setup_logging()

        # have the statuscontroller register for its own notifications
        self.statusController.registerForNotifications()
            
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
            self.mainWindowController.checkForUpdates()
        
        # otherwise, only check for updates if the last check is over the
        # configured manualcheck cache age max.
        max_cache_age = munki.pref('CheckResultsCacheSeconds')
        if lastcheck.timeIntervalSinceNow() * -1 > int(max_cache_age):
            self.mainWindowController.checkForUpdates()
                         
        # show the default initial view
        self.mainWindowController.loadInitialView()
