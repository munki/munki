//
//  SystemConfigurationInterface.m
//  MunkiStatus
//
//  Created by Greg Neagle on 4/23/09.

#import <Foundation/Foundation.h>
#import <AppKit/AppKit.h>
#import <SystemConfiguration/SystemConfiguration.h>
#import "SystemConfigurationInterface.h"

@implementation NSApplication (ASKAMultiLanguage)

- (NSString *)consoleUser
{
	CFStringRef		cfuser = NULL;
	NSString		*username;
    
    cfuser = SCDynamicStoreCopyConsoleUser( NULL, NULL, NULL );
        
    if ( cfuser != NULL ) {
		username = [ ( NSString * )cfuser retain ];
		CFRelease( cfuser );
    } else {
		username = @"";
	}
	return username;
}

@end
