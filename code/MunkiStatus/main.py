#
#  main.py
#  MunkiStatus
#
#  Created by Greg Neagle on 9/21/09.
#  Copyright Walt Disney Animation 2009. All rights reserved.
#

#import modules required by application
import objc
import Foundation
import AppKit

from PyObjCTools import AppHelper

# import modules containing classes required to start application and load MainMenu.nib
import MunkiStatusAppDelegate
import MSController

# pass control to AppKit
AppHelper.runEventLoop()
