//
//  munki.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 5/27/18.
//  Copyright © 2018-2026 The Munki Project. All rights reserved.
//

import AppKit
import Foundation
import IOKit
import SystemConfiguration

typealias PlistDict = [String: Any]

let INSTALLATLOGOUTFILE = "/private/tmp/com.googlecode.munki.installatlogout"
let UPDATECHECKLAUNCHFILE = "/private/tmp/.com.googlecode.munki.updatecheck.launchd"
let INSTALLWITHOUTLOGOUTFILE = "/private/tmp/.com.googlecode.munki.managedinstall.launchd"

let BUNDLE_ID = "ManagedInstalls" as CFString
let DEFAULT_GUI_CACHE_AGE_SECS = 3600
let WRITEABLE_SELF_SERVICE_MANIFEST_PATH = "/Users/Shared/.SelfServeManifest"

func exec(_ command: String, args: [String] = []) -> String {
    // runs a UNIX command and returns stdout as a string
    let proc = Process()
    proc.launchPath = command
    proc.arguments = args
    let pipe = Pipe()
    proc.standardOutput = pipe
    proc.launch()
    let data = pipe.fileHandleForReading.readDataToEndOfFile()
    return String(data: data, encoding: String.Encoding.utf8)!
}

func osascript(_ osastring: String) -> String {
    // Wrapper to run AppleScript commands
    let command = "/usr/bin/osascript"
    let args = ["-e", osastring]
    return exec(command, args: args)
}

func restartNow() {
    // Trigger a restart'''
    _ = osascript("tell application \"System Events\" to restart")
}

func uname_version() -> String {
    var system = utsname()
    uname(&system)
    let version = withUnsafePointer(to: &system.version.0) { ptr in
        return String(cString: ptr)
    }
    return version
}

func isAppleSilicon() -> Bool {
    // Lame but same logic as the Munki Python code,
    // so at least consistent!
    let version_str = uname_version()
    return version_str.contains("ARM64")
}

func reloadPrefs() {
    /* Uses CFPreferencesAppSynchronize(BUNDLE_ID)
     to make sure we have the latest prefs. Call this
     if another process may have modified ManagedInstalls.plist,
     this needs to be run after returning from MunkiStatus */
    CFPreferencesAppSynchronize(BUNDLE_ID)
}

func pythonishBool(_ foo: Any?) -> Bool {
    // Converts values of various types to boolean in the same way
    // Python treats non-booleans in a boolean context
    if let bar = foo as? Bool {
        return bar
    }
    if let bar = foo as? Int {
        // Anything but 0 is true
        return bar != 0
    }
    if let bar = foo as? Double {
        // Anything but 0 is true
        return bar != 0.0
    }
    if let bar = foo as? String {
        // Non-empty strings are true; else false
        return !bar.isEmpty
    }
    if let bar = foo as? [Any] {
        // Non-empty arrays are true; else false
        return !bar.isEmpty
    }
    if let bar = foo as? [AnyHashable: Any] {
        // Non-empty dicts are true; else false
        return !bar.isEmpty
    }
    // nil or unhandled type is false
    return false
}

func pref(_ prefName: String) -> Any? {
    /* Return a preference. Since this uses CFPreferencesCopyAppValue,
     Preferences can be defined several places. Precedence is:
     - MCX
     - ~/Library/Preferences/ManagedInstalls.plist
     - /Library/Preferences/ManagedInstalls.plist
     - defaultPrefs defined here. */

    let defaultPrefs: [String: Any] = [
        "ManagedInstallDir": "/Library/Managed Installs",
        "InstallAppleSoftwareUpdates": false,
        "AppleSoftwareUpdatesOnly": false,
        "ShowRemovalDetail": false,
        "InstallRequiresLogout": false,
        "CheckResultsCacheSeconds": DEFAULT_GUI_CACHE_AGE_SECS,
        "LogFile": "/Library/Managed Installs/Logs/ManagedSoftwareUpdate.log",
        "MSCOfferToQuitBlockingApps": false,
        "MSCOfferToForceQuitBlockingApps": false,
        "MSCOfferToUpdateOthers": false,
    ]

    var value: Any?
    value = CFPreferencesCopyAppValue(prefName as CFString, BUNDLE_ID)
    if value == nil {
        value = defaultPrefs[prefName]
    }
    return value
}

func logFilePref() -> String {
    /* Returns Munki's LogFile preference. Since this uses CFPreferencesCopyAppValue,
     preferences can be defined several places. Precedence is:
     - MCX/configuration profile
     - ~/Library/Preferences/ManagedInstalls.plist
     - /Library/Preferences/ManagedInstalls.plist
     - default_pref defined here.
     */
    let value = CFPreferencesCopyAppValue("LogFile" as CFString, "ManagedInstalls" as CFString)
    if value == nil {
        return "/Library/Managed Installs/Logs/ManagedSoftwareUpdate.log"
    }
    return value! as! String
}

func readSelfServiceManifest() -> PlistDict {
    // Read the SelfServeManifest if it exists
    // first try writable copy
    var selfServeManifest = WRITEABLE_SELF_SERVICE_MANIFEST_PATH
    if !(FileManager.default.isReadableFile(atPath: selfServeManifest)) {
        // no writable copy; look for system copy
        let managedinstallbase = pref("ManagedInstallDir") as! String
        selfServeManifest = NSString.path(
            withComponents: [managedinstallbase, "manifests", "SelfServeManifest"])
    }
    if FileManager.default.isReadableFile(atPath: selfServeManifest) {
        do {
            let plist = try readPlist(selfServeManifest) as? PlistDict
            return plist ?? PlistDict()
        } catch {
            return PlistDict()
        }
    } else {
        return PlistDict()
    }
}

func writeSelfServiceManifest(_ optional_install_choices: PlistDict) -> Bool {
    /* Write out our self-serve manifest
     so managedsoftwareupdate can use it. Returns True on success,
     False otherwise. */
    var manifest_contents = readSelfServiceManifest()
    manifest_contents["managed_installs"] = (optional_install_choices["managed_installs"] as? [String] ?? [String]())
    manifest_contents["managed_uninstalls"] = (optional_install_choices["managed_uninstalls"] as? [String] ?? [String]())
    do {
        try writePlist(
            manifest_contents,
            toFile: WRITEABLE_SELF_SERVICE_MANIFEST_PATH
        )
        return true
    } catch {
        return false
    }
}

func userSelfServiceChoicesChanged() -> Bool {
    /* Is WRITEABLE_SELF_SERVICE_MANIFEST_PATH different from
     the 'system' version of this file? */
    if !(FileManager.default.isReadableFile(atPath: WRITEABLE_SELF_SERVICE_MANIFEST_PATH)) {
        return false
    }
    do {
        let user_choices = try readPlist(WRITEABLE_SELF_SERVICE_MANIFEST_PATH) as? NSDictionary
        let managedinstallbase = pref("ManagedInstallDir") as! String
        let system_path = NSString.path(
            withComponents: [managedinstallbase, "manifests", "SelfServeManifest"])
        if !(FileManager.default.isReadableFile(atPath: system_path)) {
            return true
        }
        let system_choices = try readPlist(system_path) as? NSDictionary
        return user_choices != system_choices
    } catch {
        return false
    }
}

func getRemovalDetailPrefs() -> Bool {
    // Returns preference to control display of removal detail
    return pythonishBool(pref("ShowRemovalDetail"))
}

func installRequiresLogout() -> Bool {
    // Returns preference to force logout for all installs
    return pythonishBool(pref("InstallRequiresLogout"))
}

func readPlistAsNSDictionary(_ filepath: String) -> PlistDict {
    // Read a plist file and return PlistData
    do {
        let plist = try readPlist(filepath) as? PlistDict
        return plist ?? PlistDict()
    } catch {
        return PlistDict()
    }
}

func getStagedOSUpdate() -> PlistDict {
    // Returns a dictionary describing a staged OS update (if any)
    let managedinstallbase = pref("ManagedInstallDir") as! String
    let info_path = NSString.path(
        withComponents: [managedinstallbase, "StagedOSInstaller.plist"])
    let info = readPlistAsNSDictionary(info_path)
    // ensure something exists at the osinstaller_path
    if let app_path = info["osinstaller_path"] as? String {
        if FileManager.default.fileExists(atPath: app_path) {
            return info
        }
    }
    return PlistDict()
}

func getInstallInfo() -> PlistDict {
    // Returns the dictionary describing the managed installs and removals
    let managedinstallbase = pref("ManagedInstallDir") as! String
    let installinfo_path = NSString.path(
        withComponents: [managedinstallbase, "InstallInfo.plist"])
    return readPlistAsNSDictionary(installinfo_path)
}

/// Returns info about available Apple software updates
func getAppleUpdates() -> [PlistDict] {
    var appleUpdates: [PlistDict] = []
    if pythonishBool(pref("InstallAppleSoftwareUpdates")),
       let recommendedUpdates = su_pref("RecommendedUpdates") as? [[String: Any]]
    {
        // get data from Munki's AppleUpdates.plist if it exists
        let managedinstallbase = pref("ManagedInstallDir") as! String
        let appleupdates_path = NSString.path(
            withComponents: [managedinstallbase, "AppleUpdates.plist"])
        let plistData = readPlistAsNSDictionary(appleupdates_path)
        let appleUpdateInfo = plistData["AppleUpdates"] as? [PlistDict] ?? []
        if pythonishBool(plistData["AppleUpdatesTesting"]) {
            // this lets us test MSC behavior with fake data
            return appleUpdateInfo
        }
        // use com.apple.SoftwareUpdate RecommendedUpdates as source of truth
        for update in recommendedUpdates {
            guard let productKey = update["Product Key"] as? String else { continue }
            var matchingItem: PlistDict?
            for infoItem in appleUpdateInfo {
                if infoItem["productKey"] as? String == productKey {
                    matchingItem = infoItem
                }
            }
            if let matchingItem {
                appleUpdates.append(matchingItem)
            } else {
                // sadly this causes majorOS upgrades to be displayed
                // and some other things that `softwareupdate --list`
                // doesn't show
                /*
                // not in AppleUpdates.plist, construct one with the info we have
                var item = PlistDict()
                item["name"] = update["Display Name"] as? String
                item["display_name"] = item["name"]
                item["version_to_install"] = update["Display Version"] as? String
                item["productKey"] = update["Product Key"] as? String
                item["installer_item_size"] = ""
                appleUpdates.append(item)
                */
            }
        }
    }
    return appleUpdates
}

/// Class to compare two version strings in a consistent way
/// Originally based on Python's distutils.version.LooseVersion
/// The intention is for version comparisons to be the same as
/// the Python version of Munki
struct MunkiVersion: Equatable, Comparable {
    let value: String

    init(_ str: String) {
        value = str
    }

    /// pads version strings by adding extra ".0"s to one if needed
    static func pad(_ a: String, count: Int) -> String {
        var components = a.split(separator: ".", omittingEmptySubsequences: true)
        while components.count < count {
            components.append("0")
        }
        return components.joined(separator: ".")
    }

    /// compares two version strings and returns a ComparisonResult
    static func compare(_ lhs: String, _ rhs: String) -> ComparisonResult {
        let maxCount = max(lhs.count, rhs.count)
        let a = pad(lhs, count: maxCount)
        let b = pad(rhs, count: maxCount)
        return a.compare(b, options: .numeric)
    }

    static func < (lhs: MunkiVersion, rhs: MunkiVersion) -> Bool {
        return compare(lhs.value, rhs.value) == .orderedAscending
    }

    static func > (lhs: MunkiVersion, rhs: MunkiVersion) -> Bool {
        return compare(lhs.value, rhs.value) == .orderedDescending
    }

    static func == (lhs: MunkiVersion, rhs: MunkiVersion) -> Bool {
        return compare(lhs.value, rhs.value) == .orderedSame
    }
}


/// Returns the macOS version
func getOSVersion(onlyMajorMinor: Bool = true) -> String {
    let version = ProcessInfo().operatingSystemVersion

    if version.patchVersion == 0 || onlyMajorMinor {
        return "\(version.majorVersion).\(version.minorVersion)"
    } else {
        return "\(version.majorVersion).\(version.minorVersion).\(version.patchVersion)"
    }
}

func macOSOutOfDateDays() -> Int {
    guard let managedinstallbase = pref("ManagedInstallDir") as? String else {
        return 0
    }
    let appleUpdateHistoryPath = (managedinstallbase as NSString).appendingPathComponent("AppleUpdateHistory.plist")
    let appleUpdateHistory = readPlistAsNSDictionary(appleUpdateHistoryPath)
    let currentOSVersion = MunkiVersion(getOSVersion())
    let majorOSVersion = "\(ProcessInfo().operatingSystemVersion.majorVersion)."
    var macOSUpdates = [PlistDict]()
    for value in appleUpdateHistory.values {
        if let update = value as? PlistDict,
           let version = update["version"] as? String
        {
            macOSUpdates.append(update)
        }
    }
    // sort ascending by version
    macOSUpdates.sort {
        MunkiVersion($0["version"] as? String ?? "") < MunkiVersion($1["version"] as? String ?? "")
    }
    for update in macOSUpdates {
        if let version = update["version"] as? String,
           version.hasPrefix(majorOSVersion),
           let firstSeen = update["firstSeen"] as? Date,
           MunkiVersion(version) > currentOSVersion
        {
            // found a macOS update (but not _upgrade_) higher than what we are currently running
            // return the number of days it's been since that update was first seen
            return Int(Date().timeIntervalSince(firstSeen) / (24 * 60 * 60))
        }
    }
    return 0
}

func getUpdateNotificationTracking() -> PlistDict {
    // Returns a dictionary describing when items were first made available
    guard let managedinstallbase = pref("ManagedInstallDir") as? String else {
        return PlistDict()
    }
    let updatetracking_path = NSString.path(
        withComponents: [managedinstallbase, "UpdateNotificationTracking.plist"])
    return readPlistAsNSDictionary(updatetracking_path)
}

func munkiUpdatesContainAppleItems() -> Bool {
    // Return true if there are any Apple items in the list of updates
    let installinfo = getInstallInfo()
    for key in ["managed_installs", "removals"] {
        let items = (installinfo[key] ?? []) as! [PlistDict]
        for item in items {
            if let value = item["apple_item"] as? Bool {
                if value {
                    return true
                }
            }
        }
    }
    return false
}

func discardTimeZoneFromDate(_ theDate: Date) -> Date {
    /* Input: Date object
     Output: Date object with same date and time as the UTC.
     In Los Angeles (PDT), '2011-06-20T12:00:00Z' becomes
     '2011-06-20 12:00:00 -0700'.
     In New York (EDT), it becomes '2011-06-20 12:00:00 -0400'. */
    let timeZoneOffset = TimeZone.current.secondsFromGMT(for: theDate)
    return theDate.addingTimeInterval(TimeInterval(-timeZoneOffset))
}

func thereAreUpdatesToBeForcedSoon(hours: Int = 72) -> Bool {
    // Return True if any updates need to be installed within the next
    // X hours, false otherwise
    var installinfo = getInstallInfo()["managed_installs"] as? [PlistDict] ?? [PlistDict]()
    installinfo = installinfo + getAppleUpdates()
    let now_xhours = Date(timeIntervalSinceNow: TimeInterval(hours * 3600))
    for item in installinfo {
        if var force_install_after_date = item["force_install_after_date"] as? Date {
            force_install_after_date = discardTimeZoneFromDate(force_install_after_date)
            if now_xhours >= force_install_after_date {
                return true
            }
        }
    }
    return false
}

func earliestForceInstallDate(_ installinfo: [PlistDict]? = nil) -> Date? {
    // Check installable packages for force_install_after_dates
    // Returns None or earliest force_install_after_date converted to local time
    var installinfo = installinfo
    var earliest_date: Date?
    if installinfo == nil {
        let managed_installs = getInstallInfo()["managed_installs"] as? [PlistDict] ?? [PlistDict]()
        installinfo = managed_installs + getAppleUpdates()
    }
    for install in installinfo! {
        if var this_force_install_date = install["force_install_after_date"] as? Date {
            this_force_install_date = discardTimeZoneFromDate(this_force_install_date)
            if earliest_date == nil || this_force_install_date < earliest_date! {
                earliest_date = this_force_install_date
            }
        }
    }
    return earliest_date
}

func stringFromDate(_ theDate: Date) -> String {
    // Input: NSDate object
    // Output: unicode object, date and time formatted per system locale.
    let df = DateFormatter()
    df.formatterBehavior = .behavior10_4
    df.dateStyle = .long
    df.timeStyle = .short
    return df.string(from: theDate)
}

func shortRelativeStringFromDate(_ theDate: Date) -> String {
    // Input: NSDate object
    // Output: unicode object, date and time formatted per system locale.
    let df = DateFormatter()
    df.formatterBehavior = .behavior10_4
    df.dateStyle = .short
    df.timeStyle = .short
    df.doesRelativeDateFormatting = true
    return df.string(from: theDate)
}

func humanReadable(_ kbytes: Int) -> String {
    let units: [(String, Int)] = [
        ("KB", 1024),
        ("MB", 1024 * 1024),
        ("GB", 1024 * 1024 * 1024),
        ("TB", 1024 * 1024 * 1024 * 1024),
    ]
    for (suffix, limit) in units {
        if kbytes <= limit {
            return String(
                format: "%.1f %@", Double(kbytes) / Double(limit / 1024), suffix
            )
        }
    }
    return ""
}

func trimVersionString(_ version_string: String?) -> String {
    /* Trims all lone trailing zeros in the version string after major/minor.

     Examples:
     10.0.0.0 -> 10.0
     10.0.0.1 -> 10.0.0.1
     10.0.0-abc1 -> 10.0.0-abc1
     10.0.0-abc1.0 -> 10.0.0-abc1 */
    if version_string == nil || version_string!.isEmpty {
        return ""
    }
    var version_parts = version_string!.split(separator: ".")
    while version_parts.count > 2, version_parts.last == "0" {
        version_parts.removeLast()
    }
    return version_parts.joined(separator: ".")
}

func getconsoleuser() -> String? {
    // Get current GUI user
    return SCDynamicStoreCopyConsoleUser(nil, nil, nil) as String?
}

func currentGUIusers() -> [String] {
    // Gets a list of GUI users by parsing the output of /usr/bin/who
    // TO-DO: rewrite this to use the utmpx API
    let users_to_ignore = ["_mbsetupuser"]
    var gui_users = [String]()
    let who_output = exec("/usr/bin/who")
    let lines = who_output.split(separator: "\n")
    for line in lines {
        let parts = line.split(separator: " ", omittingEmptySubsequences: true)
        let username = String(parts[0])
        if parts.count > 1, parts[1] == "console", !users_to_ignore.contains(username) {
            gui_users.append(username)
        }
    }
    return gui_users
}

enum ProcessStartError: Error {
    case error(description: String)
}

func startUpdateCheck(_ suppress_apple_update_check: Bool = false) throws {
    // Does launchd magic to run managedsoftwareupdate as root.
    if !(FileManager.default.fileExists(atPath: UPDATECHECKLAUNCHFILE)) {
        let plist = ["SuppressAppleUpdateCheck": suppress_apple_update_check]
        do {
            try writePlist(plist, toFile: UPDATECHECKLAUNCHFILE)
        } catch {
            let message = "Could not create file \(UPDATECHECKLAUNCHFILE) -- \(error)"
            msc_log("MSC", "cant_write_file", msg: message)
            throw ProcessStartError.error(description: message)
        }
    }
}

func logoutNow() {
    /* Uses osascript to run an AppleScript
     to tell loginwindow to logout.
     Ugly, but it works. */
    let script = """
    ignoring application responses
        tell application "loginwindow"
            «event aevtrlgo»
        end tell
    end ignoring
    """
    _ = exec("/usr/bin/osascript", args: ["-e", script])
}

func logoutAndUpdate() throws {
    // Touch a flag so the process that runs after logout
    // knows it's OK to install everything, then trigger logout
    if !(FileManager.default.fileExists(atPath: INSTALLATLOGOUTFILE)) {
        let success = FileManager.default.createFile(
            atPath: INSTALLATLOGOUTFILE, contents: nil, attributes: nil
        )
        if !success {
            throw ProcessStartError.error(
                description: "Could not create file \(INSTALLATLOGOUTFILE)")
        }
    }
    logoutNow()
}

func justUpdate() throws {
    /* Trigger managedinstaller via launchd KeepAlive path trigger
     We touch a file that launchd is is watching
     launchd, in turn,
     launches managedsoftwareupdate --installwithnologout as root
     We write specific contents to the file to tell managedsoftwareupdate
     to launch a staged macOS installer if applicable */
    let plist = ["LaunchStagedOSInstaller": updateListContainsStagedOSUpdate()]
    do {
        try writePlist(plist, toFile: INSTALLWITHOUTLOGOUTFILE)
    } catch {
        msc_log("MSC", "cant_write_file", msg: "Couldn't write \(INSTALLWITHOUTLOGOUTFILE) -- \(error)")
        throw ProcessStartError.error(
            description: "Could not create file \(INSTALLWITHOUTLOGOUTFILE)")
    }
}

/// Returns true if a Python script matching scriptName is running
func pythonScriptRunning(_ scriptName: String) -> Bool {
    let output = exec("/bin/ps", args: ["-eo", "command="])
    let lines = output.components(separatedBy: "\n")
    for line in lines {
        let part = line.components(separatedBy: " ")
        if part[0].contains("/MacOS/Python") || part[0].contains("python") {
            if part.count > 1 {
                if (part[1] as NSString).lastPathComponent == scriptName {
                    return true
                }
            }
        }
    }
    return false
}

/// Returns true if there is a running executable exactly matching the name
func executableRunning(_ name: String) -> Bool {
    let result = exec("/usr/bin/pgrep", args: ["-x", name])
    return !result.isEmpty
}

/// Returns true if managedsoftwareupdate is running
func managedsoftwareupdateInstanceRunning() -> Bool {
    // A Python version of managedsoftwareupdate might be running,
    // or a compiled version
    if executableRunning("managedsoftwareupdate") {
        return true
    }
    if pythonScriptRunning(".managedsoftwareupdate.py") {
        return true
    }
    if pythonScriptRunning("managedsoftwareupdate.py") {
        return true
    }
    if pythonScriptRunning("managedsoftwareupdate") {
        return true
    }
    return false
}

func getRunningProcessesWithUsers() -> [[String: String]] {
    // Returns a list of usernames and paths of running processes
    var proc_list = [[String: String]]()
    let LaunchCFMApp = "/System/Library/Frameworks/Carbon.framework/Versions/A/Support/LaunchCFMApp"
    let ps_out = exec("/bin/ps", args: ["-axo", "user=,comm="])
    var saw_launch_cfmapp = false
    for line in ps_out.split(separator: "\n") {
        // split into max two parts on whitespace
        let parts = line.split(
            maxSplits: 1, omittingEmptySubsequences: true,
            whereSeparator: { " \t".contains($0) }
        )
        if parts.count > 1, parts[1] == LaunchCFMApp {
            saw_launch_cfmapp = true
        } else if parts.count > 1 {
            let user = String(parts[0])
            let pathname = String(
                parts[1]).trimmingCharacters(in: NSCharacterSet.whitespaces)
            let info = ["user": user, "pathname": pathname]
            proc_list.append(info)
        }
    }
    if saw_launch_cfmapp {
        // look at the process table again with different options
        // and get the arguments for LaunchCFMApp instances
        let ps_out = exec("/bin/ps", args: ["-axo", "user=,command="])
        for line in ps_out.split(separator: "\n") {
            // split into max three parts on whitespace
            let parts = line.split(maxSplits: 2, whereSeparator: { " \t".contains($0) })
            if parts.count > 2, parts[1] == LaunchCFMApp {
                let user = String(parts[0])
                let pathname = String(
                    parts[2]).trimmingCharacters(in: NSCharacterSet.whitespaces)
                let info = ["user": user, "pathname": pathname]
                proc_list.append(info)
            }
        }
    }
    return proc_list
}

struct BlockingAppInfo {
    var user = ""
    var pathname = ""
    var display_name = ""
}

/// Given a list of app names, return a list of BlockingAppInfo for apps i
/// the list that are running.
func getRunningBlockingApps(_ appnames: [String]) -> [BlockingAppInfo] {
    let proc_list = getRunningProcessesWithUsers()
    var running_apps = [BlockingAppInfo]()
    let filemanager = FileManager.default
    for appname in appnames {
        var matching_items = [[String: String]]()
        if appname.hasPrefix("/") {
            // search by exact path
            matching_items = proc_list.filter { $0["pathname"] == appname }
        } else if appname.hasSuffix(".app") {
            // search for app bundles
            let filterterm = "/\(appname)/Contents/MacOS/"
            matching_items = proc_list.filter { $0["pathname"] != nil && $0["pathname"]!.contains(filterterm) }
        } else {
            // check executable name
            let filterterm = "/\(appname)"
            matching_items = proc_list.filter { $0["pathname"] != nil && $0["pathname"]!.hasSuffix(filterterm) }
        }
        if matching_items.count == 0 {
            // try adding '.app' to the name and check again
            let filterterm = "/\(appname).app/Contents/MacOS/"
            matching_items = proc_list.filter { $0["pathname"] != nil && $0["pathname"]!.contains(filterterm) }
        }
        for index in 0 ..< matching_items.count {
            if var path = matching_items[index]["pathname"] {
                while path.contains("/Contents/") || path.hasSuffix("/Contents") {
                    path = (path as NSString).deletingLastPathComponent
                }
                // ask NSFileManager for localized name since end-users
                // will see this name
                matching_items[index]["display_name"] = filemanager.displayName(atPath: path)
                running_apps.append(
                    BlockingAppInfo(
                        user: matching_items[index]["user"] ?? "",
                        pathname: path,
                        display_name: filemanager.displayName(atPath: path)
                    )
                )
            }
        }
    }
    return running_apps
}

/// returns a list of blocking_applications for pkginfo item
func blockingApplicationsForItem(_ pkginfo: PlistDict) -> [String] {
    if let blockingApplications = pkginfo["blocking_applications"] as? [String] {
        return blockingApplications
    } else {
        // if no blocking_applications specified, get appnames
        // from 'installs' list if it exists
        if let installs = pkginfo["installs"] as? [PlistDict] {
            let apps = installs.filter {
                $0["type"] as? String ?? "" == "application"
            }
            let appNames = apps.map {
                ($0["path"] as? NSString)?.lastPathComponent ?? ""
            }.filter { !$0.isEmpty }
            return appNames
        }
    }
    return []
}

/// Returns a list of blocking_applications for the pkginfo item that are running
func blockingApplicationsRunning(_ pkginfo: PlistDict) -> [BlockingAppInfo] {
    let appNames = blockingApplicationsForItem(pkginfo)
    return getRunningBlockingApps(appNames)
}
