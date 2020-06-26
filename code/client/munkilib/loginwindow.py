# encoding: utf-8
#
# Copyright 2020 Greg Neagle.
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
loginwindow.py

Created by Greg Neagle on 2020-06-26.

Some utilities for dealing with the loginwindow, startup, and restart
"""
from __future__ import absolute_import, print_function

# PyLint cannot properly find names inside Cocoa libraries, so issues bogus
# No name 'Foo' in module 'Bar' warnings. Disable them.
# pylint: disable=no-name-in-module
from CoreFoundation import CFPreferencesCopyValue
from CoreFoundation import kCFPreferencesAnyUser
from CoreFoundation import kCFPreferencesCurrentHost
# pylint: enable=no-name-in-module


# Preference domain for loginwindow.
LOGINWINDOW_PREFS_DOMAIN = 'com.apple.loginwindow'


def get_pref(pref_name):
    """Returns value for pref_name from
    /Library/Preferences/com.apple.loginwindow"""
    return CFPreferencesCopyValue(
        pref_name,
        LOGINWINDOW_PREFS_DOMAIN,
        kCFPreferencesAnyUser, kCFPreferencesCurrentHost)


def just_started_up():
    """Returns a boolean. True if we're at the loginwindow because we
    just started up, and False if because a user logged out or used Fast
    User Switching to switch out to the loginwindow"""
    return get_pref('lastUser') not in ("loggedIn", "loogedOut")
