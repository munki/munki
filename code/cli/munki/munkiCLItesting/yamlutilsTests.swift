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

    /// Empty-string values must round-trip through YAML write + read.
    /// Regression test for finding #3 in the yaml-support code review:
    /// previously `sanitizeForYaml` filtered out any string value where
    /// `str.isEmpty`, so e.g. `blocking_applications: ""` or an explicit
    /// empty `description:` silently disappeared on save. After the fix,
    /// empty-string values must be emitted explicitly quoted (`key: ''`)
    /// and parse back as empty strings, not null/missing.
    @Test func emptyStringValuesRoundTrip() async throws {
        let input: [String: Any] = [
            "name": "TestApp",
            "version": "1.0",
            "description": "",
            "blocking_applications": "",
            "notes": "non-empty",
            "receipts": [
                [
                    "packageid": "com.example.testapp",
                    "version": "1.0",
                    "filename": ""
                ] as [String: Any]
            ]
        ]

        let yamlString = try yamlToString(input)

        // The empty-string keys must be present in the written YAML.
        #expect(yamlString.contains("description:"),
                "description key was dropped from YAML output: \(yamlString)")
        #expect(yamlString.contains("blocking_applications:"),
                "blocking_applications key was dropped from YAML output: \(yamlString)")
        #expect(yamlString.contains("filename:"),
                "nested filename empty-string key was dropped: \(yamlString)")

        // And the emitted empty strings must be explicitly quoted so they
        // parse back as "" rather than null.
        #expect(yamlString.contains("description: ''") || yamlString.contains("description: \"\""),
                "description empty string was not quoted: \(yamlString)")
        #expect(yamlString.contains("blocking_applications: ''") || yamlString.contains("blocking_applications: \"\""),
                "blocking_applications empty string was not quoted: \(yamlString)")

        let parsed = try #require(
            readYaml(fromString: yamlString) as? [String: Any],
            "Could not re-parse YAML output"
        )
        #expect(parsed["description"] as? String == "",
                "description did not round-trip as empty string (got \(String(describing: parsed["description"])))")
        #expect(parsed["blocking_applications"] as? String == "",
                "blocking_applications did not round-trip as empty string (got \(String(describing: parsed["blocking_applications"])))")
        #expect(parsed["name"] as? String == "TestApp")
        #expect(parsed["notes"] as? String == "non-empty")

        let receipts = try #require(parsed["receipts"] as? [[String: Any]])
        #expect(receipts.first?["filename"] as? String == "",
                "nested filename empty string did not round-trip (got \(String(describing: receipts.first?["filename"])))")
    }

    /// Known script field keys always emit as literal block scalars (`|`),
    /// even when the content is short or single-line. Key-based detection wins.
    @Test func scriptFieldShortContentEmitsAsLiteralBlock() async throws {
        let pkginfo: [String: Any] = [
            "name": "TestApp",
            "version": "1.0",
            "preinstall_script": "echo hi"
        ]
        let output = try yamlToString(pkginfo)
        // A YAML literal block starts with `|` on the key line, followed by an
        // indented value line. Plain/quoted scalars would put the value on the
        // same line as the key.
        #expect(output.contains("preinstall_script: |"),
                "Expected literal block for preinstall_script, got:\n\(output)")
        #expect(!output.contains("preinstall_script: echo hi"),
                "Expected script value on a new line, not inline. Got:\n\(output)")
    }

    /// All known script field keys round-trip as literal blocks.
    /// Regression guard against accidental removal of entries from `scriptFieldKeys`.
    @Test func allKnownScriptFieldsEmitAsLiteralBlock() async throws {
        let keys = [
            "preinstall_script",
            "postinstall_script",
            "preuninstall_script",
            "postuninstall_script",
            "uninstall_script",
            "installcheck_script",
            "uninstallcheck_script",
        ]
        for key in keys {
            let pkginfo: [String: Any] = [key: "exit 0"]
            let output = try yamlToString(pkginfo)
            #expect(output.contains("\(key): |"),
                    "Expected literal block for \(key), got:\n\(output)")
        }
    }

    /// A non-script field (`description`) must NOT emit as a literal block even
    /// when its content contains a shebang-looking prefix. This is the main
    /// false-positive the tightened heuristic is designed to prevent.
    @Test func descriptionWithShebangPrefixIsNotLiteralBlock() async throws {
        let pkginfo: [String: Any] = [
            "name": "TestApp",
            "description": "#!/bin/sh usage note for admins"
        ]
        let output = try yamlToString(pkginfo)
        // Single-line content on a non-script key must never become a literal block.
        #expect(!output.contains("description: |"),
                "Single-line description must not emit as literal block. Got:\n\(output)")
    }

    /// Short multi-line content on an arbitrary (non-script, non-prose) key with
    /// script-like tokens ("if ", indentation) must NOT trigger literal-block
    /// emission under the new stricter heuristic. Previously, content like this
    /// was a false positive.
    @Test func shortMultilineNonScriptDoesNotBecomeLiteralBlock() async throws {
        let pkginfo: [String: Any] = [
            "name": "TestApp",
            // Short (< 80 chars) multi-line string with tokens the old heuristic
            // flagged as "script-like". No shebang, so the new heuristic treats
            // it as folded prose, not a literal script block.
            "release_notes": "line one\nif fixed: bug"
        ]
        let output = try yamlToString(pkginfo)
        #expect(!output.contains("release_notes: |"),
                "Short multi-line non-script value must not emit as literal. Got:\n\(output)")
    }

    /// A multi-line value with a shebang on an unknown key IS treated as a script
    /// (literal block). Shebang is the strongest content-based signal we keep.
    @Test func multilineWithShebangOnUnknownKeyUsesLiteralBlock() async throws {
        let pkginfo: [String: Any] = [
            "custom_script_field": "#!/bin/sh\necho hi\nexit 0"
        ]
        let output = try yamlToString(pkginfo)
        #expect(output.contains("custom_script_field: |"),
                "Multi-line shebang content should emit as literal. Got:\n\(output)")
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
