//
//  osinstaller.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 8/25/22.
//  Copyright © 2022-2026 The Munki Project. All rights reserved.
//

import AppKit
import Foundation

// functions to determine if the current user is a volume owner

func volumeOwnerUUIDs() -> [String] {
    // returns a list of local account volume owner UUIDs
    var cryptousers = [String: Any]()
    let output = exec(
        "/usr/sbin/diskutil", args: ["apfs", "listUsers", "/", "-plist"])
    do {
        try cryptousers = readPlistFromString(output) as? [String: Any] ?? [String: Any]()
    } catch {
        // do nothing. cryptousers is empty
    }
    // get value of "users" from the diskutil dict
    let users = cryptousers["Users"] as? [[String:Any]] ?? [[String:Any]]()
    // filter to keep only local user accounts
    let localVolumeOwners = users.filter(
        { $0["APFSCryptoUserType"] as? String ?? "" == "LocalOpenDirectory"
            && $0["VolumeOwner"] as? Bool ?? false}
    )
    // return a list of UUIDs
    return localVolumeOwners.map({ $0["APFSCryptoUserUUID"] as? String ?? "" })
}

func generatedUID(_ username: String) -> String {
    // returns the GeneratedUID for a local account
    if let userRecord = findODuserRecord(
        username: username, nodename: "/Local/Default") {
        do {
            let values = try userRecord.values(
                forAttribute: "dsAttrTypeStandard:GeneratedUID")
            if let guidList = values as? [String] {
                if !(guidList.isEmpty) {
                    return guidList[0]
                }
            }
        } catch {
            // do nothing, fall through to return an empty string
        }
    }
    return ""
}

func userIsVolumeOwner(_ username: String) -> Bool {
    // is username a volume owner (of /)?
    return volumeOwnerUUIDs().contains(generatedUID(username))
}

func currentUserIsVolumeOwner() -> Bool {
    return userIsVolumeOwner(NSUserName())
}
