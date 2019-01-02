# encoding: utf-8
#
#  MSCAppDelegate.py
#  Managed Software Center
#
#  Copyright 2013-2019 Greg Neagle.
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

# struct for the url handler
import struct
import os
from urlparse import urlparse

from objc import YES, NO, IBAction, IBOutlet, nil
import PyObjCTools
#from Foundation import *
#from AppKit import *
# pylint: disable=wildcard-import
from CocoaWrapper import *
# pylint: enable=wildcard-import


from MSCStatusController import MSCStatusController

import munki
import mschtml
import msclog
import MunkiItems

class MSCAppDelegate(NSObject):

    mainWindowController = IBOutlet()
    statusController = IBOutlet()
    passwordAlertController = IBOutlet()

    def applicationShouldTerminate_(self, sender):
        '''Called if user selects 'Quit' from menu'''
        return self.mainWindowController.appShouldTerminate()

    def applicationDidFinishLaunching_(self, sender):
        '''NSApplication delegate method called at launch'''
        NSLog("Finished launching")
        # setup client logging
        msclog.setup_logging()
        
        # userInfo dict can be nil, seems to be with 10.6
        if sender.userInfo():
            userNotification = sender.userInfo().get('NSApplicationLaunchUserNotificationKey')
            # we get this notification at launch because it's too early to have declared ourself
            # a NSUserNotificationCenterDelegate
            if userNotification:
                NSLog("Launched via Notification interaction")
                self.userNotificationCenter_didActivateNotification_(
                    NSUserNotificationCenter.defaultUserNotificationCenter(), userNotification)
        
        # Prevent automatic relaunching at login on Lion+
        if NSApp.respondsToSelector_('disableRelaunchOnLogin'):
            NSApp.disableRelaunchOnLogin()

        ver = NSBundle.mainBundle().infoDictionary().get('CFBundleShortVersionString')
        msclog.log("MSC", "launched", "VER=%s" % ver)
        
        # if we're running under Snow Leopard, swap out the Dock icon for one
        # without the Retina assets to avoid an appearance issue when the
        # icon has a badge in the Dock (and App Switcher)
        # Darwin major version 10 is Snow Leopard (10.6)
        if int(os.uname()[2].split('.')[0]) == 10:
            myImage = NSImage.imageNamed_("Managed Software Center 10_6")
            NSApp.setApplicationIconImage_(myImage)

        # if we are running under Mountain Lion or later set ourselves as a delegate
        # for NSUserNotificationCenter notifications
        if int(os.uname()[2].split('.')[0]) > 11:
            NSUserNotificationCenter.defaultUserNotificationCenter().setDelegate_(self)

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

    def openMunkiURL(self, url):
        '''Display page associated with munki:// url'''
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

    def openURL_withReplyEvent_(self, event, replyEvent):
        '''Handle openURL messages'''
        keyDirectObject = struct.unpack(">i", "----")[0]
        url = event.paramDescriptorForKeyword_(keyDirectObject).stringValue().decode('utf8')
        msclog.log("MSU", "Called by external URL: %s", url)
        self.openMunkiURL(url)

    def userNotificationCenter_didActivateNotification_(self, center, notification):
        '''User clicked on a Notification Center alert'''
        user_info = notification.userInfo() or {}
        if user_info.get('action') == 'open_url':
            url = user_info.get('value', 'munki://updates')
            msclog.log("MSU", "Got user notification to open %s" % url)
            self.openMunkiURL(url)
            center.removeDeliveredNotification_(notification)
        else:
            msclog.log("MSU", "Got user notification with unrecognized userInfo")
            self.openMunkiURL('munki://updates')

    def userNotificationCenter_shouldPresentNotification_(self, center, notification):
        return True

    def userNotificationCenter_didDeliverNotification_(self, center, notification):
        pass
