//
//  manifests.swift
//  munki
//
//  Created by Greg Neagle on 8/9/24.
//

import Foundation

let PRIMARY_MANIFEST_TAG = "_primary_manifest_"

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
            return "Manifest was not retreived: \(description)"
        case let .connection(errorCode, description):
            return "There was a connection error: \(errorCode): \(description)"
        case let .http(errorCode, description):
            return "There was an HTTP error: \(errorCode): \(description)"
        }
    }
}

class Manifests {
    // a Singleton class to track manifest_name -> local path
    static let shared = Manifests()

    var db: [String: String]

    private init() {
        db = [String: String]()
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

func getManifest(_ name: String, suppressErrors: Bool = false) throws -> String {
    // Gets a manifest from the server.
    //
    // Returns:
    //    string local path to the downloaded manifest
    // Throws:
    //    ManifestError

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
    displayDetail("Getting manifest \(name)...")
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
            displayError("Could not retrieve manifest \(name) from the server. HTTP error \(errorCode): \(description)")
        }
        throw ManifestError.http(errorCode: errorCode, description: description)
    } catch {
        if !suppressErrors {
            displayError("Could not retrieve manifest \(name) from the server: \(error.localizedDescription)")
        }
        throw ManifestError.notRetrieved(error.localizedDescription)
    }

    // validate the plist
    do {
        _ = try readPlist(fromFile: manifestLocalPath)
    } catch {
        displayError("Manifest returned for \(name) is invalid.")
        try? FileManager.default.removeItem(atPath: manifestLocalPath)
        throw ManifestError.invalid(
            "Manifest returned for \(name) is invalid: \(error.localizedDescription)")
    }

    // got a valid plist
    displayDetail("Retreived manifest \(name)")
    Manifests.shared.set(name, path: manifestLocalPath)
    return manifestLocalPath
}

func getPrimaryManifest(alternateIdentifier: String = "") throws -> String {
    // Gets the primary client manifest from the server.
    // Can throw all the same errors as getManifest
    var clientIdentifier = ""
    if !alternateIdentifier.isEmpty {
        clientIdentifier = alternateIdentifier
    } else if pref("UseClientCertificate") as? Bool ?? false,
              pref("UseClientCertificateCNAsClientIdentifier") as? Bool ?? false
    {
        // TODO: implement using client cert common name as ClientIdentifier
    } else {
        clientIdentifier = pref("ClientIdentifier") as? String ?? ""
    }

    var manifest = ""
    if !clientIdentifier.isEmpty {
        manifest = try getManifest(clientIdentifier)
    } else {
        // no clientIdentifer specified. Try a variety of possible identifiers
        displayDetail("No client identifier specified. Trying default manifest resolution...")
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
            displayDetail("Requesting manifest \(identifier)...")
            do {
                manifest = try getManifest(identifier, suppressErrors: true)
            } catch {
                if error is ManifestError,
                   index < identifiers.count
                {
                    displayDetail("Manifest \(identifier) not found...")
                    continue // try the next identifier
                } else {
                    // juse rethrow it
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
    displayDetail("Using primary manifest: \(clientIdentifier)")
    return manifest
}

func cleanUpManifests() {
    // Removes any manifest files that are no longer in use by this client
    let manifestDir = managedInstallsDir(subpath: "manifests")
    let exceptions = ["SelfServeManifest"]
    let filemanager = FileManager.default
    let dirEnum = filemanager.enumerator(atPath: manifestDir)
    var foundDirectories = [String]()
    while let file = dirEnum?.nextObject() as? String {
        if exceptions.contains(file) {
            continue
        }
        let fullPath = (manifestDir as NSString).appendingPathComponent(file)
        if pathIsDirectory(fullPath) {
            foundDirectories.append(fullPath)
            continue
        }
        if Manifests.shared.get(file) == nil {
            try? filemanager.removeItem(atPath: fullPath)
        }
    }
    // clean up any empty directories
    for directory in foundDirectories.reversed() {
        if let contents = try? filemanager.contentsOfDirectory(atPath: directory),
           contents.isEmpty
        {
            try? filemanager.removeItem(atPath: directory)
        }
    }
}

func manifestData(_ path: String) -> PlistDict? {
    // Reads a manifest file, returns a dictionary.
    if pathExists(path) {
        do {
            if let plist = try readPlist(fromFile: path) as? PlistDict {
                return plist
            } else {
                // could not coerce to correct format
                displayError("\(path) is the wrong format")
            }
        } catch let PlistError.readError(description) {
            displayError("file error for \(path): \(description)")
        } catch {
            displayError("file error for \(path): \(error.localizedDescription)")
        }
        // if we get here there's something wrong with the file. Try to remove it
        try? FileManager.default.removeItem(atPath: path)
    } else {
        displayError("\(path) does not exist")
    }
    return nil
}

func getManifestValue(_ path: String, forKey key: String) -> Any? {
    if let manifest = manifestData(path) {
        if let value = manifest[key] {
            return value
        } else {
            displayError("Failed to get manifest value for key: \(key) (\(path))")
        }
    }
    return nil
}

func removeItemFromSelfServeSection(itemname: String, section: String) {
    // Remove the given itemname from the self-serve manifest's
    // managed_uninstalls list
    displayDebug1("Removing \(itemname) from SelfServeManifest's \(section)...")
    let manifestPath = managedInstallsDir(subpath: "manifests/SelfServeManifest")
    if !pathExists(manifestPath) {
        displayDebug1("\(manifestPath) doesn't exist.")
        return
    }
    guard var manifest = manifestData(manifestPath) else {
        // manifestData displays its own errors
        return
    }
    // section should be a list of strings
    guard var sectionContents = manifest[section] as? [String] else {
        displayDebug1("\(manifestPath): missing or invalid \(section)")
        return
    }
    sectionContents = sectionContents.filter {
        $0 != itemname
    }
    manifest[section] = sectionContents
    do {
        try writePlist(manifest, toFile: manifestPath)
    } catch {
        displayDebug1("Error writing \(manifestPath): \(error.localizedDescription)")
    }
}

func removeFromSelfServeInstalls(_ itemName: String) {
    // Remove the given itemname from the self-serve manifest's
    // managed_installs list
    removeItemFromSelfServeSection(itemname: itemName, section: "managed_installs")
}

func removeFromSelfServeUninstalls(_ itemName: String) {
    // Remove the given itemname from the self-serve manifest's
    // managed_uninstalls list
    removeItemFromSelfServeSection(itemname: itemName, section: "managed_uninstalls")
}
