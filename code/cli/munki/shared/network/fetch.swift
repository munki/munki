//
//  fetch.swift
//  munki
//
//  Created by Greg Neagle on 8/13/24.
//

import Foundation

// XATTR name storing the ETAG of the file when downloaded via http(s).
// let XATTR_ETAG = "com.googlecode.munki.etag"
// XATTR name storing the sha256 of the file after original download by munki.
let XATTR_SHA = "com.googlecode.munki.sha256"

// default value for User-Agent header
let DEFAULT_USER_AGENT = "managedsoftwareupdate/\(getVersion()) Darwin/\(uname_release())"

class GurlError: MunkiError {
    // General exception for gurl errors
}

class ConnectionError: GurlError {
    // General exception for gurl connection errors
}

class HTTPError: GurlError {
    // General exception for http/https errors
}

class DownloadError: MunkiError {
    // Base exception for download errors
}

class GurlDownloadError: DownloadError {
    // Gurl failed to download the item
}

class FileCopyError: DownloadError {
    // Download failed because of file copy errors
}

class PackageVerificationError: DownloadError {
    // Package failed verification
}

func storeCachedChecksum(toPath path: String, hash: String? = nil) -> String? {
    var fhash: String = if let hash {
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

func verifySoftwarePackageIntegrity(_ path: String, expectedHash: String, alwaysHash: Bool = false) -> (Bool, String) {
    // Verifies the integrity of the given software package.

    // The feature is controlled through the PackageVerificationMode key in
    // Munki's preferences. Following modes currently exist:
    //     none: No integrity check is performed.
    //     hash: Integrity check is performed by calculating a SHA-256 hash of
    //         the given file and comparing it against the reference value in
    //         catalog. Only applies for package plists that contain the
    //         item_key; for packages without the item_key, verification always
    //         returns true.
    //     hash_strict: Same as hash, but returns false for package plists that
    //         do not contain the item_key.
    //
    // Args:
    //     path: The file to check integrity on.
    //     expectedHash: the sha256 hash expected.
    //     alwaysHash: Boolean. Always check and return the hash even if not
    //                 necessary for this function.
    //
    // Returns:
    //     (true/false, sha256-hash)
    //     true if the package integrity could be validated. Otherwise, false.
    let mode = pref("PackageVerificationMode") as? String ?? "hash"
    let itemName = (path as NSString).lastPathComponent
    var calculatedHash = ""
    if alwaysHash {
        calculatedHash = sha256hash(file: path)
    }
    switch mode.lowercased() {
    case "none":
        displayWarning("Package integrity checking is disabled.")
        return (true, calculatedHash)
    case "hash", "hash_strict":
        if !expectedHash.isEmpty {
            displayMinorStatus("Verifying package integrity...")
            if calculatedHash.isEmpty {
                calculatedHash = sha256hash(file: path)
            }
            if expectedHash == calculatedHash {
                return (true, calculatedHash)
            }
            // expectedHash != calculatedHash
            displayError("Hash value integrity check for \(itemName) failed.")
            return (false, calculatedHash)
        } else {
            // no expected hash
            if mode.lowercased() == "hash_strict" {
                displayError("Expected hash value for \(itemName) is missing in catalog.")
                return (false, calculatedHash)
            }
            // mode is "hash"
            displayWarning(
                "Expected hash value missing for \(itemName) -- package integrity verification skipped.")
            return (true, calculatedHash)
        }
    default:
        displayError("The PackageVerificationMode in the ManagedInstalls preferences has an illegal value: \(mode)")
    }
    return (false, calculatedHash)
}

func headerDictFromList(_ strList: [String]?) -> [String: String] {
    // Given a list of strings in http header format, return a dict.
    // A User-Agent header is added if none is present in the list.
    // If strList is nil, returns a dict with only the User-Agent header.
    var headerDict = [String: String]()
    headerDict["User-Agent"] = DEFAULT_USER_AGENT

    if let strList {
        for item in strList {
            if item.contains(":") {
                let parts = item.components(separatedBy: ":")
                if parts.count == 2 {
                    headerDict[parts[0]] = parts[1]
                }
            }
        }
    }
    return headerDict
}

func getURL(
    _ url: String,
    destinationPath: String,
    customHeaders: [String]? = nil,
    message: String = "",
    onlyIfNewer: Bool = false,
    resume: Bool = false,
    followRedirects: String = "none",
    pkginfo: PlistDict? = nil
) throws -> [String: String] {
    // Gets an HTTP or HTTPS URL and stores it in
    // destination path. Returns a dictionary of headers, which includes
    // http_result_code and http_result_description.
    // Will raise ConnectionError if Gurl has a connection error.
    // Will raise HTTPError if HTTP Result code is not 2xx or 304.
    // Will raise GurlError if Gurl has some other error.
    // If destinationpath already exists, you can set 'onlyifnewer' to true to
    // indicate you only want to download the file only if it's newer on the
    // server.
    // If you set resume to True, Gurl will attempt to resume an
    // interrupted download.
    let tempDownloadPath = destinationPath + ".download"
    if pathExists(tempDownloadPath), !resume {
        try? FileManager.default.removeItem(atPath: tempDownloadPath)
    }

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
        url: url,
        destinationPath: tempDownloadPath,
        additionalHeaders: headerDictFromList(customHeaders),
        followRedirects: followRedirects,
        ignoreSystemProxy: ignoreSystemProxy,
        canResume: resume,
        downloadOnlyIfChanged: onlyIfNewer,
        cacheData: cacheData,
        log: displayDebug2
    )

    // TODO: middleware support
    // (which will use pkginfo)

    let session = Gurl(options: options)
    var displayMessage = message
    var storedPercentComplete = -1
    var storedBytesReceived = 0
    session.start()
    // TODO: add support for Cntl-C, etc
    while true {
        // if we did `while not session.isDone()` we'd miss printing
        // messages and displaying percentages if we exit the loop first
        let done = session.isDone()
        if !displayMessage.isEmpty, session.status != 0, session.status != 304 {
            // log always, display if verbose is 1 or more
            // also display in MunkiStatus detail field
            displayMinorStatus(displayMessage)
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
            displayDetail("Bytes received: \(storedBytesReceived)")
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
            displayDetail("Download error \(errorCode): \(errorDescription)")
        } else {
            errorDescription = error.localizedDescription
            displayDetail("Download error: \(errorDescription)")
        }
        if session.SSLerror != 0 {
            errorCode = session.SSLerror
            errorDescription = sslErrorForCode(errorCode)
            displayDetail("SSL error \(errorCode) detail: \(errorDescription)")
            // TODO: keychain debug output
        }
        displayDetail("Headers: \(session.headers ?? [:])")
        if pathExists(tempDownloadPath) {
            try? FileManager.default.removeItem(atPath: tempDownloadPath)
        }
        throw ConnectionError("\(errorCode): \(errorDescription)")
    }

    displayDebug1("Status: \(session.status)")
    displayDebug1("Headers: \(session.headers ?? [:])")
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
            throw GurlError(error.localizedDescription)
        }
        return returnedHeaders
    }
    if session.status == 304 {
        // unchanged on server
        displayDebug1("Item is unchanged on the server.")
        return returnedHeaders
    }
    // if we get here there was an HTTP error of some sort
    if pathExists(tempDownloadPath) {
        try? FileManager.default.removeItem(atPath: tempDownloadPath)
    }
    throw HTTPError("\(session.status): statusDescription")
}

func getHTTPfileIfChangedAtomically(
    _ url: String,
    destinationPath: String,
    customHeaders: [String]? = nil,
    message: String = "",
    resume: Bool = false,
    followRedirects: String = "none",
    pkginfo: PlistDict? = nil
) throws -> Bool {
    // Gets file from HTTP URL, checking first to see if it has changed on the
    // server.

    // Returns True if a new download was required; False if the
    // item is already in the local cache.

    // Raises GurlDownloadError if there is an error.
    // var eTag = ""
    var getOnlyIfNewer = false
    if pathExists(destinationPath) {
        getOnlyIfNewer = true
        /*
         // see if we have an etag attribute
         do {
             let data = try getXattr(named: XATTR_ETAG, atPath: destinationPath)
             eTag = String(data: data, encoding: .utf8) ?? ""
         } catch {
             // fall through
         }
         if eTag.isEmpty {
             getOnlyIfNewer = false
         }*/
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
            followRedirects: followRedirects,
            pkginfo: pkginfo
        )
    } catch let err as ConnectionError {
        // just rethrow it
        throw err
    } catch let err as HTTPError {
        throw GurlDownloadError(err.description)
    } catch let err as GurlError {
        throw GurlDownloadError(err.description)
    }

    if (headers["http_result_code"] ?? "") == "304" {
        // not modified, return existing file
        displayDebug1("\(destinationPath) already exists and is up-to-date.")
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
    /*
      // not sure why we're storing the etag in yet another xattr since gurl
      // is doing it already in a different xattr. Wondering if this is leftover
      // logic from when we were using curl
     if let eTag = headers["etag"], let data = eTag.data(using: .utf8) {
         // store etag in extended attribute for future use
         try? setXattr(named: XATTR_ETAG, data: data, atPath: destinationPath)
     }
      */
    return true
}

func getFileIfChangedAtomically(_ path: String, destinationPath: String) throws -> Bool {
    // Gets file from path, checking first to see if it has changed on the
    // source.

    // Returns true if a new copy was required; false if the
    // item is already in the local cache.

    // Throws FileCopyError if there is an error.
    let filemanager = FileManager.default
    if !pathExists(path) {
        throw FileCopyError("Source does not exist: \(path)")
    }
    guard let sourceAttrs = try? filemanager.attributesOfItem(atPath: path) else {
        throw FileCopyError("Could not get file attributes for: \(path)")
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
            throw FileCopyError("Removing \(tempDestinationPath) failed: \(error.localizedDescription)")
        }
    }
    do {
        try filemanager.copyItem(atPath: path, toPath: tempDestinationPath)
    } catch {
        throw FileCopyError("Copying \(path) to \(tempDestinationPath) failed: \(error.localizedDescription)")
    }

    if pathExists(destinationPath) {
        do {
            try filemanager.removeItem(atPath: destinationPath)
        } catch {
            throw FileCopyError("Could not remove previous \(destinationPath): \(error.localizedDescription)")
        }
    }
    do {
        try filemanager.moveItem(atPath: tempDestinationPath, toPath: destinationPath)
    } catch {
        throw FileCopyError("Could not move \(tempDestinationPath) to \(destinationPath): \(error.localizedDescription)")
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

func getResourceIfChangedAtomically(
    _ url: String,
    destinationPath: String,
    customHeaders: [String]? = nil,
    expectedHash: String? = nil,
    message: String = "",
    resume: Bool = false,
    verify: Bool = false,
    followRedirects: String? = nil,
    pkginfo: PlistDict? = nil
) throws -> Bool {
    // Gets file from a URL.
    // Checks first if there is already a file with the necessary checksum.
    // Then checks if the file has changed on the server, resuming or
    // re-downloading as necessary.

    // If the file has changed verify the pkg hash if so configured.

    // Supported schemes are http, https, file.

    // Returns True if a new download was required; False if the
    // item is already in the local cache.

    // Raises a FetchError derived exception if there is an error.

    guard let resolvedURL = URL(string: url) else {
        throw MunkiError("Invalid URL: \(url)")
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
    var resolvedFollowRedirects: String = if let followRedirects {
        followRedirects
    } else {
        // If we haven't explicitly specified followRedirects,
        // the preference decides
        pref("FollowHTTPRedirects") as? String ?? "none"
    }
    displayDebug1("FollowHTTPRedirects is: \(resolvedFollowRedirects)")

    if ["http", "https"].contains(resolvedURL.scheme) {
        changed = try getHTTPfileIfChangedAtomically(
            url,
            destinationPath: destinationPath,
            customHeaders: customHeaders,
            message: message,
            resume: resume,
            followRedirects: resolvedFollowRedirects,
            pkginfo: pkginfo
        )
    } else if resolvedURL.scheme == "file" {
        changed = try getFileIfChangedAtomically(
            resolvedURL.path, destinationPath: destinationPath
        )
    } else {
        throw MunkiError("Unsupported url scheme: \(String(describing: resolvedURL.scheme)) in \(url)")
    }

    if changed, verify {
        let (verifyOK, calculatedHash) = verifySoftwarePackageIntegrity(
            destinationPath, expectedHash: expectedHash ?? ""
        )
        if !verifyOK {
            try? FileManager.default.removeItem(atPath: destinationPath)
            throw PackageVerificationError("")
        }
        if !calculatedHash.isEmpty {
            let _ = storeCachedChecksum(toPath: destinationPath, hash: calculatedHash)
        }
    }
    return changed
}

func munkiResource(
    _ url: String,
    destinationPath: String,
    message: String = "",
    resume: Bool = false,
    expectedHash: String? = nil,
    verify: Bool = false,
    pkginfo: PlistDict? = nil
) throws -> Bool {
    // The high-level function for getting resources from the Munki repo.
    // Gets a given URL from the Munki server.
    // Adds any additional headers to the request if present

    // Add any additional headers specified in ManagedInstalls.plist.
    // AdditionalHttpHeaders must be an array of strings with valid HTTP
    // header format. For example:
    // <key>AdditionalHttpHeaders</key>
    // <array>
    //   <string>Key-With-Optional-Dashes: Foo Value</string>
    //   <string>another-custom-header: bar value</string>
    // </array>
    let customHeaders = pref(ADDITIONAL_HTTP_HEADERS_KEY) as? [String]
    return try getResourceIfChangedAtomically(
        url,
        destinationPath: destinationPath,
        customHeaders: customHeaders,
        expectedHash: expectedHash,
        message: message,
        resume: resume,
        verify: verify,
        pkginfo: pkginfo
    )
}
