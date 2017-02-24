# -*- coding: utf-8 -*-
#
#  AppDelegate.py
#  munki-notifier
#
#  Created by Greg Neagle on 4/11/15.
#  Copyright (c) 2015-2017 The Munki Project. All rights reserved.
#
#  Much inspiration from terminal-notifier
#  https://github.com/alloy/terminal-notifier
#

import os

from Foundation import *
from AppKit import *

import objc


MSCBUNDLEIDENTIFIER = u'com.googlecode.munki.ManagedSoftwareCenter'
NOTIFICATIONCENTERBUNDLEID = u'com.apple.notificationcenterui'


def convertDictionary(a_dict):
    '''Converts a python dictionary to a more native-ish NSDictionary containing NSStrings'''
    # convert all our strings to native NSStrings to avoid this on Sierra+:
    #  "Class 'OC_PythonDictionary' has a superclass that supports secure
    #   coding, but 'OC_PythonDictionary' overrides -initWithCoder: and does
    #   not override +supportsSecureCoding. The class must implement
    #   +supportsSecureCoding and return YES"
    new_dict = {}
    for key, value in a_dict.items():
        if isinstance(value, basestring):
            value = NSString.stringWithString_(value)
        new_dict[NSString.stringWithString_(key)] = value
    return NSDictionary.dictionaryWithDictionary_(new_dict)


class AppDelegate(NSObject):
    '''NSApplication delegate'''
    def applicationDidFinishLaunching_(self, notification):
        '''React to app launch'''
        nc = NSUserNotificationCenter.defaultUserNotificationCenter()
        nc.setDelegate_(self)

        userNotification = notification.userInfo().get('NSApplicationLaunchUserNotificationKey')
        if userNotification:
            NSLog('%@', 'Launched due to NSUserNotification')
            self.userActivatedNotification_(userNotification)
            NSApp.terminate_(self)
            return
        else:
            # can we post a Notification Center notification?
            runningProcesses = NSWorkspace.sharedWorkspace(
                ).runningApplications().valueForKey_('bundleIdentifier')
            if NOTIFICATIONCENTERBUNDLEID in runningProcesses:
                # Notification Center is running, OK to notify
                self.notify('Software updates available',
                            text='Some updates have been pending for more than 3 days',
                            url='munki://updates')
                return
        # Notification center is not available; just launch MSC.app and show updates
        NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_('munki://updates'))
        NSApp.terminate_(self)

    def notify(self, title='', subtitle='', text='', url=''):
        '''Send our notification'''
        notification = NSUserNotification.alloc().init()
        notification.setTitle_(title)
        if subtitle:
            notification.setSubtitle_(subtitle)
        if text:
            notification.setInformativeText_(text)
        notification.setSoundName_('NSUserNotificationDefaultSoundName')
        if url:
            user_info = convertDictionary({'action': 'open_url',
                                           'value': url,
                                           'type': 'updates'})
            notification.setUserInfo_(user_info)
        notification.setHasActionButton_(True)
        notification.setActionButtonTitle_('Details')
        # attempt to do notifications of alert style by default
        # (unsupported private API!)
        notification.setValue_forKey_(True, "_showsButtons")
        nc = NSUserNotificationCenter.defaultUserNotificationCenter()
        # remove previously delivered notifications so we don't have multiple
        # update notifications in Notification Center
        nc.removeAllDeliveredNotifications()
        # send our notification on its way
        nc.deliverNotification_(notification)

    def userNotificationCenter_didActivateNotification_(self, center, notification):
        '''User clicked on our notification'''
        self.userActivatedNotification_(notification)
        NSApp.terminate_(self)

    def userNotificationCenter_shouldPresentNotification_(self, center, notification):
        '''Delegate method called when Notification Center has decided it doesn't
        need to present the notification -- returning True overrides that decision'''
        return True

    def userNotificationCenter_didDeliverNotification_(self, center, notification):
        '''Notification was delivered and we can exit'''
        NSApp.terminate_(self)

    def userActivatedNotification_(self, notification):
        '''React to user clicking on notification by opening a URL or by launching MSC.app and
        showing Updates page'''
        NSUserNotificationCenter.defaultUserNotificationCenter().removeDeliveredNotification_(
            notification)
        user_info = notification.userInfo()
        if user_info and user_info.get('action') == 'open_url':
            url = user_info.get('value', 'munki://updates')
            NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_(url))
        else:
            # just fall back to our default behavior, which is to show MSC updates
            NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_('munki://updates'))


def swizzle(*args):
    """
        Decorator to override an ObjC selector's implementation with a
        custom implementation ("method swizzling").

        Use like this:

        @swizzle(NSOriginalClass, 'selectorName')
        def swizzled_selectorName(self, original):
        --> `self` points to the instance
        --> `original` is the original implementation

        Originally from http://klep.name/programming/python/

        (The link was dead on 2013-05-22 but the Google Cache version works:
        http://goo.gl/ABGvJ)
        """
    cls, SEL = args

    def decorator(func):
        old_IMP = cls.instanceMethodForSelector_(SEL)

        def wrapper(self, *args, **kwargs):
            return func(self, old_IMP, *args, **kwargs)

        new_IMP = objc.selector(wrapper, selector=old_IMP.selector,
                                signature=old_IMP.signature)
        objc.classAddMethod(cls, SEL, new_IMP)
        return wrapper

    return decorator


@swizzle(NSBundle, 'bundleIdentifier')
def swizzled_bundleIdentifier(self, original):
    """Swizzle [NSBundle bundleIdentifier] to post a notification as a different bundleID

        Original idea for this approach by Norio Numura:
        https://github.com/norio-nomura/usernotification
        """
    if self == NSBundle.mainBundle():
        # return our fake bundle identifier
        return MSCBUNDLEIDENTIFIER
    else:
        # call original function
        return original(self)
