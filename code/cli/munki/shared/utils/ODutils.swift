//
//  ODutils.swift
//  munki
//
//  Created by Greg Neagle on 9/8/24.
//  Copyright 2024-2026 The Munki Project. All rights reserved.
//
//  Licensed under the Apache License, Version 2.0 (the "License");
//  you may not use this file except in compliance with the License.
//  You may obtain a copy of the License at
//
//       https://www.apache.org/licenses/LICENSE-2.0
//
//  Unless required by applicable law or agreed to in writing, software
//  distributed under the License is distributed on an "AS IS" BASIS,
//  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
//  See the License for the specific language governing permissions and
//  limitations under the License.

import Foundation
import OpenDirectory

/// Returns local DS node
func localDSNode() -> ODNode? {
    do {
        return try ODNode(session: ODSession.default(), name: "/Local/Default")
    } catch {
        return nil
    }
}

/// Returns a user record for userName
func getUserRecord(_ userName: String) -> ODRecord? {
    if let node = localDSNode() {
        do {
            return try node.record(withRecordType: kODRecordTypeUsers, name: userName, attributes: nil)
        } catch {
            // if the record doesn't exist it throws, so nothing special to do
            return nil
        }
    }
    return nil
}

/// Returns GeneratedUID value for userName
func getGeneratedUID(_ userName: String) -> String {
    if let userRecord = getUserRecord(userName),
       let values = try? userRecord.values(
           forAttribute: "dsAttrTypeStandard:GeneratedUID"
       ) as? [String],
       !values.isEmpty
    {
        return values[0]
    }
    return ""
}
