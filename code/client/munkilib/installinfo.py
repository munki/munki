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
installinfo.py

Created by Greg Neagle on 2017-01-01.

Functions for getting data from the InstallInfo.plist, etc
"""

# standard libs
import os

# Apple's libs
# PyLint cannot properly find names inside Cocoa libraries, so issues bogus
# No name 'Foo' in module 'Bar' warnings. Disable them.
# pylint: disable=E0611
from Foundation import NSDate
# pylint: enable=E0611

# our libs
from . import display
from . import info
from . import prefs
from . import reports
from . import FoundationPlist


# This many hours before a force install deadline, start notifying the user.
FORCE_INSTALL_WARNING_HOURS = 4


def display_update_info():
    '''Prints info about available updates'''

    def display_and_record_restart_info(item):
        '''Displays logout/restart info for item if present and also updates
        our report'''
        if (item.get('RestartAction') == 'RequireRestart' or
                item.get('RestartAction') == 'RecommendRestart'):
            display.display_info('       *Restart required')
            reports.report['RestartRequired'] = True
        if item.get('RestartAction') == 'RequireLogout':
            display.display_info('       *Logout required')
            reports.report['LogoutRequired'] = True

    installinfopath = os.path.join(
        prefs.pref('ManagedInstallDir'), 'InstallInfo.plist')
    try:
        installinfo = FoundationPlist.readPlist(installinfopath)
    except FoundationPlist.NSPropertyListSerializationException:
        installinfo = {}

    installcount = len(installinfo.get('managed_installs', []))
    removalcount = len(installinfo.get('removals', []))

    if installcount:
        display.display_info('')
        display.display_info(
            'The following items will be installed or upgraded:')
    for item in installinfo.get('managed_installs', []):
        if item.get('installer_item'):
            display.display_info(
                '    + %s-%s', item.get('name', ''),
                item.get('version_to_install', ''))
            if item.get('description'):
                display.display_info('        %s', item['description'])
            display_and_record_restart_info(item)

    if removalcount:
        display.display_info('The following items will be removed:')
    for item in installinfo.get('removals', []):
        if item.get('installed'):
            display.display_info('    - %s', item.get('name'))
            display_and_record_restart_info(item)

    if installcount == 0 and removalcount == 0:
        display.display_info(
            'No changes to managed software are available.')


def force_install_package_check():
    """Check installable packages and applicable Apple updates
    for force install parameters.

    This method modifies InstallInfo and/or AppleUpdates in one scenario:
    It enables the unattended_install flag on all packages which need to be
    force installed and do not have a RestartAction.

    The return value may be one of:
        'now': a force install is about to occur
        'soon': a force install will occur within FORCE_INSTALL_WARNING_HOURS
        'logout': a force install is about to occur and requires logout
        'restart': a force install is about to occur and requires restart
        None: no force installs are about to occur
    """
    result = None

    managed_install_dir = prefs.pref('ManagedInstallDir')

    installinfo_types = {
        'InstallInfo.plist' : 'managed_installs',
        'AppleUpdates.plist': 'AppleUpdates'
    }

    now = NSDate.date()
    now_xhours = NSDate.dateWithTimeIntervalSinceNow_(
        FORCE_INSTALL_WARNING_HOURS * 3600)

    for installinfo_plist in installinfo_types:
        pl_dict = installinfo_types[installinfo_plist]
        installinfopath = os.path.join(managed_install_dir, installinfo_plist)
        try:
            installinfo = FoundationPlist.readPlist(installinfopath)
        except FoundationPlist.NSPropertyListSerializationException:
            continue

        writeback = False

        for i in xrange(len(installinfo.get(pl_dict, []))):
            install = installinfo[pl_dict][i]
            force_install_after_date = install.get('force_install_after_date')

            if not force_install_after_date:
                continue

            force_install_after_date = (
                info.subtract_tzoffset_from_date(force_install_after_date))
            display.display_debug1(
                'Forced install for %s at %s',
                install['name'], force_install_after_date)
            if now >= force_install_after_date:
                result = 'now'
                if install.get('RestartAction'):
                    if install['RestartAction'] == 'RequireLogout':
                        result = 'logout'
                    elif (install['RestartAction'] == 'RequireRestart' or
                          install['RestartAction'] == 'RecommendRestart'):
                        result = 'restart'
                elif not install.get('unattended_install', False):
                    display.display_debug1(
                        'Setting unattended install for %s', install['name'])
                    install['unattended_install'] = True
                    installinfo[pl_dict][i] = install
                    writeback = True

            if not result and now_xhours >= force_install_after_date:
                result = 'soon'

        if writeback:
            FoundationPlist.writePlist(installinfo, installinfopath)

    return result


if __name__ == '__main__':
    print 'This is a library of support tools for the Munki Suite.'
