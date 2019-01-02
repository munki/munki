# encoding: utf-8
#
#  MSUAppDelegate.py
#  MunkiStatus
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
'''Following Cocoa application design pattern - defines our app delegate
class'''

from objc import YES, NO, IBOutlet
import PyObjCTools
## pylint: disable=wildcard-import
## pylint: disable=unused-wildcard-import
## pylint: disable=redefined-builtin
#from Foundation import *
#from AppKit import *
## pylint: enable=redefined-builtin
## pylint: enable=wildcard-import

# pylint: disable=wildcard-import
from CocoaWrapper import *
# pylint: enable=wildcard-import

import munki

# lots of camelCase names following Cocoa style
# pylint: disable=C0103


class MSUAppDelegate(NSObject):
    '''Implements some NSApplicationDelegateProtocol methods'''

    # since this subclasses NSObject,
    # it doesn't have a Python __init__method
    # pylint: disable=no-init

    # several delegate methods pass a 'sender' object that we don't use
    # pylint: disable=unused-argument

    statusWindowController = IBOutlet()
    logWindowController = IBOutlet()

    def applicationWillFinishLaunching_(self, sender):
        '''NSApplicationDelegate method
        Sent by the default notification center immediately before the
        application object is initialized.'''

        # pylint: disable=no-self-use

        consoleuser = munki.getconsoleuser()
        if consoleuser == None or consoleuser == u"loginwindow":
            # don't show menu bar
            NSMenu.setMenuBarVisible_(NO)
            # make sure we're active
            NSApp.activateIgnoringOtherApps_(YES)

    def applicationDidFinishLaunching_(self, sender):
        '''NSApplicationDelegate method
        Sent by the default notification center after the application has
        been launched and initialized but before it has received its first
        event.'''

        # Prevent automatic relaunching at login on Lion+
        if NSApp.respondsToSelector_('disableRelaunchOnLogin'):
            NSApp.disableRelaunchOnLogin()

        # show the default initial view
        self.statusWindowController.initStatusSession()

