//
//  MiddlewareFactory.swift
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

/// Loads a Middleware plugin from a dylib
/// implementation lifted from
/// https://theswiftdev.com/building-and-loading-dynamic-libraries-at-runtime-in-swift/
private func loadMiddlewarePlugin(at path: String) throws -> MiddlewarePluginBuilder {
    typealias InitFunction = @convention(c) () -> UnsafeMutableRawPointer

    let openRes = dlopen(path, RTLD_NOW | RTLD_LOCAL)
    if openRes != nil {
        defer {
            dlclose(openRes)
        }

        let symbolName = "createPlugin"
        let sym = dlsym(openRes, symbolName)

        if sym != nil {
            let f: InitFunction = unsafeBitCast(sym, to: InitFunction.self)
            let pluginPointer = f()
            let builder = Unmanaged<MiddlewarePluginBuilder>.fromOpaque(pluginPointer).takeRetainedValue()
            return builder
        } else {
            throw MunkiError("Could not find symbol \(symbolName) in lib: \(path)")
        }
    } else {
        if let err = dlerror() {
            throw MunkiError("Error opening lib: \(String(format: "%s", err)), path: \(path)")
        } else {
            throw MunkiError("Error opening lib: unknown error, path: \(path)")
        }
    }
}

/// Try to load a middleware plugin from our MiddlewarePlugins directory
func loadMiddlewarePlugin() throws -> MunkiMiddleware? {
    let pluginExt = ".plugin"
    let pluginsDir = (Bundle.main.bundlePath as NSString).appendingPathComponent("middleware")
    let filenames = (try? FileManager.default.contentsOfDirectory(atPath: pluginsDir)) ?? []
    for filename in filenames {
        if filename.hasSuffix(pluginExt) {
            let pluginPath = (pluginsDir as NSString).appendingPathComponent(filename)
            let repoPlugin = try loadMiddlewarePlugin(at: pluginPath)
            return repoPlugin.create()
        }
    }
    return nil
}
