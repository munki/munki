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

from .. import munkistatus
from .. import FoundationPlist

# We wildcard-import from submodules for backwards compatibility; functions
# that were previously available from this module
# pylint: disable=wildcard-import
from .authrestart import *
from .constants import *
from .dmgutils import *
from .info import *
from .osutils import *
from .output import *
from .pkgutils import *
from .prefs import *
# pylint: enable=wildcard-import

import LaunchServices

# PyLint cannot properly find names inside Cocoa libraries, so issues bogus
# No name 'Foo' in module 'Bar' warnings. Disable them.
# pylint: disable=E0611
from Foundation import NSDate, NSMetadataQuery, NSPredicate, NSRunLoop
# pylint: enable=E0611

# we use lots of camelCase-style names. Deal with it.
# pylint: disable=C0103


# misc functions

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


def main():
    """Placeholder"""
    print 'This is a library of support tools for the Munki Suite.'


if __name__ == '__main__':
    main()
