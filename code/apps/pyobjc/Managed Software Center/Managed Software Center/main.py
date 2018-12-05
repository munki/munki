# encoding: utf-8
#
#  main.py
#
#  Created by Greg Neagle on 2/14/13.
#

#import modules required by application
import objc
import Foundation
import AppKit

from PyObjCTools import AppHelper

# import modules containing classes required to start application and
# MainMenu.nib
import MSCAppDelegate
import MSCMainWindowController
import MSCPasswordAlertController
import MSCStatusController
import MSCLogWindowController
import MSCToolbar

# get more debugging info on exceptions
objc.setVerbose(1)

# pass control to AppKit
AppHelper.runEventLoop()
