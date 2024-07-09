//
//  makepkginfo.swift
//  makepkginfo
//
//  Created by Greg Neagle on 7/6/24.
//

import ArgumentParser
import Foundation

@main
struct MakePkgInfo: ParsableCommand {
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

        if let installerItem {
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
}
