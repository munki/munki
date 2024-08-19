//
//  analyze.swift
//  munki
//
//  Created by Greg Neagle on 8/19/24.
//

import Foundation

func itemInInstallInfo(_ thisItem: PlistDict, theList: [PlistDict], version: String = "") -> Bool {
    // Determines if an item is in a list of processed items.
    //
    // Returns true if the item has already been processed (it's in the list)
    // and, optionally, the version is the same or greater.
    for listItem in theList {
        if let listItemName = listItem["name"] as? String,
           let thisItemName = thisItem["name"] as? String
        {
            if listItemName == thisItemName {
                if version.isEmpty {
                    return true
                }
                // if the version already installed or processed to be
                // installed is the same or greater, then we're good.
            }
        }
    }
    return false
}
