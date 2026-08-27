//
//  passwdutil.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 6/29/18.
//  Copyright © 2018-2026 The Munki Project. All rights reserved.
//

import Foundation
import OpenDirectory

func findODuserRecords(username: String, nodename: String = "/Search") throws -> [ODRecord] {
    // Uses OpenDirectory methods to find user records for username
    let searchNode = try ODNode(session: ODSession.default(), name: nodename)
    let query = try ODQuery(node: searchNode,
                            forRecordTypes: kODRecordTypeUsers,
                            attribute: kODAttributeTypeRecordName,
                            matchType: ODMatchType(kODMatchEqualTo),
                            queryValues: username,
                            returnAttributes: kODAttributeTypeAllAttributes,
                            maximumResults: 0)
    return (try query.resultsAllowingPartial(false) as! [ODRecord])
}

func findODuserRecord(username: String, nodename: String = "/Search") -> ODRecord? {
    // Returns first record found for username, or nil if not found
    do {
        let records = try findODuserRecords(username: username)
        if records.isEmpty {
            return nil
        }
        return records[0]
    } catch {
        return nil
    }
}

func verifyODPassword(username: String, password: String) -> Bool {
    // Uses OpenDirectory methods to verify password for username
    // returns false if invalid username or wrong password for valid username,
    // true otherwise
    if let userRecord = findODuserRecord(username: username) {
        do {
            try userRecord.verifyPassword(password)
            return true
        } catch {
            return false
        }
    }
    return false
}
