//
//  errors.swift
//  munki
//
//  Created by Greg Neagle on 7/15/24.
//
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

/// General error class for Munki errors
class MunkiError: Error, CustomStringConvertible {
    private let message: String

    // Creates a new error with the given message.
    public init(_ message: String) {
        self.message = message
    }

    public var description: String {
        return message
    }
}

/// Ensures we can return a useful localizedError
extension MunkiError: LocalizedError {
    var errorDescription: String? {
        return message
    }
}

/// an exception to throw when user cancels
struct UserCancelled: Error {
    // nothing special
}
