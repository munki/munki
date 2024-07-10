//
//  osinstaller.swift
//  munki
//
//  Created by Greg Neagle on 7/9/24.
//

import Foundation

func pathIsInstallMacOSApp(_ path: String) -> Bool {
    let startosinstallPath = (path as NSString).appendingPathComponent(
        "Contents/Resources/startosinstall")
    return FileManager.default.fileExists(atPath: startosinstallPath)
}

func findInstallMacOSApp(_ dirpath: String) -> String? {
    // Returns the path to the first Install macOS.app found the top level of
    // dirpath, or nil
    let filemanager = FileManager.default
    if let filelist = try? filemanager.contentsOfDirectory(atPath: dirpath) {
        for item in filelist {
            let itemPath = (dirpath as NSString).appendingPathComponent(item)
            if pathIsInstallMacOSApp(itemPath) {
                return itemPath
            }
        }
    }
    return nil
}

func installMacOSAppIsStub(_ apppath: String) -> Bool {
    // Some downloaded macOS installer apps are stubs that don't contain
    // all the needed resources, which are later downloaded when the app is run
    // we can't use those
    let installESDdmg = (apppath as NSString).appendingPathComponent("Contents/SharedSupport/InstallESD.dmg")
    let sharedSupportDmg = (apppath as NSString).appendingPathComponent("Contents/SharedSupport/SharedSupport.dmg")
    let filemanager = FileManager.default
    return !(filemanager.fileExists(atPath: installESDdmg) ||
        filemanager.fileExists(atPath: sharedSupportDmg))
}

func getInfoFromInstallMacOSApp(_ appPath: String) throws -> PlistDict {
    // Returns info parsed out of OS Installer app
    var appInfo = PlistDict()
    let installInfoPlist = (appPath as NSString).appendingPathComponent("Contents/SharedSupport/InstallInfo.plist")
    if pathIsRegularFile(installInfoPlist) {
        appInfo["version"] = ""
        do {
            if let installInfo = try readPlist(installInfoPlist) as? PlistDict,
               let imageInfo = installInfo["System Image Info"] as? PlistDict,
               let version = imageInfo["version"] as? String
            {
                appInfo["version"] = version
                return appInfo
            }
        } catch {
            // nothing
        }
        throw PkgInfoGenerationError.error(
            description: "Could not get info from Contents/SharedSupport/InstallInfo.plist")
    }
    let sharedSupportDmg = (appPath as NSString).appendingPathComponent("Contents/SharedSupport/SharedSupport.dmg")
    if pathIsRegularFile(sharedSupportDmg) {
        guard let mountpoint = try? mountdmg(sharedSupportDmg) else {
            throw PkgInfoGenerationError.error(
                description: "Could not mount Contents/SharedSupport/SharedSupport.dmg")
        }
        let plistPath = (mountpoint as NSString).appendingPathComponent("com_apple_MobileAsset_MacSoftwareUpdate/com_apple_MobileAsset_MacSoftwareUpdate.xml")
        do {
            if let plist = try readPlist(plistPath) as? PlistDict,
               let assets = plist["Assets"] as? [PlistDict],
               let version = assets[0]["OSVersion"] as? String
            {
                appInfo["version"] = version
                var models = [String]()
                for asset in assets {
                    if let modelList = asset["SupportedDeviceModels"] as? [String] {
                        models += modelList
                    }
                }
                if !models.isEmpty {
                    appInfo["SupportedDeviceModels"] = models
                }
                return appInfo
            }
            unmountdmg(mountpoint)
        } catch {
            unmountdmg(mountpoint)
            throw PkgInfoGenerationError.error(description: "Could not parse com_apple_MobileAsset_MacSoftwareUpdate.xml")
        }
    }
    throw PkgInfoGenerationError.error(
        description: "Could not parse info from \((appPath as NSString).lastPathComponent)")
}

func generateInstallableCondition(_ models: [String]) -> String {
    // Generates an NSPredicate expression to be used as an installable
    // condition limiting the hardware models this item is applicable for
    var predicates = [String]()
    let boardIDs = models.filter { $0.hasPrefix("Mac-") }
    let deviceIDs = models.filter { !$0.hasPrefix("Mac-") }
    if !boardIDs.isEmpty {
        let boardIDList = boardIDs.joined(separator: ", ")
        predicates.append("board_id IN {\(boardIDList)}")
    }
    if !deviceIDs.isEmpty {
        let deviceIDList = deviceIDs.joined(separator: ", ")
        predicates.append("device_id IN {\(deviceIDList)}")
    }
    return predicates.joined(separator: " OR ")
}

func makeStartOSInstallPkgInfo(mountpoint: String, item: String) throws -> PlistDict {
    // Returns pkginfo for a macOS installer on a disk
    // image, using the startosinstall installation method
    let appPath = (mountpoint as NSString).appendingPathComponent(item)
    guard pathIsInstallMacOSApp(appPath) else {
        throw PkgInfoGenerationError.error(
            description: "Disk image item \(item) doesn't appear to be a macOS installer app")
    }
    let appName = (item as NSString).lastPathComponent
    let appInfo = try getInfoFromInstallMacOSApp(appPath)
    guard let version = appInfo["version"] as? String else {
        throw PkgInfoGenerationError.error(
            description: "Could not parse version from \(item)")
    }
    let displayName = (appName as NSString).deletingPathExtension
    let munkiItemName = displayName.replacingOccurrences(of: " ", with: "_")
    let description = "Installs macOS version \(version)"

    var installedSize = Int(18.5 * 1024 * 1024)
    var minimumMunkiVersion = "3.6.3"
    let minimumOSVersion = "10.9"
    if version.hasPrefix("10.14") {
        // https://support.apple.com/en-us/HT201475
        // use inital values
    } else if version.hasPrefix("11.") {
        // https://support.apple.com/en-us/HT211238
        installedSize = Int(35.5 * 1024 * 1024)
        minimumMunkiVersion = "5.1.0"
    } else if version.hasPrefix("12.") {
        // https://support.apple.com/en-us/HT212551
        installedSize = Int(26 * 1024 * 1024)
        minimumMunkiVersion = "5.1.0"
    } else {
        // no published guidance from Apple, just use same as Monterey
        installedSize = Int(26 * 1024 * 1024)
        minimumMunkiVersion = "5.1.0"
    }
    var pkginfo: PlistDict
    pkginfo = [
        "RestartAction": "RequireRestart",
        "apple_item": true,
        "description": description,
        "display_name": displayName,
        "installed_size": installedSize,
        "installer_type": "startosinstall",
        "minimum_munki_version": minimumMunkiVersion,
        "minimum_os_version": minimumOSVersion,
        "name": munkiItemName,
        "supported_architectures": ["x86_64"],
        "uninstallable": false,
        "version": version,
    ]
    if let models = appInfo["SupportedDeviceModels"] as? [String] {
        pkginfo["installable_condition_disabled"] = generateInstallableCondition(models)
    }

    return pkginfo
}

func makeStageOSInstallerPkgInfo(_ appPath: String) throws -> PlistDict {
    // Returns additional pkginfo from macOS installer at app_path,
    // describing a stage_os_installer item

    // calculate the size of the installer app
    let appSize = getSizeOfDirectory(appPath)
    let appName = (appPath as NSString).lastPathComponent
    let appInfo = try getInfoFromInstallMacOSApp(appPath)
    guard let version = appInfo["version"] as? String else {
        throw PkgInfoGenerationError.error(
            description: "Could not parse version from \(appName)")
    }

    let displayNameStaged = (appName as NSString).deletingPathExtension
    let macOSName = displayNameStaged.replacingOccurrences(of: "Install ", with: "")
    let displayName = "\(macOSName) Installer"
    let munkiItemName = displayNameStaged.replacingOccurrences(of: " ", with: "_")
    let description = "Downloads \(macOSName) installer"
    let descriptionStaged = "Installs \(macOSName), version \(version)"

    var installedSize = Int(35.5 * 1024 * 1024)
    let minimumMunkiVersion = "6.0.0"
    let minimumOSVersion = "10.9"
    if version.hasPrefix("11.") {
        // https://support.apple.com/en-us/HT211238
        // use intial values
    } else if version.hasPrefix("12.") {
        // https://support.apple.com/en-us/HT212551
        installedSize = Int(26 * 1024 * 1024)
    } else {
        // no published guidance from Apple, just use same as Monterey
        installedSize = Int(26 * 1024 * 1024)
    }

    var pkginfo: PlistDict
    pkginfo = [
        "description": description,
        "description_staged": descriptionStaged,
        "display_name": displayName,
        "display_name_staged": displayNameStaged,
        "installed_size": appSize,
        "installed_size_staged": installedSize,
        "installer_type": "stage_os_installer",
        "minimum_munki_version": minimumMunkiVersion,
        "minimum_os_version": minimumOSVersion,
        "name": munkiItemName,
        "uninstallable": true,
        "version": version,
    ]

    if let models = appInfo["SupportedDeviceModels"] as? [String] {
        pkginfo["installable_condition_disabled"] = generateInstallableCondition(models)
    }

    return pkginfo
}
