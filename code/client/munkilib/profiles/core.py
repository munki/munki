# encoding: utf-8
#
# Copyright 2014-2023 Greg Neagle.
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
profiles.py
Munki module for working with configuration profiles.
"""
from __future__ import absolute_import, print_function

import os
import subprocess
import tempfile

from . import localmcx
from .. import display
from .. import munkihash
from .. import osutils
from .. import prefs
from .. import FoundationPlist


def profiles_supported():
    '''Returns True if config profiles are supported on this OS'''
    darwin_vers = int(os.uname()[2].split('.')[0])
    return darwin_vers > 10


def profile_install_supported():
    '''Returns True if we can install profiles on this OS'''
    darwin_vers = int(os.uname()[2].split('.')[0])
    return darwin_vers > 10 and darwin_vers < 20


def should_emulate_profile_support():
    '''Returns True if admin has indicated we should fake profile support
    on Big Sur+'''
    return prefs.pref('EmulateProfileSupport')


def config_profile_info(ignore_cache=False):
    '''Returns a dictionary representing the output of `profiles -C -o`'''
    if not hasattr(config_profile_info, 'cache'):
        # a place to cache our return value so we don't have to
        # call /usr/bin/profiles again
        config_profile_info.cache = None
    if not profiles_supported():
        config_profile_info.cache = {}
        return config_profile_info.cache
    if not ignore_cache and config_profile_info.cache is not None:
        return config_profile_info.cache
    output_plist = os.path.join(
        tempfile.mkdtemp(dir=osutils.tmpdir()), 'profiles')
    cmd = ['/usr/bin/profiles', '-C', '-o', output_plist]
    # /usr/bin/profiles likes to output errors to stdout instead of stderr
    # so let's redirect everything to stdout and just use that
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    stdout = proc.communicate()[0].decode('UTF-8')
    if proc.returncode != 0:
        display.display_error(
            'Could not obtain configuration profile info: %s' % stdout)
        config_profile_info.cache = {}
    else:
        try:
            config_profile_info.cache = FoundationPlist.readPlist(
                output_plist + '.plist')
        except BaseException as err:
            display.display_error(
                'Could not read configuration profile info: %s' % err)
            config_profile_info.cache = {}
        finally:
            try:
                os.unlink(output_plist + '.plist')
            except BaseException:
                pass
    return config_profile_info.cache


def info_for_installed_identifier(identifier, ignore_cache=False):
    '''Returns the info dict for an installed profile identified by
    identifier, or empty dict if identifier not found.'''
    for profile in config_profile_info(
            ignore_cache=ignore_cache).get('_computerlevel', []):
        if profile['ProfileIdentifier'] == identifier:
            return profile
    return {}


def in_config_profile_info(identifier):
    '''Returns True if identifier is among the installed PayloadIdentifiers,
    False otherwise'''
    for profile in config_profile_info().get('_computerlevel', []):
        if profile['ProfileIdentifier'] == identifier:
            return True
    return False


def profile_receipt_data_path():
    '''Returns the path to our installed profile data store'''
    return os.path.join(
        prefs.pref('ManagedInstallDir'), 'ConfigProfileData.plist')


def profile_receipt_data():
    '''Reads profile install data'''
    try:
        profile_data = FoundationPlist.readPlist(profile_receipt_data_path())
        return profile_data
    except BaseException:
        return {}


def store_profile_receipt_data(identifier, hash_value):
    '''Stores info for profile identifier.
    If hash_value is None, item is removed from the datastore.'''
    profile_data = profile_receipt_data()
    if hash_value is not None:
        profile_dict = info_for_installed_identifier(identifier,
                                                     ignore_cache=True)
        install_date = profile_dict.get('ProfileInstallDate', 'UNKNOWN')
        profile_data[identifier] = {
            'FileHash': hash_value,
            'ProfileInstallDate': install_date
        }
    elif identifier in list(profile_data.keys()):
        del profile_data[identifier]
    try:
        FoundationPlist.writePlist(profile_data, profile_receipt_data_path())
    except BaseException as err:
        display.display_error(
            'Cannot update hash for %s: %s' % (identifier, err))


def read_profile(profile_path):
    '''Reads a profile.'''
    try:
        return FoundationPlist.readPlist(profile_path)
    except FoundationPlist.NSPropertyListSerializationException:
        # possibly a signed profile
        return read_signed_profile(profile_path)
    except BaseException as err:
        display.display_error(
            'Error reading profile %s: %s' % (profile_path, err))
        return {}


def read_signed_profile(profile_path):
    '''Attempts to read a (presumably) signed profile.'''

    # filed for future reference:
    # openssl smime -inform DER -verify -in Signed.mobileconfig
    #                           -noverify -out Unsigned.mobileconfig
    # will strip the signing from a signed profile
    # this might be a better approach
    # from: https://apple.stackexchange.com/questions/105981/
    #       how-do-i-view-or-verify-signed-mobileconfig-files-using-terminal

    # but... we're going to use an Apple-provided tool instead.

    cmd = ['/usr/bin/security', 'cms', '-D', '-i', profile_path]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = proc.communicate()
    if proc.returncode:
        # security cms -D couldn't decode the file
        display.display_error(
            'Error reading profile %s: %s'
            % (profile_path, stderr.decode('UTF-8')))
        return {}
    try:
        return FoundationPlist.readPlistFromString(stdout)
    except FoundationPlist.NSPropertyListSerializationException as err:
        # not a valid plist
        display.display_error(
            'Error reading profile %s: %s' % (profile_path, err))
        return {}


def record_profile_receipt(profile_path, profile_identifier):
    '''Stores a receipt for this profile in our profile tracking plist'''
    profile_hash = munkihash.getsha256hash(profile_path)
    if profile_identifier:
        store_profile_receipt_data(profile_identifier, profile_hash)


def remove_profile_receipt(identifier):
    '''Removes the stored hash for profile with identifier'''
    store_profile_receipt_data(identifier, None)


def get_profile_receipt(profile_identifier):
    '''Returns the receipt dict for profile_identifier'''
    receipt = profile_receipt_data().get(profile_identifier)
    # validate it before returning it
    try:
        # try to get a value for the FileHash key
        dummy = receipt['FileHash']
        return receipt
    except (TypeError, AttributeError, KeyError):
        # invalid receipt!
        return None


def install_profile(profile_path, profile_identifier):
    '''Installs a profile. Returns True on success, False otherwise'''
    if not profile_install_supported():
        if not should_emulate_profile_support():
            display.display_info(
                "Cannot install profiles in this macOS version.")
            return False
        display.display_debug1('Emulating profile install via LocalMCX')
        # create some localmcx instead
        profile_data = read_profile(profile_path)
        if localmcx.install_profile(profile_data):
            # remove any existing profile with the same identifier
            if in_config_profile_info(profile_identifier):
                _remove_profile_basic(profile_identifier)
            record_profile_receipt(profile_path, profile_identifier)
            return True
        return False
    cmd = ['/usr/bin/profiles', '-IF', profile_path]
    # /usr/bin/profiles likes to output errors to stdout instead of stderr
    # so let's redirect everything to stdout and just use that
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    stdout = proc.communicate()[0].decode('UTF-8')
    if proc.returncode != 0:
        display.display_error(
            u'Profile %s installation failed: %s'
            % (os.path.basename(profile_path), stdout))
        return False
    if profile_identifier:
        record_profile_receipt(profile_path, profile_identifier)
    else:
        display.display_warning(
            u'No identifier for profile %s; cannot record an installation '
            'receipt.' % os.path.basename(profile_path))
    return True


def _remove_profile_basic(identifier):
    '''Lower-level profile removal code called a couple of places.
    Returns a boolean to indicate success.'''
    cmd = ['/usr/bin/profiles', '-Rp', identifier]
    # /usr/bin/profiles likes to output errors to stdout instead of stderr
    # so let's redirect everything to stdout and just use that
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    stdout = proc.communicate()[0].decode('UTF-8')
    if proc.returncode != 0:
        display.display_error(
            'Profile %s removal failed: %s' % (identifier, stdout))
        return False
    return True


def remove_profile(identifier):
    '''Removes a profile with the given identifier. Returns True on success,
    False otherwise'''
    if not profiles_supported():
        display.display_info("No support for profiles in this macOS version.")
        return False
    if in_config_profile_info(identifier):
        if _remove_profile_basic(identifier):
            remove_profile_receipt(identifier)
            return True
        return False
    elif localmcx.profile_is_installed(identifier):
        if localmcx.remove_profile(identifier):
            remove_profile_receipt(identifier)
            return True
        return False
    else:
        # no evidence it's installed at all!
        remove_profile_receipt(identifier)
        return True


def profile_needs_to_be_installed(identifier, hash_value):
    '''If any of these conditions is True, we should install the profile:
    1) identifier is not in the output of `profiles -C`
    2) We don't have a receipt for this profile identifier
    3) receipt's hash_value for identifier does not match ours
    4) ProfileInstallDate doesn't match the receipt'''
    if not profile_install_supported():
        if not should_emulate_profile_support():
            display.display_info(
                "Cannot install profiles in this macOS version, so skipping "
                "check, and will treat as already installed.")
            # profile _can't_ be installed so return False
            return False
    if (not in_config_profile_info(identifier) and
            not localmcx.profile_is_installed(identifier)):
        display.display_debug2(
            'Profile identifier %s is not installed.' % identifier)
        return True
    receipt = get_profile_receipt(identifier)
    if not receipt:
        display.display_debug2(
            'No receipt for profile identifier %s.' % identifier)
        return True
    display.display_debug2('Receipt for %s:\n%s' % (identifier, receipt))
    if receipt.get('FileHash') != hash_value:
        display.display_debug2(
            'Receipt FileHash for profile identifier %s does not match.'
            % identifier)
        return True
    installed_dict = info_for_installed_identifier(identifier)
    if (installed_dict and
            installed_dict.get('ProfileInstallDate')
            != receipt.get('ProfileInstallDate')):
        display.display_debug2(
            'Receipt ProfileInstallDate for profile identifier %s does not '
            'match.' % identifier)
        return True
    return False


def profile_is_installed(identifier):
    '''If identifier is in the output of `profiles -C`
    return True, else return False'''
    if not profiles_supported():
        display.display_info("Cannot install profiles in this macOS version.")
        return False
    if in_config_profile_info(identifier):
        display.display_debug2(
            'Profile identifier %s is installed.' % identifier)
        return True
    if localmcx.profile_is_installed(identifier):
        display.display_debug2(
            'Profile identifier %s is installed as localmcx.' % identifier)
        return True
    display.display_debug2(
        'Profile identifier %s is not installed.' % identifier)
    return False


if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
