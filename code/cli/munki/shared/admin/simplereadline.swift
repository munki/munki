//
//  simplereadline.swift
//  munki
//
//  Simple replacement for readline functionality without system dependencies
//

import Foundation

/// Simple replacement for readline functionality
func getInput(prompt: String? = nil, defaultText: String? = nil) -> String? {
    if let prompt = prompt {
        print(prompt, terminator: "")
    }
    
    if let defaultText = defaultText, !defaultText.isEmpty {
        print("[\(defaultText)] ", terminator: "")
    }
    
    guard let input = readLine() else {
        return nil
    }
    
    // If input is empty and we have default text, return the default
    if input.isEmpty && defaultText != nil {
        return defaultText
    }
    
    return input
}

/// Simple cleanup function - no-op for simple implementation
func cleanupReadline() {
    // No-op for simple implementation
}
