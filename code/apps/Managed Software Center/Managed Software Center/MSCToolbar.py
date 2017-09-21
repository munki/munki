# encoding: utf-8
#
#  MSCToolbar
#  Managed Software Center
#
#  Created by Daniel Hazelbaker on 9/2/14.
#

# builtin super doesn't work with Cocoa classes in recent PyObjC releases.
from objc import super

from objc import YES, NO, nil
#from Foundation import *
#from AppKit import *
# pylint: disable=wildcard-import
from CocoaWrapper import *
# pylint: enable=wildcard-import



class MSCToolbarButton(NSButton):
    '''Subclass of NSButton which properly works inside of a toolbar item
        to allow clicking on the label.'''

    def hitTest_(self, aPoint):
        view = super(MSCToolbarButton, self).hitTest_(aPoint)

        if view == nil:
            for v in self.superview().subviews():
                if v != self and v.hitTest_(aPoint) != nil:
                    view = self
                    break
        
        return view


class MSCToolbarButtonCell(NSButtonCell):
    '''Subclass of NSButtonCell which properly works inside of a toolbar item
        to allow clicking on the label.'''

    def _hitTestForTrackMouseEvent_inRect_ofView_(self, theEvent,
                                                  rect, controlView):
        aPoint = controlView.superview().convertPoint_fromView_(
            theEvent.locationInWindow(), nil)
        hit = NO

        for v in controlView.superview().subviews():
            if v.hitTest_(aPoint) != nil:
                hit = YES
                break

        return hit


