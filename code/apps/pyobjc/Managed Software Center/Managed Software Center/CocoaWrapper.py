# -*- coding: utf-8 -*-
#
#  CocoaWrapper.py
#  Managed Software Center
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
    NSAppleEventManager,
    NSBundle,
    NSCachesDirectory,
    NSData,
    NSDate,
    NSDateFormatter,
    NSDateFormatterBehavior10_4,
    NSFileHandle,
    NSFileManager,
    NSInsetRect,
    NSLocalizedString,
    NSLog,
    NSMakePoint,
    NSMakeRect,
    NSMakeSize,
    NSMinX,
    NSMinY,
    NSMutableArray,
    NSObject,
    NSOffsetRect,
    NSPoint,
    NSPredicate,
    NSString,
    NSTimer,
    NSURL,
    NSURLFileScheme,
    NSURLRequest,
    NSURLRequestReloadIgnoringLocalCacheData,
    NSUTF8StringEncoding,
    NSUserDomainMask,
    NSUserName,
    NSZeroRect,
    kCFDateFormatterLongStyle,
    kCFDateFormatterShortStyle,
)

# put all AppKit imports used by the project here
from AppKit import (
    NSAlert,
    NSAlertAlternateReturn,
    NSAlertDefaultReturn,
    NSAlertFirstButtonReturn,
    NSAlertOtherReturn,
    NSAlertSecondButtonReturn,
    NSApp,
    NSApplication,
    NSBezierPath,
    NSButton,
    NSButtonCell,
    NSColor,
    NSCompositeCopy,
    NSCriticalAlertStyle,
    NSDistributedNotificationCenter,
    NSDragOperationAll,
    NSFontAttributeName,
    NSFontManager,
    NSGraphicsContext,
    NSImage,
    NSNotFound,
    NSNotificationDeliverImmediately,
    NSNotificationPostToAllSessions,
    NSNotificationSuspensionBehaviorDeliverImmediately,
    NSOnState,
    NSPasteboard,
    NSScreen,
    NSUserNotificationCenter,
    NSWindowController,
    NSWorkspace,
)
