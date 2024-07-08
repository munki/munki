//
//  pkginfolib.swift
//  munki
//
//  Created by Greg Neagle on 7/2/24.
//  functions used by makepkginfo to create pkginfo files

// This implementation drops support for:
//   - pkginfo creation for configuration profiles
//   - pkginfo creation for Apple Update Metadata
//   - special handling of Adobe installers

import Foundation

enum PkgInfoGenerationError: Error {
    case error(description: String)
}

func pkginfoMetadata() -> PlistDict {
    // Helps us record  information about the environment in which the pkginfo was
    // created so we have a bit of an audit trail. Returns a dictionary.
    var metadata = PlistDict()
    metadata["created_by"] = NSUserName()
    metadata["creation_date"] = Date()
    metadata["munki_version"] = getVersion()
    metadata["os_version"] = getOSVersion(onlyMajorMinor: false)
    return metadata
}

struct PkginfoOptions {
    var installerChoices = false
    var pkgname = ""
    var itemtocopy = ""
    var destitemname = ""
    var destinationpath = ""
    var user = ""
    var group = ""
    var mode = ""
    var installerTypeRequested = ""
    var nopkg = false
    var printWarnings = true
    var uninstalleritem = ""
    var catalogs = [String]()
    var description = ""
    var displayName = ""
    var name = ""
    var version = ""
    var category = ""
    var developer = ""
    var iconName = ""
    var files = [String]()
    var installcheckScript = ""
    var uninstallcheckScript = ""
    var postinstallScript = ""
    var preinstallScript = ""
    var postuninstallScript = ""
    var preuninstallScript = ""
    var uninstallScript = ""
    var minimumMunkiversion = ""
    var autoremove = false
    var onDemand = false
    var unattendedInstall = false
    var unattendedUninstall = false
    var minimumOSVersion = ""
    var maximumOSVersion = ""
    var supportedArchitectures = [String]()
    var forceInstallAfterDate: NSDate?
    var restartAction = ""
    var updateFor = [String]()
    var requires = [String]()
    var blockingApplications = [String]()
    var uninstallMethod = ""
    var installerEnvironment = [String: String]()
    var notes = ""
}

func createPkgInfoFromPkg(_ pkgpath: String,
                          options: PkginfoOptions = PkginfoOptions()) throws -> PlistDict
{
    // Gets package metadata for the package at pkgpath.
    // Returns pkginfo
    var info = PlistDict()

    if hasValidPackageExt(pkgpath) {
        info = try getPackageMetaData(pkgpath)
        if options.installerChoices {
            if let installerChoices = getChoiceChangesXML(pkgpath) {
                info["installer_choices_xml"] = installerChoices
            }
        }
        if !pathIsDirectory(pkgpath) {
            // generate and add installer_item_size
            if let attributes = try? FileManager.default.attributesOfItem(atPath: pkgpath) {
                let filesize = (attributes as NSDictionary).fileSize()
                info["installer_item_size"] = Int(filesize / 1024)
            }
            info["installer_item_hash"] = sha256hash(file: pkgpath)
        }
    }
    return info
}

func createInstallsItem(_ itempath: String) -> PlistDict {
    // Creates an item for a pkginfo "installs" array
    // Determines if the item is an application, bundle, Info.plist, or a file or
    // directory and gets additional metadata for later comparison.
    var info = PlistDict()
    if isApplication(itempath) {
        info["type"] = "application"
        if let plist = getBundleInfo(itempath) {
            for key in ["CFBundleName", "CFBundleIdentifier",
                        "CFBundleShortVersionString", "CFBundleVersion"]
            {
                if let value = plist[key] as? String {
                    info[key] = value
                }
            }
            if let minOSVers = plist["LSMinimumSystemVersion"] as? String {
                info["minosversion"] = minOSVers
            } else if let minOSVersByArch = plist["LSMinimumSystemVersionByArchitecture"] as? [String: String] {
                // get the highest/latest of all the minmum os versions
                let minOSVersions = minOSVersByArch.values
                let versions = minOSVersions.map { MunkiVersion($0) }
                if let maxVersion = versions.max() {
                    info["minosversion"] = maxVersion.value
                }
            } else if let minSysVers = plist["SystemVersionCheck:MinimumSystemVersion"] as? String {
                info["minosversion"] = minSysVers
            }
        }
    } else if let plist = getBundleInfo(itempath) {
        // if we can find bundle info and we're not an app
        // we must be a bundle
        info["type"] = "bundle"
        for key in ["CFBundleShortVersionString", "CFBundleVersion"] {
            if let value = plist[key] as? String {
                info[key] = value
            }
        }
    } else if let plist = try? readPlist(itempath) as? PlistDict {
        // we must be a plist
        info["type"] = "plist"
        for key in ["CFBundleShortVersionString", "CFBundleVersion"] {
            if let value = plist[key] as? String {
                info[key] = value
            }
        }
    }
    // help the admin by switching to CFBundleVersion if CFBundleShortVersionString
    // value seems invalid
    if let shortVersionString = info["CFBundleShortVersionString"] as? String {
        let shortVersionStringFirst = String(shortVersionString.first ?? "X")
        if !"0123456789".contains(shortVersionStringFirst) {
            if info["CFBundleVersion"] != nil {
                info["version_comparison_key"] = "CFBundleVersion"
            }
        } else {
            info["version_comparison_key"] = "CFBundleShortVersionString"
        }
    }

    if !info.keys.contains("CFBundleShortVersionString"), !info.keys.contains("CFBundleVersion") {
        // no version keys, so must be either a plist without version info
        // or just a simple file or directory
        info["type"] = "file"
        if pathIsRegularFile(itempath) || pathIsSymlink(itempath) {
            info["md5checksum"] = md5hash(file: itempath)
        }
    }
    if !info.isEmpty {
        info["path"] = itempath
    }
    return info
}

func createPkgInfoForDragNDrop(_ mountpoint: String, options: PkginfoOptions = PkginfoOptions()) throws -> PlistDict {
    // processes a drag-n-drop dmg to build pkginfo
    var info = PlistDict()
    var dragNDropItem = ""
    var installsitem = PlistDict()
    if !options.itemtocopy.isEmpty {
        // specific item given
        dragNDropItem = options.itemtocopy
        let itempath = (mountpoint as NSString).appendingPathComponent(dragNDropItem)
        installsitem = createInstallsItem(itempath)
        if installsitem.isEmpty {
            throw PkgInfoGenerationError.error(
                description: "\(dragNDropItem) not found on disk image.")
        }
    } else {
        // no item specified; look for an application at root of
        // mounted dmg
        let filemanager = FileManager.default
        if let filelist = try? filemanager.contentsOfDirectory(atPath: mountpoint) {
            for item in filelist {
                let itempath = (mountpoint as NSString).appendingPathComponent(item)
                if isApplication(itempath) {
                    dragNDropItem = item
                    installsitem = createInstallsItem(itempath)
                    if !installsitem.isEmpty {
                        break
                    }
                }
            }
        }
    }

    if !installsitem.isEmpty {
        var itemsToCopyItem = PlistDict()
        var mountpointPattern = mountpoint
        if !mountpointPattern.hasSuffix("/") {
            mountpointPattern += "/"
        }
        if dragNDropItem.hasPrefix(mountpointPattern) {
            let startIndex = dragNDropItem.index(
                dragNDropItem.startIndex, offsetBy: mountpointPattern.count
            )
            dragNDropItem = String(dragNDropItem[startIndex...])
        }
        var destItem = dragNDropItem
        if !options.destitemname.isEmpty {
            destItem = options.destitemname
            itemsToCopyItem["destination_item"] = destItem
        }

        let destItemFilename = (destItem as NSString).lastPathComponent
        if !options.destinationpath.isEmpty {
            installsitem["path"] = (options.destinationpath as NSString).appendingPathComponent(destItemFilename)
        } else {
            installsitem["path"] = ("/Applications" as NSString).appendingPathComponent(destItemFilename)
        }
        if let name = installsitem["CFBundleName"] as? String {
            info["name"] = name
        } else {
            info["name"] = (dragNDropItem as NSString).deletingPathExtension
        }
        let comparisonKey = installsitem["version_comparison_key"] as? String ?? "CFBundleShortVersionString"
        let version = installsitem[comparisonKey] as? String ?? "0.0.0.0.0"
        if let minOSVers = installsitem["minosversion"] as? String {
            info["minimum_os_version"] = minOSVers
        }
        info["version"] = version
        info["installs"] = [installsitem]
        info["installer_type"] = "copy_from_dmg"
        // build items_to_copy array
        itemsToCopyItem["source_item"] = dragNDropItem
        if !options.destinationpath.isEmpty {
            itemsToCopyItem["destination_path"] = options.destinationpath
        } else {
            itemsToCopyItem["destination_path"] = "/Applications"
        }
        if !options.user.isEmpty {
            itemsToCopyItem["user"] = options.user
        }
        if !options.group.isEmpty {
            itemsToCopyItem["user"] = options.group
        }
        if !options.mode.isEmpty {
            itemsToCopyItem["user"] = options.mode
        }
        info["items_to_copy"] = [itemsToCopyItem]
        info["uninstallable"] = true
        info["uninstall_method"] = "remove_copied_items"

        if options.installerTypeRequested == "stage_os_installer" {
            // TODO: transform this copy_from_dmg item
            // into a staged_os_installer item
        }
    }

    return info
}

func createPkgInfoFromDmg(_ dmgpath: String,
                          options: PkginfoOptions = PkginfoOptions()) throws -> PlistDict
{
    // Mounts a disk image if it"s not already mounted
    // Builds pkginfo for the first installer item found at the root level,
    // or a specific one if specified by options.pkgname or options.item
    // Unmounts the disk image if it wasn"t already mounted
    var info = PlistDict()
    let wasAlreadyMounted = diskImageIsMounted(dmgpath)
    guard let mountpoint = mountdmg(dmgpath, useExistingMounts: true) else {
        throw PkgInfoGenerationError.error(description: "Could not mount \(dmgpath)")
    }
    if !options.pkgname.isEmpty {
        // a package was specified
        let pkgpath = (mountpoint as NSString).appendingPathComponent(options.pkgname)
        info = try createPkgInfoFromPkg(pkgpath, options: options)
        info["package_path"] = options.pkgname
    } else if options.itemtocopy.isEmpty {
        // look for first package at the root of the mounted dmg
        if let filelist = try? FileManager.default.contentsOfDirectory(atPath: mountpoint) {
            for item in filelist {
                if hasValidPackageExt(item) {
                    let pkgpath = (mountpoint as NSString).appendingPathComponent(item)
                    info = try createPkgInfoFromPkg(pkgpath, options: options)
                    break
                }
            }
        }
    }
    if info.isEmpty, options.itemtocopy.isEmpty {
        // TODO: check for macOS installer
    }
    if info.isEmpty {
        // maybe this is a drag-n-drop disk image
        if let dragNDropInfo = try? createPkgInfoForDragNDrop(
            mountpoint, options: options
        ) {
            info = dragNDropInfo
        }
    }
    if !info.isEmpty {
        // generate and add installer_item_size
        if let attributes = try? FileManager.default.attributesOfItem(atPath: dmgpath) {
            let filesize = (attributes as NSDictionary).fileSize()
            info["installer_item_size"] = Int(filesize / 1024)
        }
        info["installer_item_hash"] = sha256hash(file: dmgpath)
    }
    // eject the dmg
    if !wasAlreadyMounted {
        unmountdmg(mountpoint)
    }
    return info
}

func readFileOrString(_ fileNameOrString: String) -> String {
    // attempt to read a file with the same name as the input string and return its text,
    // otherwise return the input string
    if let fileText = try? String(contentsOfFile: fileNameOrString, encoding: .utf8) {
        return fileText
    }
    return fileNameOrString
}

func makepkginfo(_ filepath: String,
                 options: PkginfoOptions = PkginfoOptions()) throws -> PlistDict
{
    // Return a pkginfo dictionary for installeritem
    var installeritem = filepath
    var pkginfo = PlistDict()

    if !installeritem.isEmpty {
        if !FileManager.default.fileExists(atPath: installeritem) {
            throw PkgInfoGenerationError.error(
                description: "File \(installeritem) does not exist")
        }

        // is this the mountpoint for a mounted disk image?
        if pathIsVolumeMountPoint(installeritem) {
            // Get the disk image path for the mountpoint
            // and use that instead of the original item
            if let dmgPath = diskImageForMountPoint(installeritem) {
                installeritem = dmgPath
            }
        }

        // is this a disk image?
        if hasValidDiskImageExt(installeritem) {
            pkginfo = try createPkgInfoFromDmg(installeritem, options: options)
            if pkginfo.isEmpty {
                throw PkgInfoGenerationError.error(
                    description: "Could not find a supported installer item in \(installeritem)")
            }
            if dmgIsWritable(installeritem), options.printWarnings {
                printStderr("WARNING: \(installeritem) is a writable disk image. Checksum verification is not supported.")
                pkginfo["installer_item_hash"] = "N/A"
            }
            // is this a package?
        } else if hasValidPackageExt(installeritem) {
            if !options.installerTypeRequested.isEmpty, options.printWarnings {
                printStderr("WARNING: installer_type requested is \(options.installerTypeRequested). Provided installer item appears to be an Apple pkg.")
            }
            pkginfo = try createPkgInfoFromPkg(installeritem, options: options)
            if pkginfo.isEmpty {
                throw PkgInfoGenerationError.error(
                    description: "\(installeritem) doesn't appear to be a valid installer item.")
            }
            if pathIsDirectory(installeritem), options.printWarnings {
                printStderr("WARNING: \(installeritem) is a bundle-style package!\nTo use it with Munki, you should encapsulate it in a disk image.")
            }
        } else {
            throw PkgInfoGenerationError.error(
                description: "\(installeritem) is not a supported installer item!")
        }

        // try to generate the correct item location if item was imported from
        // inside the munki repo
        // TODO: remove start of path if it refers to the Munki repo pkgs dir

        // for now, just the filename
        pkginfo["installer_item_location"] = (installeritem as NSString).lastPathComponent

        if !options.uninstalleritem.isEmpty {
            pkginfo["uninstallable"] = true
            pkginfo["uninstall_method"] = "uninstall_package"
            let minMunkiVers = pkginfo["minimum_munki_version"] as? String ?? "0"
            if MunkiVersion(minMunkiVers) > MunkiVersion("6.2") {
                pkginfo["minimum_munki_version"] = "6.2"
            }
            let uninstallerpath = options.uninstalleritem
            if !FileManager.default.fileExists(atPath: uninstallerpath) {
                throw PkgInfoGenerationError.error(
                    description: "No uninstaller item at \(uninstallerpath)")
            }
            // TODO: remove start of path if it refers to the Munki repo pkgs dir
            // for now, just the filename
            pkginfo["uninstaller_item_location"] = (uninstallerpath as NSString).lastPathComponent
            pkginfo["uninstaller_item_hash"] = sha256hash(file: uninstallerpath)
            if let attributes = try? FileManager.default.attributesOfItem(atPath: uninstallerpath) {
                let filesize = (attributes as NSDictionary).fileSize()
                pkginfo["uninstaller_item_size"] = Int(filesize / 1024)
            }
        }

        // No uninstall method yet?
        // if we have receipts, assume we can uninstall using them
        if !pkginfo.keys.contains("uninstall_method") {
            if let receipts = pkginfo["receipts"] as? [PlistDict] {
                if !receipts.isEmpty {
                    pkginfo["uninstallable"] = true
                    pkginfo["uninstall_method"] = "removepackages"
                }
            }
        }

    } else {
        // no installer item
        if options.nopkg {
            pkginfo["installer_type"] = "nopkg"
        }
    }

    if !options.catalogs.isEmpty {
        pkginfo["catalogs"] = options.catalogs
    } else {
        pkginfo["catalogs"] = ["testing"]
    }
    if !options.description.isEmpty {
        pkginfo["description"] = readFileOrString(options.description)
    }
    if !options.displayName.isEmpty {
        pkginfo["display_name"] = options.displayName
    }
    if !options.name.isEmpty {
        pkginfo["name"] = options.name
    }
    if !options.version.isEmpty {
        pkginfo["version"] = options.version
    }
    if !options.category.isEmpty {
        pkginfo["category"] = options.category
    }
    if !options.developer.isEmpty {
        pkginfo["developer"] = options.developer
    }
    if !options.iconName.isEmpty {
        pkginfo["icon_name"] = options.iconName
    }
    if !pkginfo.isEmpty {
        pkginfo["autoremove"] = false
    }
    // process items for installs array
    var installs = [PlistDict]()
    for var file in options.files {
        if file.hasSuffix("/") {
            file.removeLast()
        }
        if FileManager.default.fileExists(atPath: file) {
            let installsItem = createInstallsItem(file)
            installs.append(installsItem)
        } else {
            printStderr("Item \(file) doesn't exist. Skipping.")
        }
    }
    if !installs.isEmpty {
        pkginfo["installs"] = installs
    }
    // add pkginfo scripts if specified
    if !options.installcheckScript.isEmpty {
        if let scriptText = try? String(contentsOfFile: options.installcheckScript, encoding: .utf8) {
            pkginfo["installcheck_script"] = scriptText
        }
    }
    if !options.uninstallcheckScript.isEmpty {
        if let scriptText = try? String(contentsOfFile: options.uninstallcheckScript, encoding: .utf8) {
            pkginfo["uninstallcheck_script"] = scriptText
        }
    }
    if !options.postinstallScript.isEmpty {
        if let scriptText = try? String(contentsOfFile: options.postinstallScript, encoding: .utf8) {
            pkginfo["postinstall_script"] = scriptText
        }
    }
    if !options.preinstallScript.isEmpty {
        if let scriptText = try? String(contentsOfFile: options.preinstallScript, encoding: .utf8) {
            pkginfo["preinstall_script"] = scriptText
        }
    }
    if !options.postuninstallScript.isEmpty {
        if let scriptText = try? String(contentsOfFile: options.postuninstallScript, encoding: .utf8) {
            pkginfo["postuninstall_script"] = scriptText
        }
    }
    if !options.preuninstallScript.isEmpty {
        if let scriptText = try? String(contentsOfFile: options.preuninstallScript, encoding: .utf8) {
            pkginfo["preuninstall_script"] = scriptText
        }
    }
    if !options.uninstallScript.isEmpty {
        if let scriptText = try? String(contentsOfFile: options.uninstallScript, encoding: .utf8) {
            pkginfo["uninstall_script"] = scriptText
            pkginfo["uninstall_method"] = "uninstall_script"
            pkginfo["uninstallable"] = true
        }
    }
    // more options
    if options.autoremove {
        pkginfo["autoremove"] = true
    }
    if !options.minimumMunkiversion.isEmpty {
        pkginfo["miminum_munki_version"] = options.minimumMunkiversion
    }
    if options.onDemand {
        pkginfo["OnDemand"] = true
    }
    if options.unattendedInstall {
        pkginfo["unattended_install"] = true
    }
    if options.unattendedUninstall {
        pkginfo["unattended_uninstall"] = true
    }
    if !options.minimumOSVersion.isEmpty {
        pkginfo["minimum_os_version"] = options.minimumOSVersion
    }
    if !options.maximumOSVersion.isEmpty {
        pkginfo["maximum_os_version"] = options.maximumOSVersion
    }
    if !options.supportedArchitectures.isEmpty {
        pkginfo["supported_architectures"] = options.supportedArchitectures
    }
    if options.forceInstallAfterDate != nil {
        pkginfo["force_install_after_date"] = options.forceInstallAfterDate
    }
    if !options.restartAction.isEmpty {
        pkginfo["RestartAction"] = options.restartAction
    }
    if !options.updateFor.isEmpty {
        pkginfo["update_for"] = options.updateFor
    }
    if !options.requires.isEmpty {
        pkginfo["update_for"] = options.requires
    }
    if !options.blockingApplications.isEmpty {
        pkginfo["update_for"] = options.blockingApplications
    }
    if !options.uninstallMethod.isEmpty {
        pkginfo["uninstall_method"] = options.uninstallMethod
        pkginfo["uninstallable"] = true
    }
    if !options.installerEnvironment.isEmpty {
        pkginfo["installer_environment"] = options.installerEnvironment
    }
    if !options.notes.isEmpty {
        pkginfo["notes"] = readFileOrString(options.notes)
    }
    pkginfo["_metadata"] = pkginfoMetadata()

    return pkginfo
}
