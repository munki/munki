//
//  msclog.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 6/6/18.
//  Copyright © 2018 The Munki Project. All rights reserved.
//

import Foundation

func setup_logging() {
    // stub
}

func msc_log(_ source: String, _ event: String, msg: String = "") {
    // stub
    print("\(source): \(event)  \(msg)")
}

func msc_debug_log(_ logMessage: String) {
    // stub
    print(logMessage)
}
