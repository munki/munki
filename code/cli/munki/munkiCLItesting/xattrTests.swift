//
//  xattrTests.swift
//  munkiCLItesting
//
//  Created by Greg Neagle on 5/4/25.
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

import Testing

struct xattrTests {
    /// remove, list, add, and get xattrs
    @Test func runXattrTests() throws {
        let filepath = tempFile()
        let unwrappedFilepath = try #require(filepath, "Can't create temporary filepath")
        try #require(FileManager.default.createFile(
            atPath: unwrappedFilepath, contents: nil
        ),
        "Could not create a temporary file")

        var xattrs = (try? listXattrs(atPath: unwrappedFilepath)) ?? []
        for xattr in xattrs {
            try? removeXattr(xattr, atPath: unwrappedFilepath)
        }
        xattrs = (try? listXattrs(atPath: unwrappedFilepath)) ?? []
        // #expect(xattrs.isEmpty)

        let xattrName = "com.googlecode.munki.test"
        let xattrValue = "Hello, World!".data(using: .utf8)!
        try? setXattr(named: xattrName, data: xattrValue, atPath: unwrappedFilepath)
        xattrs = (try? listXattrs(atPath: unwrappedFilepath)) ?? []
        #expect(xattrs.contains(xattrName))

        let retrievedXattrValue = (try? getXattr(named: xattrName, atPath: unwrappedFilepath)) ?? Data()
        #expect(retrievedXattrValue == xattrValue)
    }
}
