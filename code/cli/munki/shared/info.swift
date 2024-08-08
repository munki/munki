//
//  info.swift
//  munki
//
//  Created by Greg Neagle on 8/7/24.
//

import CoreServices.LaunchServices
import Foundation
import IOKit

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
        displayWarning("Could not parse output from system_profiler; skipping SPApplicationsDataType query: \(description)")
        return applicationData
    } catch ProcessError.timeout {
        displayWarning("system_profiler hung; skipping SPApplicationsDataType query")
        return applicationData
    } catch let ProcessError.error(description) {
        displayWarning("Unexpected error with system_profiler; skipping SPApplicationsDataType query: \(description)")
        return applicationData
    } catch {
        displayWarning("Unexpected error with system_profiler; skipping SPApplicationsDataType query")
        return applicationData
    }

    return applicationData
}

func getSystemProfilerData(_ dataType: String) async -> PlistDict {
    // Uses system profiler to get info of data_type for this machine
    let tool = "/usr/sbin/system_profiler"
    let arguments = [dataType, "-xml"]
    let result = await runCliAsync(tool, arguments: arguments)
    if result.exitcode != 0 {
        return PlistDict()
    }
    do {
        if let plist = try readPlist(fromString: result.output) as? [PlistDict] {
            // system_profiler xml is an array
            if let items = plist[0]["_items"] as? [PlistDict],
               items.count > 0
            {
                return items[0]
            }
        }
    } catch {
        return PlistDict()
    }
    return PlistDict()
}

func getHardwareInfo() async -> PlistDict {
    // Uses system profiler to get hardware info for this machine
    return await getSystemProfilerData("SPHardwareDataType")
}

func getIBridgeInfo() async -> PlistDict {
    // Uses system profiler to get iBridge info for this machine
    return await getSystemProfilerData("SPiBridgeDataType")
}

func getIPAddresses(_ kind: String) async -> [String] {
    // Uses system profiler to get active IP addresses for this machine
    // kind must be one of 'IPv4' or 'IPv6'
    // NOTE this does not return any utun addresses.
    var ipAddresses = [String]()
    let tool = "/usr/sbin/system_profiler"
    let arguments = ["SPNetworkDataType", "-xml"]
    let result = await runCliAsync(tool, arguments: arguments)
    if result.exitcode != 0 {
        return ipAddresses
    }
    do {
        if let plist = try readPlist(fromString: result.output) as? [PlistDict] {
            // system_profiler xml is an array
            if let items = plist[0]["_items"] as? [PlistDict] {
                for item in items {
                    if let addressType = item[kind] as? PlistDict,
                       let addresses = addressType["Addresses"] as? [String]
                    {
                        ipAddresses += addresses
                    }
                }
            }
        }
    } catch {
        return ipAddresses
    }
    return ipAddresses
}

// IOKit helpers

private func serviceMatching(_ className: String) -> io_registry_entry_t {
    // returns a reference to an IOKit service matching on IOService class name,
    // typically something like "IOPlatformExpertDevice"
    return IOServiceGetMatchingService(
        kIOMasterPortDefault, IOServiceMatching(className)
    )
}

private func serviceNameMatching(_ name: String) -> io_registry_entry_t {
    // returns a reference to an IOKit service matching on IOService name
    return IOServiceGetMatchingService(
        kIOMasterPortDefault, IOServiceNameMatching(name)
    )
}

private func stringValueForIOServiceProperty(service: io_registry_entry_t, key: String) -> String? {
    // attempts to return a string value for the given property key
    let rawData = IORegistryEntryCreateCFProperty(
        service, key as CFString, kCFAllocatorDefault, 0
    )
    if rawData == nil {
        return nil
    }
    let data = rawData?.takeRetainedValue() as! CFData
    return String(data: data as Data,
                  encoding: .utf8)?.trimmingCharacters(in: ["\0"])
}

// info functions that call IOKit

func serialNumber() -> String {
    // Returns the serial number of this Mac
    let serial = IORegistryEntryCreateCFProperty(
        serviceMatching("IOPlatformExpertDevice"),
        kIOPlatformSerialNumberKey as CFString,
        kCFAllocatorDefault,
        0
    )
    if let serial = serial?.takeRetainedValue() {
        return (serial as! CFString) as String
    }
    return ""
}

func productName() -> String {
    // Returns the product name from IORegistry
    return stringValueForIOServiceProperty(
        service: serviceNameMatching("product"),
        key: "product-name"
    ) ?? ""
}

func boardID() -> String {
    // Returns board-id from IORegistry
    return stringValueForIOServiceProperty(
        service: serviceMatching("IOPlatformExpertDevice"),
        key: "board-id"
    ) ?? "<none>"
}

func deviceID() -> String {
    // Returns board-id from IORegistry
    return stringValueForIOServiceProperty(
        service: serviceMatching("IOPlatformExpertDevice"),
        key: "target-sub-type"
    ) ?? "<none>"
}

// info functions that use sysctlbyname

func hardwareModel() -> String {
    // returns model (Mac1,2)
    var size = 0
    // call sysctlbyname to get the size of the returned string
    let err1 = sysctlbyname("hw.model", nil, &size, nil, 0)
    if err1 != 0 {
        return ""
    }
    // allocate a buffer large enough for model name
    let buffer = UnsafeMutablePointer<UInt8>.allocate(capacity: size)
    defer { buffer.deallocate() }
    // call sysctlbyname again with the buffer
    let err2 = sysctlbyname("hw.model", buffer, &size, nil, 0)
    if err2 != 0 {
        return ""
    }
    return NSString(bytes: buffer,
                    length: size,
                    encoding: String.Encoding.utf8.rawValue) as? String ?? ""
}

func hasIntel64Support() -> Bool {
    // returns true if this Mac has an Intel processor that supports 64bit code
    var size = 0
    // call sysctlbyname to get the size of the returned value
    let err1 = sysctlbyname("hw.optional.x86_64", nil, &size, nil, 0)
    if err1 != 0 {
        return false
    }
    // allocate a buffer large enough for model name
    let buffer = UnsafeMutablePointer<UInt8>.allocate(capacity: size)
    defer { buffer.deallocate() }
    // call sysctlbyname again with the buffer
    let err2 = sysctlbyname("hw.optional.x86_64", buffer, &size, nil, 0)
    if err2 != 0 {
        return false
    }
    return buffer[0] == 1
}
