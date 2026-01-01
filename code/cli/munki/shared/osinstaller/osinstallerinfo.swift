//
//  osinstallerinfo.swift
//  munki
//
//  Created by Greg Neagle on 5/2/25.
//
//  Copyright 2024-2026 The Munki Project. All rights reserved.
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

// functions for retrieving info about osinstallers
// may not call display* functions or munkilog* functions

import Foundation

/// Check to see if path appears to be a macOS Install app
func pathIsInstallMacOSApp(_ path: String) -> Bool {
    let startosinstallPath = (path as NSString).appendingPathComponent(
        "Contents/Resources/startosinstall")
    return FileManager.default.fileExists(atPath: startosinstallPath)
}

/// Returns the path to the first Install macOS.app found the top level of dirpath, or nil
func findInstallMacOSApp(_ dirpath: String) -> String? {
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

/// Returns info parsed out of OS Installer app
func getInfoFromInstallMacOSApp(_ appPath: String) throws -> PlistDict {
    var appInfo = PlistDict()
    let installInfoPlist = (appPath as NSString).appendingPathComponent("Contents/SharedSupport/InstallInfo.plist")
    if pathIsRegularFile(installInfoPlist) {
        appInfo["version"] = ""
        do {
            if let installInfo = try readPlist(fromFile: installInfoPlist) as? PlistDict,
               let imageInfo = installInfo["System Image Info"] as? PlistDict,
               let version = imageInfo["version"] as? String
            {
                appInfo["version"] = version
                return appInfo
            }
        } catch {
            // nothing
        }
        throw MunkiError("Could not get info from Contents/SharedSupport/InstallInfo.plist")
    }
    let sharedSupportDmg = (appPath as NSString).appendingPathComponent("Contents/SharedSupport/SharedSupport.dmg")
    if pathIsRegularFile(sharedSupportDmg) {
        guard let mountpoint = try? mountdmg(sharedSupportDmg) else {
            throw MunkiError("Could not mount Contents/SharedSupport/SharedSupport.dmg")
        }
        defer {
            do {
                try unmountdmg(mountpoint)
            } catch {
                printStderr(error.localizedDescription)
            }
        }
        let plistPath = (mountpoint as NSString).appendingPathComponent("com_apple_MobileAsset_MacSoftwareUpdate/com_apple_MobileAsset_MacSoftwareUpdate.xml")
        do {
            if let plist = try readPlist(fromFile: plistPath) as? PlistDict,
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
        } catch {
            throw MunkiError("Could not parse com_apple_MobileAsset_MacSoftwareUpdate.xml")
        }
    }
    throw MunkiError("Could not parse info from \((appPath as NSString).lastPathComponent)")
}

/// Generates an NSPredicate expression to be used as an installable
/// condition limiting the hardware models this item is applicable for
func generateInstallableCondition(_ models: [String]) -> String {
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

/// Returns additional pkginfo from macOS installer at app_path,
/// describing a stage_os_installer item
func makeStageOSInstallerPkgInfo(_ appPath: String) throws -> PlistDict {
    // calculate the size of the installer app
    let appSize = getSizeOfDirectory(appPath) / 1024 // this value is kbytes
    let appName = (appPath as NSString).lastPathComponent
    let appInfo = try getInfoFromInstallMacOSApp(appPath)
    guard let version = appInfo["version"] as? String else {
        throw MunkiError("Could not parse version from \(appName)")
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
        // use initial values
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

/// Returns the path to the StagedOSInstaller.plist (which may or may not actually exist)
func stagedOSInstallerInfoPath() -> String {
    return managedInstallsDir(subpath: "StagedOSInstaller.plist")
}

/// Returns the expected path to the locally staged macOS installer
func getOSInstallerPath(_ iteminfo: PlistDict) -> String? {
    guard let itemsToCopy = iteminfo["items_to_copy"] as? [PlistDict],
          itemsToCopy.count > 0
    else {
        return nil
    }
    let copiedItem = itemsToCopy[0]
    let sourceItem = copiedItem["source_item"] as? String ?? ""
    let destinationPath = copiedItem["destination_path"] as? String ?? ""
    let destinationItem = copiedItem["destination_item"] as? String ?? ""
    if destinationPath.isEmpty {
        // destinationItem better contain a full path to the destination
        return destinationItem
    }
    // destinationPath should path to the directory the item should be copied to
    if destinationItem.isEmpty {
        return (destinationPath as NSString).appendingPathComponent(baseName(sourceItem))
    }
    return (destinationPath as NSString).appendingPathComponent(baseName(destinationItem))
}

/// Creates a dict describing a staged OS installer
func createOSInstallerInfo(_ iteminfo: PlistDict) -> PlistDict? {
    guard let osInstallerPath = getOSInstallerPath(iteminfo) else {
        return nil
    }
    var osInstallerInfo = PlistDict()
    osInstallerInfo["osinstaller_path"] = osInstallerPath
    osInstallerInfo["name"] = iteminfo["name"] as? String ?? ""
    osInstallerInfo["display_name"] = iteminfo["display_name_staged"] as? String ?? iteminfo["display_name"] as? String ?? iteminfo["name"] as? String ?? ""
    osInstallerInfo["description"] = iteminfo["description_staged"] as? String ?? iteminfo["description"] as? String ?? ""
    osInstallerInfo["installed_size"] = iteminfo["installed_size_staged"] as? Int ?? iteminfo["installed_size"] as? Int ?? iteminfo["installer_item_size"] as? Int ?? 0
    osInstallerInfo["installed"] = false
    osInstallerInfo["version_to_install"] = iteminfo["version_to_install"] as? String ?? iteminfo["version"] as? String ?? "UNKNOWN"
    osInstallerInfo["developer"] = iteminfo["developer"] as? String ?? "Apple"
    // optional keys to copy if they exist
    for key in ["category", "icon_name", "localized_strings"] {
        osInstallerInfo[key] = iteminfo[key]
    }
    return osInstallerInfo
}
