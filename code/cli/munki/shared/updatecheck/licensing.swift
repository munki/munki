//
//  licensing.swift
//  munki
//
//  Created by Greg Neagle on 8/20/24.
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

/// Records # of available seats for each optional install
/// returns an updated list of optional_installs with license info
func updateAvailableLicenseSeats(_ optionalInstalls: [PlistDict]) -> [PlistDict] {
    guard let licenseInfoURL = pref("LicenseInfoURL") as? String else {
        // nothing to do
        return optionalInstalls
    }

    let display = DisplayAndLog.main
    var mutableOptionalInstalls = optionalInstalls

    var licenseInfo = PlistDict()
    let itemsToCheck: [String]
    itemsToCheck = mutableOptionalInstalls.filter {
        ($0["licensed_seat_info_available"] as? Bool ?? false) &&
            !($0["installed"] as? Bool ?? false)
    }.map {
        $0["name"] as? String ?? ""
    }.filter {
        !$0.isEmpty
    }
    let queryItems = itemsToCheck.map {
        "name=\(($0 as NSString).addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? "<invalidname>")"
    }

    // complicated logic here to 'batch' process our GET requests but
    // keep them under 256 characters each
    var startIndex = 0
    // Use ampersand when the license_info_url contains a ?
    let qChar = if licenseInfoURL.contains("?") {
        "&"
    } else {
        "?"
    }
    while startIndex < itemsToCheck.count {
        var endIndex = itemsToCheck.count
        var url = ""
        while true {
            url = licenseInfoURL + qChar + queryItems[startIndex ..< endIndex].joined(separator: "&")
            if url.count < 256 {
                break
            }
            // too long; drop an item and see if we're under 256 characters
            endIndex -= 1
        }
        display.debug1("Fetching licensed seat data from \(url)")
        do {
            if let licenseData = try getDataFromURL(url) {
                display.debug1("Got: \(String(data: licenseData, encoding: .utf8) ?? "")")
                if let licenseDict = try readPlist(fromData: licenseData) as? PlistDict {
                    licenseInfo.merge(licenseDict) { _, second in second }
                }
            }
        } catch {
            display.error("Error getting license data: \(error.localizedDescription)")
        }
        // next loop, start where we ended
        startIndex = endIndex
    }

    // use licenseInfo to update remaining seats
    for (index, item) in mutableOptionalInstalls.enumerated() {
        guard let itemName = item["name"] as? String else {
            continue
        }
        if itemsToCheck.contains(itemName) {
            display.debug2("Looking for license info for \(itemName)")
            var seatsAvailable = false
            let seatInfo = licenseInfo[itemName] as? Int ?? 0
            display.debug1("\(seatInfo) seats available for \(itemName)")
            if seatInfo > 0 {
                seatsAvailable = true
            }
            mutableOptionalInstalls[index]["licensed_seats_available"] = seatsAvailable
        }
    }
    return mutableOptionalInstalls
}
