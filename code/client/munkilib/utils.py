# encoding: utf-8
#
# Copyright 2010-2017 Google Inc. All Rights Reserved.
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
utils

Created by Justin McWilliams on 2010-10-26.

Common utility functions used throughout Munki.

Note: this module should be 100% free of ObjC-dependent Python imports.
"""
from __future__ import absolute_import, print_function


import grp
import os
import subprocess
import stat


class Memoize(dict):
    '''Class to cache the return values of an expensive function.
    This version supports only functions with non-keyword arguments'''
    def __init__(self, func):
        super(Memoize, self).__init__()
        self.func = func

    def __call__(self, *args):
        return self[args]

    def __missing__(self, key):
        result = self[key] = self.func(*key)
        return result


class Error(Exception):
    """Class for domain specific exceptions."""


class RunExternalScriptError(Error):
    """There was an error running the script."""


class ScriptNotFoundError(RunExternalScriptError):
    """The script was not found at the given path."""


class VerifyFilePermissionsError(Error):
    """There was an error verifying file permissions."""


class InsecureFilePermissionsError(VerifyFilePermissionsError):
    """The permissions of the specified file are insecure."""


# Munki uses a lot of camelCase names due to its OS X and Cocoa relationships.
# so disable PyLint warnings about invalid function names
# pylint: disable=C0103

def verifyFileOnlyWritableByMunkiAndRoot(file_path):
    """
    Check the permissions on a given file path; fail if owner or group
    does not match the munki process (default: root/admin) or the group is not
    'wheel', or if other users are able to write to the file. This prevents
    escalated execution of arbitrary code.

    Args:
      file_path: str path of file to verify permissions on.
    Raises:
      VerifyFilePermissionsError: there was an error verifying file permissions.
      InsecureFilePermissionsError: file permissions were found to be insecure.
    """
    try:
        file_stat = os.stat(file_path)
    except OSError as err:
        raise VerifyFilePermissionsError(
            '%s does not exist. \n %s' % (file_path, str(err)))

    try:
        admin_gid = grp.getgrnam('admin').gr_gid
        wheel_gid = grp.getgrnam('wheel').gr_gid
        user_gid = os.getegid()
        # verify the munki process uid matches the file owner uid.
        if os.geteuid() != file_stat.st_uid:
            raise InsecureFilePermissionsError(
                'owner does not match munki process!')
        # verify the munki process gid matches the file owner gid, or the file
        # owner gid is wheel or admin gid.
        elif file_stat.st_gid not in [admin_gid, wheel_gid, user_gid]:
            raise InsecureFilePermissionsError(
                'group does not match munki process!')
        # verify other users cannot write to the file.
        elif file_stat.st_mode & stat.S_IWOTH != 0:
            raise InsecureFilePermissionsError('world writable!')
    except InsecureFilePermissionsError as err:
        raise InsecureFilePermissionsError(
            '%s is not secure! %s' % (file_path, err.args[0]))


def runExternalScript(script, allow_insecure=False, script_args=()):
    """Run a script (e.g. preflight/postflight) and return its exit status.

    Args:
      script: string path to the script to execute.
      allow_insecure: bool skip the permissions check of executable.
      args: args to pass to the script.
    Returns:
      Tuple. (integer exit status from script, str stdout, str stderr).
    Raises:
      ScriptNotFoundError: the script was not found at the given path.
      RunExternalScriptError: there was an error running the script.
    """
    if not os.path.exists(script):
        raise ScriptNotFoundError('script does not exist: %s' % script)

    if not allow_insecure:
        try:
            verifyFileOnlyWritableByMunkiAndRoot(script)
        except VerifyFilePermissionsError as err:
            msg = ('Skipping execution due to failed file permissions '
                   'verification: %s\n%s' % (script, str(err)))
            raise RunExternalScriptError(msg)

    if not os.access(script, os.X_OK):
        raise RunExternalScriptError('%s not executable' % script)

    cmd = [script]
    if script_args:
        cmd.extend(script_args)
    proc = None
    try:
        proc = subprocess.Popen(cmd, shell=False,
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
    except (OSError, IOError) as err:
        raise RunExternalScriptError(
            u'Error %s when attempting to run %s' % (err, script))
    (stdout, stderr) = proc.communicate()
    return (proc.returncode, stdout.decode('UTF-8', 'replace'),
            stderr.decode('UTF-8', 'replace'))



def getPIDforProcessName(processname):
    '''Returns a process ID for processname'''
    cmd = ['/bin/ps', '-eo', 'pid=,command=']
    try:
        proc = subprocess.Popen(cmd, shell=False, bufsize=-1,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT)
    except OSError:
        return 0

    while True:
        line = proc.stdout.readline().decode('UTF-8')
        if not line and (proc.poll() != None):
            break
        line = line.rstrip('\n')
        if line:
            try:
                (pid, process) = line.split(None, 1)
            except ValueError:
                # funky process line, so we'll skip it
                pass
            else:
                if process.find(processname) != -1:
                    return pid

    return 0


def getFirstPlist(byteString):
    """Gets the next plist from a byte string that may contain one or
    more text-style plists.
    Returns a tuple - the first plist (if any) and the remaining
    string after the plist"""
    plist_header = b'<?xml version'
    plist_footer = b'</plist>'
    plist_start_index = byteString.find(plist_header)
    if plist_start_index == -1:
        # not found
        return (b"", byteString)
    plist_end_index = byteString.find(
        plist_footer, plist_start_index + len(plist_header))
    if plist_end_index == -1:
        # not found
        return (b"", byteString)
    # adjust end value
    plist_end_index = plist_end_index + len(plist_footer)
    return (byteString[plist_start_index:plist_end_index],
            byteString[plist_end_index:])


if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
