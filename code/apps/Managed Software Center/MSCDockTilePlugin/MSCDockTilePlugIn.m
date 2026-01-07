/*

   File: MSCDockTilePlugIn.m
 
   Copyright © 2015-2026 The Munki Project
   Liberally adapted from Apple sample code:
   https://developer.apple.com/library/mac/samplecode/DockTile/Listings/DockTilePlugIn_DockTilePlugIn_h.html
 
   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at
 
   https://www.apache.org/licenses/LICENSE-2.0
 
   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.

*/

#import "MSCDockTilePlugIn.h"

@implementation MSCDockTilePlugIn

@synthesize updateObserver;

static void updateCount(NSDockTile *tile) {
    CFPreferencesAppSynchronize(CFSTR("ManagedInstalls"));
    NSInteger count = CFPreferencesGetAppIntegerValue(CFSTR("PendingUpdateCount"), CFSTR("ManagedInstalls"), NULL);
    if (count) {
        [tile setBadgeLabel:[NSString stringWithFormat:@"%ld", (long)count]];
    } else {
        [tile setBadgeLabel: nil];
    }
}

- (void)setDockTile:(NSDockTile *)dockTile {
    if (dockTile) {
        // Attach an observer that will update the count in the dock tile whenever it changes
	    self.updateObserver = [[NSDistributedNotificationCenter defaultCenter] addObserverForName:@"com.googlecode.munki.managedsoftwareupdate.dock.updateschanged" object:nil queue:nil usingBlock:^(NSNotification *notification) {
	    updateCount(dockTile);	// Note that this block captures (and retains) dockTile for use later. Also note that it does not capture self, which means -dealloc may be called even while the notification is active. Although it's not clear this needs to be supported, this does eliminate a potential source of leaks.
	}];
        updateCount(dockTile);	// Make sure count is updated as soon as we are invoked
    } else {
        // Strictly speaking this may not be necessary (since the plug-in may be terminated when it's removed from the dock),
        /// but it's good practice
        [[NSDistributedNotificationCenter defaultCenter] removeObserver:self.updateObserver];
	self.updateObserver = nil;
    }
}

- (void)dealloc {
    if (self.updateObserver) {
	    [[NSDistributedNotificationCenter defaultCenter] removeObserver:self.updateObserver];
	    self.updateObserver = nil;
    }
    //[super dealloc];
}

@end
