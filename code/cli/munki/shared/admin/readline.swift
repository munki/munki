//
//  readline.swift
//  munki
//
//  Created by Greg Neagle on 7/13/24.
//

import Foundation

func getInput(prompt: String? = nil, defaultText: String? = nil) -> String? {
    // A really awful hack to get default text since
    // the readline implmentation is so broken
    let queue = OperationQueue()
    let insertOperation = BlockOperation {
        usleep(10000)
        rl_set_prompt(prompt ?? "")
        if let defaultText {
            rl_insert_text(defaultText)
        }
        rl_forced_update_display()
    }
    queue.addOperation(insertOperation)

    guard let cString = readline("") else { return nil }
    defer { free(cString) }
    return String(cString: cString)
}
