//
//  dateutils.swift
//  munki
//
//  Created by Greg Neagle on 1/6/25.
//
//  Copyright 2024-2025 Greg Neagle.
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
