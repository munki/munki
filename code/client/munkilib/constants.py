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
constants.py

Created by Greg Neagle on 2016-12-14.

Commonly used constants
"""
from __future__ import absolute_import, print_function

# NOTE: it's very important that defined exit codes are never changed!
# Preflight exit codes.
EXIT_STATUS_PREFLIGHT_FAILURE = 1  # Python crash yields 1.
# Client config exit codes.
EXIT_STATUS_OBJC_MISSING = 100
EXIT_STATUS_MUNKI_DIRS_FAILURE = 101
# Server connection exit codes.
EXIT_STATUS_SERVER_UNAVAILABLE = 150
# User related exit codes.
EXIT_STATUS_INVALID_PARAMETERS = 200
EXIT_STATUS_ROOT_REQUIRED = 201

BUNDLE_ID = 'ManagedInstalls'
# the following two items are not used internally by Munki
# any longer, but remain for backwards compatibility with
# pre and postflight script that might access these files directly
MANAGED_INSTALLS_PLIST_PATH = '/Library/Preferences/' + BUNDLE_ID + '.plist'
SECURE_MANAGED_INSTALLS_PLIST_PATH = \
    '/private/var/root/Library/Preferences/' + BUNDLE_ID + '.plist'

ADDITIONAL_HTTP_HEADERS_KEY = 'AdditionalHttpHeaders'

LOGINWINDOW = (
    '/System/Library/CoreServices/loginwindow.app/Contents/MacOS/loginwindow')

CHECKANDINSTALLATSTARTUPFLAG = (
    '/Users/Shared/.com.googlecode.munki.checkandinstallatstartup')
INSTALLATSTARTUPFLAG = '/Users/Shared/.com.googlecode.munki.installatstartup'
INSTALLATLOGOUTFLAG = '/private/tmp/com.googlecode.munki.installatlogout'

# postinstall actions
POSTACTION_NONE = 0
POSTACTION_LOGOUT = 1
POSTACTION_RESTART = 2
POSTACTION_SHUTDOWN = 4


if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
