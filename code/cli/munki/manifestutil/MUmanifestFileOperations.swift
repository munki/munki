//
//  MUmanifestFileOperations.swift
//  manifestutil
//
//  Created by Greg Neagle on 4/14/25.
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

import ArgumentParser
import Foundation

/// Saves a manifest
func saveManifest(repo: Repo,
                  manifest: PlistDict,
                  name: String,
                  overwrite: Bool = false) async -> Bool
{
    if !overwrite {
        let existingManifestNames = await getManifestNames(repo: repo) ?? []
        if existingManifestNames.contains(name) {
            printStderr("Manifest '\(name)' already exists")
            return false
        }
    }
    do {
        let data = try plistToData(manifest)
        try await repo.put("manifests/\(name)", content: data)
        return true
    } catch {
        printStderr("Saving \(name) failed: \(error.localizedDescription)")
        return false
    }
}

/// Copies or renames a manifest.
/// (To rename we make a copy under the new name, then delete the original)
func copyOrRenameManifest(repo: Repo, sourceName: String, destinationName: String, overwrite: Bool = false, deleteSource: Bool = false) async -> Bool {
    if !overwrite {
        let existingManifestNames = await getManifestNames(repo: repo) ?? []
        if existingManifestNames.contains(destinationName) {
            printStderr("Manifest '\(destinationName)' already exists")
            return false
        }
    }
    do {
        let data = try await repo.get("manifests/\(sourceName)")
        try await repo.put("manifests/\(destinationName)", content: data)
        // TODO: on a case-insensitive file system this can end up deleting the file
        // (If you rename "test" to "TEST", then delete "test" you actually delete "TEST")
        if deleteSource {
            try await repo.delete("manifests/\(sourceName)")
        }
        return true
    } catch {
        printStderr("Renaming \(sourceName) to \(destinationName) failed: \(error.localizedDescription)")
        return false
    }
}

/// Creates a new, empty manifest
func newManifest(repo: Repo, name: String) async -> Bool {
    let manifest = [
        "catalogs": [String](),
        "included_manifests": [String](),
        "managed_installs": [String](),
        "managed_uninstalls": [String](),
    ]
    return await saveManifest(repo: repo, manifest: manifest, name: name)
}

/// Deletes a manifest
func deleteManifest(repo: Repo, name: String) async -> Bool {
    let existingManifestNames = await getManifestNames(repo: repo) ?? []
    if !existingManifestNames.contains(name) {
        printStderr("No such manifest: \(name)")
        return false
    }
    do {
        try await repo.delete("manifests/\(name)")
        return true
    } catch {
        printStderr("Deleting \(name) failed: \(error.localizedDescription)")
        return false
    }
}

/// Create a new empty manifest
extension ManifestUtil {
    struct NewManifest: AsyncParsableCommand {
        static var configuration = CommandConfiguration(
            abstract: "Creates a new empty manifest")

        @Argument(help: ArgumentHelp(
            "Name for the newly-created manifest",
            valueName: "manifest-name"
        ))
        var manifestName: String

        func run() async throws {
            guard let repo = RepoConnection.shared.repo else { return }
            _ = await newManifest(repo: repo, name: manifestName)
        }
    }
}

/// Copy a manifest
extension ManifestUtil {
    struct CopyManifest: AsyncParsableCommand {
        static var configuration = CommandConfiguration(
            abstract: "Copies a manifest")

        @Argument(help: ArgumentHelp(
            "Name of the source manifest",
            valueName: "source-name"
        ))
        var sourceName: String

        @Argument(help: ArgumentHelp(
            "Name of the destination manifest",
            valueName: "destination-name"
        ))
        var destinationName: String

        func run() async throws {
            guard let repo = RepoConnection.shared.repo else { return }
            _ = await copyOrRenameManifest(
                repo: repo,
                sourceName: sourceName,
                destinationName: destinationName
            )
        }
    }
}

/// Rename a manifest
extension ManifestUtil {
    struct RenameManifest: AsyncParsableCommand {
        static var configuration = CommandConfiguration(
            abstract: "Renames a manifest")

        @Argument(help: ArgumentHelp(
            "Name of the source manifest",
            valueName: "source-name"
        ))
        var sourceName: String

        @Argument(help: ArgumentHelp(
            "Name of the destination manifest",
            valueName: "destination-name"
        ))
        var destinationName: String

        func run() async throws {
            guard let repo = RepoConnection.shared.repo else { return }
            _ = await copyOrRenameManifest(
                repo: repo,
                sourceName: sourceName,
                destinationName: destinationName,
                deleteSource: true
            )
        }
    }
}

/// Delete a manifest
extension ManifestUtil {
    struct DeleteManifest: AsyncParsableCommand {
        static var configuration = CommandConfiguration(
            abstract: "Deletes a manifest")

        @Argument(help: ArgumentHelp(
            "Name of the manifest to be deleted",
            valueName: "manifest-name"
        ))
        var manifestName: String

        func run() async throws {
            guard let repo = RepoConnection.shared.repo else { return }
            _ = await deleteManifest(repo: repo, name: manifestName)
        }
    }
}
