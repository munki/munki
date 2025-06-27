//
//  MainSplitViewController.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 6/25/25.
//  Copyright © 2025 The Munki Project. All rights reserved.
//

import Cocoa

class MainSplitViewController: NSSplitViewController {
    
    var sidebarWidth: CGFloat = 0.0
    
    //MARK: NSSplitViewDelegate methods
    
    // prevent sidebar from being arbitrarily resized
    override func splitView(
        _ splitView: NSSplitView,
        constrainSplitPosition proposedPosition: CGFloat,
        ofSubviewAt dividerIndex: Int
    ) -> CGFloat
    {
        if sidebarWidth != 0 {
            return sidebarWidth
        }
        return proposedPosition
    }
}
