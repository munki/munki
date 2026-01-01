//
//  AppDelegate.h
//  munki-notifier
//
//  Created by Greg Neagle on 2/23/17.
//  Copyright © 2018-2026 The Munki Project. All rights reserved.
//

#import <Cocoa/Cocoa.h>
#import <UserNotifications/UserNotifications.h>

@interface AppDelegate : NSObject <NSApplicationDelegate, NSUserNotificationCenterDelegate, UNUserNotificationCenterDelegate>
@end
