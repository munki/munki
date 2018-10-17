//
//  MSWindow.swift
//  MunkiStatus
//
//  Created by Steve Küng on 16.10.18.
//  Copyright © 2018 The Munki Project. All rights reserved.
//

import Cocoa

class MSWindow: NSWindow {
    override var canBecomeKey: Bool {
        return true
    }
}
