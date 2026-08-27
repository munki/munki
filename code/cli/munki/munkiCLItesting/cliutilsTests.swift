//
//  cliutilsTests.swift
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

struct runCLITests {
    /// Basic tests for runCLI functionality
    @Test func outputIsExpected() {
        let expectedOutput = "Hello, world"
        let results = runCLI("/bin/echo", arguments: [expectedOutput])
        #expect(results.exitcode == 0)
        #expect(results.output == expectedOutput)
    }

    @Test func returnsErrorForNonExistentTool() {
        let results = runCLI("/bin/_does_not_exist")
        #expect(results.exitcode != 0)
    }

    @Test func returnsErrorWhenExpected() {
        let results = runCLI("/usr/bin/false")
        #expect(results.exitcode == 1)
    }
}

struct runCliAsyncTests {
    /// Basic tests for runCliAsync functionality
    @Test func outputIsExpected() async {
        let expectedOutput = "Hello, world"
        let results = await runCliAsync("/bin/echo", arguments: [expectedOutput])
        #expect(results.exitcode == 0)
        #expect(results.output == expectedOutput)
    }

    @Test func returnsErrorForNonExistentTool() async {
        let results = await runCliAsync("/bin/_does_not_exist")
        #expect(results.exitcode != 0)
    }

    @Test func returnsErrorWhenExpected() async {
        let results = await runCliAsync("/usr/bin/false")
        #expect(results.exitcode == 1)
    }

    @Test func throwsExceptionForTimeout() async throws {
        await #expect(throws: ProcessError.self) {
            _ = try await runCliAsync("/bin/sleep", arguments: ["2"], timeout: 1)
        }
    }

    @Test func doesNotThrowExceptionForTimeout() async throws {
        _ = try await runCliAsync("/bin/sleep", arguments: ["1"], timeout: 2)
    }
}

struct checkOutputTests {
    /// Basic tests for checkOutput functionality
    @Test func outputIsExpected() throws {
        let expectedOutput = "Hello, world"
        let toolOutput = try checkOutput("/bin/echo", arguments: [expectedOutput])
        #expect(toolOutput == expectedOutput)
    }

    @Test func throwsExceptionForNonExistentTool() throws {
        #expect(throws: ProcessError.self) {
            try checkOutput("/bin/_does_not_exist")
        }
    }

    @Test func throwsExceptionForToolError() throws {
        #expect(throws: ProcessError.self) {
            try checkOutput("/usr/bin/false")
        }
    }
}
