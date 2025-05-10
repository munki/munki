//
//  MWA2APIRepo.swift
//  MWA2APIRepo
//
//  Created by Greg Neagle on 5/8/25.
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

class RepoError: Error, CustomStringConvertible {
    private let message: String

    // Creates a new error with the given message.
    public init(_ message: String) {
        self.message = message
    }

    public var description: String {
        return message
    }
}

/// Ensures we can return a useful localizedError
extension RepoError: LocalizedError {
    var errorDescription: String? {
        return message
    }
}

class HTTPRepoError: Error, CustomStringConvertible {
    public let errorCode: Int

    public init(_ errorCode: Int) {
        self.errorCode = errorCode
    }

    public var description: String {
        return "HTTP error code \(errorCode)"
    }
}

/// Ensures we can return a useful localizedError
extension HTTPRepoError: LocalizedError {
    var errorDescription: String? {
        return description
    }
}

/// Throws an error if we don't get an HTTP statusCode in the range 200-299
private func throwIfStatusNotOK(_ response: URLResponse) throws {
    if let httpResponse = response as? HTTPURLResponse {
        if !(200 ... 299).contains(httpResponse.statusCode) {
            throw HTTPRepoError(httpResponse.statusCode)
        }
    } else {
        throw RepoError("Response was not an HTTPURLResponse")
    }
}

class MWA2APIRepo: Repo {
    var baseURL: URL
    var authtoken: String = ""

    required init(_ url: String) throws {
        if let baseURL = URL(string: url) {
            self.baseURL = baseURL
            getAuthToken()
        } else {
            throw RepoError("Could not create valid URL from \(url)")
        }
    }

    /// retrieve an authtoken from env vars, or prompt for one
    private func getAuthToken() {
        if authtoken.isEmpty {
            // try to get authtoken from environment var
            let env = ProcessInfo.processInfo.environment
            if let tokenFromEnv = env["MUNKIREPO_AUTHTOKEN"] {
                authtoken = tokenFromEnv
                return
            }
            // prompt user for credentials
            var username = ""
            print("Connecting to \(baseURL)...")
            print("Username: ", terminator: "")
            if let input = readLine(strippingNewline: true) {
                username = input
            }
            var password = ""
            if let input = getpass("Password: ") {
                password = String(cString: input, encoding: .utf8) ?? ""
            }
            let userAndPass = (username + ":" + password)
            if let userAndPassData = userAndPass.data(using: .utf8) {
                let base64EncodedString = userAndPassData.base64EncodedString()
                authtoken = "Basic \(base64EncodedString)"
            }
        }
    }

    /// Convenience wrapper since we always need to add the Authorization header to every request
    private func baseRequest(_ url: URL) -> URLRequest {
        var request = URLRequest(url: url)
        if !authtoken.isEmpty {
            request.setValue(authtoken, forHTTPHeaderField: "Authorization")
        }
        return request
    }

    // MARK: Repo protocol implementations

    /// Returns a list of items for the "kind"; AKA a list of catalogs, manifests, pkgs, etc
    func list(_ kind: String) async throws -> [String] {
        var url = baseURL
        if #available(macOS 13.0, *) {
            url = baseURL.appending(path: kind)
        } else {
            // Fallback on earlier versions
            url = baseURL.appendingPathComponent(kind)
        }
        if #available(macOS 13.0, *) {
            url = url.appending(
                queryItems: [URLQueryItem(name: "api_fields", value: "filename")])
        } else {
            // Fallback on earlier versions
            let urlString = url.absoluteString + "?api_fields=filename"
            if let tempUrl = URL(string: urlString) {
                url = tempUrl
            }
        }
        var request = baseRequest(url)
        request.setValue("application/xml", forHTTPHeaderField: "Accept")
        let (data, response) = try await URLSession.shared.data(for: request)
        try throwIfStatusNotOK(response)
        let plist = try PropertyListSerialization.propertyList(from: data, format: nil)
        let resourceType = (kind as NSString).pathComponents.first ?? ""
        if ["catalogs", "manifests", "pkgsinfo"].contains(resourceType) {
            let dl = plist as? [[String: String]] ?? []
            let filenames = dl.compactMap { $0["filename"] }
            return filenames
        }
        return plist as? [String] ?? []
    }

    /// Gets the requested item (like "manifests/site_default") and returns it as Data
    func get(_ identifier: String) async throws -> Data {
        var url = baseURL
        if #available(macOS 13.0, *) {
            url = baseURL.appending(path: identifier)
        } else {
            // Fallback on earlier versions
            url = baseURL.appendingPathComponent(identifier)
        }
        var request = baseRequest(url)
        let resourceType = (identifier as NSString).pathComponents.first ?? ""
        if ["catalogs", "manifests", "pkgsinfo"].contains(resourceType) {
            request.setValue("application/xml", forHTTPHeaderField: "Accept")
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        try throwIfStatusNotOK(response)
        return data
    }

    /// Gets the requested item (like "manifests/site_default") saves it to local_file_path
    func get(_ identifier: String, toFile local_file_path: String) async throws {
        var url = baseURL
        if #available(macOS 13.0, *) {
            url = baseURL.appending(path: identifier)
        } else {
            // Fallback on earlier versions
            url = baseURL.appendingPathComponent(identifier)
        }
        var request = baseRequest(url)
        let resourceType = (identifier as NSString).pathComponents.first ?? ""
        if ["catalogs", "manifests", "pkgsinfo"].contains(resourceType) {
            request.setValue("application/xml", forHTTPHeaderField: "Accept")
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        try throwIfStatusNotOK(response)
        FileManager.default.createFile(atPath: local_file_path, contents: data)
    }

    /// Stores Data in the repo as the resource identified by identifier: "/manifests/foo" or "pkgsinfo/bar", etc
    func put(_ identifier: String, content: Data) async throws {
        var url = baseURL
        if #available(macOS 13.0, *) {
            url = baseURL.appending(path: identifier)
        } else {
            // Fallback on earlier versions
            url = baseURL.appendingPathComponent(identifier)
        }
        var request = baseRequest(url)
        let resourceType = (identifier as NSString).pathComponents.first ?? ""
        if ["catalogs", "manifests", "pkgsinfo"].contains(resourceType) {
            request.setValue("application/xml", forHTTPHeaderField: "Content-type")
        }
        request.httpMethod = "PUT"
        let (_, response) = try await URLSession.shared.upload(for: request, from: content)
        try throwIfStatusNotOK(response)
    }

    /// Uploads the local_file_path, storing it as the resource identified by identifier
    func put(_ identifier: String, fromFile local_file_path: String) async throws {
        // TODO: handle pkgs and icons differently (POST form-encoded)
        var url = baseURL
        if #available(macOS 13.0, *) {
            url = baseURL.appending(path: identifier)
        } else {
            // Fallback on earlier versions
            url = baseURL.appendingPathComponent(identifier)
        }
        let localFile = URL(fileURLWithPath: local_file_path)
        var request = baseRequest(url)
        let resourceType = (identifier as NSString).pathComponents.first ?? ""
        if ["catalogs", "manifests", "pkgsinfo"].contains(resourceType) {
            request.setValue("application/xml", forHTTPHeaderField: "Content-type")
        }
        request.httpMethod = "PUT"
        let (_, response) = try await URLSession.shared.upload(for: request, fromFile: localFile)
        try throwIfStatusNotOK(response)
    }

    /// Deletes a repo item
    func delete(_ identifier: String) async throws {
        var url = baseURL
        if #available(macOS 13.0, *) {
            url = baseURL.appending(path: identifier)
        } else {
            // Fallback on earlier versions
            url = baseURL.appendingPathComponent(identifier)
        }
        var request = baseRequest(url)
        request.httpMethod = "DELETE"
        let (_, response) = try await URLSession.shared.data(for: request)
        try throwIfStatusNotOK(response)
    }

    /// Non-filesystem repos (like this one) should return nil
    func pathFor(_: String) -> String? {
        // not a file-system-based repo, so no local path
        return nil
    }
}

// MARK: dylib "interface"

/// Function with C calling style for our dylib. We use it to instantiate the Repo object and return an instance
@_cdecl("createPlugin")
public func createPlugin() -> UnsafeMutableRawPointer {
    return Unmanaged.passRetained(MWA2APIRepoBuilder()).toOpaque()
}

final class MWA2APIRepoBuilder: RepoPluginBuilder {
    override func connect(_ url: String) -> Repo? {
        return try? MWA2APIRepo(url)
    }
}
