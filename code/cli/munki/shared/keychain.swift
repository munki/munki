//
//  keychain.swift
//  munki
//
//  Created by Greg Neagle on 3/15/25.
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

import CryptoKit
import Foundation
import Security

private let DEFAULT_KEYCHAIN_NAME = "munki.keychain"
private let DEFAULT_KEYCHAIN_PASSWORD = "munki"
private let KEYCHAIN_DIRECTORY = managedInstallsDir(subpath: "Keychains") as NSString
private let display = DisplayAndLog.main

/// Read in a base64 pem file, return data of embedded certificate
func pemCertData(_ certPath: String) throws -> Data {
    guard let certString = try? String(contentsOfFile: certPath, encoding: .utf8) else {
        throw MunkiError("File not decodeable as UTF-8")
    }
    let startTag = "-----BEGIN CERTIFICATE-----"
    let endTag = "-----END CERTIFICATE-----"
    guard let startIndex = certString.range(of: startTag)?.upperBound,
          let endIndex = certString.range(of: endTag)?.lowerBound
    else {
        throw MunkiError("File does not appear to be .pem file")
    }
    let certDataString = String(certString[startIndex ..< endIndex])
        .trimmingCharacters(in: .whitespacesAndNewlines)
        .components(separatedBy: .newlines)
        .joined()
    guard let certData = Data(base64Encoded: String(certDataString)) else {
        throw MunkiError("Could not decode cert string as base64")
    }
    return certData
}

/// Return SHA1 digest for pem certificate at path
func pemCertSha1Digest(_ certPath: String) throws -> String {
    let certData = try pemCertData(certPath)
    let hashed = Insecure.SHA1.hash(data: certData)
    return hashed.compactMap { String(format: "%02x", $0) }.joined().uppercased()
}

/// Attempt to get information we need from Munki's preferences or defaults.
/// Returns a dictionary.
func getMunkiServerCertInfo() -> [String: String] {
    var certInfo = [
        "ca_cert_path": "",
        "ca_dir_path": "",
    ]

    // get server CA cert if it exists so we can verify the Munki server
    let default_ca_cert_path = managedInstallsDir(subpath: "certs/ca.pem")
    if pathExists(default_ca_cert_path) {
        certInfo["ca_cert_path"] = default_ca_cert_path
    }
    if let ca_path = pref("SoftwareRepoCAPath") as? String {
        if pathIsRegularFile(ca_path) {
            certInfo["ca_cert_path"] = ca_path
        } else if pathIsDirectory(ca_path) {
            certInfo["ca_cert_path"] = ""
            certInfo["ca_dir_path"] = ca_path
        }
    }
    if let ca_cert_path = pref("SoftwareRepoCACertificate") as? String {
        certInfo["ca_cert_path"] = ca_cert_path
    }
    return certInfo
}

extension String {
    // remove a suffix if it exists
    func deletingSuffix(_ suffix: String) -> String {
        guard hasSuffix(suffix) else { return self }
        return String(dropLast(suffix.count))
    }
}

/// Attempt to get client cert and key information from Munki's preferences or defaults.
/// Returns a dictionary.
func getMunkiClientCertInfo() -> [String: Any] {
    var certInfo = [
        "client_cert_path": "",
        "client_key_path": "",
        "site_urls": [String](),
    ] as [String: Any]

    // should we use a client cert at all?
    if !(pref("UseClientCertificate") as? Bool ?? false) {
        return certInfo
    }
    // get client cert if it exists
    certInfo["client_cert_path"] = pref("ClientCertificatePath") as? String ?? ""
    certInfo["client_key_path"] = pref("ClientKeyPath") as? String ?? ""
    if (certInfo["client_cert_path"] as? String ?? "").isEmpty {
        for name in ["cert.pem", "client.pem", "munki.pem"] {
            let client_cert_path = managedInstallsDir(subpath: "certs/\(name)")
            if pathExists(client_cert_path) {
                certInfo["client_cert_path"] = client_cert_path
                break
            }
        }
    }
    // get site urls
    var siteUrls = [String]()
    for key in ["SoftwareRepoURL", "PackageURL", "CatalogURL",
                "ManifestURL", "IconURL", "ClientResourceURL"]
    {
        if let url = pref(key) as? String,
           !url.isEmpty
        {
            siteUrls.append(url.deletingSuffix("/") + "/")
        }
    }
    certInfo["site_urls"] = siteUrls
    return certInfo
}

/// Attempt to extract the CN from cert data
func getCommonNameFromCertData(_ certData: Data) -> String? {
    if let cert = SecCertificateCreateWithData(
        kCFAllocatorDefault, certData as CFData
    ) {
        var commonName: CFString?
        if SecCertificateCopyCommonName(cert, &commonName) == errSecSuccess {
            return commonName as String?
        }
    }
    return nil
}

/// Returns the common name for the client cert, if any
func getClientCertCommonName() -> String? {
    let certInfo = getMunkiClientCertInfo()
    if let certPath = certInfo["client_cert_path"] as? String {
        if let certData = try? pemCertData(certPath) {
            return getCommonNameFromCertData(certData)
        }
    }
    return nil
}

// MARK: keychain functions

class SecurityError: MunkiError {}

/// Runs the security binary with args. Returns stdout.
/// Raises SecurityError for a non-zero return code
/// This version allows variadic args which look nicer
func security(_ args: String..., environment: [String: String] = [:]) throws -> String {
    try security(args, environment: environment)
}

/// Runs the security binary with args. Returns stdout.
/// Raises SecurityError for a non-zero return code
func security(_ args: [String], environment: [String: String] = [:]) throws -> String {
    let result = runCLI("/usr/bin/security", arguments: args, environment: environment)
    if result.exitcode != 0 {
        throw SecurityError(result.error)
    }
    if !result.output.isEmpty {
        return result.output
    } else {
        return result.error
    }
}

/// Returns an absolute path for our Munki keychain
func getKeychainPath() -> String {
    var keychainName = pref("KeychainName") as? String ?? DEFAULT_KEYCHAIN_NAME
    // We only care about the filename, not the path
    // if we have an odd path that appears to be all directory and no
    // file name, revert to default filename
    keychainName = baseName(keychainName)
    if keychainName.isEmpty {
        keychainName = DEFAULT_KEYCHAIN_NAME
    }
    // Correct the filename to include '.keychain' if not already present
    if !["keychain", "keychain-db"].contains((keychainName as NSString).pathExtension) {
        keychainName = keychainName + ".keychain"
    }
    return getAbsolutePath(KEYCHAIN_DIRECTORY.appendingPathComponent(keychainName))
}

/// Debugging output for keychain
func debugKeychainOutput() {
    do {
        display.debug2("***Keychain search list for common domain***")
        try display.debug2(security("list-keychains", "-d", "common"))
        display.debug2("***Default keychain info***")
        try display.debug2(security("default-keychain", "-d", "common"))
        let keychainfile = getKeychainPath()
        if pathExists(keychainfile) {
            display.debug2("***Info for \(keychainfile)***")
            try display.debug2(security("show-keychain-info", keychainfile))
        }
    } catch {
        display.error("Error: \(error.localizedDescription)")
    }
}

/// Ensure the keychain is in the search path. Returns boolean to indicate if the keychain was added
func addToKeychainList(_ keychainPath: String, environment: [String: String] = [:]) -> Bool {
    var addedKeychain = false
    guard let output = try? security(
        "list-keychains", "-d", "common",
        environment: environment
    ) else { return false }
    // Split the output and strip it of whitespace and leading/trailing
    // quotes, the result are absolute paths to keychains
    // Preserve the order in case we need to append to them
    var searchKeychains: [String] = []
    var quoteChar = CharacterSet()
    quoteChar.insert("\"")
    for line in output.split(separator: "\n") {
        let trimmedLine = line.trimmingCharacters(in: .whitespaces).trimmingCharacters(in: quoteChar)
        if !trimmedLine.isEmpty {
            searchKeychains.append(trimmedLine)
        }
    }
    if !searchKeychains.contains(keychainPath) {
        // Keychain is not in the search paths, let's add it
        display.debug2("Adding client keychain to search path...")
        searchKeychains.append(keychainPath)
        do {
            let output = try security(
                ["list-keychains", "-d", "common", "-s"] + searchKeychains,
                environment: environment
            )
            if !output.isEmpty {
                display.debug2(output)
            }
            addedKeychain = true
        } catch {
            display.error("Could not add keychain \(keychainPath) to keychain list: \(error.localizedDescription)")
        }
    }
    if loggingLevel() > 2 {
        debugKeychainOutput()
    }
    return addedKeychain
}

/// Remove keychain from the list of keychains
func removeFromKeychainList(_ keychainPath: String, environment: [String: String] = [:]) {
    guard let output = try? security("list-keychains", "-d", "common", environment: environment) else {
        return
    }
    // Split the output and strip it of whitespace and leading/trailing
    // quotes, the result are absolute paths to keychains
    // Preserve the order in case we need to append to them
    var searchKeychains: [String] = []
    var quoteChar = CharacterSet()
    quoteChar.insert("\"")
    for line in output.split(separator: "\n") {
        let trimmedLine = line.trimmingCharacters(in: .whitespaces).trimmingCharacters(in: quoteChar)
        if !trimmedLine.isEmpty {
            searchKeychains.append(trimmedLine)
        }
    }
    if searchKeychains.contains(keychainPath) {
        // Keychain is in the search path
        display.debug2("Removing \(keychainPath) from search path...")
        let filteredKeychains = searchKeychains.filter { $0 != keychainPath }
        do {
            let output = try security(
                ["list-keychains", "-d", "common", "-s"] + filteredKeychains,
                environment: environment
            )
            if !output.isEmpty {
                display.debug2(output)
            }
        } catch {
            display.error("Could not remove keychain \(keychainPath) from keychain list: \(error.localizedDescription)")
        }
    }
    if loggingLevel() > 2 {
        debugKeychainOutput()
    }
}

/// Unlocks the keychain and sets it to non-locking
func unlockAndSetNonLocking(_ keychainPath: String, environment: [String: String] = [:]) {
    let keychainPassword = pref("KeychainPassword") as? String ?? DEFAULT_KEYCHAIN_PASSWORD
    do {
        let output = try security(
            "unlock-keychain", "-p", keychainPassword, keychainPath,
            environment: environment
        )
        if !output.isEmpty {
            display.debug2(output)
        }
    } catch {
        // some problem unlocking the keychain
        display.error("Could not unlock \(keychainPath): \(error.localizedDescription)")
        // just delete the keychain
        do {
            try FileManager.default.removeItem(atPath: keychainPath)
        } catch {
            display.error("Could not remove \(keychainPath): \(error.localizedDescription)")
        }
        return
    }
    do {
        let output = try security(
            "set-keychain-settings", keychainPath,
            environment: environment
        )
        if !output.isEmpty {
            display.debug2(output)
        }
    } catch {
        display.error("Could not set keychain settings for  \(keychainPath): \(error.localizedDescription)")
    }
}

/// Returns true if a client cert exists that we need to import into a keychain
func clientCertExists() -> Bool {
    let certInfo = getMunkiClientCertInfo()
    let client_cert_path = certInfo["client_cert_path"] as? String ?? ""
    return !client_cert_path.isEmpty && pathExists(client_cert_path)
}

/// Builds a client cert keychain from existing client certs
/// If keychain was added to the search list, returns true
func makeClientKeychain(_ certInfo: [String: Any] = [:]) -> Bool {
    var certInfo = certInfo
    if certInfo.isEmpty {
        // grab data from Munki's preferences/defaults
        certInfo = getMunkiClientCertInfo()
    }
    let client_cert_path = certInfo["client_cert_path"] as? String ?? ""
    let client_key_path = certInfo["client_key_path"] as? String ?? ""
    if client_cert_path.isEmpty {
        // no client cert, so nothing to do
        display.debug1("No client cert info provided, so no client keychain will be created.")
        return false
    } else {
        display.debug1("Client cert path: \(client_cert_path)")
        display.debug1("Client key path: \(client_key_path)")
    }

    // to do some of the following options correctly, we need to be root
    // and have root's home.
    // check to see if we're root
    if NSUserName().lowercased() != "root" {
        display.error("Can't make our client keychain unless we are root!")
        return false
    }
    // make sure HOME has root's home
    var env = ProcessInfo.processInfo.environment
    env["HOME"] = NSHomeDirectoryForUser("root") ?? "/var/root"

    let keychainPassword = pref("KeychainPassword") as? String ?? DEFAULT_KEYCHAIN_PASSWORD
    let keychainPath = getKeychainPath()
    if pathExists(keychainPath) {
        try? FileManager.default.removeItem(atPath: keychainPath)
    }
    if !pathExists(dirName(keychainPath)) {
        let attrs = [
            FileAttributeKey.posixPermissions: 0o700,
        ] as [FileAttributeKey: Any]
        try? FileManager.default.createDirectory(atPath: dirName(keychainPath), withIntermediateDirectories: true, attributes: attrs)
    }
    // create a new keychain
    display.debug1("Creating client keychain...")
    do {
        let output = try security(
            "create-keychain", "-p", keychainPassword, keychainPath,
            environment: env
        )
        if !output.isEmpty {
            display.debug2(output)
        }
    } catch {
        display.error("Could not create keychain \(keychainPath): \(error)")
    }

    // Ensure the keychain is in the search path and unlocked
    let addedKeychain = addToKeychainList(keychainPath, environment: env)
    unlockAndSetNonLocking(keychainPath, environment: env)

    // Add client cert (and optionally key)
    var client_cert_file = ""
    var combined_pem = ""
    if !client_key_path.isEmpty {
        // combine client cert and private key before we import
        if let certData = try? Data(contentsOf: URL(fileURLWithPath: client_cert_path)),
           let keyData = try? Data(contentsOf: URL(fileURLWithPath: client_key_path)),
           let tempDir = TempDir.shared.path
        {
            // write the combined data
            combined_pem = (tempDir as NSString).appendingPathComponent("combined.pem")
            let combinedData = certData + keyData
            do {
                try combinedData.write(to: URL(fileURLWithPath: combined_pem))
                client_cert_file = combined_pem
            } catch {
                display.error("Could not combine client cert and key for import!")
            }
        } else {
            display.error("Could not read client cert or key file")
        }
    } else {
        client_cert_file = client_cert_path
    }
    if !client_cert_file.isEmpty {
        // client_cert_file is combined_pem or client_cert_file
        display.debug2("Importing client cert and key...")
        do {
            let output = try security(
                "import", client_cert_file, "-A", "-k", keychainPath,
                environment: env
            )
            if !output.isEmpty {
                display.debug2(output)
            }
        } catch {
            display.error("Could not import \(client_cert_file): \(error.localizedDescription)")
        }
    }
    if !combined_pem.isEmpty {
        // we created this; we should clean it up
        try? FileManager.default.removeItem(atPath: combined_pem)
    }

    // we're done
    // if addedKeychain {
    //    removeFromKeychainList(keychainPath, environment: env)
    // }
    display.info("Completed creation of client keychain at \(keychainPath)")
    return addedKeychain
}

/// Wrapper class for handling the client keychain
class MunkiKeychain {
    var keychainPath = ""
    var addedKeychain = false

    /// Unlocks the munki.keychain if it exists.
    /// Makes sure the munki.keychain is in the search list.
    /// Creates a new client keychain if needed.
    init() {
        keychainPath = getKeychainPath()
        if clientCertExists(), pathExists(keychainPath) {
            do {
                try FileManager.default.removeItem(atPath: keychainPath)
            } catch {
                display.error("Could not remove pre-existing \(keychainPath): \(error.localizedDescription)")
            }
        }
        if pathExists(keychainPath) {
            // ensure existing keychain is available for use
            addedKeychain = addToKeychainList(keychainPath)
            unlockAndSetNonLocking(keychainPath)
        }
        if !pathExists(keychainPath) {
            // try making a new keychain
            addedKeychain = makeClientKeychain()
        }
        if !pathExists(keychainPath) {
            // give up
            keychainPath = ""
            addedKeychain = false
        }
    }

    deinit {
        // Remove our keychain from the keychain list if we added it
        if addedKeychain {
            removeFromKeychainList(keychainPath)
        }
    }
}
