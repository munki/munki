# encoding: utf-8
#
# Copyright 2009-2017 Greg Neagle.
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
Functions originally written by Wes Whetstone, Summer/Fall 2016

Functions supporting FileVault authrestart.
"""

import subprocess

from . import display
from . import osutils
from . import prefs

from . import FoundationPlist


def supports_auth_restart():
    """Check if FileVault is enabled then checks
    if an Authorized Restart is supported, returns True
    or False accordingly.
    """
    display.display_debug1('Checking if FileVault is enabled...')
    active_cmd = ['/usr/bin/fdesetup', 'isactive']
    try:
        is_active = subprocess.check_output(
            active_cmd, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as exc:
        if exc.output and 'false' in exc.output:
            display.display_warning('FileVault appears to be disabled...')
        elif not exc.output:
            display.display_warning(
                'Encountered problem determining FileVault status...')
        else:
            display.display_warning(exc.output)
        return False
    display.display_debug1(
        'Checking if FileVault can perform an AuthRestart...')
    support_cmd = ['/usr/bin/fdesetup', 'supportsauthrestart']
    try:
        is_supported = subprocess.check_output(
            support_cmd, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as exc:
        if exc.output:
            display.display_warning(exc.output)
        else:
            display.display_warning(
                'Encountered problem determining AuthRestart Status...')
        return False
    if 'true' in is_active and 'true' in is_supported:
        display.display_debug1(
            'FileVault is on and supports an AuthRestart...')
        return True
    else:
        display.display_warning(
            'FileVault is disabled or does not support an AuthRestart...')
        return False


def get_auth_restart_key():
    """Returns recovery key as a string... If we failed
    to get the proper information, returns an empty string"""
    # checks to see if recovery key preference is set
    recoverykeyplist = prefs.pref('RecoveryKeyFile')
    if not recoverykeyplist:
        display.display_warning(
            "RecoveryKeyFile preference is not set")
        return ''
    display.display_debug1(
        'RecoveryKeyFile preference is set to %s...', recoverykeyplist)
    # try to get the recovery key from the defined location
    try:
        keyplist = FoundationPlist.readPlist(recoverykeyplist)
        recovery_key = keyplist['RecoveryKey'].strip()
        return recovery_key
    except FoundationPlist.NSPropertyListSerializationException:
        display.display_error(
            'We had trouble getting info from %s...', recoverykeyplist)
        return ''
    except KeyError:
        display.display_error(
            'Problem with key: RecoveryKey in %s...', recoverykeyplist)
        return ''


def perform_auth_restart():
    """When called this will perform an authorized restart. Before trying
    to perform an authorized restart it checks to see if the machine supports
    the feature. If supported it will then look for the defined plist containing
    a key called RecoveryKey. It will use that value to perform the restart"""
    display.display_debug1(
        'Checking if performing an Auth Restart is fully supported...')
    if not supports_auth_restart():
        display.display_warning(
            "Machine doesn't support Authorized Restarts...")
        return False
    display.display_debug1('Machine supports Authorized Restarts...')
    recovery_key = get_auth_restart_key()
    if not recovery_key:
        return False
    key = {'Password': recovery_key}
    inputplist = FoundationPlist.writePlistToString(key)
    display.display_info('Attempting an Authorized Restart now...')
    cmd = subprocess.Popen(
        ['/usr/bin/fdesetup', 'authrestart', '-inputplist'],
        stdout=subprocess.PIPE,
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE)
    (dummy_out, err) = cmd.communicate(input=inputplist)
    os_version_tuple = osutils.getOsVersion(as_tuple=True)
    if os_version_tuple >= (10, 12) and 'System is being restarted' in err:
        return True
    if err:
        display.display_error(err)
        return False
    else:
        return True


if __name__ == '__main__':
    print 'This is a library of support tools for the Munki Suite.'
