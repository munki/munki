//
//  pkgutils.swift
//  munki
//
//  Created by Greg Neagle on 7/2/24.
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

import Foundation

/// Queries a package and returns restart info
func getPkgRestartInfo(_ pkgpath: String) throws -> PlistDict {
    var installerinfo = PlistDict()
    let results = runCLI(
        "/usr/sbin/installer",
        arguments: ["-query", "RestartAction",
                    "-pkg", pkgpath,
                    "-plist"]
    )
    if results.exitcode != 0 {
        throw MunkiError("installer -query for \(pkgpath) failed: \(results.error)")
    }
    let (pliststr, _) = parseFirstPlist(fromString: results.output)
    if !pliststr.isEmpty {
        if let plist = try? readPlist(fromString: pliststr) as? PlistDict {
            if let restartAction = plist["RestartAction"] as? String {
                if restartAction != "None" {
                    installerinfo["RestartAction"] = restartAction
                }
            }
        }
    }
    return installerinfo
}

/// Gets a version string from the plist.
///
/// If a key is explicitly specified, the string value of that key is returned
/// without modification, or an empty string if the key does not exist or the value
/// is not a string.
///
/// If key is not specified:
/// if there"s a valid CFBundleShortVersionString, returns that.
/// else if there"s a CFBundleVersion, returns that
/// else returns an empty string.
func getVersionString(plist: PlistDict, key: String = "") -> String {
    if !key.isEmpty {
        return plist[key] as? String ?? ""
    }
    for aKey in ["CFBundleShortVersionString", "CFBundleVersion"] {
        if let version = plist[aKey] as? String {
            return version
        }
    }
    return ""
}

// MARK: bundle functions

/// Returns Info.plist data if available for bundle at bundlepath/
func getBundleInfo(_ bundlepath: String) -> PlistDict? {
    var infopath = (bundlepath as NSString).appendingPathComponent("Contents/Info.plist")
    let filemanager = FileManager.default
    if !filemanager.fileExists(atPath: infopath) {
        infopath = (bundlepath as NSString).appendingPathComponent("Resources/Info.plist")
    }
    if filemanager.fileExists(atPath: infopath) {
        return try? readPlist(fromFile: infopath) as? PlistDict
    }
    return nil
}

/// Returns path to the actual executable in an app bundle or empty string
func getAppBundleExecutable(_ bundlepath: String) -> String {
    var executableName = (bundlepath as NSString).lastPathComponent
    executableName = (executableName as NSString).deletingPathExtension
    if let plist = getBundleInfo(bundlepath) {
        if let cfBundleExecutable = plist["CFBundleExecutable"] as? String {
            executableName = cfBundleExecutable
        } else if let cfBundleName = plist["CFBundleName"] as? String {
            executableName = cfBundleName
        }
    }
    var executablePath = (bundlepath as NSString).appendingPathComponent("Contents/MacOS")
    executablePath = (executablePath as NSString).appendingPathComponent(executableName)
    if FileManager.default.fileExists(atPath: executablePath) {
        return executablePath
    }
    return ""
}

/// Parses an ancient data format in old bundle-style packages and returns a PlistDict
func parseInfoFile(_ infofilepath: String) -> PlistDict {
    // text might be in one of two encodings

    func parseInfoFileText(_ text: String) -> [String: String] {
        var info = [String: String]()
        for line in text.components(separatedBy: .newlines) {
            let parts = line.components(separatedBy: .whitespaces)
            if parts.count > 1 {
                let key = parts[0]
                let value = parts[1...].joined(separator: " ")
                info[key] = value
            }
        }
        return info
    }

    if let filedata = NSData(contentsOfFile: infofilepath) {
        if let filetext = String(data: filedata as Data, encoding: .macOSRoman) {
            return parseInfoFileText(filetext)
        } else if let filetext = String(data: filedata as Data, encoding: .utf8) {
            return parseInfoFileText(filetext)
        }
    }
    return PlistDict()
}

/// Returns a path to an old-style .info file inside the bundle if present
func getOldStyleInfoFile(_ bundlepath: String) -> String? {
    let infopath = (bundlepath as NSString).appendingPathComponent("Contents/Resources/English.lproj")
    if pathIsDirectory(infopath) {
        let filemanager = FileManager.default
        if let dirlist = try? filemanager.contentsOfDirectory(atPath: infopath) {
            for item in dirlist {
                if item.hasSuffix(".info") {
                    return (infopath as NSString).appendingPathComponent(item)
                }
            }
        }
    }
    return nil
}

/// Returns version number from a bundle.
/// Some extra code to deal with very old-style bundle packages
///
/// Specify key to use a specific key in the Info.plist for the version string.
func getBundleVersion(_ bundlepath: String, key: String = "") -> String {
    if let plist = getBundleInfo(bundlepath) {
        let version = getVersionString(plist: plist, key: key)
        if !version.isEmpty {
            return version
        }
    }
    // no version number in Info.plist. Maybe old-style package?
    if let infofile = getOldStyleInfoFile(bundlepath) {
        let info = parseInfoFile(infofile)
        if let version = info["Version"] as? String {
            return version
        }
    }
    return ""
}

/// Gets bom listing from pkgpath, which should be a path to a bundle-style package
/// Returns a list of strings
func getBomList(_ pkgpath: String) -> [String] {
    let contentsPath = (pkgpath as NSString).appendingPathComponent("Contents")
    if pathIsDirectory(contentsPath) {
        let filemanager = FileManager.default
        if let dirlist = try? filemanager.contentsOfDirectory(atPath: contentsPath) {
            for item in dirlist {
                if item.hasSuffix(".bom") {
                    let bompath = (contentsPath as NSString).appendingPathComponent(item)
                    let results = runCLI(
                        "/usr/bin/lsbom", arguments: ["-s", bompath]
                    )
                    if results.exitcode == 0 {
                        return results.output.components(separatedBy: .newlines)
                    }
                    break
                }
            }
        }
    }
    return [String]()
}

/// Returns receipt info for a single bundle-style package
func getSinglePkgReceipt(_ pkgpath: String) -> PlistDict {
    var receipt = PlistDict()
    let pkgname = (pkgpath as NSString).lastPathComponent
    if let plist = getBundleInfo(pkgpath) {
        receipt["filename"] = pkgname
        if let identifier = plist["CFBundleIdentifier"] as? String {
            receipt["packageid"] = identifier
        } else if let identifier = plist["Bundle identifier"] as? String {
            receipt["packageid"] = identifier
        } else {
            receipt["packageid"] = pkgname
        }
        if let name = plist["CFBundleName"] as? String {
            receipt["name"] = name
        }
        if let installedSize = plist["IFPkgFlagInstalledSize"] as? Int {
            receipt["installed_size"] = installedSize
        }
        receipt["version"] = getBundleVersion(pkgpath)
    } else {
        // look for really old-style .info file
        if let infofile = getOldStyleInfoFile(pkgpath) {
            let info = parseInfoFile(infofile)
            receipt["version"] = info["Version"] as? String ?? "0.0"
            receipt["name"] = info["Title"] as? String ?? pkgname
            receipt["packageid"] = pkgname
            receipt["filename"] = pkgname
        }
    }
    return receipt
}

/// Get metadata from a bundle-style package
func getBundlePackageInfo(_ pkgpath: String) throws -> PlistDict {
    var receiptarray = [PlistDict]()
    if pkgpath.hasSuffix(".pkg") {
        // try to get info as if this is a single component pkg
        let receipt = getSinglePkgReceipt(pkgpath)
        if !receipt.isEmpty {
            receiptarray.append(receipt)
            return ["receipts": receiptarray]
        }
    }
    // might be a mpkg
    let contentsPath = (pkgpath as NSString).appendingPathComponent("Contents")
    let filemanager = FileManager.default
    if pathIsDirectory(contentsPath) {
        if let dirlist = try? filemanager.contentsOfDirectory(atPath: contentsPath) {
            for item in dirlist {
                if item.hasSuffix(".dist") {
                    let distfilepath = (contentsPath as NSString).appendingPathComponent(item)
                    let receiptarray = receiptsFromDistFile(distfilepath)
                    return ["receipts": receiptarray]
                }
            }
        }
        // no .dist file found; let"s look for subpackages
        var searchDirs = [String]()
        if let info = getBundleInfo(pkgpath) {
            if let componentDir = info["IFPkgFlagComponentDirectory"] as? String {
                searchDirs.append(componentDir)
            }
        }
        if searchDirs.isEmpty {
            searchDirs = ["", "Contents", "Contents/Installers",
                          "Contents/Packages", "Contents/Resources",
                          "Contents/Resources/Packages"]
        }
        for dir in searchDirs {
            let searchDir = (pkgpath as NSString).appendingPathComponent(dir)
            guard pathIsDirectory(searchDir) else { continue }
            guard let dirlist = try? filemanager.contentsOfDirectory(atPath: searchDir) else { continue }
            for item in dirlist {
                let itempath = (searchDir as NSString).appendingPathComponent(item)
                guard pathIsDirectory(itempath) else { continue }
                if itempath.hasSuffix(".pkg") {
                    let receipt = getSinglePkgReceipt(itempath)
                    if !receipt.isEmpty {
                        receiptarray.append(receipt)
                    }
                } else if itempath.hasSuffix(".mpkg") {
                    let info = try getBundlePackageInfo(itempath)
                    if !info.isEmpty {
                        if let receipts = info["receipts"] as? [PlistDict] {
                            receiptarray += receipts
                        }
                    }
                }
            }
        }
    }
    if !receiptarray.isEmpty {
        return ["receipts": receiptarray]
    }
    throw MunkiError("Could not get receipt info from \(pkgpath)")
}

// MARK: XML file functions (mostly for flat packages)

/// Extracts product version from a Distribution file
func getProductVersionFromDist(_ filepath: String) -> String {
    guard let data = NSData(contentsOfFile: filepath) else { return "" }
    guard let doc = try? XMLDocument(data: data as Data, options: []) else { return "" }
    guard let products = try? doc.nodes(forXPath: "//product") else { return "" }
    if products.isEmpty { return "" }
    guard let product = products[0] as? XMLElement else { return "" }
    guard let versionAttr = product.attribute(forName: "version") else { return "" }
    return versionAttr.stringValue ?? ""
}

/// Attempts to get a minimum os version
func getMinOSVersFromDist(_ filepath: String) -> String {
    guard let data = NSData(contentsOfFile: filepath) else { return "" }
    guard let doc = try? XMLDocument(data: data as Data, options: []) else { return "" }
    guard let volumeChecks = try? doc.nodes(forXPath: "//volume-check") else { return "" }
    if volumeChecks.isEmpty { return "" }
    guard let allowedOSVersions = try? volumeChecks[0].nodes(forXPath: "child::allowed-os-versions") else { return "" }
    if allowedOSVersions.isEmpty { return "" }
    guard let osVersions = try? allowedOSVersions[0].nodes(forXPath: "child::os-version") else { return "" }
    var minOSVersionStrings = [String]()
    for osVersion in osVersions {
        guard let element = osVersion as? XMLElement else { continue }
        if let minAttr = element.attribute(forName: "min") {
            if let os = minAttr.stringValue {
                minOSVersionStrings.append(os)
            }
        }
    }
    // if there's more than one, use the highest minimum OS
    let versions = minOSVersionStrings.map { MunkiVersion($0) }
    if let maxVersion = versions.max() {
        return maxVersion.value
    }
    return ""
}

// Parses a PackageInfo file and returns a package receipt
// No official Apple documentation on the format of this file, but
// http://s.sudre.free.fr/Stuff/Ivanhoe/FLAT.html has some
func receiptFromPackageInfoFile(_ filepath: String) -> PlistDict? {
    guard let data = NSData(contentsOfFile: filepath) else { return PlistDict() }
    guard let doc = try? XMLDocument(data: data as Data, options: []) else { return PlistDict() }
    guard let nodes = try? doc.nodes(forXPath: "//pkg-info") else { return PlistDict() }
    for node in nodes {
        guard let element = node as? XMLElement else { continue }
        if let identifierAttr = element.attribute(forName: "identifier"),
           let versionAttr = element.attribute(forName: "version")
        {
            var pkginfo = PlistDict()
            if let identifier = identifierAttr.stringValue {
                pkginfo["packageid"] = identifier
            }
            if let version = versionAttr.stringValue {
                pkginfo["version"] = version
            }
            if let payloads = try? element.nodes(forXPath: "child::payload") {
                if payloads.isEmpty { continue }
                guard let payload = payloads[0] as? XMLElement else { continue }
                if let sizeAttr = payload.attribute(forName: "installKBytes") {
                    if let size = sizeAttr.stringValue {
                        pkginfo["installed_size"] = Int(size)
                    }
                }
                return pkginfo
            }
            // no payloads means payload-free pkg that doesn't actually
            // leave a receipt, so keep looking and eventually fall through
        }
    }
    return nil
}

/// Converts the partial file urls found in Distribution pkg-refs to relative file paths
func partialFileURLToRelativePath(_ partialURL: String) -> String {
    if partialURL.hasPrefix("file:") {
        if let url = URL(string: partialURL) {
            return url.relativePath
        }
    }
    var temp = partialURL
    if temp.hasPrefix("#") {
        temp.removeFirst()
    }
    let fileurl = URL(string: "file:///")
    if let url = URL(string: temp, relativeTo: fileurl) {
        return url.relativePath
    }
    // fallback in case that failed
    return temp.removingPercentEncoding ?? ""
}

/// Parses a package Distribution file and returns a list of package receipts
func receiptsFromDistFile(_ filepath: String) -> [PlistDict] {
    /* https://developer.apple.com/library/archive/documentation/DeveloperTools/Reference/DistributionDefinitionRef/Chapters/Distribution_XML_Ref.html
     */
    var info = [PlistDict]()
    var pkgrefDict = [String: PlistDict]()
    guard let data = NSData(contentsOfFile: filepath) else { return info }
    guard let doc = try? XMLDocument(data: data as Data, options: []) else {
        return info
    }
    guard let nodes = try? doc.nodes(forXPath: "//pkg-ref") else {
        return info
    }
    for node in nodes {
        guard let element = node as? XMLElement else { continue }
        guard let idAttr = element.attribute(forName: "id") else { continue }
        if let pkgid = idAttr.stringValue {
            if !pkgrefDict.keys.contains(pkgid) {
                pkgrefDict[pkgid] = ["packageid": pkgid]
            }
            if let versAttr = element.attribute(forName: "version") {
                if let version = versAttr.stringValue {
                    pkgrefDict[pkgid]?["version"] = version
                }
            }
            if let sizeAttr = element.attribute(forName: "installKBytes") {
                if let size = sizeAttr.stringValue {
                    pkgrefDict[pkgid]?["installed_size"] = Int(size)
                }
            }
            element.normalizeAdjacentTextNodesPreservingCDATA(false)
            var textvalue = ""
            if let textnodes = try? element.nodes(forXPath: "child::text()") {
                for textnode in textnodes {
                    if let str = textnode.stringValue {
                        textvalue += str
                    }
                }
            }
            if !textvalue.isEmpty {
                pkgrefDict[pkgid]?["file"] = partialFileURLToRelativePath(textvalue)
            }
        }
    }
    for pkgref in pkgrefDict.values {
        if pkgref.keys.contains("file"), pkgref.keys.contains("version") {
            var receipt = pkgref
            receipt["file"] = nil
            info.append(receipt)
        }
    }
    return info
}

// MARK: flat pkg methods

/// Returns info for a flat package, including receipts array
func getFlatPackageInfo(_ pkgpath: String) throws -> PlistDict {
    var info = PlistDict()
    var receiptarray = [PlistDict]()
    var productVersion = ""
    var minimumOSVersion = ""
    var errors = [String]()

    // get the absolute path to the pkg because we need to do a chdir later
    let absolutePkgPath = getAbsolutePath(pkgpath)
    // make a tmp dir to expand the flat package into
    guard let pkgTmpDir = TempDir.shared.makeTempDir() else { return info }
    // record our current working dir
    let filemanager = FileManager.default
    let cwd = filemanager.currentDirectoryPath
    // change into our tmpdir so we can use xar to unarchive the flat package
    filemanager.changeCurrentDirectoryPath(pkgTmpDir)
    // Get the TOC of the flat pkg so we can search it later
    let tocResults = runCLI("/usr/bin/xar", arguments: ["-tf", absolutePkgPath])
    if tocResults.exitcode == 0 {
        let tocEntries = tocResults.output.components(separatedBy: .newlines)
        for tocEntry in tocEntries {
            if tocEntry.hasSuffix("PackageInfo") {
                let extractResults = runCLI(
                    "/usr/bin/xar", arguments: ["-xf", absolutePkgPath, tocEntry]
                )
                if extractResults.exitcode == 0 {
                    let packageInfoPath = getAbsolutePath(
                        (pkgTmpDir as NSString).appendingPathComponent(tocEntry))
                    if let receipt = receiptFromPackageInfoFile(packageInfoPath) {
                        receiptarray.append(receipt)
                    }
                } else {
                    errors.append(
                        "An error occurred while extracting \(tocEntry): \(tocResults.error)")
                }
            }
        }
        // now get data from a Distribution file
        for tocEntry in tocEntries {
            if tocEntry.hasSuffix("Distribution") {
                let extractResults = runCLI(
                    "/usr/bin/xar", arguments: ["-xf", absolutePkgPath, tocEntry]
                )
                if extractResults.exitcode == 0 {
                    let distributionPath = getAbsolutePath(
                        (pkgTmpDir as NSString).appendingPathComponent(tocEntry))
                    productVersion = getProductVersionFromDist(distributionPath)
                    minimumOSVersion = getMinOSVersFromDist(distributionPath)
                    if receiptarray.isEmpty {
                        receiptarray = receiptsFromDistFile(distributionPath)
                    }
                    break
                } else {
                    errors.append(
                        "An error occurred while extracting \(tocEntry): \(tocResults.error)")
                }
            }
        }

        if receiptarray.isEmpty {
            errors.append("No receipts found in Distribution or PackageInfo files within the package.")
        }
    } else {
        errors.append("An error occurred while getting table of contents for \(pkgpath): \(tocResults.error)")
    }
    // change back to original working dir
    filemanager.changeCurrentDirectoryPath(cwd)
    // clean up tmpdir
    try? filemanager.removeItem(atPath: pkgTmpDir)
    if !receiptarray.isEmpty {
        info["receipts"] = receiptarray
    }
    if !productVersion.isEmpty {
        info["product_version"] = productVersion
    }
    if !minimumOSVersion.isEmpty {
        info["minimum_os_version"] = minimumOSVersion
    }
    if !info.isEmpty {
        return info
    }
    throw MunkiError("Could not parse info from \(pkgpath):\n\(errors.joined(separator: "\n"))")
}

// MARK: higher-level functions for getting pkg metadata

/// Get some package info (receipts, version, etc) and return as a dict
func getPackageInfo(_ pkgpath: String) throws -> PlistDict {
    guard hasValidPackageExt(pkgpath) else { return PlistDict() }
    if pathIsDirectory(pkgpath) {
        return try getBundlePackageInfo(pkgpath)
    }
    return try getFlatPackageInfo(pkgpath)
}

/// Queries an installer item (.pkg, .mpkg, .dist)
/// and gets metadata. There are a lot of valid Apple package formats
/// and this function may not deal with them all equally well.
///
/// metadata items include:
/// installer_item_size:  size of the installer item (.dmg, .pkg, etc)
/// installed_size: size of items that will be installed
/// RestartAction: will a restart be needed after installation?
/// name
/// version
/// receipts: an array of packageids that may be installed
///           (some may not be installed on some machines)
func getPackageMetaData(_ pkgpath: String) throws -> PlistDict {
    var pkginfo = PlistDict()
    if !hasValidPackageExt(pkgpath) {
        printStderr("\(pkgpath) does not appear to be an Apple installer package.")
        return pkginfo
    }

    pkginfo = try getPackageInfo(pkgpath)
    let restartInfo = try getPkgRestartInfo(pkgpath)
    if let restartAction = restartInfo["RestartAction"] as? String {
        pkginfo["RestartAction"] = restartAction
    }
    var packageVersion = ""
    if let productVersion = pkginfo["product_version"] as? String {
        packageVersion = productVersion
        pkginfo["product_version"] = nil
    }
    if packageVersion.isEmpty {
        // get it from a bundle package
        let bundleVersion = getBundleVersion(pkgpath)
        if !bundleVersion.isEmpty {
            packageVersion = bundleVersion
        }
    }
    if packageVersion.isEmpty {
        // go through receipts and find highest version
        if let receipts = pkginfo["receipts"] as? [PlistDict] {
            let receiptVersions = receipts.map { MunkiVersion($0["version"] as? String ?? "0.0") }
            if let maxVersion = receiptVersions.max() {
                packageVersion = maxVersion.value
            }
        }
    }
    if packageVersion.isEmpty {
        packageVersion = "0.0.0.0.0"
    }

    pkginfo["version"] = packageVersion
    let nameAndExt = (pkgpath as NSString).lastPathComponent
    let nameMaybeWithVersion = (nameAndExt as NSString).deletingPathExtension
    pkginfo["name"] = nameAndVersion(nameMaybeWithVersion).0
    var installedSize = 0
    if let receipts = pkginfo["receipts"] as? [PlistDict] {
        pkginfo["receipts"] = receipts
        for receipt in receipts {
            if let size = receipt["installed_size"] as? Int {
                installedSize += size
            }
        }
    }
    if installedSize > 0 {
        pkginfo["installed_size"] = installedSize
    }

    return pkginfo
}

// MARK: miscellaneous functions

/// Verifies a path ends in '.pkg' or '.mpkg'
func hasValidPackageExt(_ path: String) -> Bool {
    let ext = (path as NSString).pathExtension
    return ["pkg", "mpkg"].contains(ext.lowercased())
}

/// Verifies a path ends in '.dmg' or '.iso'
func hasValidDiskImageExt(_ path: String) -> Bool {
    let ext = (path as NSString).pathExtension
    return ["dmg", "iso"].contains(ext.lowercased())
}

/// Verifies path refers to an item we can (possibly) install
func hasValidInstallerItemExt(_ path: String) -> Bool {
    return hasValidPackageExt(path) || hasValidDiskImageExt(path)
}

/// Queries package for 'ChoiceChangesXML'
func getChoiceChangesXML(_ pkgpath: String) -> [PlistDict]? {
    var choices: [PlistDict]?
    do {
        let results = runCLI(
            "/usr/sbin/installer",
            arguments: ["-showChoiceChangesXML", "-pkg", pkgpath]
        )
        if results.exitcode == 0 {
            let (pliststr, _) = parseFirstPlist(fromString: results.output)
            let plist = try readPlist(fromString: pliststr) as? [PlistDict] ?? [PlistDict]()
            choices = plist.filter {
                ($0["choiceAttribute"] as? String ?? "") == "selected"
            }
        }
    } catch {
        // nothing right now
    }
    return choices
}

/// Splits a string into name and version
func nameAndVersion(_ str: String, onlySplitOnHyphens: Bool = true) -> (String, String) {
    // first look for hyphen or double-hyphen as separator
    for delim in ["--", "-"] {
        if str.contains(delim) {
            var parts = str.components(separatedBy: delim)
            if parts.count > 1 {
                let version = parts.removeLast()
                if "0123456789".contains(version.first ?? " ") {
                    let name = parts.joined(separator: delim)
                    return (name, version)
                }
            }
        }
    }
    if onlySplitOnHyphens {
        return (str, "")
    }

    // more loosey-goosey method (used when importing items)
    // use regex
    // let REGEX = "[0-9]+(\\.[0-9]+)((\\.|a|b|d|v)[0-9]+)+"
    let REGEX = "[0-9]+(\\.[0-9]+)+[\\.|a|b|d|v][0-9]+"
    if let versionRange = str.range(of: REGEX, options: .regularExpression) {
        let version = String(str[versionRange.lowerBound...])
        var name = String(str[..<versionRange.lowerBound])
        if let range = name.range(of: "[ v\\._-]+$", options: .regularExpression) {
            name = name.replacingCharacters(in: range, with: "")
        }
        return (name, version)
    }
    return (str, "")
}

/// Builds a dictionary of installed receipts and their version number
func generateInstalledPackages() async -> [String: String] {
    var installedpkgs = [String: String]()

    let results = await runCliAsync(
        "/usr/sbin/pkgutil", arguments: ["--regexp", "--pkg-info-plist", ".*"]
    )
    if results.exitcode == 0 {
        var out = results.output
        while !out.isEmpty {
            let (pliststr, tempOut) = parseFirstPlist(fromString: out)
            out = tempOut
            if pliststr.isEmpty {
                break
            }
            if let plist = try? readPlist(fromString: pliststr) as? PlistDict {
                if let pkgid = plist["pkgid"] as? String,
                   let version = plist["pkg-version"] as? String
                {
                    installedpkgs[pkgid] = version
                }
            }
        }
    }
    return installedpkgs
}

/// a Singleton class for receipts, since they are expensive to generate
class Receipts {
    static let shared = Receipts()

    var receipts: [String: String]

    private init() {
        receipts = [String: String]()
    }

    func get() async -> [String: String] {
        if receipts.isEmpty {
            receipts = await generateInstalledPackages()
        }
        return receipts
    }
}

/// Uses the singleton Receipts since getting the info is expensive
func getInstalledPackages() async -> [String: String] {
    return await Receipts.shared.get()
}

/// This function doesn't really have anything to do with packages or receipts
/// but is used by makepkginfo, munkiimport, and installer, so it might as
/// well live here for now
func isApplication(_ pathname: String) -> Bool {
    // Returns true if path appears to be a macOS application
    if pathIsDirectory(pathname) {
        if pathname.hasSuffix(".app") {
            return true
        }
        // if path extension is not absent (and it's not .app) we can't be an application
        guard (pathname as NSString).pathExtension == "" else { return false }
        // look to see if we have the structure of an application
        if let plist = getBundleInfo(pathname) {
            if let bundlePkgType = plist["CFBundlePackageType"] as? String {
                if bundlePkgType != "APPL" {
                    return false
                }
            }
            return !getAppBundleExecutable(pathname).isEmpty
        }
    }
    return false
}
