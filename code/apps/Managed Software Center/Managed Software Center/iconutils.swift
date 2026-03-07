//
//  iconutils.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 6/11/18.
//  Copyright © 2018-2026 The Munki Project. All rights reserved.
//

import Cocoa

struct IconCandidate {
    var index: Int = 0
    var dpi: Int = 0
    var height: Int = 0
}

func convertIconToPNG(_ icon_path: String,
                      destination dest_path: String,
                      preferredSize desired_size: Int) -> Bool {
    // Converts an icns file to a png file, choosing the
    // representation closest to (but >= than if possible) the desired_size.
    // Returns true if successful, false otherwise
    
    if !FileManager.default.fileExists(atPath: icon_path) {
        return false
    }
    let icns_url = NSURL.fileURL(withPath: icon_path)
    let png_url = NSURL.fileURL(withPath: dest_path)
    let desired_dpi = 72
    
    if let image_source = CGImageSourceCreateWithURL(icns_url as CFURL, nil) {
        let number_of_images = CGImageSourceGetCount(image_source)
        if number_of_images == 0 {
            return false
        }
        var candidate = IconCandidate()
        // iterate through the individual icon sizes to find the "best" one
        for index in 0..<number_of_images {
            if let properties = CGImageSourceCopyPropertiesAtIndex(
                image_source, index, nil) {
                let dpi = (properties as NSDictionary)[kCGImagePropertyDPIHeight] as? Int ?? 0
                let height = (properties as NSDictionary)[kCGImagePropertyPixelHeight] as? Int ?? 0
                if ((candidate.height == 0) ||
                    (height < desired_size && height > candidate.height) ||
                    (height >= desired_size && height < candidate.height) ||
                    (height == candidate.height && dpi == desired_dpi)) {
                    candidate.index = index
                    candidate.height = height
                    candidate.dpi = dpi
                }
            }
        }
        if let image = CGImageSourceCreateImageAtIndex(image_source, candidate.index, nil) {
            if let image_dest = CGImageDestinationCreateWithURL(
                png_url as CFURL, "public.png" as CFString, 1, nil) {
                CGImageDestinationAddImage(image_dest, image, nil)
                return CGImageDestinationFinalize(image_dest)
            }
        }
    }
    return false
}

/// Finds the icon file for app_path. Returns a path or nil
func findIconForApp(_ appPath: String) -> String? {
    guard FileManager.default.fileExists(atPath: appPath) else { return nil }
    let infoPlistPath = (appPath as NSString).appendingPathComponent("Contents/Info.plist")
    guard let info = try? readPlist(infoPlistPath) as? PlistDict else { return nil }
    let appName = (appPath as NSString).lastPathComponent
    var iconFilename = info["CFBundleIconFile"] as? String ?? info["CFBundleIconName"] as? String ?? appName
    if (iconFilename as NSString).pathExtension.isEmpty {
        iconFilename += ".icns"
    }
    let iconPath = (appPath as NSString).appendingPathComponent(
        "Contents/Resources/\(iconFilename)")
    if FileManager.default.fileExists(atPath: iconPath) {
        return iconPath
    }
    return nil
}

func convertAppIconToPNG(_ app_path: String,
                         destination dest_path: String,
                         preferredSize desired_size: Int) -> Bool {
    // Converts an application icns file to a png file, choosing the
    // representation closest to (but >= than if possible) the desired_size.
    // Returns true if successful, false otherwise
    guard let icon_path = findIconForApp(app_path) else { return false }
    return convertIconToPNG(icon_path, destination: dest_path, preferredSize: desired_size)
}
