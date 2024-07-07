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

    mutating func validate() throws {}

    mutating func run() throws {
        if version {
            print(getVersion())
            return
        }

    }
}
