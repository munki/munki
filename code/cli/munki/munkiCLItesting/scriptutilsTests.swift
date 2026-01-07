//
//  scriptutilsTests.swift
//  munkiCLItesting
//
//  Created by Greg Neagle on 12/24/25.
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

private let SCRIPT_TEXT = """
#!/bin/sh
/bin/echo "Hello, world!"
"""

private let ERROR_SCRIPT_TEXT = """
#!/bin/sh
exit 1
"""

private let PKGINFO: PlistDict = [
    "postinstall_script": """
    #!/bin/sh
    /bin/echo "Hello, world!"
    """,
]

struct createExecutableFileTests {
    @Test func returnsTrue() throws {
        let filePath = try #require(tempFile(), "Can't get a temp file path")
        let success = createExecutableFile(
            atPath: filePath, withStringContents: SCRIPT_TEXT
        )
        #expect(success)
    }
}

struct runScriptTests {
    @Test func returnsZero() async throws {
        let filePath = try #require(tempFile(), "Can't get a temp file path")
        let success = createExecutableFile(
            atPath: filePath, withStringContents: SCRIPT_TEXT
        )
        try #require(success, "Expected to create a file at \(filePath)")
        let exitCode = await runScript(filePath, itemName: "Foo", scriptName: "Bar")
        #expect(exitCode == 0)
    }

    @Test func returnsNonZero() async throws {
        let filePath = try #require(tempFile(), "Can't get a temp file path")
        let success = createExecutableFile(
            atPath: filePath, withStringContents: ERROR_SCRIPT_TEXT
        )
        try #require(success, "Expected to create a file at \(filePath)")
        let exitCode = await runScript(
            filePath, itemName: "Foo", scriptName: "error_script"
        )
        #expect(exitCode != 0)
    }
}

struct runScriptAndReturnResultsTests {
    @Test func returnsExpected() async throws {
        let filePath = try #require(tempFile(), "Can't get a temp file path")
        let success = createExecutableFile(
            atPath: filePath, withStringContents: SCRIPT_TEXT
        )
        try #require(success, "Expected to create a file at \(filePath)")
        let results = await runScriptAndReturnResults(
            filePath, itemName: "Foo", scriptName: "Bar"
        )
        #expect(results.exitcode == 0)
        #expect(results.output == "Hello, world!")
    }
}

struct runEmbeddedScriptTests {
    @Test func returnsZero() async throws {
        let exitCode = await runEmbeddedScript(
            name: "postinstall_script", pkginfo: PKGINFO
        )
        #expect(exitCode == 0)
    }
}

struct runEmbeddedScriptAndReturnResultsTests {
    @Test func returnsExpected() async throws {
        let results = await runEmbeddedScriptAndReturnResults(
            name: "postinstall_script", pkginfo: PKGINFO
        )
        #expect(results.exitcode == 0)
        #expect(results.output == "Hello, world!")
    }
}
