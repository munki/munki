//
//  dmgutils.swift
//  munki
//
//  Created by Greg Neagle on 6/30/24.
//

import Foundation

func hdiutilData(arguments: [String], stdIn: String = "") -> PlistDict {
    // runs an hdiutil <command> on a dmg and attempts to return a plist data structure
    var hdiUtilArgs = arguments
    if !hdiUtilArgs.contains("-plist") {
        hdiUtilArgs.append("-plist")
    }
    let results = runCLI("/usr/bin/hdiutil", arguments: hdiUtilArgs, stdIn: stdIn)
    if results.exitcode != 0 {
        displayError("hdiutil error \(results.error) with arguments \(arguments)")
    }
    let (plistStr, _) = parseFirstPlist(fromString: results.output)
    if !plistStr.isEmpty {
        do {
            if let plist = try readPlistFromString(plistStr) as? PlistDict {
                return plist
            }
        } catch {
            return PlistDict()
        }
    }
    return PlistDict()
}

func dmgImageInfo(_ dmgPath: String) -> PlistDict {
    // runs hdiutil imageinfo on a dmg and returns a plist data structure
    return hdiutilData(arguments: ["imageinfo", dmgPath])
}


func dmgIsWritable(_ dmgPath: String) -> Bool {
    // Attempts to determine if the given disk image is writable
    let imageInfo = dmgImageInfo(dmgPath)
    if let format = imageInfo["Format"] as? String {
        if ["UDSB", "UDSP", "UDRW", "RdWr"].contains(format) {
            return true
        }
    }
    return false
}


func dmgHasSLA(_ dmgPath: String) -> Bool {
    // Returns true if dmg has a Software License Agreement.
    // These dmgs normally cannot be attached without user intervention
    let imageInfo = dmgImageInfo(dmgPath)
    if let properties = imageInfo["Properties"] as? PlistDict {
        if let hasSLA = properties["Software License Agreement"] as? Bool {
            return hasSLA
        }
    }
    return false
}


func hdiutilInfo() -> PlistDict {
    // runs hdiutil info on a dmg and returns a plist data structure
    return hdiutilData(arguments: ["info"])
}


func pathIsVolumeMountPoint(_ path: String) -> Bool {
    // Returns a boolean to indicate if path is a mountpoint for a disk image
    let info = hdiutilInfo()
    if let images = info["images"] as? [PlistDict] {
        // "images" is an array of dicts
        for image in images {
            if let systemEntities = image["system-entities"] as? [PlistDict] {
                // "system-entities" is an array of dicts
                for entity in systemEntities {
                    if let mountpoint = entity["mount-point"] as? String {
                        // there's a mount-point for this!
                        if path == mountpoint {
                            // our path is this mountpoint
                            return true
                        }
                    }
                }
            }
        }
    }
    return false
}


func diskImageForMountPoint(_ path: String) -> String? {
    // Attempts to find the path to a dmg for a given mount point
    let info = hdiutilInfo()
    if let images = info["images"] as? [PlistDict] {
        // "images" is an array of dicts
        for image in images {
            if let imagePath = image["image-path"] as? String {
                if let systemEntities = image["system-entities"] as? [PlistDict] {
                    // "system-entities" is an array of dicts
                    for entity in systemEntities {
                        if let mountpoint = entity["mount-point"] as? String {
                            // there's a mount-point for this!
                            if path == mountpoint {
                                // our path is this mountpoint
                                return imagePath
                            }
                        }
                    }
                }
            }
        }
    }
    return nil
}

func mountPointsForDiskImage(_ dmgPath: String) -> [String] {
    // returns a list of mountpoints for the given disk image
    var mountpoints = [String]()
    let info = hdiutilInfo()
    if let images = info["images"] as? [PlistDict] {
        // "images" is an array of dicts
        for image in images {
            if let imagePath = image["image-path"] as? String {
                // "image-path" is path to dmg file
                if imagePath == dmgPath {
                    // this is our disk image
                    if let systemEntities = image["system-entities"] as? [PlistDict] {
                        // "system-entities" is an array of dicts
                        for entity in systemEntities {
                            if let mountpoint = entity["mount-point"] as? String {
                                // there's a mount-point for this!
                                mountpoints.append(mountpoint)
                            }
                        }
                    }
                }
            }
        }
    }
    return mountpoints
}


func diskImageIsMounted(_ dmgPath: String) -> Bool {
    // Returns true if the given disk image is currently mounted
    return !mountPointsForDiskImage(dmgPath).isEmpty
}


func mountdmg(
    _ dmgPath: String,
    useShadow: Bool = false,
    useExistingMounts: Bool = false,
    randomMountpoint: Bool = true,
    skipVerification: Bool = false) -> [String]
{
    // Attempts to mount the dmg at dmgpath
    // and returns a list of mountpoints
    // If use_shadow is true, mount image with shadow file
    // If random_mountpoint, mount at random dir under /tmp
    var mountpoints = [String]()
    let dmgName = (dmgPath as NSString).lastPathComponent
    
    if useExistingMounts {
        if diskImageIsMounted(dmgPath) {
            return mountPointsForDiskImage(dmgPath)
        }
    }
    
    // attempt to mount the dmg
    var stdIn = ""
    if dmgHasSLA(dmgPath) {
        stdIn = "Y\n"
        displayDetail("NOTE: \(dmgName) has embedded Software License Agreement")
    }
    var arguments = ["attach", dmgPath, "-nobrowse"]
    if randomMountpoint {
        arguments += ["-mountRandom", "/tmp"]
    }
    if useShadow {
        arguments.append("-shadow")
    }
    if skipVerification {
        arguments.append("-noverify")
    }
    let plistData = hdiutilData(arguments: arguments, stdIn: stdIn)
    if let systemEntities = plistData["system-entities"] as? [PlistDict] {
        for entity in systemEntities {
            if let mountPoint = entity["mount-point"] as? String {
                mountpoints.append(mountPoint)
            }
        }
    } else {
        displayError("Could not get mountpoint info from results of hdiutil attach \(dmgName)")
    }
    return mountpoints
}

func unmountdmg(_ mountpoint: String) {
    // Unmounts the dmg at mountpoint
    var arguments = ["detach", mountpoint]
    let results = runCLI("/usr/bin/hdiutil", arguments: arguments)
    if results.exitcode != 0 {
        // regular unmount failed; try to force unmount
        displayError("Polite unmount failed: \(results.error)")
        displayError("Attempting to force unmount \(mountpoint)")
        arguments.append("-force")
        let results = runCLI("/usr/bin/hdiutil", arguments: arguments)
        if results.exitcode != 0 {
            displayWarning("WARNING: Failed to unmount \(mountpoint): \(results.error)")
        }
    }
}

