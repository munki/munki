//
//  makepkginfo.swift
//  munki
//
//  Created by Greg Neagle on 7/6/24.
//
//  Copyright 2024-2025 Greg Neagle.
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

import ArgumentParser
import Foundation

@main
struct MakePkgInfo: ParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "makepkginfo",
        abstract: "Creates a pkginfo file (or fragment thereof) from given input.",
        usage: """
              makepkginfo [<options>] <installer-item>
              makepkginfo convert [--to-yaml|--to-plist] <source> [<destination>]
              """,
        discussion: """
              By default, makepkginfo creates a pkginfo file from a package or disk image.
              Use 'makepkginfo convert' to convert existing pkginfo files between formats.
              
              For a full list of options, run: makepkginfo create --help
              """,
        subcommands: [
            Create.self,
            Convert.self,
        ],
        defaultSubcommand: Create.self
    )

    // Note: --version flag is handled by the Create subcommand (default)
    // The parent command only handles the case when no arguments are given

    mutating func run() throws {
        // If this run() is reached with no subcommand and no version flag,
        // it means the user ran just 'makepkginfo' with no arguments.
        // Show help since there's nothing to do.
        throw CleanExit.helpRequest(self)
    }
}

/// The default subcommand for creating pkginfo from installer items
struct Create: ParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "create",
        abstract: "Create a pkginfo file from an installer item (default command).",
        shouldDisplay: true  // Show in help so users can see the full options
    )

    @OptionGroup(title: "Pkginfo Override Options")
    var overrideOptions: OverrideOptions

    @OptionGroup(title: "Script Options")
    var scriptOptions: ScriptOptions

    @OptionGroup(title: "Drag-n-drop Disk Image Options")
    var dmgOptions: DragNDropOptions

    @OptionGroup(title: "Installer Package Options")
    var packageOptions: ApplePackageOptions

    @OptionGroup(title: "Forced/Unattended Options")
    var unattendedOptions: UnattendedInstallOptions

    @OptionGroup(title: "Generating 'installs' Items")
    var installsOptions: GeneratingInstallsOptions

    @OptionGroup(title: "Installer Types")
    var installerTypeOptions: InstallerTypeOptions

    @OptionGroup(title: "Additional Options")
    var additionalOptions: AdditionalPkginfoOptions

    @OptionGroup(visibility: .private)
    var hiddenOptions: HiddenPkginfoOptions

    @Flag(name: [.long, .customShort("V")],
          help: "Print the version of the Munki tools and exit.")
    var version = false

    @Flag(help: "Output in YAML format instead of XML plist.")
    var yaml = false

    @Argument(help: "Path to installer item (package or disk image)")
    var installerItem: String?

    /// Determine if YAML output should be used based on flag or global preference
    private var shouldUseYaml: Bool {
        if yaml {
            return true
        }
        return UserDefaults.standard.bool(forKey: "yaml")
    }

    mutating func run() throws {
        if version {
            print(getVersion())
            return
        }

        let options = PkginfoOptions(
            override: overrideOptions,
            script: scriptOptions,
            dmg: dmgOptions,
            pkg: packageOptions,
            force: unattendedOptions,
            installs: installsOptions,
            type: installerTypeOptions,
            other: additionalOptions,
            hidden: hiddenOptions
        )

        if installerItem == nil,
           options.installs.file.isEmpty,
           options.type.nopkg == false,
           options.pkg.installerEnvironment.isEmpty,
           options.script.installcheckScript == nil,
           options.script.uninstallcheckScript == nil,
           options.script.preinstallScript == nil,
           options.script.postinstallScript == nil,
           options.script.preuninstallScript == nil,
           options.script.postuninstallScript == nil,
           options.script.uninstallScript == nil
        {
            throw ValidationError("Can't figure out what to do!")
        }

        do {
            let pkginfo = try makepkginfo(installerItem, options: options)
            let plistStr = try plistToString(pkginfo, yamlOutput: shouldUseYaml)
            print(plistStr)
        } catch let PlistError.writeError(description) {
            printStderr("ERROR: \(description)")
            throw ExitCode(-1)
        } catch let error as MunkiError {
            printStderr("ERROR: \(error.description)")
            throw ExitCode(-1)
        } catch {
            printStderr("Unexpected error: \(type(of: error))")
            printStderr(error)
            throw ExitCode(-1)
        }
    }
}
