//
//  pkginfoOptions.swift
//  munki
//
//  Created by Greg Neagle on 7/7/24.
//

import ArgumentParser
import Foundation

// Defines option groups for makepkginfo
// These are also used by munkiimport

struct OverrideOptions: ParsableArguments {
    // Pkginfo Override Options
    @Option(help: "Name to be used to refer to the installer item.")
    var name: String? = nil

    @Option(help: "Display name to be used for the installer item.")
    var displayname: String? = nil

    @Option(help: ArgumentHelp(
        "A description for the installer item. Can be a path to a file (plain text or html).",
        valueName: "text|path"
    ))
    var description: String? = nil

    @Option(help: ArgumentHelp("Version to use for the installer item.",
                               valueName: "version-string"))
    var pkgvers: String? = nil

    @Option(name: [.customLong("RestartAction")],
            help: "Specify a 'RestartAction' for the installer item.  Supported actions: RequireRestart, RequireLogout, or RecommendRestart")
    var restartAction: String? = nil

    @Option(name: [.long, .customLong("uninstall_method")],
            help: "Specify an 'uninstall_method' for the installer item.  Default method depends on the package type: i.e.  drag-n-drop, Apple package, or an embedded uninstall script. Can be a path to a script on the client computer.")
    var uninstallMethod: String? = nil
}

struct ScriptOptions: ParsableArguments {
    // Script options
    @Option(name: [.long, .customLong("installcheck_script")],
            help: ArgumentHelp("Path to an optional script to be run to determine if item should be installed. An exit code of 0 indicates installation should occur. Takes precedence over installs items and receipts.", valueName: "path"))
    var installcheckScript: String? = nil

    @Option(name: [.long, .customLong("uninstallcheck_script")],
            help: ArgumentHelp("Path to an optional script to be run to determine if item should be uninstalled. An exit code of 0 indicates installation should occur. Takes precedence over installs items and receipts.", valueName: "path"))
    var uninstallcheckScript: String? = nil

    @Option(name: [.long, .customLong("preinstall_script")],
            help: ArgumentHelp("Path to an optional script to be run before installation of the item.", valueName: "path"))
    var preinstallScript: String? = nil

    @Option(name: [.long, .customLong("postinstall_script")],
            help: ArgumentHelp("Path to an optional script to be run after installation of the item.", valueName: "path"))
    var postinstallScript: String? = nil

    @Option(name: [.long, .customLong("preuninstall_script")],
            help: ArgumentHelp("Path to an optional script to be run before removal of the item.", valueName: "path"))
    var preuninstallScript: String? = nil

    @Option(name: [.long, .customLong("postuninstall_script")],
            help: ArgumentHelp("Path to an optional script to be run after removal of the item.", valueName: "path"))
    var postuninstallScript: String? = nil

    @Option(name: [.long, .customLong("uninstall_script")],
            help: ArgumentHelp("Path to a script to be run in order to uninstall this item.", valueName: "path"))
    var uninstallScript: String? = nil
}

struct DragNDropOptions: ParsableArguments {
    // "Drag-n-drop" Disk Image Options
    @Option(name: [.short, .long, .customShort("a"), .customLong("app")],
            help: "Name or relative path of the item to be installed. Useful if there is more than one item at the root of the dmg or the item is located in a subdirectory. Absolute paths can be provided as well but they must point to an item located within the dmg.")
    var item: String? = nil

    @Option(name: .shortAndLong,
            help: ArgumentHelp("Path to which the item should be copied. Defaults to /Applications.", valueName: "path"))
    var destinationpath: String? = nil

    @Option(name: [.customLong("destinationitemname"), .customLong("destinationitem")],
            help: ArgumentHelp("Alternate name for which the item should be copied as. Specifying this option also alters the corresponding 'installs' item's path with the provided name.", valueName: "name"))
    var destitemname: String? = nil

    @Option(name: [.customShort("o"), .customLong("owner")],
            help: "Sets the owner of the copied item. The owner may be either a UID number or a UNIX short name. The owner will be set recursively on the item.")
    var user: String? = nil

    @Option(name: .shortAndLong,
            help: "Sets the group of the copied item. The group may be either a GID number or a name. The group will be set recursively on the item.")
    var group: String? = nil

    @Option(name: .shortAndLong,
            help: "Sets the mode of the copied item. The specified mode must be in symbolic form. See the manpage for chmod(1) for more information. The mode is applied recursively.")
    var mode: String? = nil
}

struct ApplePackageOptions: ParsableArguments {
    // Apple package specific options
    @Option(name: .shortAndLong,
            help: "If the installer item is a disk image containing multiple packages, or the package to be installed is not at the root of the mounted disk image, <pkgname> is a relative path from the root of the mounted disk image to the specific package to be installed.")
    var pkgname: String? = nil

    @Option(name: [.customShort("U"),
                   .long,
                   .customLong("uninstallerdmg"),
                   .customLong("uninstallerpkg")],
            help: "<uninstalleritem> is a path to an uninstall package or a disk image containing an uninstall package.")
    var uninstalleritem: String? = nil

    @Flag(name: [.long, .customLong("installer_choices_xml")],
          help: "Generate installer choices for distribution packages.")
    var installerChoicesXML = false

    @Option(
        name: [.customShort("E"), .long, .customLong("installer_environment")],
        help: ArgumentHelp("Specifies a key/value pair to set environment variables for use by /usr/sbin/installer. A key/value pair of USER=CURRENT_CONSOLE_USER indicates that USER be set to the GUI user, otherwise root. Can be specified multiple times.", valueName: "key=value")
    )
    var installerEnvironment = [String]()
}

struct UnattendedInstallOptions: ParsableArguments {
    // Forced/Unattended (install) options
    @Flag(name: [.long, .customLong("unattended_install")],
          help: "Item can be installed without notifying the user.")
    var unattendedInstall = false

    @Flag(name: [.long, .customLong("unattended_uninstall")],
          help: "Item can be uninstalled without notifying the user.")
    var unattendedUninstall = false

    @Option(name: [.long, .customLong("force_install_after_date")],
            help: ArgumentHelp("Specify a date, in local time, after which the package will be forcefully installed. DATE format: yyyy-mm-ddThh:mm:ssZ Example: '2011-08-11T12:55:00Z' equates to 11 August 2011 at 12:55 PM local time.", valueName: "date"))
    var forceInstallAfterDate: String? = nil
}

struct GeneratingInstallsOptions: ParsableArguments {
    // 'installs' generation options
    @Option(name: .shortAndLong,
            help: "Path to a filesystem item installed by this installer item, typically an application. This generates an 'installs' item for the pkginfo, to be used to determine if this software has been installed. Can be specified multiple times.")
    var file = [String]()
}

struct InstallerTypeOptions: ParsableArguments {
    // installer type options
    @Option(name: [.long, .customLong("installer_type")],
            help: "Specify an intended installer_type when the installer item could be one of multiple types. Currently supported only to specify the intended type for a macOS installer ('startosinstall' or 'stage_os_installer').")
    var installerType: String? = nil

    @Flag(help: "Indicates this pkginfo should have an 'installer_type' of 'nopkg'. Ignored if a package or dmg argument is supplied.")
    var nopkg = false
}

struct AdditionalPkginfoOptions: ParsableArguments {
    @Flag(help: "Indicates this package should be automatically removed if it is not listed in any applicable 'managed_installs'.")
    var autoremove = false

    @Flag(name: [.customLong("OnDemand")],
          help: "Indicates this package should be an OnDemand package. These items should only be used as optional_installs.")
    var onDemand = false

    @Option(name: [.long, .customLong("minimum_munki_version")],
            help: ArgumentHelp("Minimum version of Munki required to perform installation. Uses format produced by \'--version\' query from any Munki utility.", valueName: "version-string"))
    var minumumMunkiVersion: String? = nil

    @Option(name: [.long, .customLong("minimum_os_version")],
            help: ArgumentHelp("Minimum OS version for the installer item.",
                               valueName: "version-string"))
    var minumumOSVersion: String? = nil

    @Option(name: [.long, .customLong("maximum_os_version")],
            help: ArgumentHelp("Maximum OS version for the installer item.", valueName: "version-string"))
    var maximumOSVersion: String? = nil

    @Option(name: [.customLong("arch"),
                   .customLong("supported_architecture"),
                   .customLong("supported-architecture")],
            help: "Declares a supported architecture for the item. Can be specified multiple times to declare multiple supported architectures.")
    var supportedArchitectures = [String]()

    @Option(name: [.short, .long, .customLong("update_for")],
            help: ArgumentHelp("Specifies a Munki item for which the current package is an update. Can be specified multiple times to build an array of items.", valueName: "munki-item-name"))
    var updateFor = [String]()

    @Option(name: .shortAndLong,
            help: ArgumentHelp("Specifies a Munki item required by the current item. Can be specified multiple times to build an array of required items.", valueName: "munki-item-name"))
    var requires = [String]()

    @Option(name: [.short, .long, .customLong("blocking_applications")],
            help: ArgumentHelp("Specifies an application that blocks installation. Can be specified multiple times to build an array of blocking applications.", valueName: "application-name"))
    var blockingApplication = [String]()

    @Option(name: .shortAndLong,
            help: "Specifies in which catalog the item should appear. The default is 'testing'. Can be specified multiple times to add the item to multiple catalogs.")
    var catalog = [String]()

    @Option(help: "Category for display in Managed Software Center.")
    var category: String? = nil

    @Option(help: "Developer name for display in Managed Software Center.")
    var developer: String? = nil

    @Option(name: [.customLong("icon"),
                   .customLong("iconname"),
                   .customLong("icon-name"),
                   .customLong("icon_name")],
            help: "Name of icon file for display in Managed Software Center.")
    var iconName: String? = nil

    @Option(help: ArgumentHelp("Specifies administrator provided notes to be embedded into the pkginfo. Can be a path to a file.", valueName: "text|path"))
    var notes: String? = nil
}

struct HiddenPkginfoOptions: ParsableArguments {
    @Flag(inversion: .prefixedNo)
    var printWarnings = true
}
