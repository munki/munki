//
//  main.swift
//  munkitester
//
//  Created by Greg Neagle on 6/25/24.
//

// this is a temporary target to use to test things

import Foundation
import AppKit

DisplayOptions.verbose = 10

let logger = DisplayAndLog.main
logger.level = 4

logger.debug("test debug message")
logger.detail("test detail message")
logger.info("test info message")
logger.warning("test warning message")
logger.error("test error message")
