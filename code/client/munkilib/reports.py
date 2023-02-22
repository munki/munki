# encoding: utf-8
#
# Copyright 2009-2023 Greg Neagle.
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
reports.py

Created by Greg Neagle on 2016-12-14.


Reporting functions
"""
from __future__ import absolute_import, print_function

import os
import subprocess
import sys
import time

# PyLint cannot properly find names inside Cocoa libraries, so issues bogus
# No name 'Foo' in module 'Bar' warnings. Disable them.
# pylint: disable=E0611
from Foundation import NSDate
# pylint: enable=E0611

from . import munkilog
from . import prefs
from . import FoundationPlist


def format_time(timestamp=None):
    """Return timestamp as an ISO 8601 formatted string, in the current
    timezone.
    If timestamp isn't given the current time is used."""
    if timestamp is None:
        return str(NSDate.new())
    return str(NSDate.dateWithTimeIntervalSince1970_(timestamp))


def printreportitem(label, value, indent=0):
    """Prints a report item in an 'attractive' way"""
    indentspace = '    '
    if isinstance(value, type(None)):
        print(indentspace*indent, '%s: !NONE!' % label)
    elif isinstance(value, list) or type(value).__name__ == 'NSCFArray':
        if label:
            print(indentspace*indent, '%s:' % label)
        index = 0
        for item in value:
            index += 1
            printreportitem(index, item, indent+1)
    elif isinstance(value, dict) or type(value).__name__ == 'NSCFDictionary':
        if label:
            print(indentspace*indent, '%s:' % label)
        for subkey in value.keys():
            printreportitem(subkey, value[subkey], indent+1)
    else:
        print(indentspace*indent, '%s: %s' % (label, value))


def printreport(reportdict):
    """Prints the report dictionary in a pretty(?) way"""
    for key in reportdict.keys():
        printreportitem(key, reportdict[key])


def savereport():
    """Save our report"""
    FoundationPlist.writePlist(
        report, os.path.join(
            prefs.pref('ManagedInstallDir'), 'ManagedInstallReport.plist'))


def readreport():
    """Read report data from file"""
    global report
    reportfile = os.path.join(
        prefs.pref('ManagedInstallDir'), 'ManagedInstallReport.plist')
    try:
        report = FoundationPlist.readPlist(reportfile)
    except FoundationPlist.NSPropertyListSerializationException:
        report = {}


def _warn(msg):
    """We can't use display module functions here because that would require
    circular imports. So a partial reimplementation."""
    warning = 'WARNING: %s' % msg
    print(warning.encode('UTF-8'), file=sys.stderr)
    munkilog.log(warning)
    # append this warning to our warnings log
    munkilog.log(warning, 'warnings.log')


def archive_report():
    """Archive a report"""
    reportfile = os.path.join(
        prefs.pref('ManagedInstallDir'), 'ManagedInstallReport.plist')
    if os.path.exists(reportfile):
        modtime = os.stat(reportfile).st_mtime
        formatstr = '%Y-%m-%d-%H%M%S'
        archivename = ('ManagedInstallReport-%s.plist'
                       % time.strftime(formatstr, time.localtime(modtime)))
        archivepath = os.path.join(prefs.pref('ManagedInstallDir'), 'Archives')
        if not os.path.exists(archivepath):
            try:
                os.mkdir(archivepath)
            except (OSError, IOError):
                _warn('Could not create report archive path.')
        try:
            os.rename(reportfile, os.path.join(archivepath, archivename))
        except (OSError, IOError):
            _warn('Could not archive report.')
        # now keep number of archived reports to 100 or fewer
        proc = subprocess.Popen(['/bin/ls', '-t1', archivepath],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        output = proc.communicate()[0].decode('UTF-8')
        if output:
            archiveitems = [item
                            for item in str(output).splitlines()
                            if item.startswith('ManagedInstallReport-')]
            if len(archiveitems) > 100:
                for item in archiveitems[100:]:
                    itempath = os.path.join(archivepath, item)
                    if os.path.isfile(itempath):
                        try:
                            os.unlink(itempath)
                        except (OSError, IOError):
                            _warn('Could not remove archive item %s' % item)


# module globals
# pylint: disable=invalid-name
report = {}
# pylint: enable=invalid-name


if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
