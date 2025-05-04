//
//  installationstateTests.swift
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

struct installedStateTests {
    /// a pkginfo item with "OnDemand" == true should always be considered as not installed
    @Test func onDemandReturnsNotInstalled() async throws {
        let item: PlistDict = [
            "name": "Foo",
            "version": "1.2.3",
            "OnDemand": true,
        ]
        #expect(await installedState(item) == .thisVersionNotInstalled)
    }

    /// If an installcheck_script returns 0, consider the item not installed
    @Test func installCheckScriptZeroExitReturnsNotInstalled() async throws {
        let item: PlistDict = [
            "name": "Foo",
            "version": "1.2.3",
            "installcheck_script": """
            #!/bin/sh
            exit 0
            """,
        ]
        #expect(await installedState(item) == .thisVersionNotInstalled)
    }

    /// If an installcheck_script returns non-zero, consider the item installed
    @Test func installCheckScriptNonZeroExitReturnsInstalled() async throws {
        let item: PlistDict = [
            "name": "Foo",
            "version": "1.2.3",
            "installcheck_script": """
            #!/bin/sh
            exit 1
            """,
        ]
        #expect(await installedState(item) == .thisVersionInstalled)
    }

    /// If version_script returns a higher version than the item's version, return .newerVersionInstalled
    @Test func versionScriptHigherVersionExitReturnsNewerVersionInstalled() async throws {
        let item: PlistDict = [
            "name": "Foo",
            "version": "1.2.3",
            "version_script": """
            #!/bin/sh
            echo "1.20"
            """,
        ]
        #expect(await installedState(item) == .newerVersionInstalled)
    }

    /// If version_script returns the same version as the item's version, return .thisVersionInstalled
    @Test func versionScriptSameVersionExitReturnsThisVersionInstalled() async throws {
        let item: PlistDict = [
            "name": "Foo",
            "version": "1.2.3",
            "version_script": """
            #!/bin/sh
            echo "1.2.3.0"
            """,
        ]
        #expect(await installedState(item) == .thisVersionInstalled)
    }

    /// If version_script returns a lower version than the item's version, return .thisVersionNotInstalled
    @Test func versionScriptLowerVersionReturnsNotInstalled() async throws {
        let item: PlistDict = [
            "name": "Foo",
            "version": "1.2.3",
            "version_script": """
            #!/bin/sh
            echo "1.2"
            """,
        ]
        #expect(await installedState(item) == .thisVersionNotInstalled)
    }

    /// If version_script returns nothing, return .thisVersionNotInstalled
    @Test func versionScriptNoOutputReturnsNotInstalled() async throws {
        let item: PlistDict = [
            "name": "Foo",
            "version": "1.2.3",
            "version_script": """
            #!/bin/sh
            echo ""
            """,
        ]
        #expect(await installedState(item) == .thisVersionNotInstalled)
    }

    /// If version_script returns only whitespace, return .thisVersionNotInstalled
    @Test func versionScriptWhitespaceOutputReturnsNotInstalled() async throws {
        let item: PlistDict = [
            "name": "Foo",
            "version": "1.2.3",
            "version_script": """
            #!/bin/sh
            echo "     \n\t"
            """,
        ]
        #expect(await installedState(item) == .thisVersionNotInstalled)
    }

    /*
         /// If version_script something that isn't parseable as a version, return .thisVersionNotInstalled
         @Test func installedStateWithVersionScriptInvalidOutputReturnsNotInstalled() async throws {
             let item: PlistDict = [
                 "name": "Foo",
                 "version": "1.2.3",
                 "version_script": """
     #!/bin/sh
     echo "Foobarbaz"
     """
             ]
             #expect(await installedState(item) == .thisVersionNotInstalled)
         }
     */

    /// If version_script exits non-zero, return .thisVersionNotInstalled
    @Test func versionScriptErrorReturnsNotInstalled() async throws {
        let item: PlistDict = [
            "name": "Foo",
            "version": "1.2.3",
            "version_script": """
            #!/bin/sh
            exit 1
            """,
        ]
        #expect(await installedState(item) == .thisVersionNotInstalled)
    }
}

struct someVersionInstalledTests {
    /// someVersionInstalled() with an OnDemand item should return false
    @Test func itemIsOnDemandReturnsFalse() async throws {
        let item: PlistDict = [
            "name": "Foo",
            "version": "1.2.3",
            "OnDemand": true,
        ]
        #expect(await someVersionInstalled(item) == false)
    }

    /// If an installcheck_script returns 0, consider the item not installed
    @Test func installCheckScriptZeroExitReturnsFalse() async throws {
        let item: PlistDict = [
            "name": "Foo",
            "version": "1.2.3",
            "installcheck_script": """
            #!/bin/sh
            exit 0
            """,
        ]
        #expect(await someVersionInstalled(item) == false)
    }

    /// If an installcheck_script returns non-zero, consider the item installed
    @Test func installCheckScriptNonZeroExitReturnsTrue() async throws {
        let item: PlistDict = [
            "name": "Foo",
            "version": "1.2.3",
            "installcheck_script": """
            #!/bin/sh
            exit 1
            """,
        ]
        #expect(await someVersionInstalled(item) == true)
    }

    /// If version_script returns a higher version than the item's version, return true
    @Test func versionScriptHigherVersionExitReturnsTrue() async throws {
        let item: PlistDict = [
            "name": "Foo",
            "version": "1.2.3",
            "version_script": """
            #!/bin/sh
            echo "1.20"
            """,
        ]
        #expect(await someVersionInstalled(item) == true)
    }

    /// If version_script returns the same version as the item's version, return true
    @Test func versionScriptSameVersionExitReturnsTrue() async throws {
        let item: PlistDict = [
            "name": "Foo",
            "version": "1.2.3",
            "version_script": """
            #!/bin/sh
            echo "1.2.3.0"
            """,
        ]
        #expect(await someVersionInstalled(item) == true)
    }

    /// If version_script returns a lower version than the item's version, return true
    @Test func versionScriptLowerVersionExitReturnsTrue() async throws {
        let item: PlistDict = [
            "name": "Foo",
            "version": "1.2.3",
            "version_script": """
            #!/bin/sh
            echo "1.2.0"
            """,
        ]
        #expect(await someVersionInstalled(item) == true)
    }

    /// If version_script returns nothing, return false
    @Test func versionScriptNoOutputReturnsFalse() async throws {
        let item: PlistDict = [
            "name": "Foo",
            "version": "1.2.3",
            "version_script": """
            #!/bin/sh
            echo ""
            """,
        ]
        #expect(await someVersionInstalled(item) == false)
    }

    /// If version_script returns only whitespace, return false
    @Test func versionScriptWhitespaceOutputReturnsFalse() async throws {
        let item: PlistDict = [
            "name": "Foo",
            "version": "1.2.3",
            "version_script": """
            #!/bin/sh
            echo "     \n\t"
            """,
        ]
        #expect(await someVersionInstalled(item) == false)
    }

    /// If version_script exits non-zero, return false
    @Test func versionScriptErrorReturnsFalse() async throws {
        let item: PlistDict = [
            "name": "Foo",
            "version": "1.2.3",
            "version_script": """
            #!/bin/sh
            exit 1
            """,
        ]
        #expect(await someVersionInstalled(item) == false)
    }
}

struct evidenceThisIsInstalledTests {
    /// someVersionInstalled() with an OnDemand item should return false
    @Test func itemIsOnDemandReturnsFalse() async throws {
        let item: PlistDict = [
            "name": "Foo",
            "version": "1.2.3",
            "OnDemand": true,
        ]
        #expect(await evidenceThisIsInstalled(item) == false)
    }

    /// If an uninstallcheck_script returns 0, consider the item not installed
    @Test func uninstallCheckScriptZeroExitReturnsTrue() async throws {
        let item: PlistDict = [
            "name": "Foo",
            "version": "1.2.3",
            "uninstallcheck_script": """
            #!/bin/sh
            exit 0
            """,
        ]
        #expect(await evidenceThisIsInstalled(item) == true)
    }

    /// If an uninstallcheck_script returns non-zero, consider the item installed
    @Test func uninstallCheckScriptNonZeroExitReturnsFalse() async throws {
        let item: PlistDict = [
            "name": "Foo",
            "version": "1.2.3",
            "uninstallcheck_script": """
            #!/bin/sh
            exit 1
            """,
        ]
        #expect(await evidenceThisIsInstalled(item) == false)
    }

    /// If an installcheck_script returns 0, consider the item not installed
    @Test func installCheckScriptZeroExitReturnsFalse() async throws {
        let item: PlistDict = [
            "name": "Foo",
            "version": "1.2.3",
            "installcheck_script": """
            #!/bin/sh
            exit 0
            """,
        ]
        #expect(await evidenceThisIsInstalled(item) == false)
    }

    /// If an installcheck_script returns non-zero, consider the item installed
    @Test func installCheckScriptNonZeroExitReturnsTrue() async throws {
        let item: PlistDict = [
            "name": "Foo",
            "version": "1.2.3",
            "installcheck_script": """
            #!/bin/sh
            exit 1
            """,
        ]
        #expect(await evidenceThisIsInstalled(item) == true)
    }

    /// If version_script returns a higher version than the item's version, return true
    @Test func versionScriptHigherVersionExitReturnsTrue() async throws {
        let item: PlistDict = [
            "name": "Foo",
            "version": "1.2.3",
            "version_script": """
            #!/bin/sh
            echo "1.20"
            """,
        ]
        #expect(await evidenceThisIsInstalled(item) == true)
    }

    /// If version_script returns the same version as the item's version, return true
    @Test func versionScriptSameVersionExitReturnsTrue() async throws {
        let item: PlistDict = [
            "name": "Foo",
            "version": "1.2.3",
            "version_script": """
            #!/bin/sh
            echo "1.2.3.0"
            """,
        ]
        #expect(await evidenceThisIsInstalled(item) == true)
    }

    /// If version_script returns a lower version than the item's version, return true
    @Test func versionScriptLowerVersionExitReturnsTrue() async throws {
        let item: PlistDict = [
            "name": "Foo",
            "version": "1.2.3",
            "version_script": """
            #!/bin/sh
            echo "1.2.0"
            """,
        ]
        #expect(await evidenceThisIsInstalled(item) == true)
    }

    /// If version_script returns nothing, return false
    @Test func versionScriptNoOutputReturnsFalse() async throws {
        let item: PlistDict = [
            "name": "Foo",
            "version": "1.2.3",
            "version_script": """
            #!/bin/sh
            echo ""
            """,
        ]
        #expect(await evidenceThisIsInstalled(item) == false)
    }

    /// If version_script returns only whitespace, return false
    @Test func versionScriptWhitespaceOutputReturnsFalse() async throws {
        let item: PlistDict = [
            "name": "Foo",
            "version": "1.2.3",
            "version_script": """
            #!/bin/sh
            echo "     \n\t"
            """,
        ]
        #expect(await evidenceThisIsInstalled(item) == false)
    }

    /// If version_script exits non-zero, return false
    @Test func versionScriptErrorReturnsFalse() async throws {
        let item: PlistDict = [
            "name": "Foo",
            "version": "1.2.3",
            "version_script": """
            #!/bin/sh
            exit 1
            """,
        ]
        #expect(await evidenceThisIsInstalled(item) == false)
    }

    /// If item is a startosinstall item, return true
    @Test func startOSInstallItemReturnsTrue() async throws {
        let item: PlistDict = [
            "name": "Foo",
            "version": "1.2.3",
            "installer_type": "startosinstall",
        ]
        #expect(await evidenceThisIsInstalled(item) == true)
    }

    /// If item is a startosinstall item, return true
    @Test func stageOSInstallerItemReturnsTrue() async throws {
        let item: PlistDict = [
            "name": "Foo",
            "version": "1.2.3",
            "installer_type": "stage_os_installer",
        ]
        #expect(await evidenceThisIsInstalled(item) == true)
    }
}
