//
//  info.swift
//  munki
//
//  Created by Greg Neagle on 8/7/24.
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

import CoreServices.LaunchServices
import Darwin
import Foundation
import IOKit

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
    return "UNKNOWN"
}

func productName() -> String {
    // Returns the product name from IORegistry
    return stringValueForIOServiceProperty(
        service: serviceNameMatching("product"),
        key: "product-name"
    ) ?? "Intel Mac"
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
        return "UNKNOWN"
    }
    // allocate a buffer large enough for model name
    let buffer = UnsafeMutablePointer<UInt8>.allocate(capacity: size)
    defer { buffer.deallocate() }
    // call sysctlbyname again with the buffer
    let err2 = sysctlbyname("hw.model", buffer, &size, nil, 0)
    if err2 != 0 {
        return "UNKNOWN"
    }
    let str = buffer.withMemoryRebound(to: CChar.self, capacity: size) { ptr in
        return String(cString: ptr)
    }
    return str
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

func availableDiskSpace(volumePath _: String = "/") -> Int {
    // Returns available diskspace in KBytes.
    // Value should be very close to `df -k` output
    // Returns negative values of there is an error
    let buffer = UnsafeMutablePointer<statvfs>.allocate(capacity: 1024)
    defer { buffer.deallocate() }
    let err = statvfs("/", buffer)
    if err != 0 {
        return -1
    }
    let f_frsize = Int(buffer.pointee.f_frsize)
    let f_bavail = Int(buffer.pointee.f_bavail)
    return Int(f_frsize * f_bavail / 1024)
}

func hostname() -> String {
    // returns uname's version of hostname
    var systemInfo = utsname()
    uname(&systemInfo)
    let size = Int(_SYS_NAMELEN) // is 256 on Darwin

    let str = withUnsafeMutablePointer(to: &systemInfo.nodename) { p in
        p.withMemoryRebound(to: CChar.self, capacity: size) { p2 in
            return String(cString: p2)
        }
    }
    return str
}

func platform() -> String {
    // returns platform (arch) ("x86_64", "arm64")
    var systemInfo = utsname()
    uname(&systemInfo)
    let size = Int(_SYS_NAMELEN) // is 256 on Darwin

    let str = withUnsafeMutablePointer(to: &systemInfo.machine) { p in
        p.withMemoryRebound(to: CChar.self, capacity: size) { p2 in
            return String(cString: p2)
        }
    }
    return str
}

func uname_version() -> String {
    // returns uname's version string
    var systemInfo = utsname()
    uname(&systemInfo)
    let size = Int(_SYS_NAMELEN) // is 256 on Darwin

    let str = withUnsafeMutablePointer(to: &systemInfo.version) { p in
        p.withMemoryRebound(to: CChar.self, capacity: size) { p2 in
            return String(cString: p2)
        }
    }
    return str
}

func isAppleSilicon() -> Bool {
    // Returns true if we're running on Apple silicon"
    return platform() == "arm64"
}

func getOSBuild() -> String {
    // Returns the OS Build "number" (example 16G1212).
    do {
        if let systemVersion = try readPlist(
            fromFile: "/System/Library/CoreServices/SystemVersion.plist"
        ) as? PlistDict {
            return systemVersion["ProductBuildVersion"] as? String ?? ""
        }
    } catch {
        // fall through
    }
    return ""
}
