//
//  MSCTableCellView.swift
//  Managed Software Center
//
//  Created by Steve Küng on 15.10.18.
//  Copyright © 2018-2026 The Munki Project. All rights reserved.
//

import Cocoa

class MSCTableCellView: NSTableCellView {

    @IBOutlet weak var imgView: NSImageView!
    @IBOutlet weak var title: NSTextField!
    @IBOutlet weak var badge: NSButton!
    @IBOutlet weak var spinner: NSProgressIndicator!
    
}
