//
//  repoutils.swift
//  munki
//
//  Created by Greg Neagle on 7/15/24.
//

import Foundation

// TODO: get rid of this
/// Returns a list of items of kind. Relative pathnames are prepended
/// with kind. (example: ["icons/Bar.png", "icons/Foo.png"])
/// Could throw RepoError
func listItemsOfKind(_ repo: Repo, _ kind: String) throws -> [String] {
    let itemlist = try repo.list(kind)
    return itemlist.map(
        { (kind as NSString).appendingPathComponent($0) }
    )
}
