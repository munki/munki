# encoding: utf-8
# Copyright 2009-2023 Greg Neagle.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
appleupdates.py

Utilities for dealing with Apple Software Update.

"""
from __future__ import absolute_import, print_function

from . import au
from . import su_prefs

from .. import display
from .. import osutils
from .. import prefs

# Make the new appleupdates module easily dropped in with exposed funcs
# for now.

# Disable PyLint complaining about 'invalid' camelCase names
# pylint: disable=C0103

def getAppleUpdatesInstance():
    """Returns either an AppleUpdates instance, either cached or new."""
    if not hasattr(getAppleUpdatesInstance, 'apple_updates_object'):
        getAppleUpdatesInstance.apple_updates_object = au.AppleUpdates()
    return getAppleUpdatesInstance.apple_updates_object


def clearAppleUpdateInfo():
    """Method for drop-in appleupdates replacement; see primary method docs."""
    return getAppleUpdatesInstance().clear_apple_update_info()


def installAppleUpdates(only_unattended=False):
    """Method for drop-in appleupdates replacement; see primary method docs."""
    return getAppleUpdatesInstance().install_apple_updates(
        only_unattended=only_unattended)


def appleSoftwareUpdatesAvailable(forcecheck=False, suppresscheck=False,
                                  client_id='', forcecatalogrefresh=False):
    """Method for drop-in appleupdates replacement; see primary method docs."""
    appleUpdatesObject = getAppleUpdatesInstance()
    os_version_tuple = osutils.getOsVersion(as_tuple=True)
    munkisuscatalog = prefs.pref('SoftwareUpdateServerURL')
    if os_version_tuple >= (10, 11):
        if munkisuscatalog:
            display.display_warning(
                "Custom softwareupdate catalog %s in Munki's preferences will "
                "be ignored." % munkisuscatalog)
    elif su_prefs.catalogurl_is_managed():
        display.display_warning(
            "Cannot efficiently manage Apple Software updates because "
            "softwareupdate's CatalogURL is managed via MCX or profiles. "
            "You may see unexpected or undesirable results.")
    appleUpdatesObject.client_id = client_id
    appleUpdatesObject.force_catalog_refresh = forcecatalogrefresh

    return appleUpdatesObject.software_updates_available(
        force_check=forcecheck, suppress_check=suppresscheck)


def installableUpdates():
    """Returns the list of installable updates, which might not include updates
    that require a restart"""
    return getAppleUpdatesInstance().installable_updates()


def displayAppleUpdateInfo():
    """Method for drop-in appleupdates replacement; see primary method docs."""
    getAppleUpdatesInstance().display_apple_update_info()


if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
