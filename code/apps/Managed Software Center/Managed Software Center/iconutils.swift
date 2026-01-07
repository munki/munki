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

func convertIconToPNG(_ app_name: String,
                      destination dest_path: String,
                      preferredSize desired_size: Int) -> Bool {
    // Converts an application icns file to a png file, choosing the
    // representation closest to (but >= than if possible) the desired_size.
    // Returns true if successful, false otherwise
    
    // find the application
    let app_path = NSString.path(
        withComponents: ["/Applications", "\(app_name).app"])
    if !FileManager.default.fileExists(atPath: app_path) {
        return false
    }
    let info_plist = NSString.path(
        withComponents: [app_path, "Contents/Info.plist"])
    var info = [String: Any]()
    do {
        info = try readPlist(info_plist) as? [String: Any] ?? [String: Any]()
    } catch {
        info = [String: Any]()
    }
    info["CFBundleIconFile"] = "AppIcon.icns"
    let icon_filename = info["CFBundleIconFile"] as? String ?? app_name
    var icon_path = NSString.path(
        withComponents: [app_path, "Contents/Resources", icon_filename])
    if (icon_path as NSString).pathExtension.isEmpty {
        icon_path += ".icns"
    }
    if FileManager.default.fileExists(atPath: icon_path) {
        // we found an icns file, convert to png
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
    }
    return false
}
