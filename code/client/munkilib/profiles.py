#!/usr/bin/python
# encoding: utf-8
#
# Copyright 2014 Greg Neagle.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
profiles.py
Munki module for working with configuration profiles.
"""

import os
import subprocess
import tempfile

import FoundationPlist
import munkicommon


CONFIG_PROFILE_INFO = None
def config_profile_info():
    '''Returns a dictionary representing the output of `profiles -C -o`'''
    global CONFIG_PROFILE_INFO
    if CONFIG_PROFILE_INFO is not None:
        return CONFIG_PROFILE_INFO
    output_plist = tempfile.mkdtemp(dir=munkicommon.tmpdir())
    cmd = ['/usr/bin/profiles', '-C', '-o', output_plist]
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    proc.communicate()
    if proc.returncode != 0:
        munkicommon.display_error(
            'Could not obtain configuration profile info: %s' % proc.stderr)
        CONFIG_PROFILE_INFO = {}
    else:
        try:
            CONFIG_PROFILE_INFO = FoundationPlist.readPlist(
                output_plist + '.plist')
        except BaseException, err:
            munkicommon.display_error(
                'Could not read configuration profile info: %s' % err)
            CONFIG_PROFILE_INFO = {}
        finally:
            try:
                os.unlink(output_plist + '.plist')
            except BaseException:
                pass
        return CONFIG_PROFILE_INFO


def identifier_in_config_profile_info(identifier):
    '''Returns True if identifier is among the installed PayloadIdentifiers,
    False otherwise'''
    for profile in config_profile_info().get('_computerlevel', []):
        if profile['ProfileIdentifier'] == identifier:
            return True
    return False


def profile_data_path():
    '''Returns the path to our installed profile data store'''
    ManagedInstallDir = munkicommon.pref('ManagedInstallDir')
    return os.path.join(ManagedInstallDir, 'ConfigProfileData.plist')


def profile_install_data():
    '''Reads profile install data'''
    try:
        profile_data = FoundationPlist.readPlist(profile_data_path())
        return profile_data
    except BaseException:
        return {}


def store_profile_install_data(identifier, hash_value):
    '''Stores file hash info for profile identifier.
    If hash_value is None, item is removed from the datastore.'''
    profile_data = profile_install_data()
    if hash_value is not None:
        profile_data[identifier] = hash_value
    elif identifier in profile_data.keys():
        del profile_data[identifier]
    try:
        FoundationPlist.writePlist(profile_data, profile_data_path())
    except BaseException, err:
        munkicommon.display_error(
            'Cannot update hash for %s: %s' % (identifier, err))


def read_profile(profile_path):
    '''Reads a profile. Currently supports only unsigned, unencrypted
    profiles'''
    try:
        return FoundationPlist.readPlist(profile_path)
    except BaseException, err:
        munkicommon.display_error(
            'Error reading profile %s: %s' % (profile_path, err))
        return {}


def record_profile_hash(profile_path):
    '''Stores a file hash for this profile in our profile tracking plist'''
    profile_identifier = read_profile(profile_path).get('PayloadIdentifier')
    profile_hash = munkicommon.getsha256hash(profile_path)
    if profile_identifier:
        store_profile_install_data(profile_identifier, profile_hash)


def remove_profile_hash(identifier):
    '''Removes the stored hash for profile with identifier'''
    store_profile_install_data(identifier, None)


def get_profile_hash(profile_identifier):
    '''Returns the hash for profile_identifier'''
    return profile_install_data().get(profile_identifier)


def install_profile(profile_path):
    '''Installs a profile. Returns True on success, False otherwise'''
    cmd = ['/usr/bin/profiles', '-IF', profile_path]
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    proc.communicate()
    if proc.returncode != 0:
        munkicommon.display_error(
            'Profile %s installation failed: %s'
            % (os.path.basename(profile_path), proc.stderr))
        return False
    record_profile_hash(profile_path)
    return True


def remove_profile(identifier):
    '''Removes a profile with the given identifier. Returns True on success,
    False otherwise'''
    cmd = ['/usr/bin/profiles', '-Rp', identifier]
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    proc.communicate()
    if proc.returncode != 0:
        munkicommon.display_error(
            'Profile %s removal failed: %s' % (identifier, proc.stderr))
        return False
    remove_profile_hash(identifier)
    return True


def profile_needs_to_be_installed(identifier, hash_value):
    '''If either condition is True, we should install the profile:
    1) identifier is not in the output of `profiles -C`
    2) stored hash_value for identifier does not match ours'''
    if not identifier_in_config_profile_info(identifier):
        return True
    if get_profile_hash(identifier) != hash_value:
        return True
    return False


def profile_is_installed(identifier):
    '''If identifier is in the output of `profiles -C`
    return True, else return False'''
    if identifier_in_config_profile_info(identifier):
        return True
    return False
