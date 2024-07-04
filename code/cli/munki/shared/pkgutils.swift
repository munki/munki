//
//  pkgutils.swift
//  munki
//
//  Created by Greg Neagle on 7/2/24.
//

import Foundation

func getPkgRestartInfo(_ pkgpath: String) -> PlistDict {
    var installerinfo = PlistDict()
    let results = runCLI(
        "/usr/sbin/installer",
        arguments: ["-query", "RestartAction",
                   "-pkg", pkgpath,
                   "-plist"]
    )
    if results.exitcode != 0 {
        displayError("installer -query for \(pkgpath) failed: \(results.error)")
        return installerinfo
    }
    let (pliststr, _) = parseFirstPlist(fromString: results.output)
    if !pliststr.isEmpty {
        if let plist = try? readPlistFromString(pliststr) as? PlistDict {
            if let restartAction = plist["RestartAction"] as? String {
                if restartAction != "None" {
                    installerinfo["RestartAction"] = restartAction
                }
            }
        }
    }
    return installerinfo
}


func getVersionString(plist: PlistDict, key: String = "") -> String {
    // Gets a version string from the plist.
    //
    // If a key is explicitly specified, the string value of that key is returned
    // without modification, or an empty string if the key does not exist or the value
    // is not a string.
    //
    // If key is not specified:
    // if there"s a valid CFBundleShortVersionString, returns that.
    // else if there"s a CFBundleVersion, returns that
    // else returns an empty string.
    
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

func getBundleInfo(_ bundlepath: String) -> PlistDict? {
    // Returns Info.plist data if available for bundle at bundlepath
    var infopath = (bundlepath as NSString).appendingPathComponent("Contents/Info.plist")
    let filemanager = FileManager.default
    if !filemanager.fileExists(atPath: infopath) {
        infopath = (bundlepath as NSString).appendingPathComponent("Resources/Info.plist")
    }
    if filemanager.fileExists(atPath: infopath) {
        return try? readPlist(infopath) as? PlistDict
    }
    return nil
}


func getAppBundleExecutable(_ bundlepath: String) -> String {
    // Returns path to the actual executable in an app bundle or empty string
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


func parseInfoFileText(_ text: String) -> [String:String] {
    var info = [String:String]()
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


func parseInfoFile(_ infofilepath: String) -> PlistDict {
    // parses an ancient data format in old bundle-style packages
    // and returns a PlistDict
    if let filedata = NSData(contentsOfFile: infofilepath) {
        if let filetext = String(data: filedata as Data, encoding: .macOSRoman) {
            return parseInfoFileText(filetext)
        } else if let filetext = String(data: filedata as Data, encoding: .utf8) {
            return parseInfoFileText(filetext)
        }
    }
    return PlistDict()
}

func getOldStyleInfoFile(_ bundlepath: String) -> String? {
    // returns a path to an old-style .info file inside the
    // bundle if present
    let infopath = (bundlepath as NSString).appendingPathComponent("Contents/Resources/English.lproj")
    if isDir(infopath) {
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


func getBundleVersion(_ bundlepath: String, key: String = "") -> String {
    // Returns version number from a bundle.
    // Some extra code to deal with very old-style bundle packages
    //
    // Specify key to use a specific key in the Info.plist for the version string.
    
    if let plist = getBundleInfo(bundlepath) {
        let versionstring = getVersionString(plist: plist, key: key)
        if !versionstring.isEmpty {
            return versionstring
        }
    }
    // no version number in Info.plist. Maybe old-style package?
    if let infofile = getOldStyleInfoFile(bundlepath) {
        let info = parseInfoFile(infofile)
        if let version = info["Version"] as? String {
            return version
        }
    }
    return "0.0.0.0.0"
}

func getBomList(_ pkgpath: String) -> [String] {
    // Gets bom listing from pkgpath, which should be a path
    // to a bundle-style package
    // Returns a list of strings
    let contentsPath = (pkgpath as NSString).appendingPathComponent("Contents")
    if isDir(contentsPath) {
        let filemanager = FileManager.default
        if let dirlist = try? filemanager.contentsOfDirectory(atPath: contentsPath) {
            for item in dirlist {
                if item.hasSuffix(".bom") {
                    let bompath = (contentsPath as NSString).appendingPathComponent(item)
                    let results = runCLI(
                        "/usr/bin/lsbom", arguments: ["-s", bompath])
                    if results.exitcode == 0 {
                        return results.output.components(separatedBy: "\n")
                    }
                    break
                }
            }
        }
    }
    return [String]()
}

func getSinglePkgReceipt(_ pkgpath: String) -> PlistDict {
    // returns receipt info for a single bundle-style package
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

func getBundlePackageInfo(_ pkgpath: String) -> PlistDict {
    // get metadate from a bundle-style package
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
    if isDir(contentsPath) {
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
            guard isDir(searchDir) else { continue }
            guard let dirlist = try? filemanager.contentsOfDirectory(atPath: searchDir) else { continue }
            for item in dirlist {
                let itempath = (searchDir as NSString).appendingPathComponent(item)
                guard isDir(itempath) else { continue }
                if itempath.hasSuffix(".pkg") {
                    let receipt = getSinglePkgReceipt(itempath)
                    if !receipt.isEmpty {
                        receiptarray.append(receipt)
                    }
                } else if itempath.hasSuffix(".mpkg") {
                    let info = getBundlePackageInfo(itempath)
                    if !info.isEmpty {
                        if let receipts = info["receipts"] as? [PlistDict] {
                            receiptarray += receipts
                        }
                    }
                }
            }
        }
    }
    return ["receipts": receiptarray]
}


// MARK: XML file functions (mostly for flat packages)

func getProductVersionFromDist(_ filepath: String) -> String {
    // Extracts product version from a Distribution file
    guard let data = NSData(contentsOfFile: filepath) else { return "" }
    guard let doc = try? XMLDocument(data: data as Data, options: []) else { return "" }
    guard let products = try? doc.nodes(forXPath: "//product") else { return "" }
    guard let product = products[0] as? XMLElement else { return "" }
    guard let versionAttr = product.attribute(forName: "version") else { return "" }
    return versionAttr.stringValue ?? ""
}


func receiptFromPackageInfoFile(_ filepath: String) -> PlistDict {
    // parses a PackageInfo file and returns a package receipt
    // No official Apple documentation on the format of this file, but
    // http://s.sudre.free.fr/Stuff/Ivanhoe/FLAT.html has some
    guard let data = NSData(contentsOfFile: filepath) else { return PlistDict() }
    guard let doc = try? XMLDocument(data: data as Data, options: []) else { return PlistDict() }
    guard let nodes = try? doc.nodes(forXPath: "//pkg-info") else { return PlistDict() }
    for node in nodes {
        guard let element = node as? XMLElement else { continue }
        if let identifierAttr = element.attribute(forName: "identifier"),
           let versionAttr = element.attribute(forName: "version") {
            var pkginfo = PlistDict()
            if let identifier = identifierAttr.stringValue {
                pkginfo["packageid"] = identifier
            }
            if let version = versionAttr.stringValue {
                pkginfo["version"] = version
            }
            if let payloads = try? element.nodes(forXPath: "child::payload") {
                guard let payload = payloads[0] as? XMLElement else { continue }
                if let sizeAttr = payload.attribute(forName: "installKBytes") {
                    if let size = sizeAttr.stringValue {
                        pkginfo["installed_size"] = Int(size)
                    }
                }
                return pkginfo
            }
        }
    }
    return PlistDict()
}


func partialFileURLToRelativePath(_ partialURL: String) -> String {
    //
    // converts the partial file urls found in Distribution pkg-refs
    // to relative file paths
    // TODO: handle pkg-ref content that starts with "file:"
    
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


func receiptsFromDistFile(_ filepath: String) -> [PlistDict] {
    // parses a package Distribution file and returns a list of
    // package receipts
    /* https://developer.apple.com/library/archive/documentation/DeveloperTools/Reference/DistributionDefinitionRef/Chapters/Distribution_XML_Ref.html
    */
    var info = [PlistDict]()
    var pkgrefDict = [String:PlistDict]()
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
        if pkgref.keys.contains("file") && pkgref.keys.contains("version") {
            var receipt = pkgref
            receipt["file"] = nil
            info.append(receipt)
        }
    }
    return info
}

// MARK: flat pkg methods

func getAbsolutePath(_ path: String) -> String {
    // returns absolute path to item referred to by path
    if (path as NSString).isAbsolutePath {
        return path
    }
    let cwd = FileManager.default.currentDirectoryPath
    let composedPath = (cwd as NSString).appendingPathComponent(path)
    return (composedPath as NSString).standardizingPath
}


func getFlatPackageReceipts(_ pkgpath: String) -> [PlistDict] {
    // returns receipts array for a flat package
    var receiptarray = [PlistDict]()
    // get the absolute path to the pkg because we need to do a chdir later
    let absolutePkgPath = getAbsolutePath(pkgpath)
    // make a tmp dir to expand the flat package into
    guard let pkgTmpDir = TempDir.shared.makeTempDir() else { return receiptarray }
    // record our current working dir
    let filemanager = FileManager.default
    let cwd = filemanager.currentDirectoryPath
    // change into our tmpdir so we can use xar to unarchive the flat package
    filemanager.changeCurrentDirectoryPath(pkgTmpDir)
    // Get the TOC of the flat pkg so we can search it later
    let tocResults = runCLI("/usr/bin/xar", arguments: ["-tf", absolutePkgPath])
    if tocResults.exitcode == 0  {
        for tocEntry in tocResults.output.components(separatedBy: "\n") {
            if tocEntry.hasSuffix("PackageInfo") {
                let extractResults = runCLI(
                    "/usr/bin/xar", arguments: ["-xf", absolutePkgPath, tocEntry])
                if extractResults.exitcode == 0 {
                    let packageInfoPath = getAbsolutePath(
                        (pkgTmpDir as NSString).appendingPathComponent(tocEntry))
                    receiptarray.append( receiptFromPackageInfoFile(packageInfoPath))
                } else {
                    displayWarning(
                        "An error occurred while extracting \(tocEntry): \(tocResults.error)")
                }
            }
        }
        if receiptarray.isEmpty {
            // nothing from PackageInfo files; try Distribution files
            for tocEntry in tocResults.output.components(separatedBy: "\n") {
                if tocEntry.hasSuffix("Distribution") {
                    let extractResults = runCLI(
                        "/usr/bin/xar", arguments: ["-xf", absolutePkgPath, tocEntry])
                    if extractResults.exitcode == 0 {
                        let distributionPath = getAbsolutePath(
                            (pkgTmpDir as NSString).appendingPathComponent(tocEntry))
                            receiptarray += receiptsFromDistFile(distributionPath)
                    } else {
                        displayWarning(
                            "An error occurred while extracting \(tocEntry): \(tocResults.error)")
                    }
                }
            }
        }
    } else {
        displayWarning(
            "An error occurred while geting table of contents for \(pkgpath): \(tocResults.error)")
    }
    // change back to original working dir
    filemanager.changeCurrentDirectoryPath(cwd)
    // clean up tmpdir
    try? filemanager.removeItem(atPath: pkgTmpDir)
    return receiptarray
}
