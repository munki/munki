//
//  tokenize.swift
//  munki
//
//  Created by Greg Neagle on 5/30/25.
//  Copyright 2025-2026 The Munki Project. All rights reserved.
//

/// Simple function to parse a string and return tokens similar to the way shells parse lines
/// handles '\' escaping and single and double quotes
func tokenize(_ input: String) -> [String] {
    var tokens = [String]()
    var currentToken = ""
    var escaping = false
    var quoted = ""

    for char in input {
        if escaping {
            escaping = false
            currentToken.append(char)
            continue
        }
        if char == "\\", quoted.isEmpty, escaping == false {
            escaping = true
            continue
        }
        if "\"'".contains(char) {
            if quoted.isEmpty {
                quoted = String(char)
                continue
            }
            if quoted == String(char) {
                // we found the matching quote
                tokens.append(currentToken)
                currentToken = ""
                quoted = ""
                continue
            }
        }
        if char == " " {
            if !quoted.isEmpty {
                currentToken.append(char)
                continue
            }
            if !currentToken.isEmpty {
                tokens.append(currentToken)
                currentToken = ""
            }
            continue
        }
        // default action
        currentToken.append(char)
    }
    // end of line; handle remaining (partial?) token
    if !currentToken.isEmpty {
        if quoted.isEmpty {
            tokens.append(currentToken)
        } else {
            // should throw a parsing error
        }
    }
    return tokens
}
