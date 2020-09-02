//
//  MSWindow.swift
//  MunkiStatus
//
//  Created by Steve Küng on 11.03.20.
//  Copyright © 2020 The Munki Project. All rights reserved.
//

import Cocoa

class MSWindow: NSWindow {
    override var canBecomeKey: Bool {
        return true
    }
}
