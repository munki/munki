//
//  configure.swift
//  munki
//
//  Created by Greg Neagle on 9/27/24.
//

import Foundation

///  Gets configuration options and saves them to preferences store
func configure(promptList: [(String, String)]) {
    var editedPrefs = PlistDict()
    for (key, prompt) in promptList {
        let newValue = getInput(
            prompt: prompt + ": ",
            defaultText: adminPref(key) as? String ?? ""
        )
        editedPrefs[key] = newValue
    }
    for (key, value) in editedPrefs {
        setAdminPref(key, value)
    }
}
