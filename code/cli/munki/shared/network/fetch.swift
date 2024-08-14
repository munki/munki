//
//  fetch.swift
//  munki
//
//  Created by Greg Neagle on 8/13/24.
//

import Foundation

// XATTR name storing the ETAG of the file when downloaded via http(s).
let XATTR_ETAG = "com.googlecode.munki.etag"
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
    var fhash: String
    if let hash {
        fhash = hash
    } else {
        fhash = sha256hash(file: path)
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

func headerDictFromList(_ strList: [String]?) -> [String:String] {
    // Given a list of strings in http header format, return a dict.
    // A User-Agent header is added if none is present in the list.
    // If strList is nil, returns a dict with only the User-Agent header.
    var headerDict = [String:String]()
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
    customHeaders: [String:String]? = nil,
    message: String = "",
    onlyIfNewer: Bool = false,
    resume: Bool = false,
    followRedirects: String = "none",
    pkginfo: PlistDict? = nil
) throws -> [String:String]
{
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
    
    var cacheData: [String:String]? = nil
    if onlyIfNewer, pathExists(destinationPath) {
        // create a temporary Gurl object so we can extract the
        // stored caching data so we can download only if the
        // file has changed on the server
        let temp = Gurl.init(options: GurlOptions(url: url, destinationPath: destinationPath))
        cacheData = temp.getStoredHeaders()
    }
    
    let ignoreSystemProxy = pref("IgnoreSystemProxies") as? Bool ?? false
    
    let options = GurlOptions(
        url: url,
        destinationPath: tempDownloadPath,
        followRedirects: followRedirects,
        ignoreSystemProxy: ignoreSystemProxy,
        canResume: resume,
        downloadOnlyIfChanged: onlyIfNewer,
        cacheData: cacheData,
        log: displayDebug2
    )
    
    // TODO: middleware support
    
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
    customHeaders: [String:String]? = nil,
    message: String = "",
    resume: Bool = false,
    followRedirects: String = "none",
    pkginfo: PlistDict? = nil
) throws -> Bool
{
    // Gets file from HTTP URL, checking first to see if it has changed on the
    // server.

    // Returns True if a new download was required; False if the
    // item is already in the local cache.

    // Raises GurlDownloadError if there is an error.
    var eTag = ""
    var getOnlyIfNewer = false
    if pathExists(destinationPath) {
        getOnlyIfNewer = true
        // see if we have an etag attribute
        do {
            let data = try getXattr(named: XATTR_ETAG, atPath: destinationPath)
            eTag = String(data: data, encoding: .utf8) ?? ""
        } catch {
            // fall through
        }
        if !eTag.isEmpty {
            getOnlyIfNewer = false
        }
    }
    var headers: [String:String]
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
                FileAttributeKey.modificationDate: modDate
            ]
            try? FileManager.default.setAttributes(attrs, ofItemAtPath: destinationPath)
        }
    }
    if let eTag = headers["etag"], let data = eTag.data(using: .utf8) {
        // store etag in extended attribute for future use
        try? setXattr(named: XATTR_ETAG, data: data, atPath: destinationPath)
    }
    return true
}

func getResourceIfChangedAtomically(
    _ url: String,
    destinationPath: String,
    customHeaders: [String:String]? = nil,
    expectedHash: String? = nil,
    message: String = "",
    resume: Bool = false,
    verify: Bool = false,
    followRedirects: String? = nil,
    pkginfo: PlistDict? = nil
) throws -> Bool
{
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
    var resolvedFollowRedirects: String
    if let followRedirects {
        resolvedFollowRedirects = followRedirects
    } else {
        // If we haven't explicitly said to follow redirects,
        // the preference decides
        resolvedFollowRedirects = pref("FollowHTTPRedirects") as? String ?? "none"
    }
    
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
        //changed = getFileIfChangedAtomically(resolvedURL.path, destinationPath)
    } else {
        throw MunkiError("Unsupported url scheme: \(String(describing: resolvedURL.scheme)) in \(url)")
    }
    
    if changed, verify {
        
    }
    return changed
}

// it's redownloading the file even if not changed

