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
updatecheck.installationstate

Created by Greg Neagle on 2017-01-01.

Utilities for determining installation status for Munki items.
"""
# This code is largely still compatible with Python 2, so for now, turn off
# Python 3 style warnings
# pylint: disable=consider-using-f-string
# pylint: disable=redundant-u-string-prefix

from __future__ import absolute_import, print_function

import os

from . import catalogs
from . import compare

from .. import display
from .. import osutils
from .. import profiles
from .. import scriptutils
from .. import utils
from ..wrappers import unicode_or_str


def installed_state(item_pl):
    """Checks to see if the item described by item_pl (or a newer version) is
    currently installed

    All tests must pass to be considered installed.
    Returns 1 if it looks like this version is installed
    Returns 2 if it looks like a newer version is installed.
    Returns 0 otherwise.
    """
    foundnewer = False

    if item_pl.get('OnDemand'):
        # always install these items -- retcode 0 means install is needed
        display.display_debug1('This is an OnDemand item. Must install.')
        return 0

    if item_pl.get('installcheck_script'):
        retcode = scriptutils.run_embedded_script(
            'installcheck_script', item_pl, suppress_error=True)
        display.display_debug1('installcheck_script returned %s', retcode)
        # retcode 0 means install is needed
        if retcode == 0:
            return 0
        # non-zero could be an error or successfully indicating
        # that an install is not needed. We hope it's the latter.
        # return 1 so we're marked as not needing to be installed
        return 1

    # this was deprecated a very long time ago. removing 02 Jan 2017
    #if item_pl.get('softwareupdatename'):
    #    available_apple_updates = appleupdates.softwareUpdateList()
    #    display.display_debug2(
    #        'Available Apple updates:\n%s', available_apple_updates)
    #    if item_pl['softwareupdatename'] in available_apple_updates:
    #        display.display_debug1(
    #            '%s is in available Apple Software Updates',
    #            item_pl['softwareupdatename'])
    #        # return 0 so we're marked as needing to be installed
    #        return 0
    #    else:
    #        display.display_debug1(
    #            '%s is not in available Apple Software Updates',
    #            item_pl['softwareupdatename'])
    #        # return 1 so we're marked as not needing to be installed
    #        return 1

    if item_pl.get('installer_type') == 'startosinstall':
        current_os_vers = osutils.getOsVersion()
        item_os_vers = item_pl.get('version')
        if int(item_os_vers.split('.')[0]) > 10:
            # if we're running Big Sur+, we just want the major (11)
            item_os_vers = item_os_vers.split('.')[0]
        else:
            # need just major.minor part of the version -- 10.12 and not 10.12.4
            item_os_vers = '.'.join(item_os_vers.split('.')[0:2])
        comparison = compare.compare_versions(current_os_vers, item_os_vers)
        if comparison == compare.VERSION_IS_LOWER:
            return 0
        if comparison == compare.VERSION_IS_HIGHER:
            return 2
        # version is the same
        return 1

    if item_pl.get('installer_type') == 'stage_os_installer':
        # we return 2 if the installed macOS is the same version or higher than
        # the version of this item
        # we return 1 if the OS installer has already been staged
        # otherwise return 0
        current_os_vers = osutils.getOsVersion()
        item_os_vers = item_pl.get('version')
        if int(item_os_vers.split('.')[0]) > 10:
            # if we're running Big Sur+, we just want the major (11)
            item_os_vers = item_os_vers.split('.')[0]
        else:
            # need just major.minor part of the version -- 10.12 and not 10.12.4
            item_os_vers = '.'.join(item_os_vers.split('.')[0:2])
        comparison = compare.compare_versions(current_os_vers, item_os_vers)
        if comparison in (compare.VERSION_IS_THE_SAME, compare.VERSION_IS_HIGHER):
            return 2
        # installed OS version is lower; check to see if we've staged the installer
        for item in item_pl.get("installs", []):
            try:
                comparison = compare.compare_item_version(item)
                if comparison == compare.VERSION_IS_THE_SAME:
                    return 1
                #else
                return 0
            except utils.Error as err:
                # some problem with the installs data
                display.display_error(unicode_or_str(err))
                # return 1 so we're marked as not needing to be installed
                return 1

    if item_pl.get('installer_type') == 'profile':
        identifier = item_pl.get('PayloadIdentifier')
        hash_value = item_pl.get('installer_item_hash')
        if profiles.profile_needs_to_be_installed(identifier, hash_value):
            return 0
        # does not need to be installed
        return 1

    # does 'installs' exist and is it non-empty?
    if item_pl.get('installs', None):
        installitems = item_pl['installs']
        for item in installitems:
            try:
                comparison = compare.compare_item_version(item)
                if comparison in (-1, 0):
                    return 0
                if comparison == 2:
                    # this item is newer
                    foundnewer = True
            except utils.Error as err:
                # some problem with the installs data
                display.display_error(unicode_or_str(err))
                # return 1 so we're marked as not needing to be installed
                return 1

    # if there is no 'installs' key, then we'll use receipt info
    # to determine install status.
    elif 'receipts' in item_pl:
        receipts = item_pl['receipts']
        for item in receipts:
            try:
                comparison = compare.compare_receipt_version(item)
                if comparison in (-1, 0):
                    # not there or older
                    return 0
                if comparison == 2:
                    foundnewer = True
            except utils.Error as err:
                # some problem with the receipts data
                display.display_error(unicode_or_str(err))
                # return 1 so we're marked as not needing to be installed
                return 1

    # if we got this far, we passed all the tests, so the item
    # must be installed (or we don't have enough info...)
    if foundnewer:
        return 2
    # not newer
    return 1


def some_version_installed(item_pl):
    """Checks to see if some version of an item is installed.

    Args:
      item_pl: item plist for the item to check for version of.

    Returns a boolean.
    """
    if item_pl.get('OnDemand'):
        # These should never be counted as installed
        display.display_debug1('This is an OnDemand item.')
        return False

    if item_pl.get('installcheck_script'):
        retcode = scriptutils.run_embedded_script(
            'installcheck_script', item_pl, suppress_error=True)
        display.display_debug1(
            'installcheck_script returned %s', retcode)
        # retcode 0 means install is needed
        # (ie, item is not installed)
        if retcode == 0:
            return False
        # non-zero could be an error or successfully indicating
        # that an install is not needed. We hope it's the latter.
        return True

    if item_pl.get('installer_type') in ['startosinstall', 'stage_os_installer']:
        # Some version of macOS is always installed!
        return True

    if item_pl.get('installer_type') == 'profile':
        identifier = item_pl.get('PayloadIdentifier')
        return profiles.profile_is_installed(identifier)

    # does 'installs' exist and is it non-empty?
    if item_pl.get('installs'):
        installitems = item_pl['installs']
        # check each item for existence
        for item in installitems:
            try:
                if compare.compare_item_version(item) == 0:
                    # not there
                    return False
            except utils.Error as err:
                # some problem with the installs data
                display.display_error(unicode_or_str(err))
                return False

    # if there is no 'installs' key, then we'll use receipt info
    # to determine install status.
    elif 'receipts' in item_pl:
        receipts = item_pl['receipts']
        for item in receipts:
            try:
                if compare.compare_receipt_version(item) == 0:
                    # not there
                    return False
            except utils.Error as err:
                # some problem with the installs data
                display.display_error(unicode_or_str(err))
                return False

    # if we got this far, we passed all the tests, so the item
    # must be installed (or we don't have enough info...)
    return True


def evidence_this_is_installed(item_pl):
    """Checks to see if there is evidence that the item described by item_pl
    (any version) is currently installed.

    If any tests pass, the item might be installed.
    This is used when determining if we can remove the item, thus
    the attention given to the uninstall method.

    Returns a boolean.
    """
    if item_pl.get('OnDemand'):
        # These should never be counted as installed
        display.display_debug1('This is an OnDemand item.')
        return False

    if item_pl.get('uninstallcheck_script'):
        retcode = scriptutils.run_embedded_script(
            'uninstallcheck_script', item_pl, suppress_error=True)
        display.display_debug1(
            'uninstallcheck_script returned %s', retcode)
        # retcode 0 means uninstall is needed
        # (ie, item is installed)
        if retcode == 0:
            return True
        # non-zero could be an error or successfully indicating
        # that an uninstall is not needed
        return False

    if item_pl.get('installcheck_script'):
        retcode = scriptutils.run_embedded_script(
            'installcheck_script', item_pl, suppress_error=True)
        display.display_debug1(
            'installcheck_script returned %s', retcode)
        # retcode 0 means install is needed
        # (ie, item is not installed)
        if retcode == 0:
            return False
        # non-zero could be an error or successfully indicating
        # that an install is not needed
        return True

    if item_pl.get('installer_type') == 'startosinstall':
        # Some version of macOS is always installed!
        return True

    if item_pl.get('installer_type') == 'profile':
        identifier = item_pl.get('PayloadIdentifier')
        return profiles.profile_is_installed(identifier)

    foundallinstallitems = False
    if ('installs' in item_pl and
            item_pl.get('uninstall_method') != 'removepackages'):
        display.display_debug2("Checking 'installs' items...")
        installitems = item_pl['installs']
        if installitems:
            foundallinstallitems = True
            for item in installitems:
                if 'path' in item:
                    # we can only check by path; if the item has been moved
                    # we're not clever enough to find it, and our removal
                    # methods are currently even less clever
                    if not os.path.exists(item['path']):
                        # this item isn't on disk
                        display.display_debug2(
                            '%s not found on disk.', item['path'])
                        foundallinstallitems = False
        if (foundallinstallitems and
                item_pl.get('uninstall_method') != 'removepackages'):
            return True
    if item_pl.get('receipts'):
        display.display_debug2("Checking receipts...")
        pkgdata = catalogs.analyze_installed_pkgs()
        if item_pl['name'] in pkgdata['installed_names']:
            return True
        #else:
        display.display_debug2("Installed receipts don't match.")

    # if we got this far, we failed all the tests, so the item
    # must not be installed (or we don't have the right info...)
    return False


if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
