#!/usr/bin/python
# encoding: utf-8
#
# Copyright 2009-2011 Greg Neagle.
#
# Licensed under the Apache License, Version 2.0 (the 'License');
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
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
import platform
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

from Foundation import NSDate, NSMetadataQuery, NSPredicate, NSRunLoop
from Foundation import CFPreferencesCopyAppValue
from Foundation import CFPreferencesSetValue
from Foundation import CFPreferencesAppSynchronize
from Foundation import kCFPreferencesAnyUser
from Foundation import kCFPreferencesCurrentHost

import munkistatus
import FoundationPlist
import LaunchServices


# our preferences "bundle_id"
BUNDLE_ID = 'ManagedInstalls'

# the following two items are not used internally by munki
# any longer, but remain for backwards compatibility with
# pre and postflight script that might access these files directly
MANAGED_INSTALLS_PLIST_PATH = "/Library/Preferences/" + BUNDLE_ID + ".plist"
SECURE_MANAGED_INSTALLS_PLIST_PATH = \
    "/private/var/root/Library/Preferences/" + BUNDLE_ID + ".plist"

ADDITIONAL_HTTP_HEADERS_KEY = 'AdditionalHttpHeaders'


class Error(Exception):
    """Class for domain specific exceptions."""


class PreferencesError(Error):
    """There was an error reading the preferences plist."""


class TimeoutError(Error):
    """Timeout limit exceeded since last I/O."""


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
            (rlist, wlist, xlist) = select.select([f], [], [], 1.0)

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

    def communicate(self, input=None, timeout=0):
        """Communicate, optionally ending after a timeout of no activity.

        Args:
            input: str, to send on stdin
            timeout: int, seconds of inactivity to raise error at
        Returns:
            (str or None, str or None) for stdout, stderr
        Raises:
            TimeoutError, if timeout is reached
        """
        if timeout <= 0:
            return super(Popen, self).communicate(input=input)

        fds = []
        stdout = []
        stderr = []

        if self.stdout is not None:
            set_file_nonblock(self.stdout)
            fds.append(self.stdout)
        if self.stderr is not None:
            set_file_nonblock(self.stderr)
            fds.append(self.stderr)
        if input is not None and sys.stdin is not None:
            sys.stdin.write(input)

        returncode = None

        while returncode is None:
            (rlist, wlist, xlist) = select.select(fds, [], [], 1.0)

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
    """Returns version of munkitools, reading version.plist
    and svnversion"""
    vers = "UNKNOWN"
    build = ""
    # find the munkilib directory, and the version files
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
            except KeyError:
                pass
    svnversionfile = os.path.join(munkilibdir, "svnversion")
    if os.path.exists(svnversionfile):
        try:
            fileobj = open(svnversionfile, mode='r')
            contents = fileobj.read()
            fileobj.close()
            build = contents.splitlines()[0]
        except OSError:
            pass
    if build:
        vers = vers + " Build " + build
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
    elif verbose > 1:
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


def concat_log_message(msg, *args):
    """Concatenates a string with any additional arguments; drops unicode."""
    if args:
        args = [str_to_ascii(arg) for arg in args]
        try:
            msg = msg % tuple(args)
        except TypeError, e:
            warnings.warn(
                'String format does not match concat args: %s' % (
                str(sys.exc_info())))
    return msg


def display_status(msg, *args):
    """
    Displays major status messages, formatting as needed
    for verbose/non-verbose and munkistatus-style output.
    """
    msg = concat_log_message(msg, *args)
    log(msg)
    if munkistatusoutput:
        munkistatus.detail(msg)
    elif verbose > 0:
        if msg.endswith('.') or msg.endswith(u'…'):
            print '%s' % msg.encode('UTF-8')
        else:
            print '%s...' % msg.encode('UTF-8')
        sys.stdout.flush()


def display_info(msg, *args):
    """
    Displays info messages.
    Not displayed in MunkiStatus.
    """
    msg = concat_log_message(msg, *args)
    log(msg)
    if munkistatusoutput:
        pass
    elif verbose > 0:
        print msg.encode('UTF-8')
        sys.stdout.flush()


def display_detail(msg, *args):
    """
    Displays minor info messages, formatting as needed
    for verbose/non-verbose and munkistatus-style output.
    These are usually logged only, but can be printed to
    stdout if verbose is set to 2 or higher
    """
    msg = concat_log_message(msg, *args)
    if munkistatusoutput:
        pass
    elif verbose > 1:
        print msg.encode('UTF-8')
        sys.stdout.flush()
    if pref('LoggingLevel') > 0:
        log(msg)


def display_debug1(msg, *args):
    """
    Displays debug messages, formatting as needed
    for verbose/non-verbose and munkistatus-style output.
    """
    msg = concat_log_message(msg, *args)
    if munkistatusoutput:
        pass
    elif verbose > 2:
        print msg.encode('UTF-8')
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
        print msg.encode('UTF-8')
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


def log(msg, logname=''):
    """Generic logging function"""
    # date/time format string
    formatstr = '%b %d %H:%M:%S'
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
    FoundationPlist.writePlist(report,
        os.path.join(pref('ManagedInstallDir'), 'ManagedInstallReport.plist'))


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
        archivename = 'ManagedInstallReport-' + \
                      time.strftime(formatstr,time.localtime(modtime)) + \
                       '.plist'
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
        (output, unused_err) = proc.communicate()
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
                            display_warning('Could not remove archive item %s'
                                             % itempath)



# misc functions

def validPlist(path):
    """Uses plutil to determine if path contains a valid plist.
    Returns True or False."""
    retcode = subprocess.call(['/usr/bin/plutil', '-lint', '-s' , path])
    if retcode == 0:
        return True
    else:
        return False


def stopRequested():
    """Allows user to cancel operations when
    MunkiStatus is being used"""
    if munkistatusoutput:
        if munkistatus.getStopButtonState() == 1:
            log('### User stopped session ###')
            return True
    return False


def getconsoleuser():
    """Return console user"""
    from SystemConfiguration import SCDynamicStoreCopyConsoleUser
    cfuser = SCDynamicStoreCopyConsoleUser( None, None, None )
    return cfuser[0]


def currentGUIusers():
    """Gets a list of GUI users by parsing the output of /usr/bin/who"""
    gui_users = []
    proc = subprocess.Popen('/usr/bin/who', shell=False,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (output, unused_err) = proc.communicate()
    lines = str(output).splitlines()
    for line in lines:
        if 'console' in line:
            parts = line.split()
            gui_users.append(parts[0])

    return gui_users


def pythonScriptRunning(scriptname):
    """Returns Process ID for a running python script"""
    cmd = ['/bin/ps', '-eo', 'pid=,command=']
    proc = subprocess.Popen(cmd, shell=False, bufsize=1,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out, unused_err) = proc.communicate()
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


# dmg helpers

def mountdmg(dmgpath, use_shadow=False):
    """
    Attempts to mount the dmg at dmgpath
    and returns a list of mountpoints
    If use_shadow is true, mount image with shadow file
    """
    mountpoints = []
    dmgname = os.path.basename(dmgpath)
    cmd = ['/usr/bin/hdiutil', 'attach', dmgpath,
                '-mountRandom', '/tmp', '-nobrowse', '-plist']
    if use_shadow:
        cmd.append('-shadow')
    proc = subprocess.Popen(cmd,
                            bufsize=1, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    (pliststr, err) = proc.communicate()
    if proc.returncode:
        display_error('Error: "%s" while mounting %s.' % (err, dmgname))
    if pliststr:
        plist = FoundationPlist.readPlistFromString(pliststr)
        for entity in plist['system-entities']:
            if 'mount-point' in entity:
                mountpoints.append(entity['mount-point'])

    return mountpoints


def unmountdmg(mountpoint):
    """
    Unmounts the dmg at mountpoint
    """
    proc = subprocess.Popen(['/usr/bin/hdiutil', 'detach', mountpoint],
                                bufsize=1, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
    (unused_output, err) = proc.communicate()
    if proc.returncode:
        display_warning('Polite unmount failed: %s' % err)
        display_info('Attempting to force unmount %s' % mountpoint)
        # try forcing the unmount
        retcode = subprocess.call(['/usr/bin/hdiutil', 'detach', mountpoint,
                                '-force'])
        if retcode:
            display_warning('Failed to unmount %s' % mountpoint)


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
            bundleexecutable = plist.get('CFBundleExecutable',
                                      os.path.basename(pathname))
            bundleexecutablepath = os.path.join(pathname, 'Contents',
                                                'MacOS', bundleexecutable)
            if os.path.exists(bundleexecutablepath):
                return True
    return False


#####################################################
# managed installs preferences/metadata
#####################################################

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
    except Exception:
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
        'InstallAppleSoftwareUpdates': False,
        'AppleSoftwareUpdatesOnly': False,
        'SoftwareUpdateServerURL': '',
        'DaysBetweenNotifications': 1,
        'LastNotifiedDate': NSDate.dateWithTimeIntervalSince1970_(0),
        'UseClientCertificate': False,
        'SuppressUserNotification': False,
        'SuppressAutoInstall': False,
        'SuppressStopButtonOnInstall': False,
        'PackageVerificationMode': 'hash'
    }
    pref_value = CFPreferencesCopyAppValue(pref_name, BUNDLE_ID)
    if pref_value == None:
        pref_value = default_prefs.get(pref_name)
        # we're using a default value. We'll write it out to
        # /Library/Preferences/<BUNDLE_ID>.plist for admin
        # discoverability
        set_pref(pref_name, pref_value)
    if type(pref_value).__name__ in ['__NSCFDate', '__NSDate', '__CFDate']:
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
    (out, unused_err) = proc.communicate()

    if out:
        # discard any lines at the beginning that aren't part of the plist
        lines = str(out).splitlines()
        plist = ''
        for index in range(len(lines)):
            try:
                plist = FoundationPlist.readPlistFromString(
                                                '\n'.join(lines[index:]) )
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


class MunkiLooseVersion (version.LooseVersion):
    '''Subclass version.LooseVersion to compare things like
    "10.6" and "10.6.0" as equal'''

    def __pad__(self, version_list, max_length):
        """Pad a version list by adding extra 0
        components to the end if needed"""
        # copy the version_list so we don't modify it
        cmp_list = list(version_list)
        while len(cmp_list) < max_length :
            cmp_list.append(0)
        return (cmp_list)

    def __cmp__ (self, other):
        if isinstance(other, StringType):
            other = MunkiLooseVersion(other)

        max_length = max(len(self.version), len(other.version))
        self_cmp_version = self.__pad__(self.version, max_length)
        other_cmp_version = self.__pad__(other.version, max_length)

        return cmp(self_cmp_version, other_cmp_version)


def padVersionString(versString, tupleCount):
    """Normalize the format of a version string"""
    if versString == None:
        versString = '0'
    components = str(versString).split('.')
    if len(components) > tupleCount :
        components = components[0:tupleCount]
    else:
        while len(components) < tupleCount :
            components.append('0')
    return '.'.join(components)


def getVersionString(plist):
    """Gets a version string from the plist.
    If there's a valid CFBundleShortVersionString, returns that.
    else if there's a CFBundleVersion, returns that
    else returns an empty string."""
    CFBundleShortVersionString = ''
    if plist.get('CFBundleShortVersionString'):
        CFBundleShortVersionString = \
            plist['CFBundleShortVersionString'].split()[0]
    if 'Bundle versions string, short' in plist:
        CFBundleShortVersionString = \
            plist['Bundle versions string, short'].split()[0]
    if CFBundleShortVersionString:
        if CFBundleShortVersionString[0] in '0123456789':
            # starts with a number; that's good
            # now for another edge case thanks to Adobe:
            # replace commas with periods
            CFBundleShortVersionString = \
                CFBundleShortVersionString.replace(',','.')
            return CFBundleShortVersionString
    if plist.get('CFBundleVersion'):
        # no CFBundleShortVersionString, or bad one
        CFBundleVersion = str(plist['CFBundleVersion']).split()[0]
        if CFBundleVersion[0] in '0123456789':
            # starts with a number; that's good
            # now for another edge case thanks to Adobe:
            # replace commas with periods
            CFBundleVersion = CFBundleVersion.replace(',','.')
            return CFBundleVersion

    return ''


def getExtendedVersion(bundlepath):
    """
    Returns five-part version number like Apple uses in distribution
    and flat packages
    """
    infoPlist = os.path.join(bundlepath, 'Contents', 'Info.plist')
    if os.path.exists(infoPlist):
        plist = FoundationPlist.readPlist(infoPlist)
        versionstring = getVersionString(plist)
        if versionstring:
            return versionstring

    # no version number in Info.plist. Maybe old-style package?
    infopath = os.path.join(bundlepath, 'Contents', 'Resources',
                                'English.lproj')
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


def parsePkgRefs(filename):
    """Parses a .dist or PackageInfo file looking for pkg-ref or pkg-info tags
    to get info on included sub-packages"""
    info = []
    dom = minidom.parse(filename)
    pkgrefs = dom.getElementsByTagName('pkg-ref')
    if pkgrefs:
        for ref in pkgrefs:
            keys = ref.attributes.keys()
            if 'id' in keys and 'version' in keys:
                pkginfo = {}
                pkginfo['packageid'] = \
                             ref.attributes['id'].value.encode('UTF-8')
                pkginfo['version'] = \
                    ref.attributes['version'].value.encode('UTF-8')
                if 'installKBytes' in keys:
                    pkginfo['installed_size'] = int(
                        ref.attributes['installKBytes'].value.encode('UTF-8'))
                if not pkginfo['packageid'].startswith('manual'):
                    if not pkginfo in info:
                        info.append(pkginfo)
    else:
        pkgrefs = dom.getElementsByTagName('pkg-info')
        if pkgrefs:
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
    pkgtmp = tempfile.mkdtemp(dir=tmpdir)
    # record our current working dir
    cwd = os.getcwd()
    # change into our tmpdir so we can use xar to unarchive the flat package
    os.chdir(pkgtmp)
    returncode = subprocess.call(['/usr/bin/xar', '-xf', abspkgpath,
                                  '--exclude', 'Payload'])
    if returncode == 0:
        currentdir = pkgtmp
        packageinfofile = os.path.join(currentdir, 'PackageInfo')
        if os.path.exists(packageinfofile):
            infoarray = parsePkgRefs(packageinfofile)

        if not infoarray:
            # didn't get any packageid info or no PackageInfo file
            # look for subpackages at the top level
            for item in listdir(currentdir):
                itempath = os.path.join(currentdir, item)
                if itempath.endswith('.pkg') and os.path.isdir(itempath):
                    packageinfofile = os.path.join(itempath, 'PackageInfo')
                    if os.path.exists(packageinfofile):
                        infoarray.extend(parsePkgRefs(packageinfofile))

        if not infoarray:
            # found no PackageInfo files and no subpackages,
            # so let's look at the Distribution file
            distributionfile = os.path.join(currentdir, 'Distribution')
            if os.path.exists(distributionfile):
                infoarray = parsePkgRefs(distributionfile)

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
        (output, unused_err) = proc.communicate()
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

            pkginfo['version'] = getExtendedVersion(pkgpath)
        except (AttributeError,
                FoundationPlist.NSPropertyListSerializationException):
            pkginfo['packageid'] = 'BAD PLIST in %s' % \
                                    os.path.basename(pkgpath)
            pkginfo['version'] = '0.0.0.0.0'
        ## now look for applications to suggest for blocking_applications
        #bomlist = getBomList(pkgpath)
        #if bomlist:
        #    pkginfo['apps'] = [os.path.basename(item) for item in bomlist
        #                        if item.endswith('.app')]
                
    else:
        # look for old-style .info files!
        infopath = os.path.join(pkgpath, 'Contents', 'Resources',
                                    'English.lproj')
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


def getText(nodelist):
    """Helper function to get text from XML child nodes"""
    text = ""
    for node in nodelist:
        if node.nodeType == node.TEXT_NODE:
            text = text + node.data
    return text


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
                dom = minidom.parse(filename)
                pkgrefs = dom.getElementsByTagName('pkg-ref')
                if pkgrefs:
                    # try to find subpackages from the file: references
                    for ref in pkgrefs:
                        fileref = getText(ref.childNodes)
                        if fileref.startswith('file:'):
                            relativepath = urllib2.unquote(fileref[5:])
                            subpkgpath = os.path.join(pkgpath, relativepath)
                            if os.path.exists(subpkgpath):
                                pkginfo = getBundlePackageInfo(subpkgpath)
                                if pkginfo:
                                    infoarray.extend(pkginfo)

                    if infoarray:
                        return infoarray

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

        if infoarray:
            return infoarray
        else:
            # couldn't find any subpackages,
            # just return info from the .dist file
            # if it exists
            for item in listdir(bundlecontents):
                if item.endswith('.dist'):
                    distfile = os.path.join(bundlecontents, item)
                    infoarray.extend(parsePkgRefs(distfile))

    return infoarray


def getReceiptInfo(pkgname):
    """Get receipt info from a package"""
    info = []
    if pkgname.endswith('.pkg') or pkgname.endswith('.mpkg'):
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
    (out, unused_err) = proc.communicate()

    if out:
        try:
            plist = FoundationPlist.readPlistFromString(out)
        except FoundationPlist.NSPropertyListSerializationException:
            pass
        else:
            foundbundleid = plist.get('pkgid')
            foundvers = plist.get('pkg-version', '0.0.0.0.0')
            if pkgid == foundbundleid:
                display_debug2('\tThis machine has %s, version %s' %
                                (pkgid, foundvers))
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
            display_debug2('\tThis machine has %s, version %s' %
                            (pkgid, highestversion))
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
    index = 0
    for char in aString:
        if char in '0123456789':
            possibleVersion = aString[index:]
            if not (' ' in possibleVersion or '_' in possibleVersion or \
                    '-' in possibleVersion or 'v' in possibleVersion):
                return (aString[0:index].rstrip(' .-_v'), possibleVersion)
        index += 1
    # no version number found, just return original string and empty string
    return (aString, '')


def isInstallerItem(path):
    """Verifies we have an installer item"""
    if (path.endswith('.pkg') or path.endswith('.mpkg') or
        path.endswith('.dmg') or path.endswith('.dist')):
        return True
    else:
        return False


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

    if not isInstallerItem(pkgitem):
        return {}

    # first get the data /usr/sbin/installer will give us
    installerinfo = getInstallerPkgInfo(pkgitem)
    if not installerinfo:
        return None
    # now look for receipt/subpkg info
    receiptinfo = getReceiptInfo(pkgitem)

    name = os.path.split(pkgitem)[1]
    shortname = os.path.splitext(name)[0]
    metaversion = getExtendedVersion(pkgitem)
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
    os_ver = map(int, platform.mac_ver()[0].split('.'))
    if os_ver[0] <= 10 and os_ver[1] <= 5:
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
    query.setPredicate_(NSPredicate.predicateWithFormat_(
                                    '(kMDItemKind = "Application")'))
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
        NSRunLoop.currentRunLoop().runUntilDate_(
                                   NSDate.dateWithTimeIntervalSinceNow_(0.3))
    query.stopQuery()

    if runtime >= maxruntime:
        display_warning('Spotlight search for applications terminated due to '
              'excessive time. This will happen if spotlight is reindexing '
              'the drive, otherwise it is a bug.')

    for item in query.results():
        p = item.valueForAttribute_('kMDItemPath')
        if not isExcludedFilesystem(p):
            applist.append(p)

    return applist


def getSpotlightInstalledApplications():
    """Get paths of currently installed applications per Spotlight.
    Return value is list of paths.
    Excludes most non-boot volumes.
    In future may include local r/w volumes.
    """
    # Includes /Users.
    skipdirs = ['Volumes', 'tmp', '.vol', '.Trashes',
                '.Spotlight-V100', '.fseventsd', 'Network', 'net',
                'home', 'cores', 'dev']
    dirlist = []
    applist = []

    for f in listdir(u'/'):
        if not f in skipdirs:
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
    apps = LaunchServices._LSCopyAllApplicationURLs(None)
    applist = []
    for app in apps:
        (status, fsobj, unused_url) = LaunchServices.LSGetApplicationForURL(
            app, _unsigned(LaunchServices.kLSRolesAll), None, None)
        if status != 0:
            continue
        app_path = fsobj.as_pathname()
        if (not app_path.startswith('/Volumes/') and not
            isExcludedFilesystem(app_path)):
            applist.append(app_path)

    return applist

# we save APPDATA in a global to avoid querying LaunchServices more than
# once per session
APPDATA = []
def getAppData():
    """Gets info on currently installed apps.
    Returns a list of dicts containing path, name, version and bundleid"""
    if APPDATA == []:
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
                    iteminfo['bundleid' ] = plist.get('CFBundleIdentifier','')
                    if 'CFBundleName' in plist:
                        iteminfo['name'] = plist['CFBundleName']
                    iteminfo['version'] = getExtendedVersion(pathname)
                    APPDATA.append(iteminfo)
                except Exception:
                    pass
    return APPDATA


def getRunningProcesses():
    """Returns a list of paths of running processes"""
    proc = subprocess.Popen(['/bin/ps', '-axo' 'comm='],
                            shell=False, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    (output, unused_err) = proc.communicate()
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
            (output, unused_err) = proc.communicate()
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

def isAppRunning(appname):
    """Tries to determine if the application in appname is currently
    running"""
    display_detail('Checking if %s is running...' % appname)
    proc_list = getRunningProcesses()
    matching_items = []
    if appname.endswith('.app'):
        # search by filename
        matching_items = [item for item in proc_list
                          if '/'+ appname + '/' in item]
    else:
        # check executable name
        matching_items = [item for item in proc_list
                          if item.endswith('/' + appname)]
    if not matching_items:
        # try adding '.app' to the name and check again
        matching_items = [item for item in proc_list
                          if '/'+ appname + '.app/' in item]

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


def cleanUpTmpDir():
    """Cleans up our temporary directory."""
    global tmpdir
    if tmpdir:
        try:
            shutil.rmtree(tmpdir)
        except (OSError, IOError):
            pass
        tmpdir = None


def listdir(path):
    """OSX HFS+ string encoding safe listdir().

    Args:
        path: path to list contents of
    Returns:
        list of contents, items as str or unicode types
    """
    # if os.listdir() is supplied a unicode object for the path,
    # it will return unicode filenames instead of their raw fs-dependent
    # version, which is decomposed utf-8 on OSX.
    #
    # we use this to our advantage here and have Python do the decoding
    # work for us, instead of decoding each item in the output list.
    #
    # references:
    # http://docs.python.org/howto/unicode.html#unicode-filenames
    # http://developer.apple.com/library/mac/#qa/qa2001/qa1235.html
    # http://lists.zerezo.com/git/msg643117.html
    # http://unicode.org/reports/tr15/    section 1.2
    if type(path) is str:
        path = unicode(path, 'utf-8')
    elif type(path) is not unicode:
        path = unicode(path)
    return os.listdir(path)


# module globals
#debug = False
verbose = 1
munkistatusoutput = False
tmpdir = tempfile.mkdtemp()
report = {}

def main():
    """Placeholder"""
    print 'This is a library of support tools for the Munki Suite.'

if __name__ == '__main__':
    main()

