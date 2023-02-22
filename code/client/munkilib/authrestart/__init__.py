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
authrestart.py

Created by Greg Neagle on 2016-12-14.
Initial work by Wes Whetstone, Summer/Fall 2016

Functions supporting FileVault authrestart.
"""
from __future__ import absolute_import, print_function

import subprocess

from .. import display
from .. import osutils
from .. import prefs

from .. import FoundationPlist


def filevault_is_active():
    """Check if FileVault is enabled; returns True or False accordingly."""
    display.display_debug1('Checking if FileVault is enabled...')
    active_cmd = ['/usr/bin/fdesetup', 'isactive']
    try:
        is_active = subprocess.check_output(
            active_cmd, stderr=subprocess.STDOUT).decode('UTF-8')
    except subprocess.CalledProcessError as exc:
        if exc.output and 'false' in exc.output.decode('UTF-8'):
            # fdesetup isactive returns 1 when FileVault is not active
            display.display_debug1('FileVault appears to be disabled...')
        elif not exc.output:
            display.display_warning(
                'Encountered problem determining FileVault status...')
        else:
            display.display_warning(exc.output)
        return False
    if 'true' in is_active:
        display.display_debug1('FileVault appears to be enabled...')
        return True
    display.display_debug1('Could not confirm FileVault is enabled...')
    return False


def supports_auth_restart():
    """Checks if an Authorized Restart is supported; returns True
    or False accordingly.
    """
    display.display_debug1(
        'Checking if FileVault can perform an AuthRestart...')
    support_cmd = ['/usr/bin/fdesetup', 'supportsauthrestart']
    try:
        is_supported = subprocess.check_output(
            support_cmd, stderr=subprocess.STDOUT).decode('UTF-8')
    except subprocess.CalledProcessError as exc:
        if exc.output:
            display.display_warning(exc.output)
        else:
            display.display_warning(
                'Encountered problem determining AuthRestart status...')
        return False
    if 'true' in is_supported:
        display.display_debug1('FileVault supports AuthRestart...')
        return True

    display.display_warning('FileVault AuthRestart is not supported...')
    return False


def is_fv_user(username):
    """Returns a boolean indicating if username is in the list of FileVault
    authorized users"""
    cmd = ['/usr/bin/fdesetup', 'list']
    try:
        userlist = subprocess.check_output(
            cmd, stderr=subprocess.STDOUT).decode('UTF-8')
    except subprocess.CalledProcessError:
        return False
    # output is in the format
    # jsmith,911D2742-7983-436D-9FA3-3F6B7421684B
    # tstark,5B0EBEE6-0917-47B2-BFF3-78A9DE437D65
    for line in userlist.splitlines():
        if line.split(',')[0] == username:
            return True
    return False


def can_attempt_auth_restart_for(username):
    '''Returns a boolean to indicate if all the needed conditions are present
    for us to attempt an authrestart with username's password'''
    os_version_tuple = osutils.getOsVersion(as_tuple=True)
    return (os_version_tuple >= (10, 8) and
            prefs.pref('PerformAuthRestarts') and filevault_is_active() and
            supports_auth_restart() and is_fv_user(username))


def get_auth_restart_key(quiet=False):
    """Returns recovery key as a string... If we failed
    to get the proper information, returns an empty string.
    If quiet is set, fail silently"""
    # checks to see if recovery key preference is set
    recoverykeyplist = prefs.pref('RecoveryKeyFile')
    if not recoverykeyplist:
        if not quiet:
            display.display_debug1('RecoveryKeyFile preference is not set')
        return ''
    if not quiet:
        display.display_debug1(
            'RecoveryKeyFile preference is set to %s...', recoverykeyplist)
    # try to get the recovery key from the defined location
    try:
        keyplist = FoundationPlist.readPlist(recoverykeyplist)
        recovery_key = keyplist['RecoveryKey'].strip()
        return recovery_key
    except FoundationPlist.NSPropertyListSerializationException:
        if not quiet:
            display.display_error(
                'We had trouble getting info from %s...', recoverykeyplist)
        return ''
    except (KeyError, ValueError):
        if not quiet:
            display.display_error(
                'Problem with key: RecoveryKey in %s...', recoverykeyplist)
        return ''


def can_attempt_auth_restart(have_password=False):
    '''Returns a boolean to indicate if all the needed conditions are present
    for us to attempt an authrestart'''
    os_version_tuple = osutils.getOsVersion(as_tuple=True)
    return (os_version_tuple >= (10, 8) and
            prefs.pref('PerformAuthRestarts') and
            filevault_is_active() and supports_auth_restart() and
            (get_auth_restart_key(quiet=True) != '' or have_password))


def perform_auth_restart(username=None, password=None, delayminutes=0):
    """When called this will perform an authorized restart. Before trying
    to perform an authorized restart it checks to see if the machine supports
    the feature. If supported it will look for the defined plist containing
    a key called RecoveryKey. If this doesn't exist, it will use a password
    (or recovery key) passed into the function. It will use that value to
    perform the restart."""
    display.display_debug1(
        'Checking if performing an Auth Restart is fully supported...')
    if not supports_auth_restart():
        display.display_warning(
            "Machine doesn't support Authorized Restarts...")
        return False
    display.display_debug1('Machine supports Authorized Restarts...')
    password = get_auth_restart_key() or password
    if not password:
        return False
    keys = {'Password': password}
    if username:
        keys['Username'] = username
    inputplist = FoundationPlist.writePlistToString(keys)
    if delayminutes == 0:
        display.display_info('Attempting an Authorized Restart now...')
    else:
        display.display_info('Configuring a delayed Authorized Restart...')
    os_version_tuple = osutils.getOsVersion(as_tuple=True)
    if os_version_tuple >= (10, 12):
        cmd = ['/usr/bin/fdesetup', 'authrestart',
               '-delayminutes', str(delayminutes), '-inputplist']
    else:
        cmd = ['/usr/bin/fdesetup', 'authrestart', '-inputplist']
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    err = proc.communicate(input=inputplist)[1].decode('UTF-8')
    if os_version_tuple >= (10, 12) and 'System is being restarted' in err:
        return True
    if err:
        display.display_error(err)
        return False
    # no error, so I guess we're successful
    return True


def do_authorized_or_normal_restart(username=None,
                                    password=None,
                                    shutdown=False):
    '''Do a shutdown if needed, or an authrestart if allowed/possible,
    else do a normal restart.'''
    if shutdown:
        # we need a shutdown here instead of any type of restart
        display.display_info('Shutting down now.')
        display.display_debug1('Performing a regular shutdown...')
        dummy_retcode = subprocess.call(['/sbin/shutdown', '-h', '-o', 'now'])
        return
    display.display_info('Restarting now.')
    os_version_tuple = osutils.getOsVersion(as_tuple=True)
    if (prefs.pref('PerformAuthRestarts') and
            (prefs.pref('RecoveryKeyFile') or password) and
            os_version_tuple >= (10, 8)):
        if filevault_is_active():
            display.display_debug1('Configured to perform AuthRestarts...')
            # try to perform an auth restart
            if not perform_auth_restart(username=username, password=password):
                # if we got to here then the auth restart failed
                # notify that it did then perform a normal restart
                display.display_warning(
                    'Authorized Restart failed. Performing normal restart...')
            else:
                # we triggered an authrestart
                return
    # fall back to normal restart
    display.display_debug1('Performing a regular restart...')
    dummy_retcode = subprocess.call(['/sbin/shutdown', '-r', 'now'])


if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
