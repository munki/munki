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
munkicommon

Created by Greg Neagle on 2008-11-18.

Common functions used by the munki tools.
"""

import ctypes
import ctypes.util
import fcntl
import hashlib
import os
import logging
import logging.handlers
import platform
import re
import select
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import time
import urllib2
import warnings
from distutils import version
from types import StringType
from xml.dom import minidom

import munkistatus
import FoundationPlist

import LaunchServices

# PyLint cannot properly find names inside Cocoa libraries, so issues bogus
# No name 'Foo' in module 'Bar' warnings. Disable them.
# pylint: disable=E0611
from Foundation import NSDate, NSMetadataQuery, NSPredicate, NSRunLoop
from Foundation import CFPreferencesAppSynchronize
from Foundation import CFPreferencesCopyAppValue
from Foundation import CFPreferencesCopyKeyList
from Foundation import CFPreferencesSetValue
from Foundation import kCFPreferencesAnyUser
from Foundation import kCFPreferencesCurrentUser
from Foundation import kCFPreferencesCurrentHost

from SystemConfiguration import SCDynamicStoreCopyConsoleUser
# pylint: enable=E0611

# we use lots of camelCase-style names. Deal with it.
# pylint: disable=C0103


# NOTE: it's very important that defined exit codes are never changed!
# Preflight exit codes.
EXIT_STATUS_PREFLIGHT_FAILURE = 1  # Python crash yields 1.
# Client config exit codes.
EXIT_STATUS_OBJC_MISSING = 100
EXIT_STATUS_MUNKI_DIRS_FAILURE = 101
# Server connection exit codes.
EXIT_STATUS_SERVER_UNAVAILABLE = 150
# User related exit codes.
EXIT_STATUS_INVALID_PARAMETERS = 200
EXIT_STATUS_ROOT_REQUIRED = 201


# our preferences "bundle_id"
BUNDLE_ID = 'ManagedInstalls'

# the following two items are not used internally by munki
# any longer, but remain for backwards compatibility with
# pre and postflight script that might access these files directly
MANAGED_INSTALLS_PLIST_PATH = "/Library/Preferences/" + BUNDLE_ID + ".plist"
SECURE_MANAGED_INSTALLS_PLIST_PATH = \
    "/private/var/root/Library/Preferences/" + BUNDLE_ID + ".plist"

ADDITIONAL_HTTP_HEADERS_KEY = 'AdditionalHttpHeaders'


LOGINWINDOW = (
    "/System/Library/CoreServices/loginwindow.app/Contents/MacOS/loginwindow")


# Always ignore these directories when discovering applications.
APP_DISCOVERY_EXCLUSION_DIRS = set([
    'Volumes', 'tmp', '.vol', '.Trashes', '.MobileBackups', '.Spotlight-V100',
    '.fseventsd', 'Network', 'net', 'home', 'cores', 'dev', 'private',
    ])


class Error(Exception):
    """Class for domain specific exceptions."""


class PreferencesError(Error):
    """There was an error reading the preferences plist."""


class TimeoutError(Error):
    """Timeout limit exceeded since last I/O."""


def getOsVersion(only_major_minor=True, as_tuple=False):
    """Returns an OS version.

    Args:
      only_major_minor: Boolean. If True, only include major/minor versions.
      as_tuple: Boolean. If True, return a tuple of ints, otherwise a string.
    """
    os_version_tuple = platform.mac_ver()[0].split('.')
    if only_major_minor:
        os_version_tuple = os_version_tuple[0:2]
    if as_tuple:
        return tuple(map(int, os_version_tuple))
    else:
        return '.'.join(os_version_tuple)


def set_file_nonblock(f, non_blocking=True):
    """Set non-blocking flag on a file object.

    Args:
      f: file
      non_blocking: bool, default True, non-blocking mode or not
    """
    flags = fcntl.fcntl(f.fileno(), fcntl.F_GETFL)
    if bool(flags & os.O_NONBLOCK) != non_blocking:
        flags ^= os.O_NONBLOCK
    fcntl.fcntl(f.fileno(), fcntl.F_SETFL, flags)


class Popen(subprocess.Popen):
    """Subclass of subprocess.Popen to add support for timeouts."""

    def timed_readline(self, f, timeout):
        """Perform readline-like operation with timeout.

        Args:
            f: file object to .readline() on
            timeout: int, seconds of inactivity to raise error at
        Raises:
            TimeoutError, if timeout is reached
        """
        set_file_nonblock(f)

        output = []
        inactive = 0
        while 1:
            (rlist, dummy_wlist, dummy_xlist) = select.select(
                [f], [], [], 1.0)

            if not rlist:
                inactive += 1  # approx -- py select doesn't return tv
                if inactive >= timeout:
                    break
            else:
                inactive = 0
                c = f.read(1)
                output.append(c)  # keep newline
                if c == '' or c == '\n':
                    break

        set_file_nonblock(f, non_blocking=False)

        if inactive >= timeout:
            raise TimeoutError  # note, an incomplete line can be lost
        else:
            return ''.join(output)

    def communicate(self, std_in=None, timeout=0):
        """Communicate, optionally ending after a timeout of no activity.

        Args:
            std_in: str, to send on stdin
            timeout: int, seconds of inactivity to raise error at
        Returns:
            (str or None, str or None) for stdout, stderr
        Raises:
            TimeoutError, if timeout is reached
        """
        if timeout <= 0:
            return super(Popen, self).communicate(input=std_in)

        fds = []
        stdout = []
        stderr = []

        if self.stdout is not None:
            set_file_nonblock(self.stdout)
            fds.append(self.stdout)
        if self.stderr is not None:
            set_file_nonblock(self.stderr)
            fds.append(self.stderr)

        if std_in is not None and sys.stdin is not None:
            sys.stdin.write(std_in)

        returncode = None
        inactive = 0
        while returncode is None:
            (rlist, dummy_wlist, dummy_xlist) = select.select(
                fds, [], [], 1.0)

            if not rlist:
                inactive += 1
                if inactive >= timeout:
                    raise TimeoutError
            else:
                inactive = 0
                for fd in rlist:
                    if fd is self.stdout:
                        stdout.append(fd.read())
                    elif fd is self.stderr:
                        stderr.append(fd.read())

            returncode = self.poll()

        if self.stdout is not None:
            stdout = ''.join(stdout)
        else:
            stdout = None
        if self.stderr is not None:
            stderr = ''.join(stderr)
        else:
            stderr = None

        return (stdout, stderr)


def get_version():
    """Returns version of munkitools, reading version.plist"""
    vers = "UNKNOWN"
    build = ""
    # find the munkilib directory, and the version file
    munkilibdir = os.path.dirname(os.path.abspath(__file__))
    versionfile = os.path.join(munkilibdir, "version.plist")
    if os.path.exists(versionfile):
        try:
            vers_plist = FoundationPlist.readPlist(versionfile)
        except FoundationPlist.NSPropertyListSerializationException:
            pass
        else:
            try:
                vers = vers_plist['CFBundleShortVersionString']
                build = vers_plist['BuildNumber']
            except KeyError:
                pass
    if build:
        vers = vers + "." + build
    return vers


# output and logging functions
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


def str_to_ascii(s):
    """Given str (unicode, latin-1, or not) return ascii.

    Args:
      s: str, likely in Unicode-16BE, UTF-8, or Latin-1 charset
    Returns:
      str, ascii form, no >7bit chars
    """
    try:
        return unicode(s).encode('ascii', 'ignore')
    except UnicodeDecodeError:
        return s.decode('ascii', 'ignore')


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

    syslog = logging.handlers.SysLogHandler('/var/run/syslog')
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


def saveappdata():
    """Save installed application data"""
    # data from getAppData() is meant for use by updatecheck
    # we need to massage it a bit for more general usage
    log('Saving application inventory...')
    app_inventory = []
    for item in getAppData():
        inventory_item = {}
        inventory_item['CFBundleName'] = item.get('name')
        inventory_item['bundleid'] = item.get('bundleid')
        inventory_item['version'] = item.get('version')
        inventory_item['path'] = item.get('path', '')
        # use last path item (minus '.app' if present) as name
        inventory_item['name'] = \
            os.path.splitext(os.path.basename(inventory_item['path']))[0]
        app_inventory.append(inventory_item)
    try:
        FoundationPlist.writePlist(
            app_inventory,
            os.path.join(
                pref('ManagedInstallDir'), 'ApplicationInventory.plist'))
    except FoundationPlist.NSPropertyListSerializationException, err:
        display_warning(
            'Unable to save inventory report: %s' % err)



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


# misc functions


def validPlist(path):
    """Uses plutil to determine if path contains a valid plist.
    Returns True or False."""
    retcode = subprocess.call(['/usr/bin/plutil', '-lint', '-s', path])
    if retcode == 0:
        return True
    else:
        return False


_stop_requested = False
def stopRequested():
    """Allows user to cancel operations when GUI status is being used"""
    global _stop_requested
    if _stop_requested:
        return True
    STOP_REQUEST_FLAG = (
        '/private/tmp/'
        'com.googlecode.munki.managedsoftwareupdate.stop_requested')
    if munkistatusoutput:
        if os.path.exists(STOP_REQUEST_FLAG):
            # store this so it's persistent until this session is over
            _stop_requested = True
            log('### User stopped session ###')
            try:
                os.unlink(STOP_REQUEST_FLAG)
            except OSError, err:
                display_error(
                    'Could not remove %s: %s', STOP_REQUEST_FLAG, err)
            return True
    return False


def getconsoleuser():
    """Return console user"""
    cfuser = SCDynamicStoreCopyConsoleUser(None, None, None)
    return cfuser[0]


def currentGUIusers():
    """Gets a list of GUI users by parsing the output of /usr/bin/who"""
    gui_users = []
    proc = subprocess.Popen('/usr/bin/who', shell=False,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (output, dummy_err) = proc.communicate()
    lines = str(output).splitlines()
    for line in lines:
        if 'console' in line:
            parts = line.split()
            gui_users.append(parts[0])

    # 10.11 sometimes has a phantom '_mbsetupuser' user. Filter it out.
    users_to_ignore = ['_mbsetupuser']
    gui_users = [user for user in gui_users if user not in users_to_ignore]

    return gui_users


def pythonScriptRunning(scriptname):
    """Returns Process ID for a running python script"""
    cmd = ['/bin/ps', '-eo', 'pid=,command=']
    proc = subprocess.Popen(cmd, shell=False, bufsize=1,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out, dummy_err) = proc.communicate()
    mypid = os.getpid()
    lines = str(out).splitlines()
    for line in lines:
        try:
            (pid, process) = line.split(None, 1)
        except ValueError:
            # funky process line, so we'll skip it
            pass
        else:
            args = process.split()
            try:
                # first look for Python processes
                if (args[0].find('MacOS/Python') != -1 or
                        args[0].find('python') != -1):
                    # look for first argument being scriptname
                    if args[1].find(scriptname) != -1:
                        try:
                            if int(pid) != int(mypid):
                                return pid
                        except ValueError:
                            # pid must have some funky characters
                            pass
            except IndexError:
                pass
    # if we get here we didn't find a Python script with scriptname
    # (other than ourselves)
    return 0


def osascript(osastring):
    """Wrapper to run AppleScript commands"""
    cmd = ['/usr/bin/osascript', '-e', osastring]
    proc = subprocess.Popen(cmd, shell=False, bufsize=1,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out, err) = proc.communicate()
    if proc.returncode != 0:
        print >> sys.stderr, 'Error: ', err
    if out:
        return str(out).decode('UTF-8').rstrip('\n')


def getFirstPlist(textString):
    """Gets the next plist from a text string that may contain one or
    more text-style plists.
    Returns a tuple - the first plist (if any) and the remaining
    string after the plist"""
    plist_header = '<?xml version'
    plist_footer = '</plist>'
    plist_start_index = textString.find(plist_header)
    if plist_start_index == -1:
        # not found
        return ("", textString)
    plist_end_index = textString.find(
        plist_footer, plist_start_index + len(plist_header))
    if plist_end_index == -1:
        # not found
        return ("", textString)
    # adjust end value
    plist_end_index = plist_end_index + len(plist_footer)
    return (textString[plist_start_index:plist_end_index],
            textString[plist_end_index:])


# dmg helpers

def DMGisWritable(dmgpath):
    '''Attempts to determine if the given disk image is writable'''
    proc = subprocess.Popen(
        ['/usr/bin/hdiutil', 'imageinfo', dmgpath, '-plist'],
        bufsize=-1, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out, err) = proc.communicate()
    if err:
        print >> sys.stderr, (
            'hdiutil error %s with image %s.' % (err, dmgpath))
    (pliststr, out) = getFirstPlist(out)
    if pliststr:
        try:
            plist = FoundationPlist.readPlistFromString(pliststr)
            dmg_format = plist.get('Format')
            if dmg_format in ['UDSB', 'UDSP', 'UDRW', 'RdWr']:
                return True
        except FoundationPlist.NSPropertyListSerializationException:
            pass
    return False


def DMGhasSLA(dmgpath):
    '''Returns true if dmg has a Software License Agreement.
    These dmgs normally cannot be attached without user intervention'''
    hasSLA = False
    proc = subprocess.Popen(
        ['/usr/bin/hdiutil', 'imageinfo', dmgpath, '-plist'],
        bufsize=-1, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out, err) = proc.communicate()
    if err:
        print >> sys.stderr, (
            'hdiutil error %s with image %s.' % (err, dmgpath))
    (pliststr, out) = getFirstPlist(out)
    if pliststr:
        try:
            plist = FoundationPlist.readPlistFromString(pliststr)
            properties = plist.get('Properties')
            if properties:
                hasSLA = properties.get('Software License Agreement', False)
        except FoundationPlist.NSPropertyListSerializationException:
            pass

    return hasSLA


def hdiutilInfo():
    """
    Convenience method for running 'hdiutil info -plist'

    Returns the root object parsed with readPlistFromString()
    """
    proc = subprocess.Popen(
        ['/usr/bin/hdiutil', 'info', '-plist'],
        bufsize=-1, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out, err) = proc.communicate()
    if err:
        print >> sys.stderr, 'hdiutil info error: %s' % err
    (pliststr, out) = getFirstPlist(out)
    if pliststr:
        try:
            plist = FoundationPlist.readPlistFromString(pliststr)
            return plist
        except FoundationPlist.NSPropertyListSerializationException:
            pass
    return None


def diskImageIsMounted(dmgpath):
    """
    Returns true if the given disk image is currently mounted
    """
    isMounted = False
    infoplist = hdiutilInfo()
    for imageProperties in infoplist.get('images'):
        if 'image-path' in imageProperties:
            imagepath = imageProperties['image-path']
            if imagepath == dmgpath:
                isMounted = True
                break
    return isMounted


def pathIsVolumeMountPoint(path):
    """
    Checks if the given path is a volume for an attached disk image

    Returns true if the given path is a mount point or false if it isn't
    """
    isMountPoint = False
    infoplist = hdiutilInfo()
    for imageProperties in infoplist.get('images'):
        if 'image-path' in imageProperties:
            for entity in imageProperties.get('system-entities', []):
                if 'mount-point' in entity:
                    mountpoint = entity['mount-point']
                    if path == mountpoint:
                        isMountPoint = True
                        break
    return isMountPoint


def diskImageForMountPoint(path):
    """
    Resolves the given mount point path to an attached disk image path

    Returns a path to a disk image file or None if the path is not
    a valid mount point
    """
    dmgpath = None
    infoplist = hdiutilInfo()
    for imageProperties in infoplist.get('images'):
        if 'image-path' in imageProperties:
            imagepath = imageProperties['image-path']
            for entity in imageProperties.get('system-entities', []):
                if 'mount-point' in entity:
                    mountpoint = entity['mount-point']
                    if os.path.samefile(path, mountpoint):
                        dmgpath = imagepath
    return dmgpath

def mountPointsForDiskImage(dmgpath):
    """
    Returns a list of mountpoints for the given disk image
    """
    mountpoints = []
    infoplist = hdiutilInfo()
    for imageProperties in infoplist.get('images'):
        if 'image-path' in imageProperties:
            imagepath = imageProperties['image-path']
            if imagepath == dmgpath:
                for entity in imageProperties.get('system-entities', []):
                    if 'mount-point' in entity:
                        mountpoints.append(entity['mount-point'])
                break
    return mountpoints


def mountdmg(dmgpath, use_shadow=False, use_existing_mounts=False):
    """
    Attempts to mount the dmg at dmgpath
    and returns a list of mountpoints
    If use_shadow is true, mount image with shadow file
    """
    mountpoints = []
    dmgname = os.path.basename(dmgpath)

    if use_existing_mounts:
        # Check if this dmg is already mounted
        # and if so, bail out and return the mountpoints
        if diskImageIsMounted(dmgpath):
            mountpoints = mountPointsForDiskImage(dmgpath)
            return mountpoints

    # Attempt to mount the dmg
    stdin = ''
    if DMGhasSLA(dmgpath):
        stdin = 'Y\n'
        display_detail(
            'NOTE: %s has embedded Software License Agreement' % dmgname)
    cmd = ['/usr/bin/hdiutil', 'attach', dmgpath,
           '-mountRandom', '/tmp', '-nobrowse', '-plist']
    if use_shadow:
        cmd.append('-shadow')
    proc = subprocess.Popen(cmd,
                            bufsize=1, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, stdin=subprocess.PIPE)
    (out, err) = proc.communicate(stdin)
    if proc.returncode:
        display_error(
            'Error: "%s" while mounting %s.' % (err.rstrip(), dmgname))
    (pliststr, out) = getFirstPlist(out)
    if pliststr:
        try:
            plist = FoundationPlist.readPlistFromString(pliststr)
            for entity in plist.get('system-entities', []):
                if 'mount-point' in entity:
                    mountpoints.append(entity['mount-point'])
        except FoundationPlist.NSPropertyListSerializationException:
            display_error(
                'Bad plist string returned when mounting diskimage %s:\n%s'
                % (dmgname, pliststr))
    return mountpoints


def unmountdmg(mountpoint):
    """
    Unmounts the dmg at mountpoint
    """
    cmd = ['/usr/bin/hdiutil', 'detach', mountpoint]
    proc = subprocess.Popen(cmd, bufsize=-1, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    (dummy_output, err) = proc.communicate()
    if proc.returncode:
        # ordinary unmount unsuccessful, try forcing
        display_warning('Polite unmount failed: %s' % err)
        display_warning('Attempting to force unmount %s' % mountpoint)
        cmd.append('-force')
        proc = subprocess.Popen(cmd, bufsize=-1, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        (dummy_output, err) = proc.communicate()
        if proc.returncode:
            display_warning('Failed to unmount %s: %s', mountpoint, err)


def gethash(filename, hash_function):
    """
    Calculates the hashvalue of the given file with the given hash_function.

    Args:
      filename: The file name to calculate the hash value of.
      hash_function: The hash function object to use, which was instanciated
          before calling this function, e.g. hashlib.md5().

    Returns:
      The hashvalue of the given file as hex string.
    """
    if not os.path.isfile(filename):
        return 'NOT A FILE'

    f = open(filename, 'rb')
    while 1:
        chunk = f.read(2**16)
        if not chunk:
            break
        hash_function.update(chunk)
    f.close()
    return hash_function.hexdigest()


def getmd5hash(filename):
    """
    Returns hex of MD5 checksum of a file
    """
    hash_function = hashlib.md5()
    return gethash(filename, hash_function)


def getsha256hash(filename):
    """
    Returns the SHA-256 hash value of a file as a hex string.
    """
    hash_function = hashlib.sha256()
    return gethash(filename, hash_function)


def isApplication(pathname):
    """Returns true if path appears to be an OS X application"""
    # No symlinks, please
    if os.path.islink(pathname):
        return False
    if pathname.endswith('.app'):
        return True
    if os.path.isdir(pathname):
        # look for app bundle structure
        # use Info.plist to determine the name of the executable
        infoplist = os.path.join(pathname, 'Contents', 'Info.plist')
        if os.path.exists(infoplist):
            plist = FoundationPlist.readPlist(infoplist)
            if 'CFBundlePackageType' in plist:
                if plist['CFBundlePackageType'] != 'APPL':
                    return False
            # get CFBundleExecutable,
            # falling back to bundle name if it's missing
            bundleexecutable = plist.get(
                'CFBundleExecutable', os.path.basename(pathname))
            bundleexecutablepath = os.path.join(
                pathname, 'Contents', 'MacOS', bundleexecutable)
            if os.path.exists(bundleexecutablepath):
                return True
    return False


#####################################################
# managed installs preferences/metadata
#####################################################

class Preferences(object):
    """Class which directly reads/writes Apple CF preferences."""

    def __init__(self, bundle_id, user=kCFPreferencesAnyUser):
        """Init.

        Args:
            bundle_id: str, like 'ManagedInstalls'
        """
        if bundle_id.endswith('.plist'):
            bundle_id = bundle_id[:-6]
        self.bundle_id = bundle_id
        self.user = user

    def __iter__(self):
        keys = CFPreferencesCopyKeyList(
            self.bundle_id, self.user, kCFPreferencesCurrentHost)
        if keys is not None:
            for i in keys:
                yield i

    def __contains__(self, pref_name):
        pref_value = CFPreferencesCopyAppValue(pref_name, self.bundle_id)
        return pref_value is not None

    def __getitem__(self, pref_name):
        return CFPreferencesCopyAppValue(pref_name, self.bundle_id)

    def __setitem__(self, pref_name, pref_value):
        CFPreferencesSetValue(
            pref_name, pref_value, self.bundle_id, self.user,
            kCFPreferencesCurrentHost)
        CFPreferencesAppSynchronize(self.bundle_id)

    def __delitem__(self, pref_name):
        self.__setitem__(pref_name, None)

    def __repr__(self):
        return '<%s %s>' % (self.__class__.__name__, self.bundle_id)

    def get(self, pref_name, default=None):
        """Return a preference or the default value"""
        if not pref_name in self:
            return default
        else:
            return self.__getitem__(pref_name)


class ManagedInstallsPreferences(Preferences):
    """Preferences which read from /L/P/ManagedInstalls."""
    def __init__(self):
        Preferences.__init__(self, 'ManagedInstalls', kCFPreferencesAnyUser)


class SecureManagedInstallsPreferences(Preferences):
    """Preferences which read from /private/var/root/L/P/ManagedInstalls."""
    def __init__(self):
        Preferences.__init__(self, 'ManagedInstalls', kCFPreferencesCurrentUser)


def reload_prefs():
    """Uses CFPreferencesAppSynchronize(BUNDLE_ID)
    to make sure we have the latest prefs. Call this
    if you have modified /Library/Preferences/ManagedInstalls.plist
    or /var/root/Library/Preferences/ManagedInstalls.plist directly"""
    CFPreferencesAppSynchronize(BUNDLE_ID)


def set_pref(pref_name, pref_value):
    """Sets a preference, writing it to
    /Library/Preferences/ManagedInstalls.plist.
    This should normally be used only for 'bookkeeping' values;
    values that control the behavior of munki may be overridden
    elsewhere (by MCX, for example)"""
    try:
        CFPreferencesSetValue(
            pref_name, pref_value, BUNDLE_ID,
            kCFPreferencesAnyUser, kCFPreferencesCurrentHost)
        CFPreferencesAppSynchronize(BUNDLE_ID)
    except BaseException:
        pass


def pref(pref_name):
    """Return a preference. Since this uses CFPreferencesCopyAppValue,
    Preferences can be defined several places. Precedence is:
        - MCX
        - /var/root/Library/Preferences/ManagedInstalls.plist
        - /Library/Preferences/ManagedInstalls.plist
        - default_prefs defined here.
    """
    default_prefs = {
        'ManagedInstallDir': '/Library/Managed Installs',
        'SoftwareRepoURL': 'http://munki/repo',
        'ClientIdentifier': '',
        'LogFile': '/Library/Managed Installs/Logs/ManagedSoftwareUpdate.log',
        'LoggingLevel': 1,
        'LogToSyslog': False,
        'InstallAppleSoftwareUpdates': False,
        'AppleSoftwareUpdatesOnly': False,
        'SoftwareUpdateServerURL': '',
        'DaysBetweenNotifications': 1,
        'LastNotifiedDate': NSDate.dateWithTimeIntervalSince1970_(0),
        'UseClientCertificate': False,
        'SuppressUserNotification': False,
        'SuppressAutoInstall': False,
        'SuppressStopButtonOnInstall': False,
        'PackageVerificationMode': 'hash',
        'FollowHTTPRedirects': 'none',
        'UnattendedAppleUpdates': False,
    }
    pref_value = CFPreferencesCopyAppValue(pref_name, BUNDLE_ID)
    if pref_value == None:
        pref_value = default_prefs.get(pref_name)
        # we're using a default value. We'll write it out to
        # /Library/Preferences/<BUNDLE_ID>.plist for admin
        # discoverability
        set_pref(pref_name, pref_value)
    if isinstance(pref_value, NSDate):
        # convert NSDate/CFDates to strings
        pref_value = str(pref_value)
    return pref_value

#####################################################
# Apple package utilities
#####################################################

def getInstallerPkgInfo(filename):
    """Uses Apple's installer tool to get basic info
    about an installer item."""
    installerinfo = {}
    proc = subprocess.Popen(['/usr/sbin/installer', '-pkginfo', '-verbose',
                             '-plist', '-pkg', filename],
                            bufsize=1, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    (out, dummy_err) = proc.communicate()

    if out:
        # discard any lines at the beginning that aren't part of the plist
        lines = str(out).splitlines()
        plist = ''
        for index in range(len(lines)):
            try:
                plist = FoundationPlist.readPlistFromString(
                    '\n'.join(lines[index:]))
            except FoundationPlist.NSPropertyListSerializationException:
                pass
            if plist:
                break
        if plist:
            if 'Size' in plist:
                installerinfo['installed_size'] = int(plist['Size'])
            installerinfo['description'] = plist.get('Description', '')
            if plist.get('Will Restart') == 'YES':
                installerinfo['RestartAction'] = 'RequireRestart'
            if 'Title' in plist:
                installerinfo['display_name'] = plist['Title']

    proc = subprocess.Popen(['/usr/sbin/installer',
                             '-query', 'RestartAction',
                             '-pkg', filename],
                            bufsize=1,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    (out, err) = proc.communicate()
    if proc.returncode:
        display_error("installer -query failed: %s %s" %
                      (out.decode('UTF-8'), err.decode('UTF-8')))
        return None

    if out:
        restartAction = str(out).rstrip('\n')
        if restartAction != 'None':
            installerinfo['RestartAction'] = restartAction

    return installerinfo


class MunkiLooseVersion(version.LooseVersion):
    '''Subclass version.LooseVersion to compare things like
    "10.6" and "10.6.0" as equal'''

    def __init__(self, vstring=None):
        if vstring is None:
            # treat None like an empty string
            self.parse('')
        if vstring is not None:
            if isinstance(vstring, unicode):
                # unicode string! Why? Oh well...
                # convert to string so version.LooseVersion doesn't choke
                vstring = vstring.encode('UTF-8')
            self.parse(str(vstring))

    def _pad(self, version_list, max_length):
        """Pad a version list by adding extra 0
        components to the end if needed"""
        # copy the version_list so we don't modify it
        cmp_list = list(version_list)
        while len(cmp_list) < max_length:
            cmp_list.append(0)
        return cmp_list

    def __cmp__(self, other):
        if isinstance(other, StringType):
            other = MunkiLooseVersion(other)

        max_length = max(len(self.version), len(other.version))
        self_cmp_version = self._pad(self.version, max_length)
        other_cmp_version = self._pad(other.version, max_length)

        return cmp(self_cmp_version, other_cmp_version)


def padVersionString(versString, tupleCount):
    """Normalize the format of a version string"""
    if versString == None:
        versString = '0'
    components = str(versString).split('.')
    if len(components) > tupleCount:
        components = components[0:tupleCount]
    else:
        while len(components) < tupleCount:
            components.append('0')
    return '.'.join(components)


def getVersionString(plist, key=None):
    """Gets a version string from the plist.

    If a key is explictly specified, the value of that key is
    returned without modification, or an empty string if the
    key does not exist.

    If key is not specified:
    if there's a valid CFBundleShortVersionString, returns that.
    else if there's a CFBundleVersion, returns that
    else returns an empty string.

    """
    VersionString = ''
    if key:
        # admin has specified a specific key
        # return value verbatum or empty string
        return plist.get(key, '')

    # default to CFBundleShortVersionString plus magic
    # and workarounds and edge case cleanupds
    key = 'CFBundleShortVersionString'
    if not 'CFBundleShortVersionString' in plist:
        if 'Bundle versions string, short' in plist:
            # workaround for broken Composer packages
            # where the key is actually named
            # 'Bundle versions string, short' instead of
            # 'CFBundleShortVersionString'
            key = 'Bundle versions string, short'
    if plist.get(key):
        # return key value up to first space
        # lets us use crappy values like '1.0 (100)'
        VersionString = plist[key].split()[0]
    if VersionString:
        if VersionString[0] in '0123456789':
            # starts with a number; that's good
            # now for another edge case thanks to Adobe:
            # replace commas with periods
            VersionString = VersionString.replace(',', '.')
            return VersionString
    if plist.get('CFBundleVersion'):
        # no CFBundleShortVersionString, or bad one
        # a future version of the Munki tools may drop this magic
        # and require admins to explicitly choose the CFBundleVersion
        # but for now Munki does some magic
        VersionString = plist['CFBundleVersion'].encode('utf-8').split()[0]
        if VersionString[0] in '0123456789':
            # starts with a number; that's good
            # now for another edge case thanks to Adobe:
            # replace commas with periods
            VersionString = VersionString.replace(',', '.')
            return VersionString

    return ''


def getAppBundleExecutable(bundlepath):
    """Returns path to the actual executable in an app bundle or None"""
    infoPlist = os.path.join(bundlepath, 'Contents', 'Info.plist')
    if os.path.exists(infoPlist):
        plist = FoundationPlist.readPlist(infoPlist)
        if 'CFBundleExecutable' in plist:
            executable = plist['CFBundleExecutable']
        elif 'CFBundleName' in plist:
            executable = plist['CFBundleName']
        else:
            executable = os.path.splitext(os.path.basename(bundlepath))[0]
        executable_path = os.path.join(bundlepath, 'Contents/MacOS', executable)
        if os.path.exists(executable_path):
            return executable_path
    return None


def getBundleVersion(bundlepath, key=None):
    """
    Returns version number from a bundle.
    Some extra code to deal with very old-style bundle packages

    Specify key to use a specific key in the Info.plist for
    the version string.
    """
    infoPlist = os.path.join(bundlepath, 'Contents', 'Info.plist')
    if not os.path.exists(infoPlist):
        infoPlist = os.path.join(bundlepath, 'Resources', 'Info.plist')
    if os.path.exists(infoPlist):
        plist = FoundationPlist.readPlist(infoPlist)
        versionstring = getVersionString(plist, key)
        if versionstring:
            return versionstring

    # no version number in Info.plist. Maybe old-style package?
    infopath = os.path.join(
        bundlepath, 'Contents', 'Resources', 'English.lproj')
    if os.path.exists(infopath):
        for item in listdir(infopath):
            if os.path.join(infopath, item).endswith('.info'):
                infofile = os.path.join(infopath, item)
                fileobj = open(infofile, mode='r')
                info = fileobj.read()
                fileobj.close()
                infolines = info.splitlines()
                for line in infolines:
                    parts = line.split(None, 1)
                    if len(parts) == 2:
                        label = parts[0]
                        if label == 'Version':
                            return parts[1]

    # didn't find a version number, so return 0...
    return '0.0.0.0.0'


def parsePkgRefs(filename, path_to_pkg=None):
    """Parses a .dist or PackageInfo file looking for pkg-ref or pkg-info tags
    to get info on included sub-packages"""
    info = []
    dom = minidom.parse(filename)
    pkgrefs = dom.getElementsByTagName('pkg-info')
    if pkgrefs:
        # this is a PackageInfo file
        for ref in pkgrefs:
            keys = ref.attributes.keys()
            if 'identifier' in keys and 'version' in keys:
                pkginfo = {}
                pkginfo['packageid'] = \
                       ref.attributes['identifier'].value.encode('UTF-8')
                pkginfo['version'] = \
                    ref.attributes['version'].value.encode('UTF-8')
                payloads = ref.getElementsByTagName('payload')
                if payloads:
                    keys = payloads[0].attributes.keys()
                    if 'installKBytes' in keys:
                        pkginfo['installed_size'] = int(
                            payloads[0].attributes[
                                'installKBytes'].value.encode('UTF-8'))
                    if not pkginfo in info:
                        info.append(pkginfo)
                # if there isn't a payload, no receipt is left by a flat
                # pkg, so don't add this to the info array
    else:
        pkgrefs = dom.getElementsByTagName('pkg-ref')
        if pkgrefs:
            # this is a Distribution or .dist file
            pkgref_dict = {}
            for ref in pkgrefs:
                keys = ref.attributes.keys()
                if 'id' in keys:
                    pkgid = ref.attributes['id'].value.encode('UTF-8')
                    if not pkgid in pkgref_dict:
                        pkgref_dict[pkgid] = {'packageid': pkgid}
                    if 'version' in keys:
                        pkgref_dict[pkgid]['version'] = \
                            ref.attributes['version'].value.encode('UTF-8')
                    if 'installKBytes' in keys:
                        pkgref_dict[pkgid]['installed_size'] = int(
                            ref.attributes['installKBytes'].value.encode(
                                'UTF-8'))
                    if ref.firstChild:
                        text = ref.firstChild.wholeText
                        if text.endswith('.pkg'):
                            if text.startswith('file:'):
                                relativepath = urllib2.unquote(
                                    text[5:].encode('UTF-8'))
                                pkgdir = os.path.dirname(
                                    path_to_pkg or filename)
                                pkgref_dict[pkgid]['file'] = os.path.join(
                                    pkgdir, relativepath)
                            else:
                                if text.startswith('#'):
                                    text = text[1:]
                                relativepath = urllib2.unquote(
                                    text.encode('UTF-8'))
                                thisdir = os.path.dirname(filename)
                                pkgref_dict[pkgid]['file'] = os.path.join(
                                    thisdir, relativepath)

            for key in pkgref_dict.keys():
                pkgref = pkgref_dict[key]
                if 'file' in pkgref:
                    if os.path.exists(pkgref['file']):
                        info.extend(getReceiptInfo(pkgref['file']))
                        continue
                if 'version' in pkgref:
                    if 'file' in pkgref:
                        del pkgref['file']
                    info.append(pkgref_dict[key])

    return info


def getFlatPackageInfo(pkgpath):
    """
    returns array of dictionaries with info on subpackages
    contained in the flat package
    """

    infoarray = []
    # get the absolute path to the pkg because we need to do a chdir later
    abspkgpath = os.path.abspath(pkgpath)
    # make a tmp dir to expand the flat package into
    pkgtmp = tempfile.mkdtemp(dir=tmpdir())
    # record our current working dir
    cwd = os.getcwd()
    # change into our tmpdir so we can use xar to unarchive the flat package
    os.chdir(pkgtmp)
    # Get the TOC of the flat pkg so we can search it later
    cmd_toc = ['/usr/bin/xar', '-tf', abspkgpath]
    proc = subprocess.Popen(cmd_toc, bufsize=-1, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    (toc, err) = proc.communicate()
    toc = toc.strip().split('\n')
    if proc.returncode == 0:
        # Walk trough the TOC entries
        for toc_entry in toc:
            # If the TOC entry is a top-level PackageInfo, extract it
            if toc_entry.startswith('PackageInfo') and len(infoarray) == 0:
                cmd_extract = ['/usr/bin/xar', '-xf', abspkgpath, toc_entry]
                result = subprocess.call(cmd_extract)
                if result == 0:
                    packageinfoabspath = os.path.abspath(
                        os.path.join(pkgtmp, toc_entry))
                    infoarray = parsePkgRefs(packageinfoabspath)
                    break
                else:
                    display_warning("An error occurred while extracting %s: %s"
                                    % (toc_entry, err))
            # If there are PackageInfo files elsewhere, gather them up
            elif toc_entry.endswith('.pkg/PackageInfo'):
                cmd_extract = ['/usr/bin/xar', '-xf', abspkgpath, toc_entry]
                result = subprocess.call(cmd_extract)
                if result == 0:
                    packageinfoabspath = os.path.abspath(
                        os.path.join(pkgtmp, toc_entry))
                    infoarray.extend(parsePkgRefs(packageinfoabspath))
                else:
                    display_warning("An error occurred while extracting %s: %s"
                                    % (toc_entry, err))
        if len(infoarray) == 0:
            for toc_entry in [item for item in toc
                              if item.startswith('Distribution')]:
                # Extract the Distribution file
                cmd_extract = ['/usr/bin/xar', '-xf', abspkgpath, toc_entry]
                result = subprocess.call(cmd_extract)
                if result == 0:
                    distributionabspath = os.path.abspath(
                        os.path.join(pkgtmp, toc_entry))
                    infoarray = parsePkgRefs(distributionabspath,
                                             path_to_pkg=pkgpath)
                    break
                else:
                    display_warning("An error occurred while extracting %s: %s"
                                    % (toc_entry, err))

        if len(infoarray) == 0:
            display_warning('No valid Distribution or PackageInfo found.')
    else:
        display_warning(err)

    # change back to original working dir
    os.chdir(cwd)
    shutil.rmtree(pkgtmp)
    return infoarray


def getBomList(pkgpath):
    '''Gets bom listing from pkgpath, which should be a path
    to a bundle-style package'''
    bompath = None
    for item in listdir(os.path.join(pkgpath, 'Contents')):
        if item.endswith('.bom'):
            bompath = os.path.join(pkgpath, 'Contents', item)
            break
    if not bompath:
        for item in listdir(os.path.join(pkgpath, 'Contents', 'Resources')):
            if item.endswith('.bom'):
                bompath = os.path.join(pkgpath, 'Contents', 'Resources', item)
                break
    if bompath:
        proc = subprocess.Popen(['/usr/bin/lsbom', '-s', bompath],
                                shell=False, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        (output, dummy_err) = proc.communicate()
        if proc.returncode == 0:
            return output.splitlines()
    return []


def getOnePackageInfo(pkgpath):
    """Gets receipt info for a single bundle-style package"""
    pkginfo = {}
    plistpath = os.path.join(pkgpath, 'Contents', 'Info.plist')
    if os.path.exists(plistpath):
        pkginfo['filename'] = os.path.basename(pkgpath)
        try:
            plist = FoundationPlist.readPlist(plistpath)
            if 'CFBundleIdentifier' in plist:
                pkginfo['packageid'] = plist['CFBundleIdentifier']
            elif 'Bundle identifier' in plist:
                # special case for JAMF Composer generated packages.
                pkginfo['packageid'] = plist['Bundle identifier']
            else:
                pkginfo['packageid'] = os.path.basename(pkgpath)

            if 'CFBundleName' in plist:
                pkginfo['name'] = plist['CFBundleName']

            if 'IFPkgFlagInstalledSize' in plist:
                pkginfo['installed_size'] = plist['IFPkgFlagInstalledSize']

            pkginfo['version'] = getBundleVersion(pkgpath)
        except (AttributeError,
                FoundationPlist.NSPropertyListSerializationException):
            pkginfo['packageid'] = 'BAD PLIST in %s' % \
                                    os.path.basename(pkgpath)
            pkginfo['version'] = '0.0'
        ## now look for applications to suggest for blocking_applications
        #bomlist = getBomList(pkgpath)
        #if bomlist:
        #    pkginfo['apps'] = [os.path.basename(item) for item in bomlist
        #                        if item.endswith('.app')]

    else:
        # look for old-style .info files!
        infopath = os.path.join(
            pkgpath, 'Contents', 'Resources', 'English.lproj')
        if os.path.exists(infopath):
            for item in listdir(infopath):
                if os.path.join(infopath, item).endswith('.info'):
                    pkginfo['filename'] = os.path.basename(pkgpath)
                    pkginfo['packageid'] = os.path.basename(pkgpath)
                    infofile = os.path.join(infopath, item)
                    fileobj = open(infofile, mode='r')
                    info = fileobj.read()
                    fileobj.close()
                    infolines = info.splitlines()
                    pkginfo['version'] = '0.0'
                    pkginfo['name'] = 'UNKNOWN'
                    for line in infolines:
                        parts = line.split(None, 1)
                        if len(parts) == 2:
                            label = parts[0]
                            if label == 'Version':
                                pkginfo['version'] = parts[1]
                            if label == 'Title':
                                pkginfo['name'] = parts[1]
                    break
    return pkginfo


def getBundlePackageInfo(pkgpath):
    """Get metadata from a bundle-style package"""
    infoarray = []

    if pkgpath.endswith('.pkg'):
        pkginfo = getOnePackageInfo(pkgpath)
        if pkginfo:
            infoarray.append(pkginfo)
            return infoarray

    bundlecontents = os.path.join(pkgpath, 'Contents')
    if os.path.exists(bundlecontents):
        for item in listdir(bundlecontents):
            if item.endswith('.dist'):
                filename = os.path.join(bundlecontents, item)
                # return info using the distribution file
                return parsePkgRefs(filename, path_to_pkg=bundlecontents)

        # no .dist file found, look for packages in subdirs
        dirsToSearch = []
        plistpath = os.path.join(pkgpath, 'Contents', 'Info.plist')
        if os.path.exists(plistpath):
            plist = FoundationPlist.readPlist(plistpath)
            if 'IFPkgFlagComponentDirectory' in plist:
                componentdir = plist['IFPkgFlagComponentDirectory']
                dirsToSearch.append(componentdir)

        if dirsToSearch == []:
            dirsToSearch = ['', 'Contents', 'Contents/Installers',
                            'Contents/Packages', 'Contents/Resources',
                            'Contents/Resources/Packages']
        for subdir in dirsToSearch:
            searchdir = os.path.join(pkgpath, subdir)
            if os.path.exists(searchdir):
                for item in listdir(searchdir):
                    itempath = os.path.join(searchdir, item)
                    if os.path.isdir(itempath):
                        if itempath.endswith('.pkg'):
                            pkginfo = getOnePackageInfo(itempath)
                            if pkginfo:
                                infoarray.append(pkginfo)
                        elif itempath.endswith('.mpkg'):
                            pkginfo = getBundlePackageInfo(itempath)
                            if pkginfo:
                                infoarray.extend(pkginfo)

    return infoarray


def getReceiptInfo(pkgname):
    """Get receipt info from a package"""
    info = []
    if hasValidPackageExt(pkgname):
        display_debug2('Examining %s' % pkgname)
        if os.path.isfile(pkgname):       # new flat package
            info = getFlatPackageInfo(pkgname)

        if os.path.isdir(pkgname):        # bundle-style package?
            info = getBundlePackageInfo(pkgname)

    elif pkgname.endswith('.dist'):
        info = parsePkgRefs(pkgname)

    return info


def getInstalledPackageVersion(pkgid):
    """
    Checks a package id against the receipts to
    determine if a package is already installed.
    Returns the version string of the installed pkg
    if it exists, or an empty string if it does not
    """

    # First check (Leopard and later) package database
    proc = subprocess.Popen(['/usr/sbin/pkgutil',
                             '--pkg-info-plist', pkgid],
                            bufsize=1,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    (out, dummy_err) = proc.communicate()

    if out:
        try:
            plist = FoundationPlist.readPlistFromString(out)
        except FoundationPlist.NSPropertyListSerializationException:
            pass
        else:
            foundbundleid = plist.get('pkgid')
            foundvers = plist.get('pkg-version', '0.0.0.0.0')
            if pkgid == foundbundleid:
                display_debug2('\tThis machine has %s, version %s',
                               pkgid, foundvers)
                return foundvers

    # If we got to this point, we haven't found the pkgid yet.
    # Check /Library/Receipts
    receiptsdir = '/Library/Receipts'
    if os.path.exists(receiptsdir):
        installitems = listdir(receiptsdir)
        highestversion = '0'
        for item in installitems:
            if item.endswith('.pkg'):
                info = getBundlePackageInfo(os.path.join(receiptsdir, item))
                if len(info):
                    infoitem = info[0]
                    foundbundleid = infoitem['packageid']
                    foundvers = infoitem['version']
                    if pkgid == foundbundleid:
                        if (MunkiLooseVersion(foundvers) >
                                MunkiLooseVersion(highestversion)):
                            highestversion = foundvers

        if highestversion != '0':
            display_debug2('\tThis machine has %s, version %s',
                           pkgid, highestversion)
            return highestversion


    # This package does not appear to be currently installed
    display_debug2('\tThis machine does not have %s' % pkgid)
    return ""


def nameAndVersion(aString):
    """
    Splits a string into the name and version numbers:
    'TextWrangler2.3b1' becomes ('TextWrangler', '2.3b1')
    'AdobePhotoshopCS3-11.2.1' becomes ('AdobePhotoshopCS3', '11.2.1')
    'MicrosoftOffice2008v12.2.1' becomes ('MicrosoftOffice2008', '12.2.1')
    """
    # first try regex
    m = re.search(r'[0-9]+(\.[0-9]+)((\.|a|b|d|v)[0-9]+)+', aString)
    if m:
        vers = m.group(0)
        name = aString[0:aString.find(vers)].rstrip(' .-_v')
        return (name, vers)

    # try another way
    index = 0
    for char in aString[::-1]:
        if char in '0123456789._':
            index -= 1
        elif char in 'abdv':
            partialVersion = aString[index:]
            if set(partialVersion).intersection(set('abdv')):
                # only one of 'abdv' allowed in the version
                break
            else:
                index -= 1
        else:
            break

    if index < 0:
        possibleVersion = aString[index:]
        # now check from the front of the possible version until we
        # reach a digit (because we might have characters in '._abdv'
        # at the start)
        for char in possibleVersion:
            if not char in '0123456789':
                index += 1
            else:
                break
        vers = aString[index:]
        return (aString[0:index].rstrip(' .-_v'), vers)
    else:
        # no version number found,
        # just return original string and empty string
        return (aString, '')


def hasValidConfigProfileExt(path):
    """Verifies a path ends in '.mobileconfig'"""
    ext = os.path.splitext(path)[1]
    return ext.lower() == '.mobileconfig'


def hasValidPackageExt(path):
    """Verifies a path ends in '.pkg' or '.mpkg'"""
    ext = os.path.splitext(path)[1]
    return ext.lower() in ['.pkg', '.mpkg']


def hasValidDiskImageExt(path):
    """Verifies a path ends in '.dmg' or '.iso'"""
    ext = os.path.splitext(path)[1]
    return ext.lower() in ['.dmg', '.iso']


def hasValidInstallerItemExt(path):
    """Verifies we have an installer item"""
    return (hasValidPackageExt(path) or hasValidDiskImageExt(path)
            or hasValidConfigProfileExt(path))


def getChoiceChangesXML(pkgitem):
    """Queries package for 'ChoiceChangesXML'"""
    choices = []
    try:
        proc = subprocess.Popen(
            ['/usr/sbin/installer', '-showChoiceChangesXML', '-pkg', pkgitem],
            bufsize=1, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        (out, dummy_err) = proc.communicate()
        if out:
            plist = FoundationPlist.readPlistFromString(out)

            # list comprehension to populate choices with those items
            # whose 'choiceAttribute' value is 'selected'
            choices = [item for item in plist
                       if 'selected' in item['choiceAttribute']]
    except BaseException:
        # No choices found or something went wrong
        pass
    return choices


def getPackageMetaData(pkgitem):
    """
    Queries an installer item (.pkg, .mpkg, .dist)
    and gets metadata. There are a lot of valid Apple package formats
    and this function may not deal with them all equally well.
    Standard bundle packages are probably the best understood and documented,
    so this code deals with those pretty well.

    metadata items include:
    installer_item_size:  size of the installer item (.dmg, .pkg, etc)
    installed_size: size of items that will be installed
    RestartAction: will a restart be needed after installation?
    name
    version
    description
    receipts: an array of packageids that may be installed
              (some may not be installed on some machines)
    """

    if not hasValidInstallerItemExt(pkgitem):
        return {}

    # first get the data /usr/sbin/installer will give us
    installerinfo = getInstallerPkgInfo(pkgitem)
    # now look for receipt/subpkg info
    receiptinfo = getReceiptInfo(pkgitem)

    name = os.path.split(pkgitem)[1]
    shortname = os.path.splitext(name)[0]
    metaversion = getBundleVersion(pkgitem)
    if metaversion == '0.0.0.0.0':
        metaversion = nameAndVersion(shortname)[1]

    highestpkgversion = '0.0'
    installedsize = 0
    for infoitem in receiptinfo:
        if (MunkiLooseVersion(infoitem['version']) >
                MunkiLooseVersion(highestpkgversion)):
            highestpkgversion = infoitem['version']
        if 'installed_size' in infoitem:
            # note this is in KBytes
            installedsize += infoitem['installed_size']

    if metaversion == '0.0.0.0.0':
        metaversion = highestpkgversion
    elif len(receiptinfo) == 1:
        # there is only one package in this item
        metaversion = highestpkgversion
    elif highestpkgversion.startswith(metaversion):
        # for example, highestpkgversion is 2.0.3124.0,
        # version in filename is 2.0
        metaversion = highestpkgversion

    cataloginfo = {}
    cataloginfo['name'] = nameAndVersion(shortname)[0]
    cataloginfo['version'] = metaversion
    for key in ('display_name', 'RestartAction', 'description'):
        if key in installerinfo:
            cataloginfo[key] = installerinfo[key]

    if 'installed_size' in installerinfo:
        if installerinfo['installed_size'] > 0:
            cataloginfo['installed_size'] = installerinfo['installed_size']
    elif installedsize:
        cataloginfo['installed_size'] = installedsize

    cataloginfo['receipts'] = receiptinfo

    if os.path.isfile(pkgitem) and not pkgitem.endswith('.dist'):
        # flat packages require 10.5.0+
        cataloginfo['minimum_os_version'] = "10.5.0"

    return cataloginfo


def _unsigned(i):
    """Translate a signed int into an unsigned int.  Int type returned
    is longer than the original since Python has no unsigned int."""
    return i & 0xFFFFFFFF


def _asciizToStr(s):
    """Transform a null-terminated string of any length into a Python str.
    Returns a normal Python str that has been terminated.
    """
    i = s.find('\0')
    if i > -1:
        s = s[0:i]
    return s


def _fFlagsToSet(f_flags):
    """Transform an int f_flags parameter into a set of mount options.
    Returns a set.
    """
    # see /usr/include/sys/mount.h for the bitmask constants.
    flags = set()
    if f_flags & 0x1:
        flags.add('read-only')
    if f_flags & 0x1000:
        flags.add('local')
    if f_flags & 0x4000:
        flags.add('rootfs')
    if f_flags & 0x4000000:
        flags.add('automounted')
    return flags


def getFilesystems():
    """Get a list of all mounted filesystems on this system.

    Return value is dict, e.g. {
        int st_dev: {
            'f_fstypename': 'nfs',
            'f_mntonname': '/mountedpath',
            'f_mntfromname': 'homenfs:/path',
        },
    }

    Note: st_dev values are static for potentially only one boot, but
    static for multiple mount instances.
    """
    MNT_NOWAIT = 2

    libc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("c"))
    # see man GETFSSTAT(2) for struct
    statfs_32_struct = '=hh ll ll ll lQ lh hl 2l 15s 90s 90s x 16x'
    statfs_64_struct = '=Ll QQ QQ Q ll l LLL 16s 1024s 1024s 32x'
    os_version = getOsVersion(as_tuple=True)
    if os_version <= (10, 5):
        mode = 32
    else:
        mode = 64

    if mode == 64:
        statfs_struct = statfs_64_struct
    else:
        statfs_struct = statfs_32_struct

    sizeof_statfs_struct = struct.calcsize(statfs_struct)
    bufsize = 30 * sizeof_statfs_struct  # only supports 30 mounted fs
    buf = ctypes.create_string_buffer(bufsize)

    if mode == 64:
        # some 10.6 boxes return 64-bit structures on getfsstat(), some do not.
        # forcefully call the 64-bit version in cases where we think
        # a 64-bit struct will be returned.
        n = libc.getfsstat64(ctypes.byref(buf), bufsize, MNT_NOWAIT)
    else:
        n = libc.getfsstat(ctypes.byref(buf), bufsize, MNT_NOWAIT)

    if n < 0:
        display_debug1('getfsstat() returned errno %d' % n)
        return {}

    ofs = 0
    output = {}
    for i in xrange(0, n):
        if mode == 64:
            (f_bsize, f_iosize, f_blocks, f_bfree, f_bavail, f_files,
             f_ffree, f_fsid_0, f_fsid_1, f_owner, f_type, f_flags,
             f_fssubtype,
             f_fstypename, f_mntonname, f_mntfromname) = struct.unpack(
                 statfs_struct, str(buf[ofs:ofs+sizeof_statfs_struct]))
        elif mode == 32:
            (f_otype, f_oflags, f_bsize, f_iosize, f_blocks, f_bfree, f_bavail,
             f_files, f_ffree, f_fsid, f_owner, f_reserved1, f_type, f_flags,
             f_reserved2_0, f_reserved2_1, f_fstypename, f_mntonname,
             f_mntfromname) = struct.unpack(
                 statfs_struct, str(buf[ofs:ofs+sizeof_statfs_struct]))

        try:
            st = os.stat(_asciizToStr(f_mntonname))
            output[st.st_dev] = {
                'f_flags_set': _fFlagsToSet(f_flags),
                'f_fstypename': _asciizToStr(f_fstypename),
                'f_mntonname': _asciizToStr(f_mntonname),
                'f_mntfromname': _asciizToStr(f_mntfromname),
            }
        except OSError:
            pass

        ofs += sizeof_statfs_struct

    return output


FILESYSTEMS = {}
def isExcludedFilesystem(path, _retry=False):
    """Gets filesystem information for a path and determine if it should be
    excluded from application searches.

    Returns True if path is located on NFS, is read only, or
    is not marked local.
    Returns False if none of these conditions are true.
    Returns None if it cannot be determined.
    """
    global FILESYSTEMS

    if not path:
        return None

    path_components = path.split('/')
    if len(path_components) > 1:
        if path_components[1] in APP_DISCOVERY_EXCLUSION_DIRS:
            return True

    if not FILESYSTEMS or _retry:
        FILESYSTEMS = getFilesystems()

    try:
        st = os.stat(path)
    except OSError:
        st = None

    if st is None or st.st_dev not in FILESYSTEMS:
        if not _retry:
            # perhaps the stat() on the path caused autofs to mount
            # the required filesystem and now it will be available.
            # try one more time to look for it after flushing the cache.
            display_debug1('Trying isExcludedFilesystem again for %s' % path)
            return isExcludedFilesystem(path, True)
        else:
            display_debug1('Could not match path %s to a filesystem' % path)
            return None

    exc_flags = ('read-only' in FILESYSTEMS[st.st_dev]['f_flags_set'] or
                 'local' not in FILESYSTEMS[st.st_dev]['f_flags_set'])
    is_nfs = FILESYSTEMS[st.st_dev]['f_fstypename'] == 'nfs'

    if is_nfs or exc_flags:
        display_debug1(
            'Excluding %s (flags %s, nfs %s)' % (path, exc_flags, is_nfs))

    return is_nfs or exc_flags


def findAppsInDirs(dirlist):
    """Do spotlight search for type applications within the
    list of directories provided. Returns a list of paths to applications
    these appear to always be some form of unicode string.
    """
    applist = []
    query = NSMetadataQuery.alloc().init()
    query.setPredicate_(
        NSPredicate.predicateWithFormat_('(kMDItemKind = "Application")'))
    query.setSearchScopes_(dirlist)
    query.startQuery()
    # Spotlight isGathering phase - this is the initial search. After the
    # isGathering phase Spotlight keeps running returning live results from
    # filesystem changes, we are not interested in that phase.
    # Run for 0.3 seconds then check if isGathering has completed.
    runtime = 0
    maxruntime = 20
    while query.isGathering() and runtime <= maxruntime:
        runtime += 0.3
        NSRunLoop.currentRunLoop(
            ).runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.3))
    query.stopQuery()

    if runtime >= maxruntime:
        display_warning(
            'Spotlight search for applications terminated due to excessive '
            'time. Possible causes: Spotlight indexing is turned off for a '
            'volume; Spotlight is reindexing a volume.')

    for item in query.results():
        p = item.valueForAttribute_('kMDItemPath')
        if p and not isExcludedFilesystem(p):
            applist.append(p)

    return applist


def getSpotlightInstalledApplications():
    """Get paths of currently installed applications per Spotlight.
    Return value is list of paths.
    Excludes most non-boot volumes.
    In future may include local r/w volumes.
    """
    dirlist = []
    applist = []

    for f in listdir(u'/'):
        p = os.path.join(u'/', f)
        if os.path.isdir(p) and not os.path.islink(p) \
                            and not isExcludedFilesystem(p):
            if f.endswith('.app'):
                applist.append(p)
            else:
                dirlist.append(p)

    # Future code changes may mean we wish to look for Applications
    # installed on any r/w local volume.
    #for f in listdir(u'/Volumes'):
    #    p = os.path.join(u'/Volumes', f)
    #    if os.path.isdir(p) and not os.path.islink(p) \
    #                        and not isExcludedFilesystem(p):
    #        dirlist.append(p)

    # /Users is not currently excluded, so no need to add /Users/Shared.
    #dirlist.append(u'/Users/Shared')

    applist.extend(findAppsInDirs(dirlist))
    return applist


def getLSInstalledApplications():
    """Get paths of currently installed applications per LaunchServices.
    Return value is list of paths.
    Ignores apps installed on other volumes
    """
    # PyLint cannot properly find names inside Cocoa libraries, so issues bogus
    # "Module 'Foo' has no 'Bar' member" warnings. Disable them.
    # pylint: disable=E1101
    # we access a "protected" function from LaunchServices
    # pylint: disable=W0212

    apps = LaunchServices._LSCopyAllApplicationURLs(None)
    applist = []
    for app in apps:
        app_path = app.path()
        if (app_path and not isExcludedFilesystem(app_path) and
                os.path.exists(app_path)):
            applist.append(app_path)

    return applist


# we save SP_APPCACHE in a global to avoid querying system_profiler more than
# once per session for application data, which can be slow
SP_APPCACHE = None
def getSPApplicationData():
    '''Uses system profiler to get application info for this machine'''
    global SP_APPCACHE
    if SP_APPCACHE is None:
        cmd = ['/usr/sbin/system_profiler', 'SPApplicationsDataType', '-xml']
        proc = Popen(cmd, shell=False, bufsize=-1,
                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE)
        try:
            output, dummy_error = proc.communicate(timeout=60)
        except TimeoutError:
            display_error(
                'system_profiler hung; skipping SPApplicationsDataType query')
            # return empty dict
            SP_APPCACHE = {}
            return SP_APPCACHE
        try:
            plist = FoundationPlist.readPlistFromString(output)
            # system_profiler xml is an array
            SP_APPCACHE = {}
            for item in plist[0]['_items']:
                SP_APPCACHE[item.get('path')] = item
        except BaseException:
            SP_APPCACHE = {}
    return SP_APPCACHE


# we save APPDATA in a global to avoid querying LaunchServices more than
# once per session
APPDATA = None
def getAppData():
    """Gets info on currently installed apps.
    Returns a list of dicts containing path, name, version and bundleid"""
    global APPDATA
    if APPDATA is None:
        APPDATA = []
        display_debug1('Getting info on currently installed applications...')
        applist = set(getLSInstalledApplications())
        applist.update(getSpotlightInstalledApplications())
        for pathname in applist:
            iteminfo = {}
            iteminfo['name'] = os.path.splitext(os.path.basename(pathname))[0]
            iteminfo['path'] = pathname
            plistpath = os.path.join(pathname, 'Contents', 'Info.plist')
            if os.path.exists(plistpath):
                try:
                    plist = FoundationPlist.readPlist(plistpath)
                    iteminfo['bundleid'] = plist.get('CFBundleIdentifier', '')
                    if 'CFBundleName' in plist:
                        iteminfo['name'] = plist['CFBundleName']
                    iteminfo['version'] = getBundleVersion(pathname)
                    APPDATA.append(iteminfo)
                except BaseException:
                    pass
            else:
                # possibly a non-bundle app. Use system_profiler data
                # to get app name and version
                sp_app_data = getSPApplicationData()
                if pathname in sp_app_data:
                    item = sp_app_data[pathname]
                    iteminfo['bundleid'] = ''
                    iteminfo['version'] = item.get('version') or '0.0.0.0.0'
                    if item.get('_name'):
                        iteminfo['name'] = item['_name']
                    APPDATA.append(iteminfo)
    return APPDATA


def getRunningProcesses():
    """Returns a list of paths of running processes"""
    proc = subprocess.Popen(['/bin/ps', '-axo' 'comm='],
                            shell=False, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    (output, dummy_err) = proc.communicate()
    if proc.returncode == 0:
        proc_list = [item for item in output.splitlines()
                     if item.startswith('/')]
        LaunchCFMApp = ('/System/Library/Frameworks/Carbon.framework'
                        '/Versions/A/Support/LaunchCFMApp')
        if LaunchCFMApp in proc_list:
            # we have a really old Carbon app
            proc = subprocess.Popen(['/bin/ps', '-axwwwo' 'args='],
                                    shell=False, stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)
            (output, dummy_err) = proc.communicate()
            if proc.returncode == 0:
                carbon_apps = [item[len(LaunchCFMApp)+1:]
                               for item in output.splitlines()
                               if item.startswith(LaunchCFMApp)]
                if carbon_apps:
                    proc_list.extend(carbon_apps)
        return proc_list
    else:
        return []


# some utility functions

def get_hardware_info():
    '''Uses system profiler to get hardware info for this machine'''
    cmd = ['/usr/sbin/system_profiler', 'SPHardwareDataType', '-xml']
    proc = subprocess.Popen(cmd, shell=False, bufsize=-1,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (output, dummy_error) = proc.communicate()
    try:
        plist = FoundationPlist.readPlistFromString(output)
        # system_profiler xml is an array
        sp_dict = plist[0]
        items = sp_dict['_items']
        sp_hardware_dict = items[0]
        return sp_hardware_dict
    except BaseException:
        return {}


def get_ipv4_addresses():
    '''Uses system profiler to get active IPv4 addresses for this machine'''
    ip_addresses = []
    cmd = ['/usr/sbin/system_profiler', 'SPNetworkDataType', '-xml']
    proc = subprocess.Popen(cmd, shell=False, bufsize=-1,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (output, dummy_error) = proc.communicate()
    try:
        plist = FoundationPlist.readPlistFromString(output)
        # system_profiler xml is an array of length 1
        sp_dict = plist[0]
        items = sp_dict['_items']
    except BaseException:
        # something is wrong with system_profiler output
        # so bail
        return ip_addresses

    for item in items:
        try:
            ip_addresses.extend(item['IPv4']['Addresses'])
        except KeyError:
            # 'IPv4" or 'Addresses' is empty, so we ignore
            # this item
            pass
    return ip_addresses

def getIntel64Support():
    """Does this machine support 64-bit Intel instruction set?"""
    libc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("c"))

    size = ctypes.c_size_t()
    buf = ctypes.c_int()
    size.value = ctypes.sizeof(buf)

    libc.sysctlbyname(
        "hw.optional.x86_64", ctypes.byref(buf), ctypes.byref(size), None, 0)

    if buf.value == 1:
        return True
    else:
        return False

MACHINE = {}
def getMachineFacts():
    """Gets some facts about this machine we use to determine if a given
    installer is applicable to this OS or hardware"""
    if not MACHINE:
        MACHINE['hostname'] = os.uname()[1]
        MACHINE['arch'] = os.uname()[4]
        MACHINE['os_vers'] = getOsVersion(only_major_minor=False)
        hardware_info = get_hardware_info()
        MACHINE['machine_model'] = hardware_info.get('machine_model', 'UNKNOWN')
        MACHINE['munki_version'] = get_version()
        MACHINE['ipv4_address'] = get_ipv4_addresses()
        MACHINE['serial_number'] = hardware_info.get('serial_number', 'UNKNOWN')

        if MACHINE['arch'] == 'x86_64':
            MACHINE['x86_64_capable'] = True
        elif MACHINE['arch'] == 'i386':
            MACHINE['x86_64_capable'] = getIntel64Support()
    return MACHINE


CONDITIONS = {}
def getConditions():
    """Fetches key/value pairs from condition scripts
    which can be placed into /usr/local/munki/conditions"""
    global CONDITIONS
    if not CONDITIONS:
        # define path to conditions directory which would contain
        # admin created scripts
        scriptdir = os.path.realpath(os.path.dirname(sys.argv[0]))
        conditionalscriptdir = os.path.join(scriptdir, "conditions")
        # define path to ConditionalItems.plist
        conditionalitemspath = os.path.join(
            pref('ManagedInstallDir'), 'ConditionalItems.plist')
        try:
            # delete CondtionalItems.plist so that we're starting fresh
            os.unlink(conditionalitemspath)
        except (OSError, IOError):
            pass
        if os.path.exists(conditionalscriptdir):
            from munkilib import utils
            for conditionalscript in listdir(conditionalscriptdir):
                if conditionalscript.startswith('.'):
                    # skip files that start with a period
                    continue
                conditionalscriptpath = os.path.join(
                    conditionalscriptdir, conditionalscript)
                if os.path.isdir(conditionalscriptpath):
                    # skip directories in conditions directory
                    continue
                try:
                    # attempt to execute condition script
                    dummy_result, dummy_stdout, dummy_stderr = (
                        utils.runExternalScript(conditionalscriptpath))
                except utils.ScriptNotFoundError:
                    pass  # script is not required, so pass
                except utils.RunExternalScriptError, err:
                    print >> sys.stderr, str(err)
        else:
            # /usr/local/munki/conditions does not exist
            pass
        if (os.path.exists(conditionalitemspath) and
                validPlist(conditionalitemspath)):
            # import conditions into CONDITIONS dict
            CONDITIONS = FoundationPlist.readPlist(conditionalitemspath)
            os.unlink(conditionalitemspath)
        else:
            # either ConditionalItems.plist does not exist
            # or does not pass validation
            CONDITIONS = {}
    return CONDITIONS


def isAppRunning(appname):
    """Tries to determine if the application in appname is currently
    running"""
    display_detail('Checking if %s is running...' % appname)
    proc_list = getRunningProcesses()
    matching_items = []
    if appname.startswith('/'):
        # search by exact path
        matching_items = [item for item in proc_list
                          if item == appname]
    elif appname.endswith('.app'):
        # search by filename
        matching_items = [item for item in proc_list
                          if '/'+ appname + '/Contents/MacOS/' in item]
    else:
        # check executable name
        matching_items = [item for item in proc_list
                          if item.endswith('/' + appname)]
    if not matching_items:
        # try adding '.app' to the name and check again
        matching_items = [item for item in proc_list
                          if '/'+ appname + '.app/Contents/MacOS/' in item]

    if matching_items:
        # it's running!
        display_debug1('Matching process list: %s' % matching_items)
        display_detail('%s is running!' % appname)
        return True

    # if we get here, we have no evidence that appname is running
    return False


def getAvailableDiskSpace(volumepath='/'):
    """Returns available diskspace in KBytes.

    Args:
      volumepath: str, optional, default '/'
    Returns:
      int, KBytes in free space available
    """
    if volumepath is None:
        volumepath = '/'
    try:
        st = os.statvfs(volumepath)
    except OSError, e:
        display_error(
            'Error getting disk space in %s: %s', volumepath, str(e))
        return 0

    return int(st.f_frsize * st.f_bavail / 1024) # f_bavail matches df(1) output


def tmpdir():
    '''Returns a temporary directory for this session'''
    global _TMPDIR
    if not _TMPDIR:
        _TMPDIR = tempfile.mkdtemp(prefix='munki-', dir='/tmp')
    return _TMPDIR


def cleanUpTmpDir():
    """Cleans up our temporary directory."""
    global _TMPDIR
    if _TMPDIR:
        try:
            shutil.rmtree(_TMPDIR)
        except (OSError, IOError), err:
            display_warning(
                'Unable to clean up temporary dir %s: %s', _TMPDIR, str(err))
        _TMPDIR = None


def listdir(path):
    """OS X HFS+ string encoding safe listdir().

    Args:
        path: path to list contents of
    Returns:
        list of contents, items as str or unicode types
    """
    # if os.listdir() is supplied a unicode object for the path,
    # it will return unicode filenames instead of their raw fs-dependent
    # version, which is decomposed utf-8 on OS X.
    #
    # we use this to our advantage here and have Python do the decoding
    # work for us, instead of decoding each item in the output list.
    #
    # references:
    # https://docs.python.org/howto/unicode.html#unicode-filenames
    # https://developer.apple.com/library/mac/#qa/qa2001/qa1235.html
    # http://lists.zerezo.com/git/msg643117.html
    # http://unicode.org/reports/tr15/    section 1.2
    if type(path) is str:
        path = unicode(path, 'utf-8')
    elif type(path) is not unicode:
        path = unicode(path)
    return os.listdir(path)


def findProcesses(user=None, exe=None):
    """Find processes in process list.

    Args:
        user: str, optional, username owning process
        exe: str, optional, executable name of process
    Returns:
        dictionary of pids = {
                pid: {
                        'user': str, username owning process,
                        'exe': str, string executable of process,
                }
        }

        list of pids, or {} if none
    """
    argv = ['/bin/ps', '-x', '-w', '-w', '-a', '-o', 'pid=,user=,comm=']
    p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (stdout, dummy_stderr) = p.communicate()

    pids = {}

    if not stdout or p.returncode != 0:
        return pids

    try:
        lines = stdout.splitlines()
        for proc in lines:
            (p_pid, p_user, p_comm) = proc.split(None, 2)

            if exe is not None:
                if not p_comm.startswith(exe):
                    continue
            if user is not None:
                if p_user != user:
                    continue
            pids[int(p_pid)] = {
                'user': p_user,
                'exe': p_comm,
            }

    except (ValueError, TypeError, IndexError):
        return pids

    return pids


# utility functions for running scripts from pkginfo files
# used by updatecheck.py and installer.py

def writefile(stringdata, path):
    '''Writes string data to path.
    Returns the path on success, empty string on failure.'''
    try:
        fileobject = open(path, mode='w', buffering=1)
        # write line-by-line to ensure proper UNIX line-endings
        for line in stringdata.splitlines():
            print >> fileobject, line.encode('UTF-8')
        fileobject.close()
        return path
    except (OSError, IOError):
        display_error("Couldn't write %s" % stringdata)
        return ""


def runEmbeddedScript(scriptname, pkginfo_item, suppress_error=False):
    '''Runs a script embedded in the pkginfo.
    Returns the result code.'''

    # get the script text from the pkginfo
    script_text = pkginfo_item.get(scriptname)
    itemname = pkginfo_item.get('name')
    if not script_text:
        display_error(
            'Missing script %s for %s' % (scriptname, itemname))
        return -1

    # write the script to a temp file
    scriptpath = os.path.join(tmpdir(), scriptname)
    if writefile(script_text, scriptpath):
        cmd = ['/bin/chmod', '-R', 'o+x', scriptpath]
        retcode = subprocess.call(cmd)
        if retcode:
            display_error(
                'Error setting script mode in %s for %s'
                % (scriptname, itemname))
            return -1
    else:
        display_error(
            'Cannot write script %s for %s' % (scriptname, itemname))
        return -1

    # now run the script
    return runScript(
        itemname, scriptpath, scriptname, suppress_error=suppress_error)


def runScript(itemname, path, scriptname, suppress_error=False):
    '''Runs a script, Returns return code.'''
    if suppress_error:
        display_detail(
            'Running %s for %s ' % (scriptname, itemname))
    else:
        display_status_minor(
            'Running %s for %s ' % (scriptname, itemname))
    if munkistatusoutput:
        # set indeterminate progress bar
        munkistatus.percent(-1)

    scriptoutput = []
    try:
        proc = subprocess.Popen(path, shell=False, bufsize=1,
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT)
    except OSError, e:
        display_error(
            'Error executing script %s: %s' % (scriptname, str(e)))
        return -1

    while True:
        msg = proc.stdout.readline().decode('UTF-8')
        if not msg and (proc.poll() != None):
            break
        # save all script output in case there is
        # an error so we can dump it to the log
        scriptoutput.append(msg)
        msg = msg.rstrip("\n")
        display_info(msg)

    retcode = proc.poll()
    if retcode and not suppress_error:
        display_error(
            'Running %s for %s failed.' % (scriptname, itemname))
        display_error("-"*78)
        for line in scriptoutput:
            display_error("\t%s" % line.rstrip("\n"))
        display_error("-"*78)
    elif not suppress_error:
        log('Running %s for %s was successful.' % (scriptname, itemname))

    if munkistatusoutput:
        # clear indeterminate progress bar
        munkistatus.percent(0)

    return retcode


def forceLogoutNow():
    """Force the logout of interactive GUI users and spawn MSU."""
    try:
        procs = findProcesses(exe=LOGINWINDOW)
        users = {}
        for pid in procs:
            users[procs[pid]['user']] = pid

        if 'root' in users:
            del users['root']

        # force MSU GUI to raise
        f = open('/private/tmp/com.googlecode.munki.installatlogout', 'w')
        f.close()

        # kill loginwindows to cause logout of current users, whether
        # active or switched away via fast user switching.
        for user in users:
            try:
                os.kill(users[user], signal.SIGKILL)
            except OSError:
                pass

    except BaseException, err:
        display_error('Exception in forceLogoutNow(): %s' % str(err))


def blockingApplicationsRunning(pkginfoitem):
    """Returns true if any application in the blocking_applications list
    is running or, if there is no blocking_applications list, if any
    application in the installs list is running."""

    if 'blocking_applications' in pkginfoitem:
        appnames = pkginfoitem['blocking_applications']
    else:
        # if no blocking_applications specified, get appnames
        # from 'installs' list if it exists
        appnames = [os.path.basename(item.get('path'))
                    for item in pkginfoitem.get('installs', [])
                    if item['type'] == 'application']

    display_debug1("Checking for %s" % appnames)
    running_apps = [appname for appname in appnames
                    if isAppRunning(appname)]
    if running_apps:
        display_detail(
            "Blocking apps for %s are running:" % pkginfoitem['name'])
        display_detail("    %s" % running_apps)
        return True
    return False


# module globals
#debug = False
verbose = 1
munkistatusoutput = False
_TMPDIR = None
report = {}

def main():
    """Placeholder"""
    print 'This is a library of support tools for the Munki Suite.'

if __name__ == '__main__':
    main()
