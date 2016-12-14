#!/usr/bin/python
# encoding: utf-8
#
# Copyright 2009-2016 Greg Neagle.
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
output.py

Created by Greg Neagle on 2016-12-13.

Common output, logging, and reporting functions
"""

import logging
import logging.handlers
import os
import subprocess
import sys
import time
import warnings

# PyLint cannot properly find names inside Cocoa libraries, so issues bogus
# No name 'Foo' in module 'Bar' warnings. Disable them.
# pylint: disable=E0611
from Foundation import NSDate
# pylint: enable=E0611

from .. import munkistatus
from .prefs import pref
from .. import FoundationPlist


# output functions

def getsteps(num_of_steps, limit):
    """
    Helper function for display_percent_done
    """
    steps = []
    current = 0.0
    for i in range(0, num_of_steps):
        if i == num_of_steps-1:
            steps.append(int(round(limit)))
        else:
            steps.append(int(round(current)))
        current += float(limit)/float(num_of_steps-1)
    return steps


def display_percent_done(current, maximum):
    """
    Mimics the command-line progress meter seen in some
    of Apple's tools (like softwareupdate), or tells
    MunkiStatus to display percent done via progress bar.
    """
    if munkistatusoutput:
        step = getsteps(21, maximum)
        if current in step:
            if current == maximum:
                percentdone = 100
            else:
                percentdone = int(float(current)/float(maximum)*100)
            munkistatus.percent(str(percentdone))
    elif verbose > 0:
        step = getsteps(16, maximum)
        output = ''
        indicator = ['\t0', '.', '.', '20', '.', '.', '40', '.', '.',
                     '60', '.', '.', '80', '.', '.', '100\n']
        for i in range(0, 16):
            if current >= step[i]:
                output += indicator[i]
        if output:
            sys.stdout.write('\r' + output)
            sys.stdout.flush()


def str_to_ascii(a_string):
    """Given str (unicode, latin-1, or not) return ascii.

    Args:
      s: str, likely in Unicode-16BE, UTF-8, or Latin-1 charset
    Returns:
      str, ascii form, no >7bit chars
    """
    try:
        return unicode(a_string).encode('ascii', 'ignore')
    except UnicodeDecodeError:
        return a_string.decode('ascii', 'ignore')


def to_unicode(obj, encoding='UTF-8'):
    """Coerces basestring obj to unicode"""
    if isinstance(obj, basestring):
        if not isinstance(obj, unicode):
            obj = unicode(obj, encoding)
    return obj


def concat_log_message(msg, *args):
    """Concatenates a string with any additional arguments,
    making sure everything is unicode"""
    # coerce msg to unicode if it's not already
    msg = to_unicode(msg)
    if args:
        # coerce all args to unicode as well
        args = [to_unicode(arg) for arg in args]
        try:
            msg = msg % tuple(args)
        except TypeError, dummy_err:
            warnings.warn(
                'String format does not match concat args: %s'
                % (str(sys.exc_info())))
    return msg.rstrip()


def display_status_major(msg, *args):
    """
    Displays major status messages, formatting as needed
    for verbose/non-verbose and munkistatus-style output.
    """
    msg = concat_log_message(msg, *args)
    log(msg)
    if munkistatusoutput:
        munkistatus.message(msg)
        munkistatus.detail('')
        munkistatus.percent(-1)
    elif verbose > 0:
        if msg.endswith('.') or msg.endswith(u'…'):
            print '%s' % msg.encode('UTF-8')
        else:
            print '%s...' % msg.encode('UTF-8')
        sys.stdout.flush()


def display_status_minor(msg, *args):
    """
    Displays minor status messages, formatting as needed
    for verbose/non-verbose and munkistatus-style output.
    """
    msg = concat_log_message(msg, *args)
    log(u'    ' + msg)
    if munkistatusoutput:
        munkistatus.detail(msg)
    elif verbose > 0:
        if msg.endswith('.') or msg.endswith(u'…'):
            print '    %s' % msg.encode('UTF-8')
        else:
            print '    %s...' % msg.encode('UTF-8')
        sys.stdout.flush()


def display_info(msg, *args):
    """
    Displays info messages.
    Not displayed in MunkiStatus.
    """
    msg = concat_log_message(msg, *args)
    log(u'    ' + msg)
    if munkistatusoutput:
        pass
    elif verbose > 0:
        print '    %s' % msg.encode('UTF-8')
        sys.stdout.flush()


def display_detail(msg, *args):
    """
    Displays minor info messages.
    Not displayed in MunkiStatus.
    These are usually logged only, but can be printed to
    stdout if verbose is set greater than 1
    """
    msg = concat_log_message(msg, *args)
    if munkistatusoutput:
        pass
    elif verbose > 1:
        print '    %s' % msg.encode('UTF-8')
        sys.stdout.flush()
    if pref('LoggingLevel') > 0:
        log(u'    ' + msg)


def display_debug1(msg, *args):
    """
    Displays debug messages, formatting as needed
    for verbose/non-verbose and munkistatus-style output.
    """
    msg = concat_log_message(msg, *args)
    if munkistatusoutput:
        pass
    elif verbose > 2:
        print '    %s' % msg.encode('UTF-8')
        sys.stdout.flush()
    if pref('LoggingLevel') > 1:
        log('DEBUG1: %s' % msg)


def display_debug2(msg, *args):
    """
    Displays debug messages, formatting as needed
    for verbose/non-verbose and munkistatus-style output.
    """
    msg = concat_log_message(msg, *args)
    if munkistatusoutput:
        pass
    elif verbose > 3:
        print '    %s' % msg.encode('UTF-8')
    if pref('LoggingLevel') > 2:
        log('DEBUG2: %s' % msg)


def reset_warnings():
    """Rotate our warnings log."""
    warningsfile = os.path.join(os.path.dirname(pref('LogFile')),
                                'warnings.log')
    if os.path.exists(warningsfile):
        rotatelog(warningsfile)


def display_warning(msg, *args):
    """
    Prints warning msgs to stderr and the log
    """
    msg = concat_log_message(msg, *args)
    warning = 'WARNING: %s' % msg
    if verbose > 0:
        print >> sys.stderr, warning.encode('UTF-8')
    log(warning)
    # append this warning to our warnings log
    log(warning, 'warnings.log')
    # collect the warning for later reporting
    if not 'Warnings' in report:
        report['Warnings'] = []
    report['Warnings'].append('%s' % msg)


def reset_errors():
    """Rotate our errors.log"""
    errorsfile = os.path.join(os.path.dirname(pref('LogFile')), 'errors.log')
    if os.path.exists(errorsfile):
        rotatelog(errorsfile)


def display_error(msg, *args):
    """
    Prints msg to stderr and the log
    """
    msg = concat_log_message(msg, *args)
    errmsg = 'ERROR: %s' % msg
    if verbose > 0:
        print >> sys.stderr, errmsg.encode('UTF-8')
    log(errmsg)
    # append this error to our errors log
    log(errmsg, 'errors.log')
    # collect the errors for later reporting
    if not 'Errors' in report:
        report['Errors'] = []
    report['Errors'].append('%s' % msg)

# logging functions

def format_time(timestamp=None):
    """Return timestamp as an ISO 8601 formatted string, in the current
    timezone.
    If timestamp isn't given the current time is used."""
    if timestamp is None:
        return str(NSDate.new())
    else:
        return str(NSDate.dateWithTimeIntervalSince1970_(timestamp))


def validateDateFormat(datetime_string):
    """Returns a formatted date/time string"""
    formatted_datetime_string = ''
    try:
        formatted_datetime_string = time.strftime(
            '%Y-%m-%dT%H:%M:%SZ', time.strptime(datetime_string,
                                                '%Y-%m-%dT%H:%M:%SZ'))
    except BaseException:
        pass
    return formatted_datetime_string


def log(msg, logname=''):
    """Generic logging function."""
    if len(msg) > 1000:
        # See http://bugs.python.org/issue11907 and RFC-3164
        # break up huge msg into chunks and send 1000 characters at a time
        msg_buffer = msg
        while msg_buffer:
            logging.info(msg_buffer[:1000])
            msg_buffer = msg_buffer[1000:]
    else:
        logging.info(msg)  # noop unless configure_syslog() is called first.

    # date/time format string
    formatstr = '%b %d %Y %H:%M:%S %z'
    if not logname:
        # use our regular logfile
        logpath = pref('LogFile')
    else:
        logpath = os.path.join(os.path.dirname(pref('LogFile')), logname)
    try:
        fileobj = open(logpath, mode='a', buffering=1)
        try:
            print >> fileobj, time.strftime(formatstr), msg.encode('UTF-8')
        except (OSError, IOError):
            pass
        fileobj.close()
    except (OSError, IOError):
        pass


def configure_syslog():
    """Configures logging to system.log, when pref('LogToSyslog') == True."""
    logger = logging.getLogger()
    # Remove existing handlers to avoid sending unexpected messages.
    for handler in logger.handlers:
        logger.removeHandler(handler)
    logger.setLevel(logging.DEBUG)

    # If /System/Library/LaunchDaemons/com.apple.syslogd.plist is restarted
    # then /var/run/syslog stops listening.  If we fail to catch this then
    # Munki completely errors.
    try:
        syslog = logging.handlers.SysLogHandler('/var/run/syslog')
    except:
        log('LogToSyslog is enabled but socket connection failed.')
        return

    syslog.setFormatter(logging.Formatter('munki: %(message)s'))
    syslog.setLevel(logging.INFO)
    logger.addHandler(syslog)


def rotatelog(logname=''):
    """Rotate a log"""
    if not logname:
        # use our regular logfile
        logpath = pref('LogFile')
    else:
        logpath = os.path.join(os.path.dirname(pref('LogFile')), logname)
    if os.path.exists(logpath):
        for i in range(3, -1, -1):
            try:
                os.unlink(logpath + '.' + str(i + 1))
            except (OSError, IOError):
                pass
            try:
                os.rename(logpath + '.' + str(i), logpath + '.' + str(i + 1))
            except (OSError, IOError):
                pass
        try:
            os.rename(logpath, logpath + '.0')
        except (OSError, IOError):
            pass


def rotate_main_log():
    """Rotate our main log"""
    if os.path.exists(pref('LogFile')):
        if os.path.getsize(pref('LogFile')) > 1000000:
            rotatelog(pref('LogFile'))

# reporting functions

def printreportitem(label, value, indent=0):
    """Prints a report item in an 'attractive' way"""
    indentspace = '    '
    if type(value) == type(None):
        print indentspace*indent, '%s: !NONE!' % label
    elif type(value) == list or type(value).__name__ == 'NSCFArray':
        if label:
            print indentspace*indent, '%s:' % label
        index = 0
        for item in value:
            index += 1
            printreportitem(index, item, indent+1)
    elif type(value) == dict or type(value).__name__ == 'NSCFDictionary':
        if label:
            print indentspace*indent, '%s:' % label
        for subkey in value.keys():
            printreportitem(subkey, value[subkey], indent+1)
    else:
        print indentspace*indent, '%s: %s' % (label, value)


def printreport(reportdict):
    """Prints the report dictionary in a pretty(?) way"""
    for key in reportdict.keys():
        printreportitem(key, reportdict[key])


def savereport():
    """Save our report"""
    FoundationPlist.writePlist(
        report, os.path.join(pref('ManagedInstallDir'),
                             'ManagedInstallReport.plist'))


def readreport():
    """Read report data from file"""
    global report
    reportfile = os.path.join(pref('ManagedInstallDir'),
                              'ManagedInstallReport.plist')
    try:
        report = FoundationPlist.readPlist(reportfile)
    except FoundationPlist.NSPropertyListSerializationException:
        report = {}


def archive_report():
    """Archive a report"""
    reportfile = os.path.join(pref('ManagedInstallDir'),
                              'ManagedInstallReport.plist')
    if os.path.exists(reportfile):
        modtime = os.stat(reportfile).st_mtime
        formatstr = '%Y-%m-%d-%H%M%S'
        archivename = ('ManagedInstallReport-%s.plist'
                       % time.strftime(formatstr, time.localtime(modtime)))
        archivepath = os.path.join(pref('ManagedInstallDir'), 'Archives')
        if not os.path.exists(archivepath):
            try:
                os.mkdir(archivepath)
            except (OSError, IOError):
                display_warning('Could not create report archive path.')
        try:
            os.rename(reportfile, os.path.join(archivepath, archivename))
        except (OSError, IOError):
            display_warning('Could not archive report.')
        # now keep number of archived reports to 100 or fewer
        proc = subprocess.Popen(['/bin/ls', '-t1', archivepath],
                                bufsize=1, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        (output, dummy_err) = proc.communicate()
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
                            display_warning(
                                'Could not remove archive item %s', itempath)


# module globals
#debug = False
verbose = 1
munkistatusoutput = False
report = {}


def main():
    """Placeholder"""
    print 'This is a library of support tools for the Munki Suite.'


if __name__ == '__main__':
    main()
