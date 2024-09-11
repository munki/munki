//
//  osinstaller.swift
//  munki
//
//  Created by Greg Neagle on 7/9/24.
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

/// Some downloaded macOS installer apps are stubs that don't contain
/// all the needed resources, which are later downloaded when the app is run
/// we can't use those
func installMacOSAppIsStub(_ apppath: String) -> Bool {
    let installESDdmg = (apppath as NSString).appendingPathComponent("Contents/SharedSupport/InstallESD.dmg")
    let sharedSupportDmg = (apppath as NSString).appendingPathComponent("Contents/SharedSupport/SharedSupport.dmg")
    let filemanager = FileManager.default
    return !(filemanager.fileExists(atPath: installESDdmg) ||
        filemanager.fileExists(atPath: sharedSupportDmg))
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
            unmountdmg(mountpoint)
        } catch {
            unmountdmg(mountpoint)
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

// TODO: implement setup_authrestart_if_applicable()

// TODO: implement StartOSInstallRunner and related functions

/// Returns pkginfo for a macOS installer on a disk image, using the startosinstall installation method
func makeStartOSInstallPkgInfo(mountpoint: String, item: String) throws -> PlistDict {
    let appPath = (mountpoint as NSString).appendingPathComponent(item)
    guard pathIsInstallMacOSApp(appPath) else {
        throw MunkiError("Disk image item \(item) doesn't appear to be a macOS installer app")
    }
    let appName = (item as NSString).lastPathComponent
    let appInfo = try getInfoFromInstallMacOSApp(appPath)
    guard let version = appInfo["version"] as? String else {
        throw MunkiError("Could not parse version from \(item)")
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

/// Attempts to trigger a "verification" process against the staged macOS
/// installer. This improves the launch time.
func verifyStagedOSInstaller(_ appPath: String) {
    displayMinorStatus("Verifying macOS installer...")
    displayPercentDone(current: -1, maximum: 100)
    let startOSInstallPath = (appPath as NSString).appendingPathComponent("Contents/Resources/startosinstall")
    let result = runCLI(startOSInstallPath, arguments: ["--usage"])
    if result.exitcode != 0 {
        displayWarning("Error verifying macOS installer: \(result.error)")
    }
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

/// Records info on a staged macOS installer. This includes info for managedsoftwareupdate and
/// Managed Software Center to display, and the path to the staged installer.
func recordStagedOSInstaller(_ iteminfo: PlistDict) {
    let infoPath = stagedOSInstallerInfoPath()
    guard let stagedOSInstallerInfo = createOSInstallerInfo(iteminfo) else {
        displayError("Error recording staged macOS installer: could not get os installer path")
        return
    }
    do {
        try writePlist(stagedOSInstallerInfo, toFile: infoPath)
    } catch {
        displayError("Error recording staged macOS installer: \(error.localizedDescription)")
    }
    // finally, trigger a verification
    if let osInstallerPath = stagedOSInstallerInfo["osinstaller_path"] as? String {
        verifyStagedOSInstaller(osInstallerPath)
    }
}

/// Returns info we may have on a staged OS installer
func getStagedOSInstallerInfo() -> PlistDict? {
    let infoPath = stagedOSInstallerInfoPath()
    if !pathExists(infoPath) {
        return nil
    }
    do {
        guard let osInstallerInfo = try readPlist(fromFile: infoPath) as? PlistDict else {
            displayError("Error reading \(infoPath): wrong format")
            return nil
        }
        let appPath = osInstallerInfo["osinstaller_path"] as? String ?? ""
        if appPath.isEmpty || !pathExists(appPath) {
            try? FileManager.default.removeItem(atPath: infoPath)
            return nil
        }
        return osInstallerInfo
    } catch {
        displayError("Error reading \(infoPath): \(error.localizedDescription)")
        return nil
    }
}

/// Removes any staged OS installer we may have
func removeStagedOSInstallerInfo() {
    let infoPath = stagedOSInstallerInfoPath()
    try? FileManager.default.removeItem(atPath: infoPath)
}

/// Prints staged macOS installer info (if any) and updates ManagedInstallReport.
func displayStagedOSInstallerInfo(info: PlistDict? = nil) {
    guard let item = info else { return }
    Report.shared.record(item, to: "StagedOSInstaller")
    displayInfo("")
    displayInfo("The following macOS upgrade is available to install:")
    let name = item["display_name"] as? String ?? item["name"] as? String ?? ""
    let version = item["version_to_install"] as? String ?? ""
    displayInfo("    + \(name)-\(version)")
    displayInfo("       *Must be manually installed")
}

// MARK: functions for determining if a user is a volume owner

/// Returns a list of UUIDs of accounts that are volume owners for /
func volumeOwnerUUIDs() -> [String] {
    var cryptoUsers = PlistDict()
    do {
        let result = runCLI(
            "/usr/sbin/diskutil",
            arguments: ["apfs", "listUsers", "/", "-plist"]
        )
        cryptoUsers = try readPlist(fromString: result.output) as? PlistDict ?? [:]
    } catch {
        // do nothing
    }
    let users = cryptoUsers["Users"] as? [PlistDict] ?? []
    return users.filter {
        $0["APFSCryptoUserUUID"] != nil &&
            $0["VolumeOwner"] as? Bool ?? false &&
            $0["APFSCryptoUserType"] as? String ?? "" == "LocalOpenDirectory"
    }.compactMap {
        $0["APFSCryptoUserUUID"] as? String
    }
}

/// Returns a boolean to indicate if the user is a volume owner of /
func userIsVolumeOwner(_ username: String) -> Bool {
    return volumeOwnerUUIDs().contains(getGeneratedUID(username))
}

// MARK: functions for launching staged macOS installer

/// Writes our adminopen script to a temp file. Returns the path.
func getAdminOpenPath() -> String? {
    let scriptText = """
    #!/bin/bash

    # This script is designed to be run as root.
    # It takes one argument, a path to an app to be launched.
    #
    # If the current console user is not a member of the admin group, the user will
    # be added to to the group.
    # The app will then be launched in the console user's context.
    # When the app exits (or this script is killed via SIGINT or SIGTERM),
    # if we had promoted the user to admin, we demote that user once again.

    export PATH=/usr/bin:/bin:/usr/sbin:/sbin

    function fail {
        echo "$@" 1>&2
        exit 1
    }

    function demote_user {
        # demote CONSOLEUSER from admin
        dseditgroup -o edit -d ${CONSOLEUSER} -t user admin
    }

    if [ $EUID -ne 0 ]; then
       fail "This script must be run as root."
    fi


    CONSOLEUSER=$(stat -f %Su /dev/console)
    if [ "${CONSOLEUSER}" == "root" ] ; then
        fail "The console user may not be root!"
    fi

    USER_UID=$(id -u ${CONSOLEUSER})
    if [ $? -ne 0 ] ; then
        # failed to get UID, bail
        fail "Could not get UID for ${CONSOLEUSER}"
    fi

    APP=$1
    if [ "${APP}" == "" ] ; then
        # no application specified
        fail "Need to specify an application!"
    fi

    # check if CONSOLEUSER is admin
    dseditgroup -o checkmember -m ${CONSOLEUSER} admin > /dev/null
    if [ $? -ne 0 ] ; then
        # not currently admin, so promote to admin
        dseditgroup -o edit -a ${CONSOLEUSER} -t user admin
        # make sure we demote the user at the end or if we are interrupted
        trap demote_user EXIT SIGINT SIGTERM
    fi

    # launch $APP as $USER_UID and wait until it exits
    launchctl asuser ${USER_UID} open -W "${APP}"

    """
    guard let tempdir = TempDir.shared.path else {
        displayError("Could not get temp directory for adminopen tool")
        return nil
    }
    let scriptPath = (tempdir as NSString).appendingPathComponent("adminopen")
    guard createExecutableFile(
        atPath: scriptPath,
        withStringContents: scriptText,
        posixPermissions: 0o744
    )
    else {
        displayError("Could not get temp directory for adminopen tool")
        return nil
    }
    return scriptPath
}

/// Runs our adminopen tool to launch the Install macOS app. adminopen is run
/// via launchd so we can exit after the app is launched (and the user may or
/// may not actually complete running it.) Returns true if we run adminopen,
/// false otherwise (some reasons: can't find Install app, no GUI user)
func launchInstallerApp(_ appPath: String) -> Bool {
    // do we have a GUI user?
    let username = getConsoleUser()
    if username.isEmpty || username == "loginwindow" {
        // we're at the loginwindow. Bail.
        displayError("Could not launch macOS installer application: No current GUI user.")
        return false
    }

    // if we're on Apple silicon -- is the user a volume owner?
    if isAppleSilicon(), !userIsVolumeOwner(username) {
        displayError("Could not launch macOS installer application: Current GUI user \(username) is not a volume owner.")
        return false
    }

    // create the adminopen tool and get its path
    guard let adminOpenPath = getAdminOpenPath() else {
        displayError("Error launching macOS installer: Can't create adminopen tool.")
        return false
    }

    // make sure the Install macOS app is present
    if !pathExists(appPath) {
        displayError("Error launching macOS installer: \(appPath) doesn't exist.")
        return false
    }

    // OK, all preconditions are met, let's go!
    displayMajorStatus("Launching macOS installer...")
    let cmd = [adminOpenPath, appPath]
    do {
        let job = try LaunchdJob(cmd: cmd, cleanUpAtExit: false)
        try job.start()
        // sleep a bit, then check to see if our launchd job has exited with an error
        usleep(1_000_000)
        if let exitcode = job.exitcode(), exitcode != 0 {
            var errorMsg = ""
            if let stderr = job.stderr {
                errorMsg = String(data: stderr.readDataToEndOfFile(), encoding: .utf8) ?? ""
            }
            throw MunkiError("(\(exitcode)) \(errorMsg)")
        }
    } catch {
        displayError("Failed to launch macOS installer due to launchd error.")
        displayError(error.localizedDescription)
        return false
    }

    // set Munki to run at boot after the OS upgrade is complete
    do {
        try setBootstrapMode()
    } catch {
        displayWarning("Could not set up Munki to run at boot after OS upgrade is complete: \(error.localizedDescription)")
    }
    // return true to indicate we launched the Install macOS app
    return true
}

/// Attempt to launch a staged OS installer
func launchStagedOSInstaller() -> Bool {
    guard let osInstallerInfo = getStagedOSInstallerInfo(),
          let osInstallerPath = osInstallerInfo["osinstaller_path"] as? String
    else {
        displayError("Could not get path to staged OS installer.")
        return false
    }
    if boolPref("SuppressStopButtonOnInstall") ?? false {
        munkiStatusHideStopButton()
    }
    munkiLog("### Beginning GUI launch of macOS installer ###")
    return launchInstallerApp(osInstallerPath)
}
