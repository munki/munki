//
//  StatusWindowView.m
//  MunkiStatus
//
//  Created by Steve Küng on 19/12/14.
//  Copyright (c) 2014 MacTech. All rights reserved.
//

#import "StatusWindowView.h"

@implementation StatusWindowView

- (void)drawRect:(NSRect)dirtyRect {
    [super drawRect:dirtyRect];
    
    [[NSColor windowBackgroundColor] set];
    NSRectFill(dirtyRect);
}

@end
