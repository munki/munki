//
//  makepkginfo.swift
//  makepkginfo
//
//  Created by Greg Neagle on 7/6/24.
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

import ArgumentParser
import Foundation

@main
struct MakePkgInfo: ParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "makepkginfo",
        abstract: "Creates a pkginfo file (or fragment thereof) from given input."
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

    @Argument(help: ArgumentHelp(
        "Path to installer item (package or disk image).",
        valueName: "installer-item"
    ))
    var installerItem: String?

    mutating func validate() throws {
        // TODO: validate installerEnvironment
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

        /*
         if (not arguments and
                     not options.file and
                     not options.nopkg and
                     not options.installer_environment and
                     not options.installcheck_script and
                     not options.uninstallcheck_script and
                     not options.preinstall_script and
                     not options.postinstall_script and
                     not options.preuninstall_script and
                     not options.postuninstall_script and
                     not options.uninstall_script and
                     not options.apple_update):
                 parser.print_usage()
                 exit(-1)
         */

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
            throw ValidationError("")
        }

        do {
            let pkginfo = try makepkginfo(installerItem, options: options)
            let plistStr = try plistToString(pkginfo)
            print(plistStr)
        } catch let PlistError.writeError(description) {
            printStderr("ERROR: \(description)")
            throw ExitCode(-1)
        } catch let PkgInfoGenerationError.error(description) {
            printStderr("ERROR: \(description)")
            throw ExitCode(-1)
        } catch let PackageParsingError.error(description) {
            printStderr("ERROR: \(description)")
            throw ExitCode(-1)
        } catch let DiskImageError.error(description) {
            printStderr("ERROR: \(description)")
            throw ExitCode(-1)
        } catch {
            printStderr("Unexpected error: \(type(of: error))")
            printStderr(error)
            throw ExitCode(-1)
        }
    }
}
