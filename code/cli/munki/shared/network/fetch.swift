//
//  fetch.swift
//  munki
//
//  Created by Greg Neagle on 8/13/24.
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

// XATTR name storing the ETAG of the file when downloaded via http(s).
// let XATTR_ETAG = "com.googlecode.munki.etag"
// XATTR name storing the sha256 of the file after original download by munki.
let XATTR_SHA = "com.googlecode.munki.sha256"

// default value for User-Agent header
let DEFAULT_USER_AGENT = "managedsoftwareupdate/\(getVersion()) Darwin/\(uname_release())"

enum FetchError: Error {
    case connection(errorCode: Int, description: String)
    case http(errorCode: Int, description: String)
    case download(errorCode: Int, description: String)
    case fileSystem(_ description: String)
    case verification
}

extension FetchError: LocalizedError {
    var errorDescription: String? {
        switch self {
        case let .connection(errorCode, description):
            return "Connection error \(errorCode): \(description)"
        case let .http(errorCode, description):
            return "HTTP error \(errorCode): \(description)"
        case let .download(errorCode, description):
            return "Download error \(errorCode): \(description)"
        case let .fileSystem(description):
            return "File system error: \(description)"
        case .verification:
            return "Checksum verification error"
        }
    }
}

/// Stores a sha256 hash of the file in an extended attribute, generating the hash if needed.
func storeCachedChecksum(toPath path: String, hash: String? = nil) -> String? {
    let fhash: String = if let hash {
        hash
    } else {
        sha256hash(file: path)
    }
    if fhash.count == 64, let data = fhash.data(using: .utf8) {
        do {
            try setXattr(named: XATTR_SHA, data: data, atPath: path)
            return fhash
        } catch {
            // fall through
        }
    }
    return nil
}

/// Verifies the integrity of the given software package.
///
/// The feature is controlled through the PackageVerificationMode key in
/// Munki's preferences. Following modes currently exist:
///     none: No integrity check is performed.
///     hash: Integrity check is performed by calculating a SHA-256 hash of
///         the given file and comparing it against the reference value in
///         catalog. Only applies for package plists that contain the
///         item_key; for packages without the item_key, verification always
///         returns true.
///     hash_strict: Same as hash, but returns false for package plists that
///         do not contain the item_key.
///
/// Args:
///     path: The file to check integrity on.
///     expectedHash: the sha256 hash expected.
///     alwaysHash: Boolean. Always check and return the hash even if not
///                 necessary for this function.
///
/// Returns:
///     (true/false, sha256-hash)
///     true if the package integrity could be validated. Otherwise, false.
func verifySoftwarePackageIntegrity(_ path: String, expectedHash: String, alwaysHash: Bool = false) -> (Bool, String) {
    let display = DisplayAndLog.main
    let mode = pref("PackageVerificationMode") as? String ?? "hash"
    let itemName = (path as NSString).lastPathComponent
    var calculatedHash = ""
    if alwaysHash {
        calculatedHash = sha256hash(file: path)
    }
    switch mode.lowercased() {
    case "none":
        display.warning("Package integrity checking is disabled.")
        return (true, calculatedHash)
    case "hash", "hash_strict":
        if !expectedHash.isEmpty {
            display.minorStatus("Verifying package integrity...")
            if calculatedHash.isEmpty {
                calculatedHash = sha256hash(file: path)
            }
            if expectedHash == calculatedHash {
                return (true, calculatedHash)
            }
            // expectedHash != calculatedHash
            display.error("Hash value integrity check for \(itemName) failed.")
            return (false, calculatedHash)
        } else {
            // no expected hash
            if mode.lowercased() == "hash_strict" {
                display.error("Expected hash value for \(itemName) is missing in catalog.")
                return (false, calculatedHash)
            }
            // mode is "hash"
            display.warning(
                "Expected hash value missing for \(itemName) -- package integrity verification skipped.")
            return (true, calculatedHash)
        }
    default:
        display.error("The PackageVerificationMode in the ManagedInstalls preferences has an illegal value: \(mode)")
    }
    return (false, calculatedHash)
}

/// Given a list of strings in http header format, return a dict.
/// A User-Agent header is added if none is present in the list.
/// If strList is nil, returns a dict with only the User-Agent header.
func headerDictFromList(_ strList: [String]?) -> [String: String] {
    var headerDict = [String: String]()
    headerDict["User-Agent"] = DEFAULT_USER_AGENT

    if let strList {
        for item in strList {
            if item.contains(":") {
                let parts = item.split(separator: ":", maxSplits: 1)
                if parts.count == 2 {
                    headerDict[String(parts[0])] = String(parts[1]).trimmingCharacters(in: .whitespaces)
                }
            }
        }
    }
    return headerDict
}

/// Singleton to avoid loading the middleware dylib for each request
class MiddlewarePluginLoader {
    static let shared = MiddlewarePluginLoader()

    var middleware: MunkiMiddleware?

    private init() {
        do {
            if let middleware = try loadMiddlewarePlugin() {
                self.middleware = middleware
            }
        } catch {
            DisplayAndLog.main.error("Could not load middleware plugin: \(error.localizedDescription)")
        }
    }
}

/// Attempts to process our request via a middleware plugin, if one is found
func runMiddleware(_ request: MunkiMiddlewareRequest) -> MunkiMiddlewareRequest {
    let display = DisplayAndLog.main

    if let middleware = MiddlewarePluginLoader.shared.middleware {
        display.debug2("Running middleware plugin")
        display.debug2("Input: \(request)")
        let modifiedRequest = middleware.processRequest(request)
        display.debug2("Output: \(modifiedRequest)")
        return modifiedRequest
    }

    // no plugin found, or error loading plugin -- just return unmodified request
    return request
}

/// Gets an HTTP or HTTPS URL and stores it in
/// destination path. Returns a dictionary of headers, which includes
/// http_result_code and http_result_description.
/// Will throw FetchError.connection if Gurl has a connection error.
/// Will throw FetchError.http if HTTP Result code is not 2xx or 304.
/// Will throw FetchError.fileSystem if Gurl has a filesystem error.
/// If destinationpath already exists, you can set 'onlyifnewer' to true to
/// indicate you only want to download the file only if it's newer on the
/// server.
/// If you set resume to true, Gurl will attempt to resume an
/// interrupted download.
func getURL(
    _ url: String,
    destinationPath: String,
    customHeaders: [String]? = nil,
    message: String = "",
    onlyIfNewer: Bool = false,
    resume: Bool = false,
    followRedirects: String = "none",
) throws -> [String: String] {
    let tempDownloadPath = destinationPath + ".download"
    if pathExists(tempDownloadPath), !resume {
        try? FileManager.default.removeItem(atPath: tempDownloadPath)
    }

    let headers = headerDictFromList(customHeaders)

    // Run middleware
    var request = MunkiMiddlewareRequest(
        url: url,
        headers: headers
    )
    request = runMiddleware(request)

    var cacheData: [String: String]?
    if onlyIfNewer, pathExists(destinationPath) {
        // create a temporary Gurl object so we can extract the
        // stored caching data so we can download only if the
        // file has changed on the server
        let temp = Gurl(options: GurlOptions(url: url, destinationPath: destinationPath))
        cacheData = temp.getStoredHeaders()
    }

    let ignoreSystemProxy = pref("IgnoreSystemProxies") as? Bool ?? false

    let options = GurlOptions(
        url: request.url,
        destinationPath: tempDownloadPath,
        additionalHeaders: request.headers,
        followRedirects: followRedirects,
        ignoreSystemProxy: ignoreSystemProxy,
        canResume: resume,
        downloadOnlyIfChanged: onlyIfNewer,
        cacheData: cacheData,
        log: DisplayAndLog.main.debug2
    )

    let display = DisplayAndLog.main
    let session = Gurl(options: options)
    var displayMessage = message
    var storedPercentComplete = -1
    var storedBytesReceived = 0
    session.start()
    while true {
        // if we did `while !session.isDone()` we'd miss printing
        // messages and displaying percentages if we exit the loop first
        let done = session.isDone()
        if !displayMessage.isEmpty, session.status != 0, session.status != 304 {
            // log always, display if verbose is 1 or more
            // also display in MunkiStatus detail field
            display.minorStatus(displayMessage)
            // now clear message so we don't display it again
            displayMessage = ""
        }
        if String(session.status).hasPrefix("2"), session.percentComplete != -1 {
            if session.percentComplete != storedPercentComplete {
                // display percent done if it has changed
                storedPercentComplete = session.percentComplete
                displayPercentDone(current: storedPercentComplete, maximum: 100)
            }
        } else if session.bytesReceived != storedBytesReceived {
            // if we don't have percent done info, log bytes received
            storedBytesReceived = session.bytesReceived
            display.detail("Bytes received: \(storedBytesReceived)")
        }
        if done {
            break
        }
    }

    if let error = session.error {
        // gurl had an NSError
        var errorCode = 0
        var errorDescription = ""
        if let urlError = error as? URLError {
            errorCode = urlError.code.rawValue
            errorDescription = urlError.localizedDescription
            display.detail("Download error \(errorCode): \(errorDescription)")
        } else {
            errorDescription = error.localizedDescription
            display.detail("Download error: \(errorDescription)")
        }
        if session.SSLerror != 0 {
            errorCode = session.SSLerror
            errorDescription = sslErrorForCode(errorCode)
            display.detail("SSL error \(errorCode) detail: \(errorDescription)")
            debugKeychainOutput()
        }
        display.detail("Headers: \(session.headers ?? [:])")
        if pathExists(tempDownloadPath) {
            try? FileManager.default.removeItem(atPath: tempDownloadPath)
        }
        throw FetchError.connection(errorCode: errorCode, description: errorDescription)
    }

    display.debug1("Status: \(session.status)")
    display.debug1("Headers: \(session.headers ?? [:])")
    // TODO: (maybe) track and display redirection info

    var returnedHeaders = session.headers ?? [:]
    returnedHeaders["http_result_code"] = String(session.status)
    let statusDescription = HTTPURLResponse.localizedString(forStatusCode: session.status)
    returnedHeaders["http_result_description"] = statusDescription

    if String(session.status).hasPrefix("2"), pathIsRegularFile(tempDownloadPath) {
        do {
            if pathIsRegularFile(destinationPath) {
                try? FileManager.default.removeItem(atPath: destinationPath)
            }
            try FileManager.default.moveItem(atPath: tempDownloadPath, toPath: destinationPath)
        } catch {
            throw FetchError.fileSystem(error.localizedDescription)
        }
        return returnedHeaders
    }
    if session.status == 304 {
        // unchanged on server
        display.debug1("Item is unchanged on the server.")
        return returnedHeaders
    }
    // if we get here there was an HTTP error of some sort
    if pathExists(tempDownloadPath) {
        try? FileManager.default.removeItem(atPath: tempDownloadPath)
    }
    throw FetchError.http(errorCode: session.status, description: statusDescription)
}

/// Gets file from HTTP URL, checking first to see if it has changed on the
/// server.
///
/// Returns True if a new download was required; False if the
/// item is already in the local cache.
///
/// Throws a FetchError if there is an error (.connection or .download)
func getHTTPfileIfChangedAtomically(
    _ url: String,
    destinationPath: String,
    customHeaders: [String]? = nil,
    message: String = "",
    resume: Bool = false,
    followRedirects: String = "none",
) throws -> Bool {
    var getOnlyIfNewer = false
    if pathExists(destinationPath) {
        // see if we have a stored etag or last-modified header
        do {
            let data = try getXattr(named: GURL_XATTR, atPath: destinationPath)
            if let headers = try readPlist(fromData: data) as? [String: String] {
                // We can use onlyIfNewer if we have either etag or last-modified
                if headers["etag"] != nil || headers["last-modified"] != nil {
                    getOnlyIfNewer = true
                }
            }
        } catch {
            // fall through - no cached headers
        }
    }
    var headers: [String: String]
    do {
        headers = try getURL(
            url,
            destinationPath: destinationPath,
            customHeaders: customHeaders,
            message: message,
            onlyIfNewer: getOnlyIfNewer,
            resume: resume,
            followRedirects: followRedirects
        )
    } catch let err as FetchError {
        switch err {
        case .connection:
            // just rethrow it
            throw err
        case let .http(errorCode, description):
            // rethrow as download error
            throw FetchError.download(errorCode: errorCode, description: description)
        case let .fileSystem(description):
            // rethrow as download error
            throw FetchError.download(errorCode: -1, description: description)
        default:
            // these can't actually happen, but makes compiler happy
            throw err
        }
    } catch {
        throw FetchError.download(errorCode: -1, description: error.localizedDescription)
    }

    if (headers["http_result_code"] ?? "") == "304" {
        // not modified, return existing file
        DisplayAndLog.main.debug1("\(destinationPath) already exists and is up-to-date.")
        // file already exists and is unchanged, so we return false
        return false
    }
    if let lastModified = headers["last-modified"] {
        // set the modtime of the downloaded file to the modtime of the
        // file on the server
        let dateformatter = DateFormatter()
        // Sample header -> Last-Modified: Wed, 21 Oct 2015 07:28:00 GMT
        dateformatter.dateFormat = "EEE, dd MMM yyyy HH:mm:ss zzz"
        if let modDate = dateformatter.date(from: lastModified) {
            let attrs = [
                FileAttributeKey.modificationDate: modDate,
            ]
            try? FileManager.default.setAttributes(attrs, ofItemAtPath: destinationPath)
        }
    }
    return true
}

/// Gets file from path, checking first to see if it has changed on the
/// source.
///
/// Returns true if a new copy was required; false if the
/// item is already in the local cache.
///
/// Throws FetchError.fileSystem if there is an error.
func getFileIfChangedAtomically(_ path: String, destinationPath: String) throws -> Bool {
    let filemanager = FileManager.default
    if !pathExists(path) {
        throw FetchError.fileSystem("Source does not exist: \(path)")
    }
    guard let sourceAttrs = try? filemanager.attributesOfItem(atPath: path) else {
        throw FetchError.fileSystem("Could not get file attributes for: \(path)")
    }
    if let destAttrs = try? filemanager.attributesOfItem(atPath: destinationPath) {
        // destinationPath exists. We should check the attributes to see if they
        // match
        if (sourceAttrs as NSDictionary).fileModificationDate() == (destAttrs as NSDictionary).fileModificationDate(),
           (sourceAttrs as NSDictionary).fileSize() == (destAttrs as NSDictionary).fileSize()
        {
            // modification dates and sizes are the same, we'll say they are the same
            // file -- return false to say it hasn't changed
            return false
        }
    }
    // copy to a temporary destination
    let tempDestinationPath = destinationPath + ".download"

    if pathExists(tempDestinationPath) {
        do {
            try filemanager.removeItem(atPath: tempDestinationPath)
        } catch {
            throw FetchError.fileSystem("Removing \(tempDestinationPath) failed: \(error.localizedDescription)")
        }
    }
    do {
        try filemanager.copyItem(atPath: path, toPath: tempDestinationPath)
    } catch {
        throw FetchError.fileSystem("Copying \(path) to \(tempDestinationPath) failed: \(error.localizedDescription)")
    }

    if pathExists(destinationPath) {
        do {
            try filemanager.removeItem(atPath: destinationPath)
        } catch {
            throw FetchError.fileSystem("Could not remove previous \(destinationPath): \(error.localizedDescription)")
        }
    }
    do {
        try filemanager.moveItem(atPath: tempDestinationPath, toPath: destinationPath)
    } catch {
        throw FetchError.fileSystem("Could not move \(tempDestinationPath) to \(destinationPath): \(error.localizedDescription)")
    }
    // set modification date of destinationPath to the same as the source
    if let modDate = (sourceAttrs as NSDictionary).fileModificationDate() {
        let attrs = [
            FileAttributeKey.modificationDate: modDate,
        ]
        try? filemanager.setAttributes(attrs, ofItemAtPath: destinationPath)
    }
    return true
}

/// Gets file from a URL.
/// Checks first if there is already a file with the necessary checksum.
/// Then checks if the file has changed on the server, resuming or
/// re-downloading as necessary.
///
/// If the file has changed verify the pkg hash if so configured.
///
/// Supported schemes are http, https, file.
///
/// Returns true if a new download was required; False if the
/// item is already in the local cache.
///
/// Throws a FetchError if there is an error.
func getResourceIfChangedAtomically(
    _ url: String,
    destinationPath: String,
    customHeaders: [String]? = nil,
    expectedHash: String? = nil,
    message: String = "",
    resume: Bool = false,
    verify: Bool = false,
    followRedirects: String? = nil,
) throws -> Bool {
    guard let resolvedURL = URL(string: url) else {
        throw FetchError.connection(errorCode: -1, description: "Invalid URL: \(url)")
    }

    var changed = false
    let verificationMode = (pref("PackageVerificationMode") as? String ?? "").lowercased()

    // If we already have a downloaded file & its (cached) hash matches what
    // we need, do nothing, return unchanged.
    if resume, let expectedHash, pathIsRegularFile(destinationPath) {
        var xattrHash: String?
        do {
            let data = try getXattr(named: XATTR_SHA, atPath: destinationPath)
            xattrHash = String(data: data, encoding: .utf8)
        } catch {
            // no hahs stored in xattrs, so generate one and store it
            xattrHash = storeCachedChecksum(toPath: destinationPath)
        }
        if let xattrHash, xattrHash == expectedHash {
            // File is already current, no change.
            munkiLog("        Cached item is current.")
            return false
        } else if ["hash_strict", "hash"].contains(verificationMode) {
            try? FileManager.default.removeItem(atPath: destinationPath)
        }
        munkiLog("Cached item does not match hash in catalog, will check if changed and redownload: \(destinationPath)")
    }
    let resolvedFollowRedirects: String = if let followRedirects {
        followRedirects
    } else {
        // If we haven't explicitly specified followRedirects,
        // the preference decides
        pref("FollowHTTPRedirects") as? String ?? "none"
    }
    DisplayAndLog.main.debug1("FollowHTTPRedirects is: \(resolvedFollowRedirects)")

    if ["http", "https"].contains(resolvedURL.scheme) {
        changed = try getHTTPfileIfChangedAtomically(
            url,
            destinationPath: destinationPath,
            customHeaders: customHeaders,
            message: message,
            resume: resume,
            followRedirects: resolvedFollowRedirects
        )
    } else if resolvedURL.scheme == "file" {
        if let sourcePath = resolvedURL.path.removingPercentEncoding {
            changed = try getFileIfChangedAtomically(
                sourcePath, destinationPath: destinationPath
            )
        } else {
            throw FetchError.connection(
                errorCode: -1,
                description: "Invalid path in URL \(url)"
            )
        }
    } else {
        throw FetchError.connection(
            errorCode: -1,
            description: "Unsupported url scheme: \(String(describing: resolvedURL.scheme)) in \(url)"
        )
    }

    if changed, verify {
        let (verifyOK, calculatedHash) = verifySoftwarePackageIntegrity(
            destinationPath, expectedHash: expectedHash ?? ""
        )
        if !verifyOK {
            try? FileManager.default.removeItem(atPath: destinationPath)
            throw FetchError.verification
        }
        if !calculatedHash.isEmpty {
            let _ = storeCachedChecksum(toPath: destinationPath, hash: calculatedHash)
        }
    }
    return changed
}

/// A high-level function for getting resources from the Munki repo.
/// Gets a given URL from the Munki server.
/// Adds any additional headers to the request if present
/// Throws a FetchError if there's an error
///
/// Add any additional headers specified in ManagedInstalls.plist.
/// AdditionalHttpHeaders must be an array of strings with valid HTTP
/// header format. For example:
/// <key>AdditionalHttpHeaders</key>
/// <array>
///   <string>Key-With-Optional-Dashes: Foo Value</string>
///   <string>another-custom-header: bar value</string>
/// </array>
func fetchMunkiResourceByURL(
    _ url: String,
    destinationPath: String,
    message: String = "",
    resume: Bool = false,
    expectedHash: String? = nil,
    verify: Bool = false
) throws -> Bool {
    DisplayAndLog.main.debug2("Fetching URL: \(url)")
    let customHeaders = pref(ADDITIONAL_HTTP_HEADERS_KEY) as? [String]
    return try getResourceIfChangedAtomically(
        url,
        destinationPath: destinationPath,
        customHeaders: customHeaders,
        expectedHash: expectedHash,
        message: message,
        resume: resume,
        verify: verify
    )
}

enum MunkiResourceType: String {
    case catalog = "catalogs"
    case clientResource = "client_resources"
    case icon = "icons"
    case manifest = "manifests"
    case package = "pkgs"
}

/// An even higher-level function for getting resources from the Munki repo.
func fetchMunkiResource(
    kind: MunkiResourceType,
    name: String,
    destinationPath: String,
    message: String = "",
    resume: Bool = false,
    expectedHash: String? = nil,
    verify: Bool = false
) throws -> Bool {
    guard let url = munkiRepoURL(kind.rawValue, resource: name) else {
        throw FetchError.connection(
            errorCode: -1,
            description: "Could not encode all characters in URL"
        )
    }
    return try fetchMunkiResourceByURL(
        url,
        destinationPath: destinationPath,
        message: message,
        resume: resume,
        expectedHash: expectedHash,
        verify: verify
    )
}

/// Returns data from URL.
/// We use the existing fetchMunkiResource function so any custom
/// authentication/authorization headers are used
/// (including, eventually, middleware-generated headers)
/// May throw a FetchError
func getDataFromURL(_ url: String) throws -> Data? {
    guard let tmpDir = TempDir.shared.makeTempDir() else {
        DisplayAndLog.main.error("Could not create temporary directory")
        return nil
    }
    defer { try? FileManager.default.removeItem(atPath: tmpDir) }
    let tempDataPath = (tmpDir as NSString).appendingPathComponent("urldata")
    _ = try fetchMunkiResourceByURL(
        url, destinationPath: tempDataPath
    )
    return FileManager.default.contents(atPath: tempDataPath)
}

/// A function we can call to check to see if the server is
/// available before we kick off a full run. This can be fooled by
/// ISPs that return results for non-existent web servers...
/// Returns a tuple (exitCode, exitDescription)
func checkServer(_ urlString: String = "") -> (Int, String) {
    let serverURL: String = if !urlString.isEmpty {
        urlString
    } else {
        munkiRepoURL() ?? ""
    }

    guard let url = URL(string: serverURL) else {
        return (-1, "Invalid URL")
    }

    if ["http", "https"].contains(url.scheme) {
        // pass
    } else if url.scheme == "file" {
        if let host = url.host, host != "localhost" {
            return (-1, "Non-local hostnames not supported for file:// URLs")
        }
        if let path = url.path.removingPercentEncoding, pathExists(path) {
            return (0, "OK")
        }
        return (-1, "Path \(url.path) does not exist")
    } else {
        return (-1, "Unsupported URL scheme: \(url.scheme ?? "<none>")")
    }
    do {
        _ = try getDataFromURL(url.absoluteString)
    } catch let err as FetchError {
        switch err {
        case let .connection(errorCode, description):
            return (errorCode, description)
        case .http:
            return (0, "OK")
        case .download:
            return (0, "OK")
        case .fileSystem:
            return (0, "OK")
        default:
            return (-1, err.localizedDescription)
        }
    } catch {
        return (-1, error.localizedDescription)
    }
    return (0, "OK")
}
