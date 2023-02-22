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
updatecheck.manifestutils

Created by Greg Neagle on 2016-12-16.


Functions for working with manifest files
"""
from __future__ import absolute_import, print_function

import os

try:
    # Python 2
    from urllib2 import quote
except ImportError:
    # Python 3
    from urllib.parse import quote

from .. import display
from .. import fetch
from .. import info
from .. import keychain
from .. import prefs
from .. import reports
from .. import FoundationPlist
from ..wrappers import unicode_or_str


PRIMARY_MANIFEST_TAG = '_primary_manifest_'


class ManifestException(Exception):
    """Lets us raise an exception when we can't get a manifest."""
    pass


class ManifestInvalidException(ManifestException):
    """Lets us raise an exception when we get an invalid manifest."""
    pass


class ManifestNotRetrievedException(ManifestException):
    """Lets us raise an exception when manifest is not retrieved."""
    pass


class ManifestServerConnectionException(ManifestException):
    """Exception for connection error."""
    pass


def manifests():
    '''Returns our internal _MANIFESTS dict'''
    return _MANIFESTS


def set_manifest(name, path):
    '''Stores path under name in our internal _MANIFESTS dict'''
    _MANIFESTS[name] = path


def get_manifest(manifest_name, suppress_errors=False):
    """Gets a manifest from the server.

    Returns:
      string local path to the downloaded manifest
    Raises:
      fetch.ConnectionError if we can't connect to the server
      ManifestException if we can't get the manifest
    """
    if manifest_name in _MANIFESTS:
        return _MANIFESTS[manifest_name]

    manifestbaseurl = (prefs.pref('ManifestURL') or
                       prefs.pref('SoftwareRepoURL') + '/manifests/')
    if (not manifestbaseurl.endswith('?') and
            not manifestbaseurl.endswith('/')):
        manifestbaseurl = manifestbaseurl + '/'
    manifest_dir = os.path.join(prefs.pref('ManagedInstallDir'),
                                'manifests')

    manifesturl = (
        manifestbaseurl + quote(manifest_name.encode('UTF-8')))

    display.display_debug2('Manifest base URL is: %s', manifestbaseurl)
    display.display_detail('Getting manifest %s...', manifest_name)
    manifestpath = os.path.join(manifest_dir, manifest_name.lstrip('/'))

    # Create the folder the manifest shall be stored in
    destinationdir = os.path.dirname(manifestpath)
    try:
        os.makedirs(destinationdir)
    except OSError as err:
        # OSError will be raised if destinationdir exists, ignore this case
        if not os.path.isdir(destinationdir):
            if not suppress_errors:
                display.display_error(
                    'Could not create folder to store manifest %s: %s',
                    manifest_name, err
                )
            raise ManifestException(err)

    message = 'Retrieving list of software for this machine...'
    try:
        dummy_value = fetch.munki_resource(
            manifesturl, manifestpath, message=message)
    except fetch.ConnectionError as err:
        raise ManifestServerConnectionException(err)
    except fetch.Error as err:
        if not suppress_errors:
            display.display_error(
                'Could not retrieve manifest %s from the server: %s',
                manifest_name, err)
        raise ManifestNotRetrievedException(err)

    try:
        # read plist to see if it is valid
        dummy_data = FoundationPlist.readPlist(manifestpath)
    except FoundationPlist.NSPropertyListSerializationException:
        errormsg = 'manifest returned for %s is invalid.' % manifest_name
        display.display_error(errormsg)
        try:
            os.unlink(manifestpath)
        except (OSError, IOError):
            pass
        raise ManifestInvalidException(errormsg)
    else:
        # plist is valid
        display.display_detail('Retrieved manifest %s', manifest_name)
        _MANIFESTS[manifest_name] = manifestpath
        return manifestpath


def get_primary_manifest(alternate_id=''):
    """Gets the primary client manifest from the server."""
    manifest = ""

    if alternate_id:
        clientidentifier = alternate_id
    elif (prefs.pref('UseClientCertificate') and
          prefs.pref('UseClientCertificateCNAsClientIdentifier')):
        # we're to use the client cert CN as the clientidentifier
        clientidentifier = keychain.get_client_cert_common_name()
    else:
        # get the ClientIdentifier from Munki's preferences
        clientidentifier = prefs.pref('ClientIdentifier')

    if clientidentifier:
        manifest = get_manifest(clientidentifier)
    else:
        # no client identifier specified, so try the hostname
        hostname = unicode_or_str(os.uname()[1])
        # os.uname()[1] seems to always return UTF-8 for hostnames that
        # contain unicode characters, so we decode to Unicode
        clientidentifier = hostname
        display.display_detail(
            'No client id specified. Requesting %s...', clientidentifier)
        try:
            manifest = get_manifest(clientidentifier, suppress_errors=True)
        except ManifestNotRetrievedException:
            pass

        if not manifest:
            # try the short hostname
            clientidentifier = hostname.split('.')[0]
            if clientidentifier:
                # need this test because of crazy people who give their
                # machines hostnames that start with a period!
                display.display_detail(
                    'Request failed. Trying %s...', clientidentifier)
                try:
                    manifest = get_manifest(
                        clientidentifier, suppress_errors=True)
                except ManifestNotRetrievedException:
                    pass

        if not manifest:
            # try the machine serial number
            clientidentifier = info.get_serial_number() or 'UNKNOWN'
            if clientidentifier != 'UNKNOWN':
                display.display_detail(
                    'Request failed. Trying %s...', clientidentifier)
                try:
                    manifest = get_manifest(
                        clientidentifier, suppress_errors=True)
                except ManifestNotRetrievedException:
                    pass

        if not manifest:
            # last resort - try for the site_default manifest
            clientidentifier = 'site_default'
            display.display_detail(
                'Request failed. Trying %s...', clientidentifier)
            manifest = get_manifest(clientidentifier, suppress_errors=True)

    # record this info for later
    # primary manifest is tagged as PRIMARY_MANIFEST_TAG
    _MANIFESTS[PRIMARY_MANIFEST_TAG] = manifest
    reports.report['ManifestName'] = clientidentifier
    display.display_detail('Using manifest: %s', clientidentifier)
    return manifest


def clean_up_manifests():
    """Removes any manifest files that are no longer in use by this client"""
    manifest_dir = os.path.join(
        prefs.pref('ManagedInstallDir'), 'manifests')

    exceptions = [
        "SelfServeManifest"
    ]

    for (dirpath, dummy_dirnames, filenames) in os.walk(
            manifest_dir, topdown=False):
        for name in filenames:

            if name in exceptions:
                continue

            abs_path = os.path.join(dirpath, name)
            rel_path = abs_path[len(manifest_dir):].lstrip("/")

            if rel_path not in _MANIFESTS:
                os.unlink(abs_path)

        # If the directory isn't the main manifest dir and is empty, try to
        # remove it
        if dirpath != manifest_dir and not os.listdir(dirpath):
            try:
                os.rmdir(dirpath)
            except OSError:
                pass


def get_manifest_data(manifestpath):
    '''Reads a manifest file, returns a dictionary-like object.'''
    plist = {}
    try:
        plist = FoundationPlist.readPlist(manifestpath)
    except FoundationPlist.NSPropertyListSerializationException:
        display.display_error(u'Could not read plist: %s', manifestpath)
        if os.path.exists(manifestpath):
            try:
                os.unlink(manifestpath)
            except OSError as err:
                display.display_error(u'Failed to delete plist: %s', err)
        else:
            display.display_error('plist does not exist.')
    return plist


def get_manifest_value_for_key(manifestpath, keyname):
    """Returns a value for keyname in manifestpath"""
    plist = get_manifest_data(manifestpath)
    try:
        return plist.get(keyname, None)
    except AttributeError as err:
        display.display_error(
            u'Failed to get manifest value for key: %s (%s)',
            manifestpath, keyname)
        display.display_error(u'Manifest is likely corrupt: %s', err)
        return None


def remove_from_selfserve_section(itemname, section):
    """Remove the given itemname from the self-serve manifest's
    managed_uninstalls list"""
    display.display_debug1(
        "Removing %s from SelfServeManifest's %s...", itemname, section)
    selfservemanifest = os.path.join(
        prefs.pref('ManagedInstallDir'), 'manifests', 'SelfServeManifest')
    if not os.path.exists(selfservemanifest):
        # SelfServeManifest doesn't exist, bail
        display.display_debug1("%s doesn't exist.", selfservemanifest)
        return
    try:
        plist = FoundationPlist.readPlist(selfservemanifest)
    except FoundationPlist.FoundationPlistException as err:
        # SelfServeManifest is broken, bail
        display.display_debug1(
            "Error reading %s: %s", selfservemanifest, err)
        return
    # make sure the section is in the plist
    if section in plist:
        # filter out our item
        plist[section] = [
            item for item in plist[section] if item != itemname
        ]
        try:
            FoundationPlist.writePlist(plist, selfservemanifest)
        except FoundationPlist.FoundationPlistException as err:
            display.display_debug1(
                "Error writing %s: %s", selfservemanifest, err)


def remove_from_selfserve_installs(itemname):
    """Remove the given itemname from the self-serve manifest's
    managed_installs list"""
    remove_from_selfserve_section(itemname, 'managed_installs')


def remove_from_selfserve_uninstalls(itemname):
    """Remove the given itemname from the self-serve manifest's
    managed_uninstalls list"""
    # pylint: disable=invalid-name
    remove_from_selfserve_section(itemname, 'managed_uninstalls')


# module globals
_MANIFESTS = {}

if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
