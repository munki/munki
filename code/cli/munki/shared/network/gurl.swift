//
//  gurl.swift
//  munki
//
//  Created by Greg Neagle on 8/10/24.
//
//  Copyright 2024 Greg Neagle.
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
import Security

struct GurlOptions {
    var url: String
    var destinationPath: String
    var additionalHeaders: [String: String]?
    var username: String?
    var password: String?
    var followRedirects: String = "none"
    var ignoreSystemProxy: Bool = false
    var canResume: Bool = false
    var downloadOnlyIfChanged: Bool = false
    var cacheData: Any? // TODO: figure this type out
    var connectionTimeout: Double = 60.0
    var minimumTLSprotocol = tls_protocol_version_t.TLSv10
}

class Gurl: NSObject, URLSessionDelegate, URLSessionTaskDelegate, URLSessionDataDelegate {
    // A class for getting content from a URL
    // using NSURLSession and friends

    let GURL_XATTR = "com.googlecode.munki.downloadData"

    var options: GurlOptions
    var resume = false
    var response: URLResponse?
    var headers: [String: String]? = nil
    var status: Int = 0 // HTTP(S) status code
    var error: NSError?
    var SSLerror: Int = 0
    var done = false
    // var redirection: Any? // TODO: figure this type out
    var destination: FileHandle?
    var bytesReceived = 0
    var expectedSize = -1
    var percentComplete = 0
    var session: URLSession?
    var task: URLSessionTask?

    init(options: GurlOptions) {
        self.options = options
        super.init()
    }

    func start() {
        // Start the connection
        guard !options.destinationPath.isEmpty else {
            printStderr("No output file specified") // TODO: fix the logging
            done = true
            return
        }
        guard let url = URL(string: options.url) else {
            printStderr("Invalid URL specified") // TODO: fix the logging
            done = true
            return
        }
        let request = NSMutableURLRequest(
            url: url,
            cachePolicy: .reloadIgnoringLocalCacheData,
            timeoutInterval: options.connectionTimeout
        )
        if let additionalHeaders = options.additionalHeaders {
            for (header, value) in additionalHeaders {
                request.setValue(value, forHTTPHeaderField: header)
            }
        }
        // TODO: support resuming partial downloads
        // TODO: support last-modified/etag
        let configuration = URLSessionConfiguration.default
        if options.ignoreSystemProxy {
            configuration.connectionProxyDictionary = [
                kCFNetworkProxiesHTTPEnable: false,
                kCFNetworkProxiesHTTPSEnable: false,
            ]
        }
        configuration.tlsMinimumSupportedProtocolVersion = options.minimumTLSprotocol
        session = URLSession(
            configuration: configuration,
            delegate: self,
            delegateQueue: nil
        )
        if let task = session?.dataTask(with: request as URLRequest) {
            self.task = task
            task.resume()
            print("Started dataTask")
        }
    }

    func cancel() {
        // Cancel the session
        if let session {
            // TODO: preserve resume data?
            session.invalidateAndCancel()
        }
        done = true
    }

    func isDone() -> Bool {
        // Check if the connection request is complete. As a side effect,
        // allow the delegates to work by letting the run loop run for a bit
        if done {
            return true
        }
        // let the delegates do their thing
        RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.1))
        return done
    }

    func getStoredHeaders() -> [String: String]? {
        // Returns any stored headers for destinationPath
        if options.destinationPath.isEmpty {
            displayDebug1("\(options.destinationPath) does not exist")
            return nil
        }
        do {
            let data = try getXattr(named: GURL_XATTR, atPath: options.destinationPath)
            if let headers = try readPlist(fromData: data) as? [String: String] {
                return headers
            } else {
                displayDebug1("xattr plist decode failure")
                return nil
            }
        } catch {
            displayDebug1("xattr read failure from \(options.destinationPath)")
            return nil
        }
    }

    func storeHeaders(_ headers: [String: String]) {
        // Store headers dictionary as an xattr for options.destinationPath
        guard let data = try? plistToData(headers) else {
            displayDebug1("header convert to plist data failure")
            return
        }
        do {
            try setXattr(
                named: GURL_XATTR,
                data: data,
                atPath: options.destinationPath
            )
        } catch {
            displayDebug1("xattr write failure for \(options.destinationPath)")
            // TODO: proper error logging
        }
    }

    func normalizeHeaderDict(_ headers: [String: String]) -> [String: String] {
        // Since HTTP header names are not case-sensitive, we normalize a
        // dictionary of HTTP headers by converting all the key names to
        // lower case
        var normalizedHeaders = [String: String]()
        for (key, value) in headers {
            normalizedHeaders[key.lowercased()] = value
        }
        return normalizedHeaders
    }

    func recordError(_ error: NSError) {
        // Record any error info from completed session
        self.error = error
        // if this was an SSL error, try to extract the SSL error code
        if let underlyingError = error.userInfo["NSUnderlyingError"] as? NSError,
           let sslCode = underlyingError.userInfo["_kCFNetworkCFStreamSSLErrorOriginalValue"] as? Int
        {
            SSLerror = sslCode
        } else {
            SSLerror = 0
        }
    }

    func removeExpectedSizeFromStoredHeaders() {
        // If a successful transfer, clear the expected size so we
        // don't attempt to resume the download next time
        if String(status).hasPrefix("2"),
           var headers = getStoredHeaders(),
           headers.keys.contains("expected-length")
        {
            headers["expected-length"] = nil
            storeHeaders(headers)
        }
    }

    @objc func urlSession(_: URLSession, task _: URLSessionTask, didCompleteWithError error: (any Error)?) {
        // URLSessionTaskDelegate method
        print("urlSession:task:didCompleteWithError:")
        if let destination, !options.destinationPath.isEmpty {
            try? destination.close()
        }
        if let error {
            recordError(error as NSError)
        } else {
            removeExpectedSizeFromStoredHeaders()
        }
        done = true
    }

    @objc func urlSession(
        _: URLSession,
        dataTask _: URLSessionDataTask,
        didReceive response: URLResponse,
        completionHandler: @escaping @Sendable (URLSession.ResponseDisposition) -> Void
    ) {
        print("urlSession:dataTask:didReceive:completionHandler:")
        // URLSessionDataDelegate method
        self.response = response
        bytesReceived = 0
        percentComplete = -1
        expectedSize = Int(response.expectedContentLength)

        var downloadData = [String: String]()
        if let response = response as? HTTPURLResponse {
            // Headers and status code only available for HTTP/S transfers
            status = response.statusCode
            headers = response.allHeaderFields as? [String: String]
            if let headers {
                let normalizedHeaders = normalizeHeaderDict(headers)
                if let lastModified = normalizedHeaders["last-modified"] {
                    downloadData["last-modified"] = lastModified
                }
                if let eTag = normalizedHeaders["etag"] {
                    downloadData["etag"] = eTag
                }
            }
            downloadData["expected-length"] = String(expectedSize)
        }
        if destination == nil, !options.destinationPath.isEmpty {
            if resume, status == 206 {
                // TODO: implement download resume
            } else if String(status).hasPrefix("2") {
                // not resuming, just open the file for writing
                destination = FileHandle(forWritingAtPath: options.destinationPath)
                // store some headers with the file for use if we need to resume
                // the download and for future checking if the file on the server
                // has changed
                storeHeaders(downloadData)
            }
        }
        completionHandler(.allow)
    }

    @objc func urlSession(
        _: URLSession,
        task _: URLSessionTask,
        willPerformHTTPRedirection _: HTTPURLResponse,
        newRequest request: URLRequest,
        completionHandler: @escaping @Sendable (URLRequest?) -> Void
    ) {
        print("urlSession:task:willPerformHTTPRedirection:newRequest:completionHandler:")
        // URLSessionTaskDelegate method
        guard let newURL = request.url else {
            // deny the redirect
            completionHandler(nil)
            return
        }
        if options.followRedirects == "all" {
            // TODO: log "Allowing redirect to \(newURL)"
            print("Allowing redirect to \(newURL)")
            // allow redirect
            completionHandler(request)
            return
        } else if options.followRedirects == "all", newURL.scheme == "https" {
            // allow redirects to https URLs
            completionHandler(request)
            return
        }
        // If we're here either the preference was set to 'none' (or not set)
        // or the url we're forwarding on to isn't https
        // TODO: log "Denying redirect to \(newURL)"
        print("Denying redirect to \(newURL)")
        completionHandler(nil)
    }

    @objc func urlSession(
        _: URLSession,
        task _: URLSessionTask,
        didReceive challenge: URLAuthenticationChallenge,
        completionHandler: @escaping @Sendable (URLSession.AuthChallengeDisposition, URLCredential?) -> Void
    ) {
        print("urlSession:task:didReceive:completionHandler:")
        // URLSessionTaskDelegate method
        // Handle an authentication challenge
        let supportedAuthMethods = [
            NSURLAuthenticationMethodDefault,
            NSURLAuthenticationMethodHTTPBasic,
            NSURLAuthenticationMethodHTTPDigest,
        ]

        let protectionSpace = challenge.protectionSpace
        let host = protectionSpace.host
        let realm = protectionSpace.realm
        let authenticationMethod = protectionSpace.authenticationMethod
        // TODO: log "Authentication challenge for Host: \(host) Realm: \(realm) AuthMethod: \(authenticationMethod)"
        print("Authentication challenge for Host: \(host) Realm: \(realm) AuthMethod: \(authenticationMethod)")
        if challenge.previousFailureCount > 0 {
            // we have the wrong credentials. just fail
            // TODO: log "Previous authentication attempt failed."
            print("Previous authentication attempt failed.")
            completionHandler(.cancelAuthenticationChallenge, nil)
        }
        // Handle HTTP Basic and Digest challenge
        if let username = options.username,
           let password = options.password,
           supportedAuthMethods.contains(authenticationMethod)
        {
            // TODO: log "Will attempt to authenticate."
            print("Will attempt to authenticate.")
            // TODO: log "Username: \(username) Password: \(String(repeating: "*", count: password.count))"
            print("Username: \(username) Password: \(String(repeating: "*", count: password.count))")
            let credential = URLCredential(user: username, password: password, persistence: .none)
            completionHandler(.useCredential, credential)
        } else if authenticationMethod == NSURLAuthenticationMethodClientCertificate {
            // TODO: log "Client certificate required"
            // get issuers info from the response
            if let distingusihedNames = protectionSpace.distinguishedNames {
                // distingusihedNames is an array of Data blobs
                // each blob is DER encoded
                // TODO: decode this stuff and handle it
            }
            // but right now, we can't handle it
            completionHandler(.cancelAuthenticationChallenge, nil)
        } else {
            // fall back to system-provided default behavior
            // TODO: log("Allowing OS to handle authentication request")
            print("Allowing OS to handle authentication request")
            completionHandler(.performDefaultHandling, nil)
        }
    }

    @objc func urlSession(_: URLSession, dataTask _: URLSessionDataTask, didReceive data: Data) {
        print("urlSession:dataTask:didReceive:")
        // URLSessionDataDelegate method
        // Handle received data
        if let destination {
            destination.write(data)
        } else if let str = String(data: data, encoding: String.Encoding.utf8) {
            // TODO: log(str)
            print(str)
        }
        bytesReceived += data.count
        // NSURLResponseUnknownLength = -1
        if expectedSize > 0 {
            percentComplete = Int(Double(bytesReceived) / Double(expectedSize) * 100)
        }
    }
}
