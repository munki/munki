//
//  StatusWindow.m
//  MunkiStatus
//
//  Created by Steve Küng on 19/12/14.
//  Copyright (c) 2014 MacTech. All rights reserved.
//

#import "StatusWindow.h"

@implementation StatusWindow

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
        [self setBackgroundColor:[NSColor clearColor]];
        [self setMovableByWindowBackground:TRUE];
        [self setStyleMask:NSBorderlessWindowMask];
        [self setHasShadow:YES];
        [self setLevel:NSMainMenuWindowLevel + 1];
    }
    
    return self;
}

- (void) setContentView:(NSView *)aView
{
    aView.wantsLayer            = YES;
    aView.layer.frame           = aView.frame;
    aView.layer.cornerRadius    = 5.0;
    aView.layer.masksToBounds   = YES;
    
    [super setContentView:aView];
}


@end
