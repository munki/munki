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
utils

Created by Justin McWilliams on 2010-10-26.

Common utility functions used throughout Munki.

Note: this module should be 100% free of ObjC-dependant Python imports.
"""


import grp
import os
import subprocess
import stat


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
    except OSError, e:
        raise VerifyFilePermissionsError(
            '%s does not exist. \n %s' % (file_path, str(e)))

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
    except InsecureFilePermissionsError, e:
        raise InsecureFilePermissionsError(
            '%s is not secure! %s' % (file_path, e.args[0]))


def runExternalScript(script, *args):
    """Run a script (e.g. preflight/postflight) and return its exit status.

    Args:
      script: string path to the script to execute.
      args: args to pass to the script.
    Returns:
      Tuple. (integer exit status from script, str stdout, str stderr).
    Raises:
      ScriptNotFoundError: the script was not found at the given path.
      RunExternalScriptError: there was an error running the script.
    """
    if not os.path.exists(script):
        raise ScriptNotFoundError('script does not exist: %s' % script)

    try:
        verifyFileOnlyWritableByMunkiAndRoot(script)
    except VerifyFilePermissionsError, e:
        msg = ('Skipping execution due to failed file permissions '
               'verification: %s\n%s' % (script, str(e)))
        raise RunExternalScriptError(msg)

    if os.access(script, os.X_OK):
        cmd = [script]
        if args:
            cmd.extend(args)
        proc = subprocess.Popen(cmd, shell=False,
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        (stdout, stderr) = proc.communicate()
        return proc.returncode, stdout, stderr
    else:
        raise RunExternalScriptError('%s not executable' % script)

