#!/usr/bin/python
# encoding: utf-8
#
# Copyright 2014 Greg Neagle.
#
# Licensed under the Apache License, Version 2.0 (the 'License');
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an 'AS IS' BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
keychain

Created by Greg Neagle on 2014-06-09.
Incorporating work and ideas from Michael Lynn here:
    https://gist.github.com/pudquick/7704254

"""

import os
import re
import stat
import subprocess
import sys

import munkicommon


DEFAULT_KEYCHAIN_NAME = 'munki.keychain'
DEFAULT_KEYCHAIN_PASSWORD = 'munki'
KEYCHAIN_DIRECTORY = os.path.join(
    munkicommon.pref('ManagedInstallDir'), 'Keychains')


def debug_output():
    '''Debugging output for keychain'''
    try:
        munkicommon.display_info('***Keychain list***')
        munkicommon.display_info(security('list-keychains', '-d', 'user'))
        munkicommon.display_info('***Default keychain info***')
        munkicommon.display_info(security('default-keychain', '-d', 'user'))
        keychainfile = get_keychain_path()
        if os.path.exists(keychainfile):
            munkicommon.display_info('***Info for %s***' % keychainfile)
            munkicommon.display_info(
                security('show-keychain-info', keychainfile))
    except SecurityError, err:
        munkicommon.display_info(str(err))


class SecurityError(Exception):
    '''An exception class to raise if there is an error running
    /usr/bin/security'''
    pass


def security(verb_name, *args):
    '''Runs the security binary with args. Returns stdout.
    Raises SecurityError for a non-zero return code'''
    cmd = ['/usr/bin/security', verb_name] + list(args)
    proc = subprocess.Popen(
        cmd, shell=False, bufsize=-1,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (output, err) = proc.communicate()
    if proc.returncode:
        raise SecurityError('%s: %s' % (proc.returncode, err))
    return output or err


def get_keychain_path():
    '''Returns an absolute path for our keychain'''
    keychain_name = (
        munkicommon.pref('KeychainName') or DEFAULT_KEYCHAIN_NAME)
    # If we have an odd path that appears to be all directory and no
    # file name, revert to default filename
    if not os.path.basename(keychain_name):
        keychain_name = DEFAULT_KEYCHAIN_NAME
    # Check to make sure it's just a simple file name, no directory
    # information
    if os.path.dirname(keychain_name):
        # keychain name should be just the filename,
        # so we'll drop down to the base name
        keychain_name = os.path.basename(
            keychain_name).strip() or DEFAULT_KEYCHAIN_NAME
    # Correct the filename to include '.keychain' if not already present
    if not keychain_name.lower().endswith('.keychain'):
        keychain_name += '.keychain'
    keychain_path = os.path.realpath(
        os.path.join(KEYCHAIN_DIRECTORY, keychain_name))
    return keychain_path


class MunkiKeychain(object):

    keychain_path = None
    added_keychain = False

    def __init__(self):
        '''Unlocks the munki.keychain if it exists.
        Makes sure the munki.keychain is in the search list.'''
        self.keychain_path = get_keychain_path()
        keychain_pass = (
            munkicommon.pref('KeychainPassword') or DEFAULT_KEYCHAIN_PASSWORD)

        if os.path.exists(self.keychain_path):
            self.ensure_in_search_list()
            try:
                output = security(
                    'unlock-keychain', '-p', keychain_pass, self.keychain_path)
            except SecurityError, err:
                # some problem unlocking the keychain.
                munkicommon.display_error(
                    'Could not unlock %s: %s.' % (self.keychain_path, err))
                self.keychain_path = None
                return
            try:
                output = security('set-keychain-settings', self.keychain_path)
            except SecurityError, err:
                munkicommon.display_error(
                    'Could not set keychain settings for %s: %s'
                    % (self.keychain_path, err))
        if not os.path.exists(self.keychain_path):
            self.keychain_path = None

    def __del__(self):
        '''Remove our keychain from the keychain list if we added it'''
        if self.added_keychain:
            self.remove_from_search_list()

    def ensure_in_search_list(self):
        '''Ensure the keychain is in the search path.'''
        self.added_keychain = False
        output = security('list-keychains', '-d', 'user')
        # Split the output and strip it of whitespace and leading/trailing
        # quotes, the result are absolute paths to keychains
        # Preserve the order in case we need to append to them
        search_keychains = [x.strip().strip('"')
                            for x in output.split('\n') if x.strip()]
        if not self.keychain_path in search_keychains:
            # Keychain is not in the search paths
            munkicommon.display_debug1('Adding keychain to search path...')
            search_keychains.append(self.keychain_path)
            try:
                output = security(
                    'list-keychains', '-d', 'user', '-s', *search_keychains)
                self.added_keychain = True
            except SecurityError, err:
                munkicommon.display_error(
                    'Could not add keychain %s to keychain list: %s'
                    % (self.keychain_path, err))
                self.added_keychain = False

    def remove_from_search_list(self):
        '''Remove our keychain from the list of keychains'''
        output = security('list-keychains', '-d', 'user')
        # Split the output and strip it of whitespace and leading/trailing
        # quotes, the result are absolute paths to keychains
        # Preserve the order in case we need to append to them
        search_keychains = [x.strip().strip('"')
                            for x in output.split('\n') if x.strip()]
        if self.keychain_path in search_keychains:
            # Keychain is in the search path
            munkicommon.display_debug1(
                'Removing %s from search path...' % self.keychain_path)
            filtered_keychains = [keychain for keychain in search_keychains
                                  if keychain != self.keychain_path]
            try:
                output = security(
                    'list-keychains', '-d', 'user', '-s', *filtered_keychains)
                self.added_keychain = False
            except SecurityError, err:
                munkicommon.display_error(
                    'Could not set new keychain list: %s' % err)
