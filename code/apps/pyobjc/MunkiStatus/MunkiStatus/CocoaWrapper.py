# -*- coding: utf-8 -*-
#
#  CocoaWrapper.py
#  MunkiStatus
#
#  Created by Greg Neagle on 6/26/17.
#  Copyright (c) 2018-2019 The Munki Project. All rights reserved.
#

"""Selectively import Cocoa symbols to speed up app launch.
Idea from Per Olofsson's AutoDMG"""

# PyLint cannot properly find names inside Cocoa libraries, so issues bogus
# No name 'Foo' in module 'Bar' warnings. Disable them.
# pylint: disable=no-name-in-module
#
# disable unused-import warning, since we don't use any of these here.
# pylint: disable=unused-import

# put all Foundation imports used by the project here
from Foundation import (
    NSBundle,
    NSData,
    NSFileHandle,
    NSLocalizedString,
    NSLog,
    NSMutableArray,
    NSObject,
    NSPoint,
    NSPredicate,
    NSString,
    NSTimer,
    NSURL,
    NSUTF8StringEncoding,
)

# put all AppKit imports used by the project here
from AppKit import (
    NSAlert,
    NSApp,
    NSBackingStoreBuffered,
    NSBorderlessWindowMask,
    NSColor,
    NSDistributedNotificationCenter,
    NSDragOperationAll,
    NSImage,
    NSMenu,
    NSNotFound,
    NSNotificationSuspensionBehaviorDeliverImmediately,
    NSPasteboard,
    NSScreen,
    NSScreenSaverWindowLevel,
    NSWindow,
    NSWindowAbove,
)
