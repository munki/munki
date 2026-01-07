//
//  MainSplitViewController.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 6/25/25.
//  Copyright © 2025-2026 The Munki Project. All rights reserved.
//

import Cocoa

class MainSplitViewController: NSSplitViewController {
    
    //MARK: NSSplitViewDelegate methods
    
    // prevent sidebar from being arbitrarily resized
    override func splitView(
        _ splitView: NSSplitView,
        constrainSplitPosition proposedPosition: CGFloat,
        ofSubviewAt dividerIndex: Int
    ) -> CGFloat
    {
        return NSSplitViewItem.unspecifiedDimension
    }
    
    // prevent resize cursor from displaying since our sidebar is not resizable
    override func splitView(_ splitView: NSSplitView, effectiveRect proposedEffectiveRect: NSRect, forDrawnRect drawnRect: NSRect, ofDividerAt dividerIndex: Int) -> NSRect {
        return .zero
    }
}
