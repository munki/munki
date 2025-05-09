//
//  RepoProtocol.swift
//  munki
//
//  Created by Greg Neagle on 5/8/25.
//

import Foundation

/// Defines methods all repo classes must implement
public protocol Repo {
    init(_ url: String) throws
    func list(_ kind: String) async throws -> [String]
    func get(_ identifier: String) async throws -> Data
    func get(_ identifier: String, toFile local_file_path: String) async throws
    func put(_ identifier: String, content: Data) async throws
    func put(_ identifier: String, fromFile local_file_path: String) async throws
    func delete(_ identifier: String) async throws
    func pathFor(_ identifier: String) -> String?
}

open class RepoPluginBuilder {
    public init() {}

    open func connect(_: String) -> Repo? {
        fatalError("You have to override this method.")
    }
}
