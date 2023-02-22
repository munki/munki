# encoding: utf-8
#
# Copyright 2017-2023 Greg Neagle.
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
bootstrapping

Created by Greg Neagle on 2017-08-31.

Functions supporting bootstrapping mode
"""
from __future__ import absolute_import

import os

# PyLint cannot properly find names inside Cocoa libraries, so issues bogus
# No name 'Foo' in module 'Bar' warnings. Disable them.
# pylint: disable=E0611
from Foundation import CFPreferencesAppSynchronize
from Foundation import CFPreferencesCopyValue
from Foundation import CFPreferencesSetValue
from Foundation import kCFPreferencesAnyUser
from Foundation import kCFPreferencesCurrentHost
# pylint: enable=E0611

from . import constants


class SetupError(Exception):
    '''Error to raise when we can not set up bootstrapping'''
    pass


def disable_fde_autologin():
    '''Disables autologin to the unlocking user's account on a FileVault-
    encrypted machines.'''

    # See https://support.apple.com/en-us/HT202842
    # We attempt to store the original value of com.apple.loginwindow
    # DisableFDEAutoLogin so if the local admin has set it to True for #reasons
    # we don't inadvertently clear it when clearing bootstrap mode

    # is OriginalDisableFDEAutoLogin already set? If so, bootstrap mode was
    # already enabled, and never properly cleared. Don't stomp on it.
    original_value = CFPreferencesCopyValue(
        'OriginalDisableFDEAutoLogin', 'com.apple.loginwindow',
        kCFPreferencesAnyUser, kCFPreferencesCurrentHost)
    if not original_value:
        # get the current value of DisableFDEAutoLogin if any
        original_value = CFPreferencesCopyValue(
            'DisableFDEAutoLogin', 'com.apple.loginwindow',
            kCFPreferencesAnyUser, kCFPreferencesCurrentHost)
        if not original_value:
            # we need a way to record the original value was not set,
            # and we can't store None...
            original_value = '<not set>'
        # store it so we can restore it later
        CFPreferencesSetValue(
            'OriginalDisableFDEAutoLogin', original_value,
            'com.apple.loginwindow',
            kCFPreferencesAnyUser, kCFPreferencesCurrentHost)
    # set com.apple.loginwindow DisableFDEAutoLogin to True
    CFPreferencesSetValue(
        'DisableFDEAutoLogin', True, 'com.apple.loginwindow',
        kCFPreferencesAnyUser, kCFPreferencesCurrentHost)
    CFPreferencesAppSynchronize('com.apple.loginwindow')


def reset_fde_autologin():
    '''Resets the state of com.apple.loginwindow DisableFDEAutoLogin to its
    value before we set it to True'''
    # get the previous value of DisableFDEAutoLogin if any
    original_value = CFPreferencesCopyValue(
        'OriginalDisableFDEAutoLogin', 'com.apple.loginwindow',
        kCFPreferencesAnyUser, kCFPreferencesCurrentHost)
    if original_value == '<not set>':
        original_value = None
    # reset DisableFDEAutoLogin to original value (if original_value is None,
    # the key gets deleted)
    CFPreferencesSetValue(
        'DisableFDEAutoLogin', original_value, 'com.apple.loginwindow',
        kCFPreferencesAnyUser, kCFPreferencesCurrentHost)
    # delete the OriginalDisableFDEAutoLogin key
    CFPreferencesSetValue(
        'OriginalDisableFDEAutoLogin', None, 'com.apple.loginwindow',
        kCFPreferencesAnyUser, kCFPreferencesCurrentHost)
    CFPreferencesAppSynchronize('com.apple.loginwindow')


def set_bootstrap_mode():
    '''Set up bootstrap mode'''
    # turn off auto login of FV unlocking user
    disable_fde_autologin()
    # create CHECKANDINSTALLATSTARTUPFLAG file
    try:
        open(constants.CHECKANDINSTALLATSTARTUPFLAG, 'w').close()
    except (OSError, IOError) as err:
        reset_fde_autologin()
        raise SetupError(
            'Could not create bootstrapping flag file: %s' % err)


def clear_bootstrap_mode():
    '''Clear bootstrap mode'''
    reset_fde_autologin()
    if os.path.exists(constants.CHECKANDINSTALLATSTARTUPFLAG):
        try:
            os.unlink(constants.CHECKANDINSTALLATSTARTUPFLAG)
        except OSError as err:
            raise SetupError(
                'Could not remove bootstrapping flag file: %s' % err)
