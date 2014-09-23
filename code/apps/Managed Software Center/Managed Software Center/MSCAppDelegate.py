# encoding: utf-8
#
#  MSCAppDelegate.py
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

# struct for the url handler
import struct
import os
from urlparse import urlparse

from objc import YES, NO, IBAction, IBOutlet, nil
import PyObjCTools
from Foundation import *
from AppKit import *

from MSCStatusController import MSCStatusController

import munki
import mschtml
import msclog
import MunkiItems

class MSCAppDelegate(NSObject):

    mainWindowController = IBOutlet()
    statusController = IBOutlet()

    def applicationShouldTerminate_(self, sender):
        '''Called if user selects 'Quit' from menu'''
        return self.mainWindowController.appShouldTerminate()

    def applicationDidFinishLaunching_(self, sender):
        '''NSApplication delegate method called at launch'''
        # Prevent automatic relaunching at login on Lion+
        if NSApp.respondsToSelector_('disableRelaunchOnLogin'):
            NSApp.disableRelaunchOnLogin()

        ver = NSBundle.mainBundle().infoDictionary().get('CFBundleShortVersionString')
        msclog.log("MSC", "launched", "VER=%s" % ver)
        
        # if we're running under Snow Leopard, swap out the Dock icon for one
        # without the Retina assets to avoid an appearance issue when the
        # icon has a badge in the Dock (and App Switcher)
        # Darwin major version 10 is Snow Leopard (10.6)
        if os.uname()[2].split('.')[0] == '10':
            myImage = NSImage.imageNamed_("Managed Software Center 10_6")
            NSApp.setApplicationIconImage_(myImage)

        # setup client logging
        msclog.setup_logging()

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
        max_cache_age = munki.pref('CheckResultsCacheSeconds')
        # if there is no lastcheck timestamp, check for updates.
        if not lastcheck:
            self.mainWindowController.checkForUpdates()
        elif lastcheck.timeIntervalSinceNow() * -1 > int(max_cache_age):
            # check for updates if the last check is over the
            # configured manualcheck cache age max.
            self.mainWindowController.checkForUpdates()
        elif MunkiItems.updateCheckNeeded():
            # check for updates if we have optional items selected for install
            # or removal that have not yet been processed
            self.mainWindowController.checkForUpdates()
        
        # load the initial view only if we are not already loading something else.
        # enables launching the app to a specific panel, eg. from URL handler
        if not self.mainWindowController.webView.isLoading():
            self.mainWindowController.loadInitialView()

    def applicationWillFinishLaunching_(self, notification):
        '''Installs URL handler for calls outside the app eg. web clicks'''
        man = NSAppleEventManager.sharedAppleEventManager()
        man.setEventHandler_andSelector_forEventClass_andEventID_(
            self,
            "openURL:withReplyEvent:",
            struct.unpack(">i", "GURL")[0],
            struct.unpack(">i", "GURL")[0])

    def openURL_withReplyEvent_(self, event, replyEvent):
        '''Handle openURL messages'''
        keyDirectObject = struct.unpack(">i", "----")[0]
        url = event.paramDescriptorForKeyword_(keyDirectObject).stringValue().decode('utf8')
        msclog.log("MSU", "Called by external URL: %s", url)
        parsed_url = urlparse(url)
        if parsed_url.scheme != 'munki':
            msclog.debug_log("URL %s has unsupported scheme" % url)
            return
        filename = mschtml.unquote(parsed_url.netloc)
        # add .html if no extension
        if not os.path.splitext(filename)[1]:
            filename += u'.html'
        if filename.endswith(u'.html'):
            mschtml.build_page(filename)
            self.mainWindowController.load_page(filename)
        else:
            msclog.debug_log("%s doesn't have a valid extension. Prevented from opening" % url)
