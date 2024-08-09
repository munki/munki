//
//  info.swift
//  munki
//
//  Created by Greg Neagle on 8/7/24.
//

import CoreServices.LaunchServices
import Darwin
import Foundation
import IOKit

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

func findAppsInDirs(_ dirList: [String]) -> [[String: String]] {
    // Do spotlight search for type applications within the
    // list of directories provided. Returns a list of paths to applications
    // dirList is actually a list of NSMetadataQuery search scopes, which
    // can be paths, or certain constants
    // Typically we'll use NSMetadataQueryLocalComputerScope to search the
    // local computer (skipping mounted network volumes)
    var appList = [[String: String]]()
    let query = NSMetadataQuery()
    query.predicate = NSPredicate(format: "(kMDItemKind = \"Application\")")
    query.searchScopes = dirList
    query.start()
    // Spotlight isGathering phase - this is the initial search. After the
    // isGathering phase Spotlight keeps running returning live results from
    // filesystem changes. We are not interested in that phase.
    // Run for 0.1 seconds then check if isGathering has completed.
    let maxRuntime = 20.0
    var runtime = 0.0
    while query.isGathering, runtime <= maxRuntime {
        runtime += 0.1
        RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.1))
    }
    query.stop()

    if runtime >= maxRuntime {
        displayWarning(
            "Spotlight search for applications terminated due to excessive time. Possible causes: Spotlight indexing is turned off for a volume; Spotlight is reindexing a volume."
        )
    }

    let count = query.resultCount
    for index in 0 ..< count {
        if let result = query.result(at: index) as? NSMetadataItem,
           let path = result.value(forAttribute: NSMetadataItemPathKey) as? String,
           !path.hasPrefix("/Volumes")
        {
            let name = result.value(forAttribute: NSMetadataItemFSNameKey) as? String ?? ""
            let bundleID = result.value(forAttribute: NSMetadataItemCFBundleIdentifierKey) as? String ?? ""
            let version = result.value(forAttribute: NSMetadataItemVersionKey) as? String ?? ""

            if bundleID.isEmpty, version.isEmpty {
                // both bundleid and version are missing. is this really an app?
                if pathIsRegularFile(path), !pathIsExecutableFile(path) {
                    // it's a file, but not executable, so can't really be an app
                    continue
                }
            }

            appList.append(
                ["name": name,
                 "path": path,
                 "bundleid": bundleID,
                 "version": version]
            )
        }
    }
    return appList
}

func spotlightInstalledApps() -> [[String: String]] {
    // Get paths of currently installed applications per Spotlight.
    // Return value is list of paths.
    // Currently searches only the local computer, but not network volumes
    return findAppsInDirs([NSMetadataQueryLocalComputerScope])
}

// private, undocumented LaunchServices function
@_silgen_name("_LSCopyAllApplicationURLs") func LSCopyAllApplicationURLs(_: UnsafeMutablePointer<NSMutableArray?>) -> OSStatus
func launchServicesInstalledApps() -> [String] {
    var apps: NSMutableArray?
    if LSCopyAllApplicationURLs(&apps) == 0 {
        if let appURLs = (apps! as NSArray) as? [URL] {
            let pathsArray = appURLs.map(\.path)
            return pathsArray
        }
    }
    return [String]()
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

func appData() -> [[String: String]] {
    // Gets info on currently installed apps.
    // Returns a list of dicts containing path, name, version and bundleid

    // one thing I'm not at all sure about is what iOS/iPadOS apps
    // installed on Apple silicon Macs look like and how/if
    // Launch Services, Spotlight, and system_profiler report them

    displayDebug1("Getting info on currently installed applications...")
    // async let spAppData = spApplicationData()
    let lsApps = launchServicesInstalledApps()
    // print("LaunchServices found \(lsApps.count) apps")
    let spotlightApps = spotlightInstalledApps()
    // print("Spotlight found \(spotlightApps.count) apps")
    // print("system_profiler found \(await spAppData.count) apps")

    // find apps that are unique to the LaunchServices list
    let spotlightAppPaths = spotlightApps.map { $0["path"] ?? "" }.filter { !$0.isEmpty }
    let uniqueToLS = Set(lsApps).subtracting(Set(spotlightAppPaths))

    var applicationData = spotlightApps
    // add apps found by Launch Services that Spotlight didn't return
    for appPath in uniqueToLS {
        var item = [String: String]()
        item["path"] = appPath
        applicationData.append(item)
    }
    // now make sure as much additional data is populated as possible
    for (index, item) in applicationData.enumerated() {
        if (item["name"] ?? "").isEmpty || (item["version"] ?? "").isEmpty ||
            (item["bundleid"] ?? "").isEmpty
        {
            var updatedItem = item
            let path = item["path"] ?? ""
            updatedItem["name"] = (path as NSString).lastPathComponent
            if let bundleInfo = getBundleInfo(path) {
                updatedItem["bundleid"] = bundleInfo["CFBundleIdentifier"] as? String ?? ""
                if let cfBundleName = bundleInfo["CFBundleName"] as? String,
                   !cfBundleName.isEmpty
                {
                    updatedItem["name"] = cfBundleName
                }
                updatedItem["version"] = getBundleVersion(path)
                if (updatedItem["version"] ?? "").isEmpty {
                    updatedItem["version"] = "0.0.0.0.0"
                }
            } else {
                // no Info.plist? Should we use system_profiler info?
                // it's not clear that calling system_profiler here will
                // help us get enough better data to be worth it.
            }
            applicationData[index] = updatedItem
        }
    }
    return applicationData
}

func filteredAppData() -> [[String: String]] {
    // Returns a filtered version of app_data, filtering out apps in user
    // home directories for use by compare_application_version()
    return appData().filter {
        !(($0["path"] ?? "").hasPrefix("/Users") && !($0["path"] ?? "").hasPrefix("/Users/Shared"))
    }
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

func getMachineFacts() async -> PlistDict {
    // Gets some facts about this machine we use to determine if a given
    // installer is applicable to this OS or hardware

    // these all call system_profiler so see if we can do
    // them concurrently
    async let ip4addresses = await getIPAddresses("IPv4")
    async let ip6addresses = await getIPAddresses("IPv6")
    async let iBridgeInfo = await getIBridgeInfo()

    var machine = PlistDict()

    machine["hostname"] = hostname()
    var arch = platform()
    if arch == "x86_64" {
        // we might be natively Intel64, or running under Rosetta.
        // uname's 'platform' returns the current execution arch, which under Rosetta
        // will be x86_64. Since what we want here is the _native_ arch, we're
        // going to use a hack for now to see if we're natively arm64
        if uname_version().contains("ARM64") {
            arch = "arm64"
        }
    }
    machine["arch"] = arch
    if arch == "x86_64" {
        machine["x86_64_capable"] = true
    } else if arch == "i386" {
        // I don't think current Swift is even supported on 32-bit Intel
        // so this is probably useless
        machine["x86_64_capable"] = hasIntel64Support()
    }
    machine["os_vers"] = getOSVersion(onlyMajorMinor: false)
    machine["os_build_number"] = getOSBuild()
    machine["machine_model"] = hardwareModel()
    machine["munki_version"] = getVersion()
    machine["ipv4_address"] = await ip4addresses
    machine["ipv6_address"] = await ip6addresses
    machine["serial_number"] = serialNumber()
    machine["product_name"] = productName()
    machine["ibridge_model_name"] = await iBridgeInfo["ibridge_model_name"] as? String ?? "NO IBRIDGE CHIP"
    machine["board_id"] = boardID()
    machine["device_id"] = deviceID()

    return machine
}

private func conditionalScriptsDir() -> String {
    // returns the path to the conditional scripts dir
    // TODO: make this relative to the managedsoftwareupdate binary
    return "/usr/local/munki/conditions"
}

func getConditions() async -> PlistDict {
    // Fetches key/value pairs from condition scripts
    // which can be placed into /usr/local/munki/conditions

    let conditionalScriptDir = conditionalScriptsDir()
    let conditionalItemsPath = (managedInstallsDir() as NSString).appendingPathComponent("ConditionalItems.plist")
    let filemanager = FileManager.default
    try? filemanager.removeItem(atPath: conditionalItemsPath)

    if pathExists(conditionalScriptDir), !pathIsDirectory(conditionalScriptDir) {
        displayWarning("\(conditionalScriptDir) exists but is not a directory.")
        return PlistDict()
    }

    if let scriptDirItems = try? filemanager.contentsOfDirectory(atPath: conditionalScriptDir) {
        for item in scriptDirItems {
            if item.hasPrefix(".") {
                // skip it
                continue
            }
            let itemPath = (conditionalScriptDir as NSString).appendingPathComponent(item)
            if pathIsDirectory(itemPath) {
                // skip it
                continue
            }
            do {
                let _ = try await runExternalScript(itemPath, timeout: 60)
            } catch {
                displayError(error.localizedDescription)
            }
        }
        if pathExists(conditionalItemsPath) {
            do {
                if let conditions = try readPlist(fromFile: conditionalItemsPath) as? PlistDict {
                    // success!!
                    try? filemanager.removeItem(atPath: conditionalItemsPath)
                    return conditions
                } else {
                    // data is in wrong formet
                    displayWarning("\(conditionalItemsPath) contents are in an unexpected format.")
                }
            } catch {
                // file was invalid
                displayWarning("\(conditionalItemsPath) contents are invalid.")
            }
        } else {
            // file doesn't exist. Not an error to warn about
        }
    } else {
        // could not get script items from dir
        displayWarning("Unexpected filesyem issue getting contents of \(conditionalScriptDir)")
    }
    return PlistDict() // empty results
}
