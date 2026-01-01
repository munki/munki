//
//  RepoFactory.swift
//  munki
//
//  Created by Greg Neagle on 6/29/24.
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

/// Loads a Repo plugin from a dylib
/// implementation lifted from
/// https://theswiftdev.com/building-and-loading-dynamic-libraries-at-runtime-in-swift/
private func loadRepoPlugin(at path: String) throws -> RepoPluginBuilder {
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
            let builder = Unmanaged<RepoPluginBuilder>.fromOpaque(pluginPointer).takeRetainedValue()
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

/// Try to load a Repo plugin from our RepoPlugins directory
func findRepoInPlugins(_ name: String, url: String) throws -> Repo? {
    let pluginName = name + ".plugin"
    let repoPluginsDir = (Bundle.main.bundlePath as NSString).appendingPathComponent("repoplugins")
    let repoPluginNames = (try? FileManager.default.contentsOfDirectory(atPath: repoPluginsDir)) ?? []
    if repoPluginNames.contains(pluginName) {
        let pluginPath = (repoPluginsDir as NSString).appendingPathComponent(pluginName)
        let repoPlugin = try loadRepoPlugin(at: pluginPath)
        return repoPlugin.connect(url)
    }
    return nil
}

/// Factory function that returns an instance of a specific Repo class
func repoConnect(url: String, plugin: String = "FileRepo") throws -> Repo {
    switch plugin {
    case "FileRepo":
        return try FileRepo(url)
    case "GitFileRepo":
        return try GitFileRepo(url)
    default:
        if let repo = try findRepoInPlugins(plugin, url: url) {
            return repo
        }
        throw MunkiError("No repo plugin named \"\(plugin)\"")
    }
}
