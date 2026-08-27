//
//  dateutils.swift
//  munki
//
//  Created by Greg Neagle on 1/6/25.
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

/// Input: NSDate object
/// Output: NSDate object with same date and time as the UTC.
/// In Los Angeles (PDT), '2011-06-20T12:00:00Z' becomes
/// '2011-06-20 12:00:00 -0700'.
/// In New York (EDT), it becomes '2011-06-20 12:00:00 -0400'.
/// This allows a pkginfo item to reference a time in UTC that
/// gets translated to the same relative local time.
/// A force_install_after_date for '2011-06-20T12:00:00Z' will happen
/// after 2011-06-20 12:00:00 local time.
func subtractTZOffsetFromDate(_ date: Date) -> Date {
    // find our time zone offset in seconds
    let timezone = NSTimeZone.default
    let secondsOffset = Double(timezone.secondsFromGMT(for: date))
    // return new Date minus the offset
    return Date(timeInterval: -secondsOffset, since: date)
}

/// Input: NSDate object
/// Output: NSDate object with timezone difference added
/// to the date. This allows conditional_item conditions to
/// be written like so:
///
/// <key>condition</key>
/// <string>date > CAST("2012-12-17T16:00:00Z", "NSDate")</string>
///
/// with the intent being that the comparison is against local time.
func addTZOffsetToDate(_ date: Date) -> Date {
    // find our time zone offset in seconds
    let timezone = NSTimeZone.default
    let secondsOffset = Double(timezone.secondsFromGMT(for: date))
    // return new Date plus the offset
    return Date(timeInterval: secondsOffset, since: date)
}

/// Returns an ISO 8601-formatted string in UTC for given date
func ISO8601String(for date: Date) -> String {
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions = [.withInternetDateTime]
    return formatter.string(from: date)
}

/// Retutns an RFC 3339-formatted string in the current time zone for given date
func RFC3339String(for date: Date) -> String {
    // RFC 3339 date format like `2024-07-01 17:30:32-08:00`
    let formatter = ISO8601DateFormatter()
    formatter.timeZone = TimeZone.current
    formatter.formatOptions = [.withInternetDateTime, .withSpaceBetweenDateAndTime]
    return formatter.string(from: date)
}
