//
//  RepoFactory.swift
//  munki
//
//  Created by Greg Neagle on 6/29/24.
//

import Foundation

func repoConnect(url: String, plugin: String = "FileRepo") throws -> Repo {
    // Factory function that returns an instance of a specific Repo class
    switch plugin {
    case "FileRepo":
        return try FileRepo(url)
    case "GitFileRepo":
        return try GitFileRepo(url)
    default:
        throw RepoError.error(description: "No repo plugin named \"\(plugin)\"")
    }
}
