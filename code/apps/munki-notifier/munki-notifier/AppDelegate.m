//
//  AppDelegate.m
//  munki-notifier
//
//  Created by Greg Neagle on 2/23/17.
//  Copyright © 2018-2026 The Munki Project. All rights reserved.
//  Much code lifted and adapted from https://github.com/julienXX/terminal-notifier
//

#import "AppDelegate.h"
#import <objc/runtime.h>
#import <UserNotifications/UserNotifications.h>
#import <OSLog/OSLog.h>

NSString * const NotificationCenterUIBundleID = @"com.apple.notificationcenterui";
NSString * const MunkiAppURL = @"munki://";
NSString * const MunkiNotificationURL = @"munki://notify";
long const DefaultUseNotificationCenterDays = 3;

@implementation AppDelegate

- (NSApplicationTerminateReply)applicationShouldTerminate:(NSApplication *)sender;
{
    return NSTerminateNow;
}

- (void)applicationWillFinishLaunching:(NSNotification *)notification;
{
    writeToLog(@"applicationWillFinishLaunching");
    UNUserNotificationCenter *center = [UNUserNotificationCenter currentNotificationCenter];
    center.delegate = self;
}

- (void)applicationDidFinishLaunching:(NSNotification *)notification;
{
    // see if we've been directed to clear all delivered notifications
    // if so, do that and exit
    writeToLog(@"applicationDidFinishLaunching");
    NSArray *args = [[NSProcessInfo processInfo] arguments];
    //NSLog(@"Arguments: %@", args);
    if ([args indexOfObject:@"-clear"] != NSNotFound) {
        //NSLog(@"Removing all delivered notifications");
        [[NSUserNotificationCenter defaultUserNotificationCenter] removeAllDeliveredNotifications];
        sleep(1);
        writeToLog(@"Application exiting");
        [NSApp terminate:self];
        return;
    }
    
    // notify user of available updates
    NSObject *notificationObject = notification.userInfo[NSApplicationLaunchUserNotificationKey];
    if (notificationObject) {
        writeToLog(@"Launched via user notification");
        //[self userActivatedNotification:userNotification];
    } else {
        [self notifyUser];
    }
}

- (void)notifyUser
{
    // Do we have a running NotificationCenter?
    NSArray *runningProcesses = [[[NSWorkspace sharedWorkspace] runningApplications]
                                 valueForKey:@"bundleIdentifier"];
    BOOL notificationCenterAvailable = (
            [runningProcesses indexOfObject:NotificationCenterUIBundleID] != NSNotFound);
    
    // get count of pending updates, oldest update days and any forced update due date
    // from Munki's preferences
    CFPropertyListRef plistRef = nil;
    long updateCount = 0;
    float oldestUpdateDays = 0;
    long useNotificationCenterDays = DefaultUseNotificationCenterDays;
    NSDate *forcedUpdateDueDate = nil;
    
    CFPreferencesAppSynchronize(CFSTR("ManagedInstalls"));
    plistRef = CFPreferencesCopyValue(CFSTR("PendingUpdateCount"),
                                      CFSTR("ManagedInstalls"),
                                      kCFPreferencesAnyUser,
                                      kCFPreferencesCurrentHost);
    if (plistRef && CFGetTypeID(plistRef) == CFNumberGetTypeID()) {
        updateCount = [(NSNumber *)CFBridgingRelease(plistRef) integerValue];
    }
    plistRef = CFPreferencesCopyValue(CFSTR("OldestUpdateDays"),
                                      CFSTR("ManagedInstalls"),
                                      kCFPreferencesAnyUser,
                                      kCFPreferencesCurrentHost);
    if (plistRef && CFGetTypeID(plistRef) == CFNumberGetTypeID()) {
        oldestUpdateDays = [(NSNumber *)CFBridgingRelease(plistRef) floatValue];
    }
    if (CFPreferencesAppValueIsForced(CFSTR("UseNotificationCenterDays"), CFSTR("ManagedInstalls"))) {
        // use CFPreferencesCopyAppValue so we can respect managed preferences
        plistRef = CFPreferencesCopyAppValue(CFSTR("UseNotificationCenterDays"), CFSTR("ManagedInstalls"));
    } else {
        // preference not managed, read from /Library/Preferences (ignoring user-level preferences)
        plistRef = CFPreferencesCopyValue(CFSTR("UseNotificationCenterDays"),
                                          CFSTR("ManagedInstalls"),
                                          kCFPreferencesAnyUser,
                                          kCFPreferencesCurrentHost);
    }
    if (plistRef && CFGetTypeID(plistRef) == CFNumberGetTypeID()) {
        useNotificationCenterDays = [(NSNumber *)CFBridgingRelease(plistRef) integerValue];
    }
    //NSLog(@"UseNotificationCenterDays: %ld", useNotificationCenterDays);
    plistRef = CFPreferencesCopyValue(CFSTR("ForcedUpdateDueDate"),
                                      CFSTR("ManagedInstalls"),
                                      kCFPreferencesAnyUser,
                                      kCFPreferencesCurrentHost);
    if (plistRef && CFGetTypeID(plistRef) == CFDateGetTypeID()) {
        forcedUpdateDueDate = (NSDate *)CFBridgingRelease((CFDateRef)plistRef);
    }
    
    if (updateCount == 0) {
        // no available updates
        if (notificationCenterAvailable) {
            // clear any previously posted updates available notifications and exit
            [[NSUserNotificationCenter defaultUserNotificationCenter] removeAllDeliveredNotifications];
        }
        writeToLog(@"Application exiting");
        [NSApp terminate: self];
        return;
    }
    
    // updateCount > 0
    if (! notificationCenterAvailable || oldestUpdateDays > useNotificationCenterDays) {
        // Notification Center is not available or Notification Manager notifications
        // are being ignored or suppressed; launch MSC.app and show updates
        if (notificationCenterAvailable) {
            // clear any previously posted updates available notifications since we are going
            // to launch MSC.app
            [[NSUserNotificationCenter defaultUserNotificationCenter] removeAllDeliveredNotifications];
        }
        // work around a bug with multiple spaces by opening the
        // app first, sleeping, then telling the app to notify
        [[NSWorkspace sharedWorkspace] openURL:[NSURL URLWithString: MunkiAppURL]];
        sleep(1);
        [[NSWorkspace sharedWorkspace] openURL:[NSURL URLWithString: MunkiNotificationURL]];
        writeToLog(@"Application exiting");
        [NSApp terminate: self];
        return;
    }
    
    // We have Notification Center, create and post our notification
    // Build a localized update count message
    NSString *updateCountMessage = NSLocalizedString(@"1 pending update", @"One Update message");
    NSString *multipleUpdatesFormatString = NSLocalizedString(@"%@ pending updates",
                                                              @"Multiple Update message");
    if (updateCount > 1) {
        updateCountMessage = [NSString stringWithFormat:multipleUpdatesFormatString,
                              [@(updateCount) stringValue]];
    }
    
    // Build a localized force install date message
    NSString *deadlineMessage = nil;
    NSString *deadlineMessageFormatString = NSLocalizedString(@"One or more items must be installed by %@",
                                                              @"Forced Install Date summary");
    if (forcedUpdateDueDate) {
        deadlineMessage = [NSString stringWithFormat:deadlineMessageFormatString,
                           [self stringFromDate: forcedUpdateDueDate]];
    }
    
    // Assemble all our needed notification info
    NSString *title    = NSLocalizedString(@"Software updates available",
                                           @"Software updates available message");
    NSString *subtitle = @"";
    NSString *message  = updateCountMessage;
    if (deadlineMessage) {
        //subtitle = updateCountMessage;
        message = deadlineMessage;
    }
    
    writeToLog(@"sending a notification");
    // deliver the notification
    [self deliverNotificationWithTitle:title
                              subtitle:subtitle
                               message:message
                               options:nil
                                 sound:nil];
}

- (NSString *)stringFromDate:(NSDate *)date
{
    NSDateFormatter *formatter = [NSDateFormatter new];
    formatter.formatterBehavior = NSDateFormatterBehavior10_4;
    formatter.dateStyle = NSDateFormatterShortStyle;
    formatter.timeStyle = NSDateFormatterNoStyle;
    formatter.doesRelativeDateFormatting = YES;
    formatter.formattingContext = NSFormattingContextDynamic;
    return [formatter stringFromDate:date];
}

- (void)deliverNotificationWithTitle:(NSString *)title
                            subtitle:(NSString *)subtitle
                             message:(NSString *)message
                             options:(NSDictionary *)options
                               sound:(NSString *)sound;
{
    UNUserNotificationCenter *center = [UNUserNotificationCenter currentNotificationCenter];
    center.delegate = self;
    // First remove earlier notifications from us
    [center removeAllPendingNotificationRequests];
    [center removeAllDeliveredNotifications];
    // request authorization
    [center requestAuthorizationWithOptions:(UNAuthorizationOptionProvisional + UNAuthorizationOptionAlert)
       completionHandler:^(BOOL granted, NSError * _Nullable error) {
            if (error != nil) {
                NSLog(@"%@", error.localizedDescription);
            }
    }];
    // create notification
    NSString *identifier = @"msc_notification";
    UNMutableNotificationContent *content = [[UNMutableNotificationContent alloc] init];
    content.title = title;
    if (! [subtitle isEqualToString:@""]) content.subtitle = subtitle;
    content.body = message;
    content.userInfo = options;
    if (sound != nil) {
        content.sound = [UNNotificationSound defaultSound];
    }
    UNNotificationRequest *request = [
        UNNotificationRequest requestWithIdentifier:identifier
                              content: content
                              trigger:nil
    ];
    [center addNotificationRequest:request withCompletionHandler:^(NSError * _Nullable error) {
        if (error != nil) {
           NSLog(@"%@", error.localizedDescription);
        }
    }];
    sleep(1);
    writeToLog(@"Application exiting");
    [NSApp terminate: self];
}

// MARK: UNUserNotificationCenterDelegate methods

- (void) userNotificationCenter:(UNUserNotificationCenter *) center
        willPresentNotification:(UNNotification *) notification
          withCompletionHandler:(void (^)(UNNotificationPresentationOptions options)) completionHandler;
{
    completionHandler(UNNotificationPresentationOptionAlert);
}

- (void)userNotificationCenter:(UNUserNotificationCenter *)center didReceiveNotificationResponse:(UNNotificationResponse *)response withCompletionHandler:(void(^)(void))completionHandler
{
    UNNotificationContent * notificationContent = response.notification.request.content;
    [self userActivatedUNUserNotification:notificationContent];
    
}

- (void)userActivatedUNUserNotification:(UNNotificationContent *)notificationContent;
{
    writeToLog(@"In userActivatedNotification:UNNotificationContent");
    NSString *action = notificationContent.userInfo[@"action"];
    NSString *value = notificationContent.userInfo[@"value"];
    
    writeToLog(@"User activated notification:");
    writeToLog(notificationContent.title);
    writeToLog(notificationContent.subtitle);
    writeToLog(notificationContent.body);
    writeToLog(action);
    writeToLog(value);
    
    if ([action isEqualToString:@"open_url"]){
        // this option currently unused
        [[NSWorkspace sharedWorkspace] openURL:[NSURL URLWithString:value]];
    } else {
        // tell MSC app to notify user of updates
        // work around a bug with multiple spaces by opening the
        // app first, sleeping, then telling the app to notify
        [[NSWorkspace sharedWorkspace] openURL:[NSURL URLWithString: MunkiAppURL]];
        sleep(1);
        [[NSWorkspace sharedWorkspace] openURL:[NSURL URLWithString: MunkiNotificationURL]];
    }
    writeToLog(@"Application exiting");
    [NSApp terminate: self];
}

void writeToLog(NSString *message) {
    os_log_t customLog = os_log_create("com.googlecode.munki.munki-notifier", "notifications");
    os_log(customLog, "%{public}s", [message cStringUsingEncoding: NSUTF8StringEncoding]);
}

@end
