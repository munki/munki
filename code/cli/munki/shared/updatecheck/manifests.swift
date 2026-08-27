//
//  manifests.swift
//  munki
//
//  Created by Greg Neagle on 8/9/24.
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

private let PRIMARY_MANIFEST_TAG = "_primary_manifest_"
private let display = DisplayAndLog.main

enum ManifestError: Error {
    case invalid(_ description: String)
    case notRetrieved(_ description: String)
    case connection(errorCode: Int, description: String)
    case http(errorCode: Int, description: String)
}

extension ManifestError: LocalizedError {
    var errorDescription: String? {
        switch self {
        case let .invalid(description):
            return "Manifest is invalid: \(description)"
        case let .notRetrieved(description):
            return "Manifest was not retrieved: \(description)"
        case let .connection(errorCode, description):
            return "There was a connection error: \(errorCode): \(description)"
        case let .http(errorCode, description):
            return "There was an HTTP error: \(errorCode): \(description)"
        }
    }
}

/// a Singleton class to track manifest name -> local path
class Manifests {
    static let shared = Manifests()

    var db: [String: String]

    private init() {
        db = [String: String]()
    }

    func list() -> [String] {
        return Array(db.keys)
    }

    func set(_ name: String, path: String) {
        db[name] = path
    }

    func get(_ name: String) -> String? {
        return db[name]
    }

    func getAll() -> [String: String] {
        return db
    }

    func delete(_ name: String) {
        db[name] = nil
    }
}

/// Gets a manifest from the server.
///
/// Returns:
///    string local path to the downloaded manifest
/// Throws:
///    ManifestError
func getManifest(_ name: String, suppressErrors: Bool = false) throws -> String {
    // have we already retrieved it this session?
    if let manifestLocalPath = Manifests.shared.get(name) {
        return manifestLocalPath
    }

    let manifestLocalPath = managedInstallsDir(subpath: "manifests/\(name)")
    // make sure the directory exists to store it
    let manifestLocalPathDir = (manifestLocalPath as NSString).deletingLastPathComponent
    if !createMissingDirs(manifestLocalPathDir) {
        throw ManifestError.notRetrieved(
            "Could not create a local directory to store manifest")
    }

    // try to get the manifest from the server
    display.detail("Getting manifest \(name)...")
    let message = "Retrieving list of software for this machine..."
    do {
        _ = try fetchMunkiResource(
            kind: .manifest,
            name: name,
            destinationPath: manifestLocalPath,
            message: message
        )
    } catch let FetchError.connection(errorCode, description) {
        throw ManifestError.connection(errorCode: errorCode, description: description)
    } catch let FetchError.http(errorCode, description) {
        if !suppressErrors {
            display.error("Could not retrieve manifest \(name) from the server. HTTP error \(errorCode): \(description)")
        }
        throw ManifestError.http(errorCode: errorCode, description: description)
    } catch {
        if !suppressErrors {
            display.error("Could not retrieve manifest \(name) from the server: \(error.localizedDescription)")
        }
        throw ManifestError.notRetrieved(error.localizedDescription)
    }

    // validate the plist
    do {
        _ = try readPlist(fromFile: manifestLocalPath)
    } catch {
        display.error("Manifest returned for \(name) is invalid.")
        try? FileManager.default.removeItem(atPath: manifestLocalPath)
        throw ManifestError.invalid(
            "Manifest returned for \(name) is invalid: \(error.localizedDescription)")
    }

    // got a valid plist
    display.detail("Retrieved manifest \(name)")
    Manifests.shared.set(name, path: manifestLocalPath)
    return manifestLocalPath
}

/// Gets the primary client manifest from the server.
/// Can throw all the same errors as getManifest
func getPrimaryManifest(alternateIdentifier: String? = nil) throws -> String {
    var clientIdentifier = ""
    if let alternateIdentifier, !alternateIdentifier.isEmpty {
        clientIdentifier = alternateIdentifier
    } else if pref("UseClientCertificate") as? Bool ?? false,
              pref("UseClientCertificateCNAsClientIdentifier") as? Bool ?? false
    {
        clientIdentifier = getClientCertCommonName() ?? ""
    } else {
        clientIdentifier = pref("ClientIdentifier") as? String ?? ""
    }

    var manifest = ""
    if !clientIdentifier.isEmpty {
        manifest = try getManifest(clientIdentifier)
    } else {
        // no clientIdentifier specified. Try a variety of possible identifiers
        display.detail("No client identifier specified. Trying default manifest resolution...")
        var identifiers = [String]()

        let uname_hostname = hostname()
        identifiers.append(uname_hostname) // append hostname

        let shortHostname = uname_hostname.components(separatedBy: ".")[0]
        if !shortHostname.isEmpty, shortHostname != uname_hostname {
            identifiers.append(shortHostname)
        }
        let sn = serialNumber()
        if sn != "UNKNOWN" {
            identifiers.append(sn)
        }
        identifiers.append("site_default")

        for (index, identifier) in identifiers.enumerated() {
            display.detail("Requesting manifest \(identifier)...")
            do {
                manifest = try getManifest(identifier, suppressErrors: true)
            } catch {
                if error is ManifestError,
                   index + 1 < identifiers.count // not last attempt
                {
                    display.detail("Manifest \(identifier) not found...")
                    continue // try the next identifier
                } else {
                    // just rethrow it
                    throw error
                }
            }
            if !manifest.isEmpty {
                clientIdentifier = identifier
                break
            }
        }
    }

    // record info and return the path to the manifest
    Manifests.shared.set(PRIMARY_MANIFEST_TAG, path: manifest)
    Report.shared.record(clientIdentifier, to: "ManifestName")
    display.detail("Using primary manifest: \(clientIdentifier)")
    return manifest
}

/// Removes any manifest files that are no longer in use by this client
func cleanUpManifests() {
    let manifestDir = managedInstallsDir(subpath: "manifests")
    let exceptions = ["SelfServeManifest"]
    let keepList = Manifests.shared.list() + exceptions
    cleanUpDir(manifestDir, keeping: keepList)
}

/// Reads a manifest file, returns a dictionary.
func manifestData(_ path: String) -> PlistDict? {
    if pathExists(path) {
        do {
            if let plist = try readPlist(fromFile: path) as? PlistDict {
                return plist
            } else {
                // could not coerce to correct format
                display.error("\(path) is the wrong format")
            }
        } catch let PlistError.readError(description) {
            display.error("file error for \(path): \(description)")
        } catch {
            display.error("file error for \(path): \(error.localizedDescription)")
        }
        // if we get here there's something wrong with the file. Try to remove it
        try? FileManager.default.removeItem(atPath: path)
    } else {
        display.error("\(path) does not exist")
    }
    return nil
}

/// Returns the value for key for a manifest
func getManifestValue(_ path: String, forKey key: String) -> Any? {
    if let manifest = manifestData(path) {
        if let value = manifest[key] {
            return value
        } else {
            display.error("Failed to get manifest value for key: \(key) (\(path))")
        }
    }
    return nil
}

/// Remove the given itemname from the self-serve manifest's managed_uninstalls list
func removeItemFromSelfServeSection(itemname: String, section: String) {
    display.debug1("Removing \(itemname) from SelfServeManifest's \(section)...")
    let manifestPath = managedInstallsDir(subpath: "manifests/SelfServeManifest")
    if !pathExists(manifestPath) {
        display.debug1("\(manifestPath) doesn't exist.")
        return
    }
    guard var manifest = manifestData(manifestPath) else {
        // manifestData displays its own errors
        return
    }
    // section should be a list of strings
    guard var sectionContents = manifest[section] as? [String] else {
        display.debug1("\(manifestPath): missing or invalid \(section)")
        return
    }
    sectionContents = sectionContents.filter {
        $0 != itemname
    }
    manifest[section] = sectionContents
    do {
        try writePlist(manifest, toFile: manifestPath)
    } catch {
        display.debug1("Error writing \(manifestPath): \(error.localizedDescription)")
    }
}

/// Remove the given itemname from the self-serve manifest's managed_installs list
func removeFromSelfServeInstalls(_ itemName: String) {
    removeItemFromSelfServeSection(itemname: itemName, section: "managed_installs")
}

func removeFromSelfServeUninstalls(_ itemName: String) {
    /// Remove the given itemname from the self-serve manifest's
    /// managed_uninstalls list
    removeItemFromSelfServeSection(itemname: itemName, section: "managed_uninstalls")
}

/// Processes keys in manifests to build the lists of items to install and
/// remove.
///
/// Can be recursive if manifests include other manifests.
/// Probably doesn't handle circular manifest references well.
///
/// manifest can be a path to a manifest file or a dictionary object.
func processManifest(
    _ manifestdata: PlistDict,
    forKey key: String,
    installInfo: inout PlistDict,
    parentCatalogs: [String] = [],
    manifestName: String = "embedded manifest"
) async throws {
    let manifestCatalogs = manifestdata["catalogs"] as? [String] ?? []
    var catalogList = [String]()
    if !manifestCatalogs.isEmpty {
        catalogList = manifestCatalogs
        getCatalogs(catalogList)
    } else if !parentCatalogs.isEmpty {
        catalogList = parentCatalogs
    }

    if catalogList.isEmpty {
        display.warning("Manifest \(manifestName) has no catalogs")
        return
    }

    // process all included manifests first
    for includedManifestName in manifestdata["included_manifests"] as? [String] ?? [] {
        if includedManifestName.isEmpty {
            continue
        }
        let nestedManifestPath = try getManifest(includedManifestName)
        if stopRequested() {
            return // maybe should throw a StopRequestedException?
        }
        try await processManifest(
            atPath: nestedManifestPath,
            forKey: key,
            installInfo: &installInfo,
            parentCatalogs: catalogList
        )
    }

    // process conditional items
    if let conditionalItems = manifestdata["conditional_items"] as? [PlistDict] {
        display.debug1("** Processing conditional_items in \(manifestName)")
        // conditionalitems should be an array of dicts
        // each dict has a predicate; the rest consists of the
        // same keys as a manifest
        for item in conditionalItems {
            guard let predicate = item["condition"] as? String else {
                display.warning("Missing predicate for conditional_item \(item)")
                continue
            }
            if await predicateEvaluatesAsTrue(
                predicate,
                infoObject: predicateInfoObject(),
                additionalInfo: ["catalogs": catalogList]
            ) {
                // use item as the embedded manifest
                try await processManifest(
                    item,
                    forKey: key,
                    installInfo: &installInfo,
                    parentCatalogs: catalogList
                )
            }
        }
    }

    if key == "default_installs",
       let itemList = manifestdata[key] as? [String]
    {
        processDefaultInstalls(itemList)
    } else if key == "featured_items",
              let itemList = manifestdata[key] as? [String]
    {
        var featuredItems = installInfo["featured_items"] as? [String] ?? []
        featuredItems += itemList
        featuredItems = Array(Set(featuredItems))
        installInfo["featured_items"] = featuredItems
    } else if let itemList = manifestdata[key] as? [String] {
        for item in itemList {
            if stopRequested() {
                return // or throw?
            }
            if key == "managed_installs" {
                _ = await processInstall(
                    item,
                    catalogList: catalogList,
                    installInfo: &installInfo
                )
            }
            if key == "managed_updates" {
                _ = await processManagedUpdate(
                    item,
                    catalogList: catalogList,
                    installInfo: &installInfo
                )
            }
            if key == "optional_installs" {
                _ = await processOptionalInstall(
                    item,
                    catalogList: catalogList,
                    installInfo: &installInfo
                )
            }
            if key == "managed_uninstalls" {
                _ = await processRemoval(
                    item,
                    catalogList: catalogList,
                    installInfo: &installInfo
                )
            }
        }
    }
}

/// Process a manifest _file_
func processManifest(
    atPath manifestPath: String,
    forKey key: String,
    installInfo: inout PlistDict,
    parentCatalogs: [String] = []
) async throws {
    display.debug1("** Processing manifest \(baseName(manifestPath)) for \(key)")
    if let manifestdata = manifestData(manifestPath) {
        try await processManifest(
            manifestdata,
            forKey: key,
            installInfo: &installInfo,
            parentCatalogs: parentCatalogs,
            manifestName: baseName(manifestPath)
        )
    }
}
