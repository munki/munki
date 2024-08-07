//
//  info.swift
//  munki
//
//  Created by Greg Neagle on 8/7/24.
//

import CoreServices.LaunchServices
import Foundation

func platform() -> String {
    // returns platform ("x86_64", "arm64")
    var systemInfo = utsname()
    uname(&systemInfo)
    let size = Int(_SYS_NAMELEN) // is 32, but posix AND its init is 256....

    let s = withUnsafeMutablePointer(to: &systemInfo.machine) { p in
        p.withMemoryRebound(to: CChar.self, capacity: size) { p2 in
            return String(cString: p2)
        }
    }
    return s
}

func isAppleSilicon() -> Bool {
    // Returns true if we're running on Apple silicon"
    return platform() == "arm64"
}

// private, undocumented LaunchServices function
@_silgen_name("_LSCopyAllApplicationURLs") func LSCopyAllApplicationURLs(_: UnsafeMutablePointer<NSMutableArray?>) -> OSStatus
func launchServicesInstalledApps() -> [String]? {
    var apps: NSMutableArray?
    if LSCopyAllApplicationURLs(&apps) == 0 {
        if let appURLs = (apps! as NSArray) as? [URL] {
            let pathsArray = appURLs.map(\.path)
            return pathsArray
        }
    }
    return nil
}

func spApplicationData() async -> PlistDict {
    // Uses system profiler to get application info for this machine
    // Returns a dictionary with app paths as keys
    var applicationData = PlistDict()
    let tool = "/usr/sbin/system_profiler"
    let arguments = ["SPApplicationsDataType", "-xml"]
    do {
        let result = try await runCliAsync(tool, arguments: arguments, timeout: 120)
        if result.exitcode != 0 {
            throw ProcessError.error(description: result.error)
        }
        if let plist = try readPlist(fromString: result.output) as? [PlistDict] {
            // system_profiler xml is an array
            if let items = plist[0]["_items"] as? [PlistDict] {
                for item in items {
                    if let path = item["path"] as? String {
                        applicationData[path] = item
                    }
                }
            } else {
                throw PlistError.readError(description: "output is wrong format")
            }
        } else {
            throw PlistError.readError(description: "output is wrong format")
        }
    } catch let PlistError.readError(description) {
        displayError("Could not parse output from system_profiler; skipping SPApplicationsDataType query: \(description)")
        return applicationData
    } catch ProcessError.timeout {
        displayError("system_profiler hung; skipping SPApplicationsDataType query")
        return applicationData
    } catch let ProcessError.error(description) {
        displayError("Unexpected error with system_profiler; skipping SPApplicationsDataType query: \(description)")
        return applicationData
    } catch {
        displayError("Unexpected error with system_profiler; skipping SPApplicationsDataType query")
        return applicationData
    }

    return applicationData
}
