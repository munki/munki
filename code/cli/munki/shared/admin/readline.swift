//
//  readline.swift
//  munki
//
//  Created by Greg Neagle on 7/13/24.
//

func getInput(prompt: String? = nil, defaultText: String? = nil, addToHistory: Bool = false) -> String? {
    // TODO: better implementation
    var finalPrompt = prompt ?? ""
    if let defaultText {
        finalPrompt = "\(finalPrompt) [\(defaultText)] "
    }
    guard let cString = readline(finalPrompt) else { return nil }
    defer { free(cString) }
    if addToHistory { add_history(cString) }
    let str = String(cString: cString)
    if str.isEmpty {
        return defaultText ?? ""
    } else {
        return str
    }
}
