//
//  dictutils.swift
//  munki
//
//  Created by Greg Neagle on 6/11/26.
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

/// A function to basicially replicate this Python behavior:
/// let foo = dict.get("foo") or "bar"
/// Where foo is assigned the value of dict["foo"] if it is defined and not "false-ish" (like an empty string)
/// otherwise foo is assigned the value "bar"
/// Unlike the Python version, this specific implementation only works with Strings
func stringValue(from dict: [String: Any], for key: String, fallback: String = "") -> String {
    if let value = dict[key] as? String, !value.isEmpty {
        return value
    }
    return fallback
}

/// Dictionary extension version of the above function
extension Dictionary {
    func getString(for key: Key, fallback: String = "") -> String {
        if let value = self[key] as? String, !value.isEmpty {
            return value
        }
        return fallback
    }
}
