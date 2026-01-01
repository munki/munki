//
//  HtmlFilter.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 6/15/18.
//  Copyright © 2018-2026 The Munki Project. All rights reserved.
//

import Foundation

func filtered_html(_ text: String, filter_images: Bool = false) -> String {
    // Filters HTML and HTML fragments for use inside description paragraphs
    
    func containsTags(_ text: String) -> Bool {
        do {
            let regex = try NSRegularExpression(pattern: "<[^<]*>",
                                                options: .caseInsensitive)
            let numberOfMatches = regex.numberOfMatches(
                in: text, options: [], range: NSMakeRange(0, text.count))
            return (numberOfMatches > 0)
        } catch {
            return false
        }
    }
    
    func containsEntities(_ text: String) -> Bool {
        do {
            let regex = try NSRegularExpression(pattern: "&[^&<>]+;",
                                                options: .caseInsensitive)
            let numberOfMatches = regex.numberOfMatches(
                in: text, options: [], range: NSMakeRange(0, text.count))
            return (numberOfMatches > 0)
        } catch {
            return false
        }
    }
    
    func replaceHTMLStartTags(_ tag: String,
                              with replacement: String,
                              inString aString: String) -> String {
        return aString.replacingOccurrences(of: "(?i)<\(tag)\\b[^<]*>",
            with: replacement,
            options: .regularExpression,
            range: nil)
    }
    
    func replaceHTMLEndTags(_ tag: String,
                            with replacement: String,
                            inString aString: String) -> String {
        return aString.replacingOccurrences(of: "</\(tag)>",
            with: replacement,
            options: .regularExpression,
            range: nil)
    }
    
    func deleteHTMLTags(_ tag: String, inString aString: String) -> String {
        return aString.replacingOccurrences(of: "(?i)</?\(tag)\\b[^<]*>",
            with: "",
            options: .regularExpression,
            range: nil)
    }
    
    func deleteHTMLElements(_ tag: String, inString aString: String) -> String {
        return aString.replacingOccurrences(of: "(?i)<\(tag)[\\V\\n\\r]*<\\/\(tag)>",
            with: "",
            options: .regularExpression,
            range: nil)
    }
    
    if !(containsTags(text) || containsEntities(text)) {
        let replacements = [
            ["&", "&amp;"],
            ["<", "&lt;"],
            [">", "&gt;"],
            ["\n", "<br>\n"]
        ]
        var mutable_text = text
        for item in replacements {
            mutable_text = mutable_text.replacingOccurrences(
                of: item[0], with: item[1])
        }
        return mutable_text
    }
    
    let delete_elements = ["script", "style", "head", "table", "form"]
    var delete_tags = ["!DOCTYPE", "html", "body"]
    let transform_tags = [
        "ul": ["<br>", "<br>"],
        "ol": ["<br>", "<br>"],
        "li": ["&nbsp;&nbsp;&bull; ", "<br>"],
        "h1": ["<strong>", "</strong><br>"],
        "h2": ["<strong>", "</strong><br>"],
        "h3": ["<strong>", "</strong><br>"],
        "h4": ["<strong>", "</strong><br>"],
        "h5": ["<strong>", "</strong><br>"],
        "h6": ["<strong>", "</strong><br>"],
        "p":  ["", "<br>"]
    ]
    
    if filter_images {
        delete_tags.append("img")
    }
    var mutable_text = text
    for element in delete_elements {
        mutable_text = deleteHTMLElements(element, inString: mutable_text)
    }
    for tag in delete_tags {
        mutable_text = deleteHTMLTags(tag, inString: mutable_text)
    }
    for (tag, replacements) in transform_tags {
        if replacements.count == 2 {
            mutable_text = replaceHTMLStartTags(tag,  with: replacements[0], inString: mutable_text)
            mutable_text = replaceHTMLEndTags(tag, with: replacements[1], inString: mutable_text)
        }
    }
    return mutable_text.trimmingCharacters(in: .whitespacesAndNewlines)
}
