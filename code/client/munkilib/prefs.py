# encoding: utf-8
#
# Copyright 2009-2024 Greg Neagle.
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
prefs.py

Created by Greg Neagle on 2016-12-13.

Preferences functions and classes used by the munki tools.
"""
from __future__ import absolute_import, print_function

import os

# PyLint cannot properly find names inside Cocoa libraries, so issues bogus
# No name 'Foo' in module 'Bar' warnings. Disable them.
# pylint: disable=E0611
from Foundation import NSDate
from Foundation import CFPreferencesAppSynchronize
from Foundation import CFPreferencesAppValueIsForced
from Foundation import CFPreferencesCopyAppValue
from Foundation import CFPreferencesCopyKeyList
from Foundation import CFPreferencesCopyValue
from Foundation import CFPreferencesSetValue
from Foundation import kCFPreferencesAnyUser
from Foundation import kCFPreferencesAnyHost
from Foundation import kCFPreferencesCurrentUser
from Foundation import kCFPreferencesCurrentHost
# pylint: enable=E0611

from .constants import BUNDLE_ID
from .wrappers import is_a_string

#####################################################
# managed installs preferences/metadata
#####################################################

DEFAULT_INSECURE_REPO_URL = 'http://munki/repo'

DEFAULT_PREFS = {
    'AdditionalHttpHeaders': None,
    'AggressiveUpdateNotificationDays': 14,
    'AppleSoftwareUpdatesIncludeMajorOSUpdates': False,
    'AppleSoftwareUpdatesOnly': False,
    'CatalogURL': None,
    'ClientCertificatePath': None,
    'ClientIdentifier': '',
    'ClientKeyPath': None,
    'ClientResourcesFilename': None,
    'ClientResourceURL': None,
    'DaysBetweenNotifications': 1,
    'EmulateProfileSupport': False,
    'FollowHTTPRedirects': 'none',
    'HelpURL': None,
    'IconURL': None,
    'IgnoreMiddleware': False,
    'IgnoreSystemProxies': False,
    'InstallRequiresLogout': False,
    'InstallAppleSoftwareUpdates': False,
    'LastNotifiedDate': NSDate.dateWithTimeIntervalSince1970_(0),
    'LocalOnlyManifest': None,
    'LogFile': '/Library/Managed Installs/Logs/ManagedSoftwareUpdate.log',
    'LoggingLevel': 1,
    'LogToSyslog': False,
    'ManagedInstallDir': '/Library/Managed Installs',
    'ManifestURL': None,
    'PackageURL': None,
    'PackageVerificationMode': 'hash',
    'PerformAuthRestarts': False,
    'RecoveryKeyFile': None,
    'ShowOptionalInstallsForHigherOSVersions': False,
    'SoftwareRepoCACertificate': None,
    'SoftwareRepoCAPath': None,
    'SoftwareRepoURL': DEFAULT_INSECURE_REPO_URL,
    'SoftwareUpdateServerURL': None,
    'SuppressAutoInstall': False,
    'SuppressLoginwindowInstall': False,
    'SuppressStopButtonOnInstall': False,
    'SuppressUserNotification': False,
    'SuspendDisplaySleepDuringBootstrap': False,
    'UnattendedAppleUpdates': False,
    'UseClientCertificate': False,
    'UseClientCertificateCNAsClientIdentifier': False,
    'UseNotificationCenterDays': 3,
}


class Preferences(object):
    """Class which directly reads/writes Apple CF preferences."""

    def __init__(self, bundle_id, user=kCFPreferencesAnyUser):
        """Init.

        Args:
            bundle_id: str, like 'ManagedInstalls'
        """
        if bundle_id.endswith('.plist'):
            bundle_id = bundle_id[:-6]
        self.bundle_id = bundle_id
        self.user = user

    def __iter__(self):
        """Iterator for keys in the specific 'level' of preferences; this
        will fail to iterate all available keys for the preferences domain
        since OS X reads from multiple 'levels' and composites them."""
        keys = CFPreferencesCopyKeyList(
            self.bundle_id, self.user, kCFPreferencesCurrentHost)
        if keys is not None:
            for i in keys:
                yield i

    def __contains__(self, pref_name):
        """Since this uses CFPreferencesCopyAppValue, it will find a preference
        regardless of the 'level' at which it is stored"""
        pref_value = CFPreferencesCopyAppValue(pref_name, self.bundle_id)
        return pref_value is not None

    def __getitem__(self, pref_name):
        """Get a preference value. Normal OS X preference search path applies"""
        return CFPreferencesCopyAppValue(pref_name, self.bundle_id)

    def __setitem__(self, pref_name, pref_value):
        """Sets a preference. if the user is kCFPreferencesCurrentUser, the
        preference actually gets written at the 'ByHost' level due to the use
        of kCFPreferencesCurrentHost"""
        CFPreferencesSetValue(
            pref_name, pref_value, self.bundle_id, self.user,
            kCFPreferencesCurrentHost)
        CFPreferencesAppSynchronize(self.bundle_id)

    def __delitem__(self, pref_name):
        """Delete a preference"""
        self.__setitem__(pref_name, None)

    def __repr__(self):
        """Return a text representation of the class"""
        return '<%s %s>' % (self.__class__.__name__, self.bundle_id)

    def get(self, pref_name, default=None):
        """Return a preference or the default value"""
        if not pref_name in self:
            return default
        return self.__getitem__(pref_name)


class ManagedInstallsPreferences(Preferences):
    """Preferences which are read using 'normal' OS X preferences precedence:
        Managed Preferences (MCX or Configuration Profile)
        ~/Library/Preferences/ByHost/ManagedInstalls.XXXX.plist
        ~/Library/Preferences/ManagedInstalls.plist
        /Library/Preferences/ManagedInstalls.plist
    Preferences are written to
        /Library/Preferences/ManagedInstalls.plist
    Since this code is usually run as root, ~ is root's home dir"""
    # pylint: disable=too-few-public-methods
    def __init__(self):
        Preferences.__init__(self, 'ManagedInstalls', kCFPreferencesAnyUser)


class SecureManagedInstallsPreferences(Preferences):
    """Preferences which are read using 'normal' OS X preferences precedence:
        Managed Preferences (MCX or Configuration Profile)
        ~/Library/Preferences/ByHost/ManagedInstalls.XXXX.plist
        ~/Library/Preferences/ManagedInstalls.plist
        /Library/Preferences/ManagedInstalls.plist
    Preferences are written to
        ~/Library/Preferences/ByHost/ManagedInstalls.XXXX.plist
    Since this code is usually run as root, ~ is root's home dir"""
    # pylint: disable=too-few-public-methods
    def __init__(self):
        Preferences.__init__(self, 'ManagedInstalls', kCFPreferencesCurrentUser)


def reload_prefs():
    """Uses CFPreferencesAppSynchronize(BUNDLE_ID)
    to make sure we have the latest prefs. Call this
    if you have modified /Library/Preferences/ManagedInstalls.plist
    or /var/root/Library/Preferences/ManagedInstalls.plist directly"""
    CFPreferencesAppSynchronize(BUNDLE_ID)


def set_pref(pref_name, pref_value):
    """Sets a preference, writing it to
    /Library/Preferences/ManagedInstalls.plist.
    This should normally be used only for 'bookkeeping' values;
    values that control the behavior of munki may be overridden
    elsewhere (by MCX, for example)"""
    try:
        CFPreferencesSetValue(
            pref_name, pref_value, BUNDLE_ID,
            kCFPreferencesAnyUser, kCFPreferencesCurrentHost)
        CFPreferencesAppSynchronize(BUNDLE_ID)
    except BaseException:
        pass


def pref(pref_name):
    """Return a preference. Since this uses CFPreferencesCopyAppValue,
    Preferences can be defined several places. Precedence is:
        - MCX/configuration profile
        - /var/root/Library/Preferences/ByHost/ManagedInstalls.XXXXXX.plist
        - /var/root/Library/Preferences/ManagedInstalls.plist
        - /Library/Preferences/ManagedInstalls.plist
        - .GlobalPreferences defined at various levels (ByHost, user, system)
        - default_prefs defined here.
    """
    pref_value = CFPreferencesCopyAppValue(pref_name, BUNDLE_ID)
    if pref_value is None:
        pref_value = DEFAULT_PREFS.get(pref_name)
        # we're using a default value. We'll write it out to
        # /Library/Preferences/<BUNDLE_ID>.plist for admin
        # discoverability
        if pref_value is not None:
            set_pref(pref_name, pref_value)
    if isinstance(pref_value, NSDate):
        # convert NSDate/CFDates to strings
        pref_value = str(pref_value)
    return pref_value


def get_config_level(domain, pref_name, value):
    '''Returns a string indicating where the given preference is defined'''
    if value is None:
        return '[not set]'
    if CFPreferencesAppValueIsForced(pref_name, domain):
        return '[MANAGED]'
    # define all the places we need to search, in priority order
    levels = [
        {'file': ('/var/root/Library/Preferences/ByHost/'
                  '%s.xxxx.plist' % domain),
         'domain': domain,
         'user': kCFPreferencesCurrentUser,
         'host': kCFPreferencesCurrentHost
        },
        {'file': '/var/root/Library/Preferences/%s.plist' % domain,
         'domain': domain,
         'user': kCFPreferencesCurrentUser,
         'host': kCFPreferencesAnyHost
        },
        {'file': ('/var/root/Library/Preferences/ByHost/'
                  '.GlobalPreferences.xxxx.plist'),
         'domain': '.GlobalPreferences',
         'user': kCFPreferencesCurrentUser,
         'host': kCFPreferencesCurrentHost
        },
        {'file': '/var/root/Library/Preferences/.GlobalPreferences.plist',
         'domain': '.GlobalPreferences',
         'user': kCFPreferencesCurrentUser,
         'host': kCFPreferencesAnyHost
        },
        {'file': '/Library/Preferences/%s.plist' % domain,
         'domain': domain,
         'user': kCFPreferencesAnyUser,
         'host': kCFPreferencesCurrentHost
        },
        {'file': '/Library/Preferences/.GlobalPreferences.plist',
         'domain': '.GlobalPreferences',
         'user': kCFPreferencesAnyUser,
         'host': kCFPreferencesCurrentHost
        },
    ]
    for level in levels:
        if (value == CFPreferencesCopyValue(
                pref_name, level['domain'], level['user'], level['host'])):
            return '[%s]' % level['file']
    if value == DEFAULT_PREFS.get(pref_name):
        return '[default]'
    return '[unknown]'


def print_config():
    '''Prints the current Munki configuration'''
    print('Current Munki configuration:')
    max_pref_name_len = max([len(pref_name) for pref_name in DEFAULT_PREFS])
    for pref_name in sorted(DEFAULT_PREFS):
        if pref_name == 'LastNotifiedDate':
            # skip it
            continue
        else:
            value = pref(pref_name)
            where = get_config_level(BUNDLE_ID, pref_name, value)
        repr_value = value
        if is_a_string(value):
            repr_value = repr(value)
        print(('%' + str(max_pref_name_len) + 's: %5s %s ') % (
            pref_name, repr_value, where))
    # also print com.apple.SoftwareUpdate CatalogURL config if
    # Munki is configured to install Apple updates
    if pref('InstallAppleSoftwareUpdates'):
        print('Current Apple softwareupdate configuration:')
        domain = 'com.apple.SoftwareUpdate'
        pref_name = 'CatalogURL'
        value = CFPreferencesCopyAppValue(pref_name, domain)
        where = get_config_level(domain, pref_name, value)
        repr_value = value
        if is_a_string(value):
            repr_value = repr(value)
        print(('%' + str(max_pref_name_len) + 's: %5s %s ') % (
            pref_name, repr_value, where))


if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
