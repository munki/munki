//
//  NSWindow+Window.m
//  MunkiStatus
//
//  Created by Küng, Steve (tpc) on 18/12/14.
//  Copyright (c) 2014 MacTech. All rights reserved.
//

#import "Window.h"

@implementation Window

-(BOOL)canBecomeKeyWindow
{
    return YES;
}

- (id)initWithContentRect:(NSRect)contentRect styleMask:(NSUInteger)aStyle backing:(NSBackingStoreType)bufferingType defer:(BOOL)flag
{
    self = [super initWithContentRect:contentRect styleMask:NSBorderlessWindowMask backing:bufferingType defer:flag];
    
    if ( self )
    {
        [self setOpaque:NO];
        //[self setBackgroundColor:[NSColor clearColor]];
        [self setMovableByWindowBackground:TRUE];
        [self setStyleMask:NSBorderlessWindowMask];
        [self setHasShadow:YES];
        [self setLevel:NSMainMenuWindowLevel + 1];
    }
    
    return self;
}

@end
