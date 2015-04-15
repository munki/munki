# -*- coding: utf-8 -*-
#
#  AppDelegate.py
#  notifier
#
#  Created by Greg Neagle on 4/11/15.
#  Copyright (c) 2015 The Munki Project. All rights reserved.
#

from Foundation import *
from AppKit import *

import objc

MSCbundleIdentifier = u'com.googlecode.munki.ManagedSoftwareCenter'
NotificationCenterUIBundleID = u'com.apple.notificationcenterui'

class AppDelegate(NSObject):
    def applicationDidFinishLaunching_(self, notification):
        userNotification = notification.userInfo().get('NSApplicationLaunchUserNotificationKey')
        if userNotification:
            NSLog('Launched due to NSUserNotification')
            self.userActivatedNotification_(userNotification)
            NSApp.terminate_(self)
        else:
            
            runningProcesses = NSWorkspace.sharedWorkspace().runningApplications().valueForKey_(
                'bundleIdentifier')
            if NotificationCenterUIBundleID not in runningProcesses:
                NSLog('[!] Unable to post a notification for the current user (%@), as it has no '
                      'running NotificationCenter instance.', NSUserName())
                NSApp.terminate_(self)
            self.notify('Updates available', '', 'Software updates are ready to install.',
                        'munki://updates')
            
            
    def notify(self, title, subtitle, text, url):
        '''Send our notification'''
        nc = NSUserNotificationCenter.defaultUserNotificationCenter()
        for userNotification in nc.deliveredNotifications():
            # remove any previously posted update notifications
            if userNotification.userInfo().get('type') == 'updates':
                nc.removeDeliveredNotification_(userNotification)
        notification = NSUserNotification.alloc().init()
        notification.setTitle_(title)
        notification.setSubtitle_(subtitle)
        notification.setInformativeText_(text)
        notification.setSoundName_('NSUserNotificationDefaultSoundName')
        notification.setUserInfo_({'action': 'open_url', 'url': url, 'type': 'updates'})
        notification.setHasActionButton_(True)
        notification.setActionButtonTitle_('Details')
        # private (undocumented) functionality
        notification.setValue_forKey_(True, '_showsButtons')
        nc.setDelegate_(self)
        nc.scheduleNotification_(notification)

    def userNotificationCenter_didActivateNotification_(self, center, notification):
        '''User clicked on our notification'''
        NSLog('Got userNotificationCenter:didActivateNotification:')
        self.userActivatedNotification_(notification)
                      
    def userNotificationCenter_shouldPresentNotification_(self, center, notification):
        '''Delegate method called when Notification Center has decided it doesn't
        need to present the notification -- returning True overrides that decision'''
        NSLog('Got userNotificationCenter:shouldPresentNotification:')
        return True
                      
    def userNotificationCenter_didDeliverNotification_(self, center, notification):
        '''Notification was delivered and we can exit'''
        NSLog('Got userNotificationCenter:didDeliverNotification:')
        NSApp.terminate_(self)

    def userActivatedNotification_(self, notification):
        '''React to user clicking on notification by launching MSC.app and showing Updates page'''
        NSUserNotificationCenter.defaultUserNotificationCenter().removeDeliveredNotification_(
            notification)
        user_info = notification.userInfo()
        if user_info.get('action') == 'open_url':
            url = user_info.get('url')
            NSWorkspace.sharedWorkspace(
                ).openURLs_withAppBundleIdentifier_options_additionalEventParamDescriptor_launchIdentifiers_(
                    [NSURL.URLWithString_(url)], MSCbundleIdentifier, 0, None, None)


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
    """Swizzle [NSBundle bundleIdentifier] to make NSUserNotifications
        work.
        
        To post NSUserNotifications OS X requires the binary to be packaged
        as an application bundle. To circumvent this restriction, we modify
        `bundleIdentifier` to return a fake bundle identifier.
        
        Original idea for this approach by Norio Numura:
        https://github.com/norio-nomura/usernotification
        """
    if self == NSBundle.mainBundle():
        # return our fake bundle identifier
        return MSCbundleIdentifier
    else:
        # call original function
        return original(self)
