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
su_prefs.py

Created by Greg Neagle on 2017-01-06.

Utilities for working with Apple software update preferences
"""
from __future__ import absolute_import, print_function

import subprocess

# PyLint cannot properly find names inside Cocoa libraries, so issues bogus
# No name 'Foo' in module 'Bar' warnings. Disable them.
# pylint: disable=no-name-in-module
from CoreFoundation import CFPreferencesAppValueIsForced
from CoreFoundation import CFPreferencesCopyAppValue
from CoreFoundation import CFPreferencesCopyKeyList
from CoreFoundation import CFPreferencesCopyValue
from CoreFoundation import CFPreferencesSetValue
from CoreFoundation import CFPreferencesSynchronize
from CoreFoundation import kCFPreferencesAnyUser
#from CoreFoundation import kCFPreferencesCurrentUser
from CoreFoundation import kCFPreferencesCurrentHost
# pylint: enable=no-name-in-module

from .. import display
from .. import osutils

# Preference domain for Apple Software Update.
APPLE_SOFTWARE_UPDATE_PREFS_DOMAIN = 'com.apple.SoftwareUpdate'

# prefs key to store original catalog URL
ORIGINAL_CATALOG_URL_KEY = '_OriginalCatalogURL'


def pref(pref_name):
    """Returns a preference from com.apple.SoftwareUpdate.

    Uses CoreFoundation.

    Args:
      pref_name: str preference name to get.
    """
    return CFPreferencesCopyAppValue(
        pref_name, APPLE_SOFTWARE_UPDATE_PREFS_DOMAIN)


def set_pref(pref_name, value):
    """Sets a value in /Library/Preferences/com.apple.SoftwareUpdate.
    Uses CoreFoundation.
    Args:
       pref_name: str preference name to set.
       valueL value to set it to.
    """
    CFPreferencesSetValue(
        pref_name, value,
        APPLE_SOFTWARE_UPDATE_PREFS_DOMAIN,
        kCFPreferencesAnyUser, kCFPreferencesCurrentHost)


def catalogurl_is_managed():
    """Returns True if Software Update's CatalogURL is managed
    via MCX or Profiles"""
    return CFPreferencesAppValueIsForced(
        'CatalogURL', APPLE_SOFTWARE_UPDATE_PREFS_DOMAIN)


def get_catalogurl():
    """Returns Software Update's CatalogURL"""
    return CFPreferencesCopyValue(
        'CatalogURL',
        APPLE_SOFTWARE_UPDATE_PREFS_DOMAIN,
        kCFPreferencesAnyUser, kCFPreferencesCurrentHost)


def set_custom_catalogurl(catalog_url):
    """Sets Software Update's CatalogURL to custom value, storing the
    original"""
    software_update_key_list = CFPreferencesCopyKeyList(
        APPLE_SOFTWARE_UPDATE_PREFS_DOMAIN,
        kCFPreferencesAnyUser, kCFPreferencesCurrentHost) or []
    if ORIGINAL_CATALOG_URL_KEY not in software_update_key_list:
        # store the original CatalogURL
        original_catalog_url = get_catalogurl()
        if not original_catalog_url:
            # can't store None as a CFPreference
            original_catalog_url = ""
        CFPreferencesSetValue(
            ORIGINAL_CATALOG_URL_KEY,
            original_catalog_url,
            APPLE_SOFTWARE_UPDATE_PREFS_DOMAIN,
            kCFPreferencesAnyUser, kCFPreferencesCurrentHost)
    # now set our custom CatalogURL
    os_version_tuple = osutils.getOsVersion(as_tuple=True)
    if os_version_tuple < (10, 11):
        CFPreferencesSetValue(
            'CatalogURL', catalog_url,
            APPLE_SOFTWARE_UPDATE_PREFS_DOMAIN,
            kCFPreferencesAnyUser, kCFPreferencesCurrentHost)
        # finally, sync things up
        if not CFPreferencesSynchronize(
                APPLE_SOFTWARE_UPDATE_PREFS_DOMAIN,
                kCFPreferencesAnyUser, kCFPreferencesCurrentHost):
            display.display_error(
                'Error setting com.apple.SoftwareUpdate CatalogURL.')
    else:
        # use softwareupdate --set-catalog
        proc = subprocess.Popen(
            ['/usr/sbin/softwareupdate', '--set-catalog', catalog_url],
            bufsize=-1, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        (output, err) = proc.communicate()
        if output:
            display.display_detail(output.decode('UTF-8'))
        if err:
            display.display_error(err.decode('UTF-8'))


def reset_original_catalogurl():
    """Resets SoftwareUpdate's CatalogURL to the original value"""
    software_update_key_list = CFPreferencesCopyKeyList(
        APPLE_SOFTWARE_UPDATE_PREFS_DOMAIN,
        kCFPreferencesAnyUser, kCFPreferencesCurrentHost) or []
    if ORIGINAL_CATALOG_URL_KEY not in software_update_key_list:
        # do nothing
        return
    original_catalog_url = CFPreferencesCopyValue(
        ORIGINAL_CATALOG_URL_KEY,
        APPLE_SOFTWARE_UPDATE_PREFS_DOMAIN,
        kCFPreferencesAnyUser, kCFPreferencesCurrentHost)
    if not original_catalog_url:
        original_catalog_url = None
    # reset CatalogURL to the one we stored
    os_version_tuple = osutils.getOsVersion(as_tuple=True)
    if os_version_tuple < (10, 11):
        CFPreferencesSetValue(
            'CatalogURL', original_catalog_url,
            APPLE_SOFTWARE_UPDATE_PREFS_DOMAIN,
            kCFPreferencesAnyUser, kCFPreferencesCurrentHost)
    else:
        if original_catalog_url:
            # use softwareupdate --set-catalog
            cmd = ['/usr/sbin/softwareupdate',
                   '--set-catalog', original_catalog_url]
        else:
            # use softwareupdate --clear-catalog
            cmd = ['/usr/sbin/softwareupdate', '--clear-catalog']
        proc = subprocess.Popen(cmd, bufsize=-1, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        (output, err) = proc.communicate()
        if output:
            display.display_detail(output.decode('UTF-8'))
        if err:
            display.display_error(err.decode('UTF-8'))

    # remove ORIGINAL_CATALOG_URL_KEY
    CFPreferencesSetValue(
        ORIGINAL_CATALOG_URL_KEY, None,
        APPLE_SOFTWARE_UPDATE_PREFS_DOMAIN,
        kCFPreferencesAnyUser, kCFPreferencesCurrentHost)
    # sync
    if not CFPreferencesSynchronize(
            APPLE_SOFTWARE_UPDATE_PREFS_DOMAIN,
            kCFPreferencesAnyUser, kCFPreferencesCurrentHost):
        display.display_error(
            'Error resetting com.apple.SoftwareUpdate CatalogURL.')


if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
