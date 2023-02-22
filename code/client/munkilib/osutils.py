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
osutils.py

Created by Greg Neagle on 2016-12-13.

Common functions and classes used by the munki tools.
"""
from __future__ import absolute_import, print_function

import platform
import os
import shutil
import subprocess
import sys
import tempfile
import time


# PyLint cannot properly find names inside Cocoa libraries, so issues bogus
# No name 'Foo' in module 'Bar' warnings. Disable them.
# pylint: disable=E0611
from SystemConfiguration import SCDynamicStoreCopyConsoleUser
# pylint: enable=E0611

from . import display
from . import munkilog

# we use lots of camelCase-style names. Deal with it.
# pylint: disable=C0103


def getOsVersion(only_major_minor=True, as_tuple=False):
    """Returns an OS version.

    Args:
      only_major_minor: Boolean. If True, only include major/minor versions.
      as_tuple: Boolean. If True, return a tuple of ints, otherwise a string.
    """
    # platform.mac_ver() returns 10.16-style version info on Big Sur
    # and is likely to do so until Python is compiled with the macOS 11 SDK
    # which may not happen for a while. And Apple's odd tricks mean that even
    # reading /System/Library/CoreServices/SystemVersion.plist is unreliable.
    # So let's use a different method.
    try:
        os_version_tuple = subprocess.check_output(
            ('/usr/bin/sw_vers', '-productVersion'),
            env={'SYSTEM_VERSION_COMPAT': '0'}
        ).decode('UTF-8').rstrip().split('.')
    except subprocess.CalledProcessError:
        os_version_tuple = platform.mac_ver()[0].split(".")
    if only_major_minor:
        if int(os_version_tuple[0]) > 10:
            # return something like (11,)
            os_version_tuple = (os_version_tuple[0],)
        else:
            # return something like (10,15)
            os_version_tuple = os_version_tuple[0:2]
    if as_tuple:
        return tuple(map(int, os_version_tuple))
    # default
    return '.'.join(os_version_tuple)


def tmpdir():
    '''Returns a temporary directory for this session'''
    if not hasattr(tmpdir, 'cache'):
        tmpdir.cache = tempfile.mkdtemp(prefix='munki-', dir='/tmp')
    return tmpdir.cache


def cleanUpTmpDir():
    """Cleans up our temporary directory."""
    if hasattr(tmpdir, 'cache'):
        try:
            shutil.rmtree(tmpdir.cache)
        except (OSError, IOError) as err:
            display.display_warning(
                'Unable to clean up temporary dir %s: %s',
                tmpdir.cache, str(err))
        del tmpdir.cache


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
    # pylint: disable=unicode-builtin
    if isinstance(path, str):
        try:
            path = unicode(path, 'utf-8')
        except NameError:
            # Python 3
            pass
    elif not isinstance(path, unicode):
        path = unicode(path)
    return os.listdir(path)


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
    output = proc.communicate()[0].decode("UTF-8")
    lines = output.splitlines()
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
    proc = subprocess.Popen(cmd, shell=False,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out = proc.communicate()[0].decode("UTF-8")
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
    proc = subprocess.Popen(cmd, shell=False,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out, err) = proc.communicate()
    if proc.returncode != 0:
        print('Error: ', err.decode('UTF-8'), file=sys.stderr)
    if out:
        return out.decode('UTF-8').rstrip('\n')
    return u''


def bridgeos_update_staged():
    '''Checks an undocumented nvram variable to see if a bridgeOS update
    has been staged. If so, we should shut down instead of restart.
    Returns a boolean.'''
    cmd = ["/usr/sbin/nvram", "BOSUpdateStarted"]
    proc = subprocess.Popen(cmd,
                            shell=False,
                            bufsize=-1,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    output = proc.communicate()[0].decode('UTF-8')
    if proc.returncode == 0:
        munkilog.log("nvram output: %s" % output)
        lines = output.splitlines()
        parts = lines[0].split()
        try:
            timestamp = int(parts[1].split(',')[0])
            now = int(time.time())
            seconds_ago = now - timestamp
            if seconds_ago < 60 * 60:
                munkilog.log(
                    "bridgeOS update staged %s seconds ago; shutdown required"
                    % seconds_ago)
                return True
            #else
            munkilog.log(
                "bridgeOS update %s seconds ago; too long ago to trust"
                % seconds_ago)
            return False
        except (IndexError, ValueError):
            munkilog.log(
                "unexpected nvram output, can't detect bridgeos update")
            return False
    #else
    munkilog.log("No bridgeOS update staged")
    return False


if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
