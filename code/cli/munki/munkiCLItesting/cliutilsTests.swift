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

struct cliutilsTests {
    /// Basic tests for runCLI functionality
    @Test func runCLIReturnsExpected() {
        let expectedOutput = "Hello, world"
        let results = runCLI("/bin/echo", arguments: [expectedOutput])
        #expect(results.exitcode == 0)
        #expect(results.output == expectedOutput)
    }

    @Test func runCLIReturnsErrorForNonExistentTool() {
        let results = runCLI("/bin/_does_not_exist")
        #expect(results.exitcode != 0)
    }

    @Test func runCLIReturnsErrorWhenExpected() {
        let results = runCLI("/usr/bin/false")
        #expect(results.exitcode == 1)
    }

    /// Basic tests for runCliAsync functionality
    @Test func runCliAsyncReturnsExpected() async {
        let expectedOutput = "Hello, world"
        let results = await runCliAsync("/bin/echo", arguments: [expectedOutput])
        #expect(results.exitcode == 0)
        #expect(results.output == expectedOutput)
    }

    @Test func runCliAsyncReturnsErrorForNonExistentTool() async {
        let results = await runCliAsync("/bin/_does_not_exist")
        #expect(results.exitcode != 0)
    }

    @Test func runCliAsyncReturnsErrorWhenExpected() async {
        let results = await runCliAsync("/usr/bin/false")
        #expect(results.exitcode == 1)
    }

    /// Basic tests for checkOutput functionality
    @Test func checkOutputReturnsExpected() throws {
        let expectedOutput = "Hello, world"
        let toolOutput = try checkOutput("/bin/echo", arguments: [expectedOutput])
        #expect(toolOutput == expectedOutput)
    }

    @Test func checkOutputThrowsForNonExistentTool() throws {
        let error = #expect(throws: ProcessError.self) {
            try checkOutput("/bin/_does_not_exist")
        }
        #expect(error != nil)
    }

    @Test func checkOutputThrowsForToolError() throws {
        let error = #expect(throws: ProcessError.self) {
            try checkOutput("/usr/bin/false")
        }
        #expect(error != nil)
    }
}
