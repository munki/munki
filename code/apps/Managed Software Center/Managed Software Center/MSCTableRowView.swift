//
//  MSCTableRowView.swift
//  Managed Software Center
//
//  Created by Steve Küng on 14.10.18.
//  Copyright © 2018-2026 The Munki Project. All rights reserved.
//

import Cocoa

class MSCTableRowView: NSTableRowView {

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)

        // Drawing code here.
    }
    
    override var isEmphasized: Bool {
        set {}
        get {
            return false;
        }
    }
}
