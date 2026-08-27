//
//  MSCWebView.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 9/9/18.
//  Copyright © 2018-2026 The Munki Project. All rights reserved.
//

import WebKit

class MSCWebView: WKWebView {
    //Subclass of WKWebView that exists solely to customize the contextual menus.
    
    override func willOpenMenu(_ menu: NSMenu, with event: NSEvent) {
        let removedIds = [
            "WKMenuItemIdentifierOpenLinkInNewWindow",
            "WKMenuItemIdentifierDownloadLinkedFile",
            "WKMenuItemIdentifierOpenImageInNewWindow",
            "WKMenuItemIdentifierDownloadImage",
        ]
        for menuItem in menu.items {
            //print(menuItem.identifier?.rawValue ?? "")
            if let menuItemId = menuItem.identifier?.rawValue {
                if removedIds.contains(menuItemId) {
                    menuItem.isHidden = true
                }
            }
        }
    }
    
    override func mouseDown(with mouseDownEvent: NSEvent) {
        guard let window = self.window else {
            return super.mouseDown(with: mouseDownEvent)
        }
        let startingPoint = mouseDownEvent.locationInWindow
        var fullSizeContentViewNoContentAreaHeight : CGFloat = 32.0
        if let windowFrameHeight = window.contentView?.frame.height {
            let contentLayoutRectHeight = window.contentLayoutRect.height
            fullSizeContentViewNoContentAreaHeight = windowFrameHeight - contentLayoutRectHeight
        }
        if startingPoint.y < window.frame.height - fullSizeContentViewNoContentAreaHeight {
            return super.mouseDown(with: mouseDownEvent)
        }
        
        // Track events until the mouse is up (in which we interpret as a click), or a drag starts (in which we pass off to the Window Server to perform the drag)
        var shouldCallSuper = false
        
        // trackEvents won't return until after the tracking all ends
        window.trackEvents(matching: [.leftMouseDragged, .leftMouseUp], timeout:NSEvent.foreverDuration, mode: RunLoop.Mode.default) { event, stop in
            switch event?.type {
                case .leftMouseUp:
                    // Stop on a mouse up; post it back into the queue and call super so it can handle it
                    shouldCallSuper = true
                    NSApp.postEvent(event!, atStart: false)
                    stop.pointee = true
                
                case .leftMouseDragged:
                    // track mouse drags, and if more than a few points are moved we start a drag
                    let currentPoint = event!.locationInWindow
                    if (abs(currentPoint.x - startingPoint.x) >= 5 || abs(currentPoint.y - startingPoint.y) >= 5) {
                        stop.pointee = true
                        window.performDrag(with: event!)
                    }
                
                default:
                    break
            }
        }
                
        if (shouldCallSuper) {
            super.mouseDown(with: mouseDownEvent)
        }
    }

}
