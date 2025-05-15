//
//  s3Middleware.swift
//  s3Middleware
//
//  Created by Greg Neagle on 5/10/25.
//

import Foundation

class s3Middleware: MunkiMiddleware {
    func processRequest(_ request: MunkiMiddlewareRequest) -> MunkiMiddlewareRequest {
        var modifiedRequest = request
        modifiedRequest.headers["X-Custom-Header-Hello"] = "Hello, World!"
        return modifiedRequest
    }
}

// MARK: dylib "interface"

/// Function with C calling style for our dylib. We use it to instantiate the Repo object and return an instance
@_cdecl("createPlugin")
public func createPlugin() -> UnsafeMutableRawPointer {
    return Unmanaged.passRetained(MWA2APIRepoBuilder()).toOpaque()
}

final class MWA2APIRepoBuilder: MiddlewarePluginBuilder {
    override func create() -> MunkiMiddleware {
        return s3Middleware()
    }
}
