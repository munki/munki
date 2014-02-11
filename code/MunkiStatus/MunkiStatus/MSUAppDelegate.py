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


import munki

class MSUAppDelegate(NSObject):
    
    statusWindowController = IBOutlet()
    
    def applicationWillFinishLaunching_(self, sender):
        consoleuser = munki.getconsoleuser()
        if consoleuser == None or consoleuser == u"loginwindow":
            # don't show menu bar
            NSMenu.setMenuBarVisible_(NO)

    def applicationDidFinishLaunching_(self, sender):
        # Prevent automatic relaunching at login on Lion+
        if NSApp.respondsToSelector_('disableRelaunchOnLogin'):
            NSApp.disableRelaunchOnLogin()
        
        # show the default initial view
        self.statusWindowController.initStatusSession()

