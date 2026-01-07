//
//  Template.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 6/15/18.
//  Copyright © 2018-2026 The Munki Project. All rights reserved.
//

// A lightweight Swift implementation of something like Python's string.Template
// for MSC's needs. Supports only "${identifier}"-style placeholders and
// not $identifier -style placeholders.

import Foundation

class Template {
    let text: String
    
    init(_ the_text: String) {
        text = the_text
    }
    
    func substitute(_ substitutions: BaseItem) -> String {
        var mutable_text = text
        for key in substitutions.keys {
            if let value = substitutions[key] {
                let description = String(describing: value)
                mutable_text = mutable_text.replacingOccurrences(of: "${\(key)}", with: description)
            }
        }
        /*// find any remaining variables and try to look them up
        if let regex = try? NSRegularExpression(pattern: "\\$\\{[^}]*\\}") {
            let string = mutable_text as NSString
            let keys = Set(
                regex.matches(in: string as String,
                              options: [],
                              range: NSMakeRange(0, string.length)).map
                    { string.substring(with: $0.range).trimmingCharacters(in: CharacterSet(charactersIn:"${})")) }
            )
            for key in keys {
                if let value = substitutions[key] {
                    
                    let description = String(describing: value)
                    mutable_text = mutable_text.replacingOccurrences(of: "${\(key)}", with: description)
                }
            }
        }*/
        return mutable_text
    }
}
