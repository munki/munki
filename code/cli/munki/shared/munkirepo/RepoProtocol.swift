//
//  RepoProtocol.swift
//  munki
//
//  Created by Greg Neagle on 5/8/25.
//

import Foundation

/// Defines methods all repo classes must implement
protocol Repo {
    init(_ url: String) throws
    func list(_ kind: String) throws -> [String]
    func get(_ identifier: String) throws -> Data
    func get(_ identifier: String, toFile local_file_path: String) throws
    func put(_ identifier: String, content: Data) throws
    func put(_ identifier: String, fromFile local_file_path: String) throws
    func delete(_ identifier: String) throws
    func pathFor(_ identifier: String) -> String?
}
