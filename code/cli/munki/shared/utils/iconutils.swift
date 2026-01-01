//
//  iconutils.swift
//  munki
//
//  Created by Greg Neagle on 7/11/24.
//
//  Copyright 2024-2026 The Munki Project.
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
import ImageIO

/// Converts an icns file to a png file.
/// desiredHeight should be one of the "native" icns sizes, like
/// 512, 256, 128, 48, 32, or 16
/// desiredDPI should be either 72 or 144
/// Returns true if successful, false otherwise
func convertIconToPNG(iconPath: String,
                      destinationPath: String,
                      desiredHeight: Int = 512,
                      desiredDPI: Int = 72) -> Bool
{
    typealias CandidateType = (height: Int, dpi: Int, index: Int)

    let iconURL = URL(fileURLWithPath: iconPath) as CFURL
    let pngURL = URL(fileURLWithPath: destinationPath) as CFURL
    guard let imageSource = CGImageSourceCreateWithURL(iconURL, nil) else { return false }
    let imageCount = CGImageSourceGetCount(imageSource)
    if imageCount == 0 {
        return false
    }
    var selectedIndex = -1
    var candidates = [CandidateType]()
    for index in 0 ..< imageCount {
        guard let properties = CGImageSourceCopyPropertiesAtIndex(imageSource, index, nil) as? PlistDict else {
            return false
        }
        let dpi = properties[kCGImagePropertyDPIHeight as String] as? Int ?? 0
        let height = properties[kCGImagePropertyPixelHeight as String] as? Int ?? 0
        if height == desiredHeight, dpi == desiredDPI {
            // we found one with our desired height and dpi
            selectedIndex = index
            break
        }
        candidates.append((height: height, dpi: dpi, index: index))
    }
    if selectedIndex == -1 {
        // didn't find an exact match, so look through the candidates and pick the best match
        for candidate in candidates {
            // is there a candidate with the desiredHeight, but wrong dpi? Use that
            if candidate.height == desiredHeight {
                selectedIndex = candidate.index
                break
            }
        }
    }
    if selectedIndex == -1 {
        // OK, now look for one with a height bigger than desired, but right dpi
        candidates.sort { $0 < $1 } // sort ascending, lowest height images first
        for candidate in candidates {
            // select the first candidate bigger than the desiredHeight with matching dpi
            if candidate.height > desiredHeight, candidate.dpi == desiredDPI {
                selectedIndex = candidate.index
                break
            }
        }
    }
    if selectedIndex == -1 {
        // still didn't find what we looked for, try again, and ignore DPI
        for candidate in candidates {
            if candidate.height > desiredHeight {
                selectedIndex = candidate.index
                break
            }
        }
    }
    if selectedIndex == -1 {
        // just grab the largest image
        candidates.sort { $0 > $1 } // sort descending, highest height images first
        selectedIndex = candidates[0].index
    }

    if let image = CGImageSourceCreateImageAtIndex(imageSource, selectedIndex, nil),
       let imageDestination = CGImageDestinationCreateWithURL(
           pngURL, "public.png" as CFString, 1, nil
       )
    {
        CGImageDestinationAddImage(imageDestination, image, nil)
        return CGImageDestinationFinalize(imageDestination)
    }

    return false
}

/// Finds the icon file for app_path. Returns a path or nil
func findIconForApp(_ appPath: String) -> String? {
    guard pathIsDirectory(appPath) else { return nil }
    let infoPlistPath = (appPath as NSString).appendingPathComponent("Contents/Info.plist")
    guard let info = try? readPlist(fromFile: infoPlistPath) as? PlistDict else { return nil }
    let appName = (appPath as NSString).lastPathComponent
    var iconFilename = info["CFBundleIconName"] as? String ?? info["CFBundleIconFile"] as? String ?? appName
    if (iconFilename as NSString).pathExtension.isEmpty {
        iconFilename += ".icns"
    }
    let iconPath = (appPath as NSString).appendingPathComponent(
        "Contents/Resources/\(iconFilename)")
    if pathIsRegularFile(iconPath) || pathIsSymlink(iconPath) {
        return iconPath
    }
    return nil
}

/// Extracts application Info.plist and .icns files into target_dir from a package archive file.
/// Returns the result code of the pax extract operation.
func extractAppBitsFromPkgArchive(_ archivePath: String, exportDir: String) -> Int {
    if !pathIsRegularFile(archivePath) {
        return -999
    }
    if !pathIsDirectory(exportDir) {
        return -998
    }
    let filemanager = FileManager.default
    let originalWorkingDir = filemanager.currentDirectoryPath
    filemanager.changeCurrentDirectoryPath(exportDir)
    var result = runCLI(
        "/bin/pax",
        arguments: ["-rzf",
                    archivePath,
                    "*.app/Contents/Info.plist",
                    "*.app/Contents/Resources/*.icns"]
    )
    if result.exitcode != 0, pathExists("/usr/bin/aa") {
        // pax failed. Maybe this Payload is an Apple Archive
        result = runCLI(
            "/usr/bin/aa",
            arguments: ["extract",
                        "-i", archivePath,
                        "-include-regex", "\\.app/Contents/Info.plist",
                        "-include-regex", "\\.app/Contents/Resources/.*\\.icns",
                        "-d", "."]
        )
    }
    filemanager.changeCurrentDirectoryPath(originalWorkingDir)
    return result.exitcode
}

/// Extracts application icons from a flat package.
/// Returns a list of paths to icns files.
func extractAppIconsFromFlatPkg(_ pkgPath: String) -> [String] {
    let result = runCLI("/usr/sbin/pkgutil", arguments: ["--bom", pkgPath])
    if result.exitcode != 0 {
        printStderr("Could not get bom files from \(pkgPath): \(result.error)")
        return [String]()
    }
    let bomFilePaths = result.output.components(separatedBy: .newlines)
    var pkgDict = [String: [String]]()
    for bomFile in bomFilePaths {
        // bomfile path is of the form:
        // /tmp/Foo.pkg.boms.2Rxa1z/FooComponent.pkg/Bom
        let tempPath = (bomFile as NSString).deletingLastPathComponent
        var pkgName = (tempPath as NSString).lastPathComponent
        if !pkgName.hasSuffix(".pkg") {
            // pkgPath is not a distribution-style pkg; we're working with
            // a component package
            pkgName = ""
        }
        let result = runCLI("/usr/bin/lsbom", arguments: ["-s", bomFile])
        if result.exitcode != 0 {
            printStderr("Could not get contents of bom: \(bomFile): \(result.error)")
            continue
        }
        let outputLines = result.output.components(separatedBy: .newlines)
        let infoPlistLines = outputLines.filter {
            $0.hasSuffix(".app/Contents/Info.plist")
        }.map {
            ($0 as NSString).standardizingPath
        }
        if !infoPlistLines.isEmpty {
            pkgDict[pkgName] = infoPlistLines
        }
    }
    if pkgDict.isEmpty {
        return [String]()
    }
    var iconPaths = [String]()
    if let pkgTmp = TempDir.shared.makeTempDir(),
       let exportTmp = TempDir.shared.makeTempDir()
    {
        defer {
            try? FileManager.default.removeItem(atPath: pkgTmp)
        }
        let expandedPkgPath = (pkgTmp as NSString).appendingPathComponent("pkg")
        let expandResult = runCLI(
            "/usr/sbin/pkgutil", arguments: ["--expand", pkgPath, expandedPkgPath]
        )
        if expandResult.exitcode == 0 {
            for pkg in pkgDict.keys {
                let archivePath = (expandedPkgPath as NSString).appendingPathComponent("\(pkg)/Payload")
                let err = extractAppBitsFromPkgArchive(archivePath, exportDir: exportTmp)
                if err == 0 {
                    if let infoPaths = pkgDict[pkg] {
                        for infoPath in infoPaths {
                            let fullPath = (exportTmp as NSString).appendingPathComponent(infoPath)
                            let appPath = ((fullPath as NSString).deletingLastPathComponent as NSString).deletingLastPathComponent
                            if let iconPath = findIconForApp(appPath) {
                                iconPaths.append(iconPath)
                            }
                        }
                    }
                } else {
                    printStderr("pax could not read files from \(archivePath)")
                    return iconPaths
                }
            }
        } else {
            printStderr("Could not expand \(pkgPath): \(expandResult.error)")
        }
    }
    return iconPaths
}

/// Returns a list of paths to application Info.plists
func getAppInfoPathsFromBOM(_ bomFile: String) -> [String] {
    var paths = [String]()
    if pathIsRegularFile(bomFile) {
        let result = runCLI("/usr/bin/lsbom", arguments: ["-s", bomFile])
        if result.exitcode == 0 {
            let lines = result.output.components(separatedBy: .newlines)
            paths = lines.filter {
                $0.hasSuffix(".app/Contents/Info.plist")
            }
        }
    }
    return paths
}

/// Returns a dict with pkg paths as keys and filename lists as values
func findInfoPlistPathsInBundlePkg(_ pkgPath: String) -> [String: [String]] {
    var pkgDict = [String: [String]]()
    let bomFile = (pkgPath as NSString).appendingPathComponent("Contents/Archive.bom")
    if pathIsRegularFile(bomFile) {
        // single (simple) package
        let infoPaths = getAppInfoPathsFromBOM(bomFile)
        if !infoPaths.isEmpty {
            pkgDict[pkgPath] = infoPaths
        }
    } else {
        // maybe meta or dist package; look for component pkgs
        var pkgs = [String]()
        let pkgContentsDir = (pkgPath as NSString).appendingPathComponent("Contents")
        if pathIsDirectory(pkgContentsDir) {
            let filemanager = FileManager.default
            let dirEnum = filemanager.enumerator(atPath: pkgContentsDir)
            while let file = dirEnum?.nextObject() as? String {
                if file.hasSuffix(".pkg"), file.hasSuffix(".mpkg") {
                    let fullPath = (pkgContentsDir as NSString).appendingPathComponent(file)
                    pkgs.append(fullPath)
                }
            }
        }
        for pkg in pkgs {
            // Inception time
            let anotherPkgDict = findInfoPlistPathsInBundlePkg(pkg)
            pkgDict.merge(anotherPkgDict) { _, second in second }
        }
    }
    return pkgDict
}

/// Returns a list of paths for application icons found inside the bundle pkg at pkg_path
func extractAppIconsFromBundlePkg(_ pkgPath: String) -> [String] {
    var iconPaths = [String]()
    let pkgDict = findInfoPlistPathsInBundlePkg(pkgPath)
    if let exportTmp = TempDir.shared.makeTempDir() {
        for pkg in pkgDict.keys {
            let archivePath = (pkg as NSString).appendingPathComponent("Contents/Archive.pax.gz")
            if pathIsRegularFile(archivePath) {
                let err = extractAppBitsFromPkgArchive(archivePath, exportDir: exportTmp)
                if err == 0,
                   let infoPaths = pkgDict[pkg]
                {
                    for infoPath in infoPaths {
                        let fullPath = ((exportTmp as NSString).appendingPathComponent(infoPath) as NSString).standardizingPath
                        let appPath = ((fullPath as NSString).deletingLastPathComponent as NSString).deletingLastPathComponent
                        if let iconPath = findIconForApp(appPath) {
                            iconPaths.append(iconPath)
                        }
                    }
                }
            }
        }
    }
    return iconPaths
}
