//
//  readline.swift
//  munki
//
//  Created by Greg Neagle on 7/13/24.
//

import Foundation

/// This is a function that is called by our custom signal handlers that react to SIGINT or SIGTERM.
/// Wtihout this, the terminal can be a mess if someone hits Control-C to interrupt the process while
/// `readline` is waiting for input
func cleanupReadline() {
    if rl_line_buffer != nil {
        rl_free_line_state()
        rl_cleanup_after_signal()
        rl_deprep_terminal()
        // Make sure we are on a new line
        print()
    }
}

/// This lets us use the libedit readline emulation to provide editable input --
/// for example in `munkiimport`, after analyzing the installer item, suggestions are made for
/// item name, etc that the user can accept or edit before hitting return. If this was the GNU readline
/// library, we'd register a `rl_startup_hook` or `rl_pre_input_hook` function that added
/// the default value/text to the input buffer. But due to bugs in the libedit readline emulation in macOS,
/// I could never get this to work (either from Python or from Swift), so instead we set up a delayed thread
/// to insert the prompt and default text _after_ we fire up _readline_. Like I said, a nasty hack.
func getInput(prompt: String? = nil, defaultText: String? = nil) -> String? {
    // A really awful hack to get default text since
    // the readline implmentation is so broken
    let queue = OperationQueue()
    let insertOperation = BlockOperation {
        usleep(10000) // 0.01 seconds
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
