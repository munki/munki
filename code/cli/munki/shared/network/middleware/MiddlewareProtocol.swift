//
//  MiddlewareProtocol.swift
//  munki
//
//  Created by Greg Neagle on 5/10/25.
//  Copyright 2025-2026 The Munki Project. All rights reserved.
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

public struct MunkiMiddlewareRequest {
    var url: String
    var headers: [String: String]
}

public protocol MunkiMiddleware {
    func processRequest(_ request: MunkiMiddlewareRequest) -> MunkiMiddlewareRequest
}

open class MiddlewarePluginBuilder {
    // public init() {}

    open func create() -> MunkiMiddleware {
        fatalError("You have to override this method.")
    }
}
