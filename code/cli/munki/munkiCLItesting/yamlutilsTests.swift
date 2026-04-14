//
//  yamlutilsTests.swift
//  munkiCLItesting
//
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

struct yamlFloatResolverTests {
    /// Trailing-zero version strings must survive parsing.
    /// Without the custom resolver, Yams parses `10.10` as Double 10.1,
    /// losing the trailing zero before normalization can recover it.
    @Test func trailingZeroVersionsSurvive() async throws {
        let yaml = """
        minimum_os_version: 10.10
        maximum_os_version: 11.20
        version: 1.0
        """
        let parsed = try #require(
            readYaml(fromString: yaml) as? [String: Any],
            "Could not parse YAML"
        )
        #expect(parsed["minimum_os_version"] as? String == "10.10")
        #expect(parsed["maximum_os_version"] as? String == "11.20")
        #expect(parsed["version"] as? String == "1.0")
    }

    /// Non-trailing-zero floats still parse as strings under the custom resolver.
    @Test func floatLikeVersionsParseAsStrings() async throws {
        let yaml = """
        minimum_os_version: 10.13
        version: 2.3
        another_version: 26.4
        """
        let parsed = try #require(
            readYaml(fromString: yaml) as? [String: Any],
            "Could not parse YAML"
        )
        #expect(parsed["minimum_os_version"] as? String == "10.13")
        #expect(parsed["version"] as? String == "2.3")
        #expect(parsed["another_version"] as? String == "26.4")
    }

    /// Bare integers on version-like keys are normalized to strings by normalizeYamlTypes.
    @Test func integerVersionsNormalizedToStrings() async throws {
        let yaml = """
        minimum_os_version: 14
        version: 10
        """
        let parsed = try #require(
            readYaml(fromString: yaml) as? [String: Any],
            "Could not parse YAML"
        )
        #expect(parsed["minimum_os_version"] as? String == "14")
        #expect(parsed["version"] as? String == "10")
    }

    /// Integer values on non-version-like keys must stay as integers.
    /// Processors and size comparisons need native int types.
    @Test func nonVersionIntegersStayInt() async throws {
        let yaml = """
        installer_item_size: 1024
        unattended_install: true
        optional: false
        """
        let parsed = try #require(
            readYaml(fromString: yaml) as? [String: Any],
            "Could not parse YAML"
        )
        #expect(parsed["installer_item_size"] as? Int == 1024)
        #expect(parsed["unattended_install"] as? Bool == true)
        #expect(parsed["optional"] as? Bool == false)
    }

    /// Explicitly quoted versions must also round-trip unchanged.
    @Test func quotedVersionsUnchanged() async throws {
        let yaml = """
        minimum_os_version: '10.10'
        version: "1.0"
        """
        let parsed = try #require(
            readYaml(fromString: yaml) as? [String: Any],
            "Could not parse YAML"
        )
        #expect(parsed["minimum_os_version"] as? String == "10.10")
        #expect(parsed["version"] as? String == "1.0")
    }

    /// Nested dicts (e.g., inside receipts or installs) must also preserve versions.
    @Test func nestedVersionsPreserved() async throws {
        let yaml = """
        name: TestApp
        version: 1.0
        receipts:
          - packageid: com.example.testapp
            version: 2.10
        installs:
          - type: application
            path: /Applications/TestApp.app
            CFBundleShortVersionString: 3.20
        """
        let parsed = try #require(
            readYaml(fromString: yaml) as? [String: Any],
            "Could not parse YAML"
        )
        #expect(parsed["version"] as? String == "1.0")

        let receipts = try #require(parsed["receipts"] as? [[String: Any]])
        #expect(receipts.first?["version"] as? String == "2.10")

        let installs = try #require(parsed["installs"] as? [[String: Any]])
        #expect(installs.first?["CFBundleShortVersionString"] as? String == "3.20")
    }
}
