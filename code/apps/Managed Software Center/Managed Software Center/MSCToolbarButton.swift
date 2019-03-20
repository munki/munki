//
//  MSCToolbarButton.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 5/27/18.
//  Copyright © 2018-2019 The Munki Project. All rights reserved.
//

import Cocoa

class MSCToolbarButton: NSButton {
    // Subclass of NSButton which properly works inside of a toolbar item
    // to allow clicking on the label.
    override func hitTest(_ point: NSPoint) -> NSView? {
        let view = super.hitTest(point)
        if (view == nil && self.superview != nil) {
            for v in self.superview!.subviews {
                if (v != self && v.hitTest(point) != nil) {
                    return self
                }
            }
        }
        return view
    }
}

class MSCToolbarButtonCell: NSButtonCell {
    // Subclass of NSButtonCell which properly works inside of a toolbar item
    // to allow clicking on the label.
    override func hitTest(for event: NSEvent, in cellFrame: NSRect, of controlView: NSView) -> NSCell.HitResult {
        let aPoint = controlView.superview!.convert(event.locationInWindow, from: nil)
        if controlView.superview != nil {
            for v in controlView.superview!.subviews {
                if v.hitTest(aPoint) != nil {
                    return NSCell.HitResult.contentArea
                }
            }
        }
        return NSCell.HitResult(rawValue: 0) // why is there no NSCell.HitResult.none ?!
    }
}
