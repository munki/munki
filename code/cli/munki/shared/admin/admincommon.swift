//
//  admincommon.swift
//  munki
//
//  Created by Greg Neagle on 6/27/24.
//

import Foundation

let ADMIN_BUNDLE_ID = "com.googlecode.munki.munkiimport" as CFString

func adminPref(_ pref_name: String) -> Any? {
    /* Return an admin preference. Since this uses CFPreferencesCopyAppValue,
     Preferences can be defined several places. Precedence is:
     - MCX/configuration profile
     - ~/Library/Preferences/ByHost/com.googlecode.munki.munkiimport.XXXXXX.plist
     - ~/Library/Preferences/com.googlecode.munki.munkiimport.plist
     - /Library/Preferences/com.googlecode.munki.munkiimport.plist
     - .GlobalPreferences defined at various levels (ByHost, user, system)
     But typically these preferences are _not_ managed and are stored in the
     user's preferences (~/Library/Preferences/com.googlecode.munki.munkiimport.plist)
     */
    return CFPreferencesCopyAppValue(pref_name as CFString, ADMIN_BUNDLE_ID)
}

func listItemsOfKind(_ repo: Repo, _ kind: String) throws -> [String] {
    // Returns a list of items of kind. Relative pathnames are prepended
    // with kind. (example: ["icons/Bar.png", "icons/Foo.png"])
    // Could throw RepoError
    let itemlist = try repo.list(kind)
    return itemlist.map(
        { (kind as NSString).appendingPathComponent($0) }
    )
}
