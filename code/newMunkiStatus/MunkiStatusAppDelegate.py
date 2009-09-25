#
#  MunkiStatusAppDelegate.py
#  MunkiStatus
#
#  Created by Greg Neagle on 9/21/09.
#  Copyright Walt Disney Animation 2009. All rights reserved.
#

from Foundation import *
from AppKit import *

class MunkiStatusAppDelegate(NSObject):
    def applicationDidFinishLaunching_(self, sender):
        #NSLog("Application did finish launching.")
        pass

    def applicationWillTerminate_(self,sender):
        NSLog("Application will terminate.")