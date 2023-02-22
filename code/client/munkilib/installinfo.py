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
installinfo.py

Created by Greg Neagle on 2017-01-01.

Functions for getting data from the InstallInfo.plist, etc
"""
# This code is largely still compatible with Python 2, so for now, turn off
# Python 3 style warnings
# pylint: disable=consider-using-f-string
# pylint: disable=redundant-u-string-prefix

from __future__ import absolute_import, print_function

# standard libs
import os

# Apple's libs
# PyLint cannot properly find names inside Cocoa libraries, so issues bogus
# No name 'Foo' in module 'Bar' warnings. Disable them.
# pylint: disable=E0611,E0401
from Foundation import NSDate
# pylint: enable=E0611,E0401

# our libs
from . import display
from . import info
from . import osinstaller
from . import prefs
from . import reports
from . import FoundationPlist

try:
    _ = xrange # pylint: disable=xrange-builtin
except NameError:
    # no xrange in Python 3
    xrange = range # pylint: disable=redefined-builtin,invalid-name


# This many hours before a force install deadline, start notifying the user.
FORCE_INSTALL_WARNING_HOURS = 4


def get_installinfo():
    '''Returns the dictionary describing the managed installs and removals'''
    managedinstallbase = prefs.pref('ManagedInstallDir')
    plist = {}
    installinfo = os.path.join(managedinstallbase, 'InstallInfo.plist')
    if os.path.exists(installinfo):
        try:
            plist = FoundationPlist.readPlist(installinfo)
        except FoundationPlist.NSPropertyListSerializationException:
            pass
    return plist


def get_appleupdates():
    '''Returns any available Apple updates'''
    managedinstallbase = prefs.pref('ManagedInstallDir')
    plist = {}
    appleupdatesfile = os.path.join(managedinstallbase, 'AppleUpdates.plist')
    if (os.path.exists(appleupdatesfile) and
            (prefs.pref('InstallAppleSoftwareUpdates') or
             prefs.pref('AppleSoftwareUpdatesOnly'))):
        try:
            plist = FoundationPlist.readPlist(appleupdatesfile)
        except FoundationPlist.NSPropertyListSerializationException:
            pass
    return plist


def oldest_pending_update_in_days():
    '''Return the datestamp of the oldest pending update'''
    pendingupdatespath = os.path.join(
        prefs.pref('ManagedInstallDir'), 'UpdateNotificationTracking.plist')
    try:
        pending_updates = FoundationPlist.readPlist(pendingupdatespath)
    except FoundationPlist.NSPropertyListSerializationException:
        return 0

    oldest_date = now = NSDate.date()
    for category in pending_updates:
        for name in pending_updates[category]:
            this_date = pending_updates[category][name]
            if this_date < oldest_date:
                oldest_date = this_date

    return now.timeIntervalSinceDate_(oldest_date) / (24 * 60 * 60)


def get_pending_update_info():
    '''Returns a dict with some data managedsoftwareupdate records at the end
    of a run'''
    data = {}
    installinfo = get_installinfo()
    data['install_count'] = len(installinfo.get('managed_installs', []))
    data['removal_count'] = len(installinfo.get('removals', []))
    appleupdates = get_appleupdates()
    data['apple_update_count'] = len(appleupdates.get('AppleUpdates', []))
    data['PendingUpdateCount'] = (data['install_count'] + data['removal_count']
                                  + data['apple_update_count'])
    data['OldestUpdateDays'] = oldest_pending_update_in_days()
    # calculate earliest date a forced install is due
    installs = installinfo.get('managed_installs', [])
    installs.extend(appleupdates.get('AppleUpdates', []))
    earliest_date = None
    for install in installs:
        this_force_install_date = install.get('force_install_after_date')

        if this_force_install_date:
            try:
                this_force_install_date = info.subtract_tzoffset_from_date(
                    this_force_install_date)
                if not earliest_date or this_force_install_date < earliest_date:
                    earliest_date = this_force_install_date
            except ValueError:
                # bad date!
                pass
    data['ForcedUpdateDueDate'] = earliest_date
    return data


def get_appleupdates_with_history():
    '''Attempt to find the date Apple Updates were first seen since they can
    appear and disappear from the list of available updates, which screws up
    our tracking of pending updates that can trigger more aggressive update
    notifications.
    Returns a dict.'''

    now = NSDate.date()
    managed_install_dir = prefs.pref('ManagedInstallDir')
    appleupdatehistorypath = os.path.join(
        managed_install_dir, 'AppleUpdateHistory.plist')
    appleupdatesinfo = get_appleupdates().get('AppleUpdates', [])
    history_info = {}
    if appleupdatesinfo:
        try:
            appleupdateshistory = FoundationPlist.readPlist(
                appleupdatehistorypath)
        except FoundationPlist.NSPropertyListSerializationException:
            appleupdateshistory = {}
        history_updated = False
        for item in appleupdatesinfo:
            product_key = item.get('productKey')
            if not product_key:
                continue
            if product_key in appleupdateshistory:
                history_info[item['name']] = (
                    appleupdateshistory[product_key].get('firstSeen', now))
            else:
                history_info[item['name']] = now
                # record this for the future
                appleupdateshistory[product_key] = {
                    'firstSeen': now,
                    'displayName': item.get('display_name', ''),
                    'version': item.get('version_to_install', '')
                }
                history_updated = True
        if history_updated:
            try:
                FoundationPlist.writePlist(
                    appleupdateshistory, appleupdatehistorypath)
            except FoundationPlist.NSPropertyListWriteException:
                # we tried! oh well
                pass
    return history_info


def save_pending_update_times():
    '''Record the time each update first is made available. We can use this to
    escalate our notifications if there are items that have been skipped a lot
    '''
    now = NSDate.date()
    managed_install_dir = prefs.pref('ManagedInstallDir')
    pendingupdatespath = os.path.join(
        managed_install_dir, 'UpdateNotificationTracking.plist')

    installinfo = get_installinfo()
    install_names = [item['name']
                     for item in installinfo.get('managed_installs', [])]
    removal_names = [item['name']
                     for item in installinfo.get('removals', [])]
    apple_updates = get_appleupdates_with_history()
    staged_os_update_names = []
    staged_os_update = osinstaller.get_staged_os_installer_info()
    if staged_os_update and "name" in staged_os_update:
        staged_os_update_names = [staged_os_update["name"]]

    update_names = {
        'managed_installs': install_names,
        'removals': removal_names,
        'AppleUpdates': apple_updates.keys(),
        'StagedOSUpdates': staged_os_update_names
    }

    try:
        prior_pending_updates = FoundationPlist.readPlist(pendingupdatespath)
    except FoundationPlist.NSPropertyListSerializationException:
        prior_pending_updates = {}
    current_pending_updates = {}

    for category in update_names:
        current_pending_updates[category] = {}
        for name in update_names[category]:
            if (category in prior_pending_updates and
                    name in prior_pending_updates[category]):
                # copy the prior datetime from matching item
                current_pending_updates[category][name] = prior_pending_updates[
                    category][name]
            else:
                if category == 'AppleUpdates':
                    current_pending_updates[category][name] = apple_updates[name]
                else:
                    # record new item with current datetime
                    current_pending_updates[category][name] = now

    try:
        FoundationPlist.writePlist(current_pending_updates, pendingupdatespath)
    except FoundationPlist.NSPropertyListWriteException:
        # we tried! oh well
        pass


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

    installinfo = get_installinfo()
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

    installinfo_types = {'InstallInfo.plist': 'managed_installs'}
    if (prefs.pref('InstallAppleSoftwareUpdates') or
            prefs.pref('AppleSoftwareUpdatesOnly')):
        # only consider Apple updates if the prefs say it's OK
        installinfo_types['AppleUpdates.plist'] = 'AppleUpdates'

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
    print('This is a library of support tools for the Munki Suite.')
