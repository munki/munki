# encoding: utf-8
#
# Copyright 2024-2025 Greg Neagle.
#
# Licensed under the Apache License, Version 2.0 (the 'License');
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an 'AS IS' BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
dateutils.py

Created by Greg Neagle on 2024-04-12.

Shared date/time functions
"""
from __future__ import absolute_import, print_function

# PyLint cannot properly find names inside Cocoa libraries, so issues bogus
# No name 'Foo' in module 'Bar' warnings. Disable them.
# pylint: disable=E0401, E0611
from Foundation import NSDate, NSDateFormatter, NSISO8601DateFormatter
from Foundation import NSTimeZone, NSLocale
# pylint: enable=E0401, E0611

# Disable PyLint complaining about 'invalid' camelCase names
# pylint: disable=C0103


def munkiDateFormatter(fmt=None):
    """Works with date strings formatted like "1984-01-24 12:34:00 +0000"
    Which historically was the result of str(<some NSDate>).
    Optionally can use a custom format string. See:
    http://www.unicode.org/reports/tr35/tr35-31/tr35-dates.html#Date_Format_Patterns
    for supported format string options."""
    dateFormatter = NSDateFormatter.alloc().init()
    dateFormatter.setLocale_(
        NSLocale.localeWithLocaleIdentifier_("en_US_POSIX"))
    if fmt is None:
        # default format string
        fmt = "yyyy-MM-dd HH:mm:ss Z"
    dateFormatter.setDateFormat_(fmt)
    dateFormatter.setTimeZone_(NSTimeZone.timeZoneForSecondsFromGMT_(0))
    return dateFormatter


def stringFromDate(nsdate, fmt=None):
    """Return a string representing an NSDate. Format of the string defaults to
    '1984-01-24 12:34:00 +0000'-style strings if format is None.
    Specify a format of 'ISO8601' for '1984-01-24T12:34:00Z'-style strings
    or a custom format string."""
    if fmt == "ISO8601":
        dateFormatter = NSISO8601DateFormatter.alloc().init()
    else:
        dateFormatter = munkiDateFormatter(fmt=fmt)
    return dateFormatter.stringFromDate_(nsdate)


def dateFromString(dateString):
    """Attempts to parse a string and return an NSDate. Tries three formats:
       1) "1984-01-24 12:34:00 +0000"
       2) "1984-01-24T12:34:00Z"
       3) "1984-01-24 12:34:00"""
    # Try classic str(<NSDate>) format
    date = munkiDateFormatter().dateFromString_(dateString)
    if not date:
        # try ISO8601 format
        date = NSISO8601DateFormatter.alloc().init().dateFromString_(dateString)
    if not date:
        # one last fallback format to try
        date = munkiDateFormatter(
            fmt="yyyy-MM-dd HH:mm:ss").dateFromString_(dateString)
    return date


def format_timestamp(timestamp=None, fmt=None):
    """Return timestamp as formatted string, in the UTC/GMT timezone.
       If timestamp isn't given the current time is used."""
    if timestamp is None:
        return stringFromDate(NSDate.new(), fmt=fmt)
    return stringFromDate(
        NSDate.dateWithTimeIntervalSince1970_(timestamp), fmt=fmt)


if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
