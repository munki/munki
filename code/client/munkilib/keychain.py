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
Based on work by Michael Lynn here: https://gist.github.com/pudquick/7704254

"""

import os
import subprocess
import re

import munkicommon


DEFAULT_KEYCHAIN_NAME = 'munki.keychain'
DEFAULT_KEYCHAIN_PASSWORD = 'munki'


def read_file(pathname):
    '''Return the contents of pathname as a string'''
    try:
        fileobj = open(pathname, mode='r')
        data = fileobj.read()
        fileobj.close()
        return data
    except (OSError, IOError), err:
        munkicommon.display_error(
            'Could not read %s: %s' % (pathname, err))
        return ''


def write_file(stringdata, pathname):
    '''Writes stringdata to pathname.
    Returns the pathname on success, empty string on failure.'''
    try:
        fileobject = open(pathname, mode='w')
        fileobject.write(stringdata)
        fileobject.close()
        return pathname
    except (OSError, IOError), err:
        display_error("Couldn't write %s to %s: %s"
                      % (stringdata, pathname, err))
        return ''

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
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (output, err) = proc.communicate()
    if proc.returncode:
        raise SecurityError('%s: %s' % (proc.returncode, err))
    return output or err


def debug_output():
    '''Debugging output for keychain'''
    try:
        munkicommon.display_info('***Keychain list***')
        munkicommon.display_info(security('list-keychains', '-d', 'user'))
        munkicommon.display_info('***Default keychain info***')
        munkicommon.display_info(security('default-keychain', '-d', 'user'))
        keychainfile = keychain_path()
        munkicommon.display_info('***Info for %s***' % keychainfile)
        munkicommon.display_info(
                        security('show-keychain-info', keychainfile))
        munkicommon.display_info('***Info for System.keychain***')
        munkicommon.display_info(
                        security('show-keychain-info', 
                                 '/Library/Keychains/System.keychain'))
    except SecurityError, err:
        munkicommon.display_info(str(err))


def keychain_path():
    '''Returns an absolute path for our keychain'''
    keychain_name = munkicommon.pref('KeychainName') or DEFAULT_KEYCHAIN_NAME
    # If we have an odd path that appears to be all directory and no file name,
    # revert to default filename
    if not os.path.basename(keychain_name):
        keychain_name = DEFAULT_KEYCHAIN_NAME
    # Check to make sure it's just a simple file name, no directory information
    if os.path.dirname(keychain_name):
        # keychain name should be just the filename,
        # so we'll drop down to the base name
        keychain_name = os.path.basename(
                                keychain_name).strip() or DEFAULT_KEYCHAIN_NAME
    # Correct the filename to include '.keychain' if not already present
    if not keychain_name.lower().endswith('.keychain'):
        keychain_name += '.keychain'
    # make full path
    abs_keychain_path = os.path.realpath(
        os.path.join(os.path.expanduser('/Library/Keychains'), keychain_name))
    return abs_keychain_path


def ensure_keychain_is_in_search_list(abs_keychain_path):
    # Check to make sure the keychain is in the search path
    try:
        output = security('list-keychains', '-d', 'user')
    except SecurityError, err:
        munkicommon.display_error(
            'Could not list keychain search path: %s' % err)
        return
    # Split the output and strip it of whitespace and leading/trailing quotes,
    # the result are absolute paths to keychains
    # Preserve the order in case we need to append to them
    search_keychains = [x.strip().strip('"') 
                        for x in output.split('\n') if x.strip()]
    if not abs_keychain_path in search_keychains:
        # Keychain is not in the search paths
        search_keychains.append(abs_keychain_path)
        try:
            output = security(
                        'list-keychains', '-d', 'user', '-s', *search_keychains)
        except SecurityError, err:
            munkicommon.display_error(
                'Could not add %s to keychain search path: %s' 
                % (abs_keychain_path, err))


def setup():
    '''Unlocks the Munki's keychain if it exists; creating it if needed'''
    abs_keychain_path = keychain_path()
    keychain_pass = (
        munkicommon.pref('KeychainPassword') or DEFAULT_KEYCHAIN_PASSWORD)
    if os.path.exists(abs_keychain_path):
        ensure_keychain_is_in_search_list(abs_keychain_path)
        try:
            output = security(
                    'unlock-keychain', '-p', keychain_pass, abs_keychain_path)
        except SecurityError, err:
            # some problem unlocking the keychain. We should move this
            # keychain aside and try to build a new one
            munkicommon.display_error(
                'Could not unlock %s: %s' % (abs_keychain_path, err))
            try:
                os.rename(abs_keychain_path, abs_keychain_path + '.previous')
            except OSError, err:
                munkicommon.display_error(
                    'Could not rename %s: %s' % (abs_keychain_path, err))
                try:
                    os.unlink(abs_keychain_path)
                except OSError, err:
                    munkicommon.display_error(
                        'Could not remove %s: %s' % (abs_keychain_path, err))
                    # we've failed completely
                    return
        try:
            output = security('set-keychain-settings', abs_keychain_path)
        except SecurityError, err:
            munkicommon.display_error(
                'Could not set keychain settings for %s: %s' 
                % (abs_keychain_path, err))
    if not os.path.exists(abs_keychain_path):
        make_keychain(abs_keychain_path)
    elif munkicommon.verbose > 2:
        debug_output()


def make_keychain(abs_keychain_path):
    '''Builds a keychain for use by managedsoftwareupdate'''

    # find existing cert/CA info
    ManagedInstallDir = munkicommon.pref('ManagedInstallDir')

    # get server CA cert if it exists
    ca_cert_path = None
    ca_dir_path = None
    if munkicommon.pref('SoftwareRepoCAPath'):
        CA_path = munkicommon.pref('SoftwareRepoCAPath')
        if os.path.isfile(CA_path):
            ca_cert_path = CA_path
        elif os.path.isdir(CA_path):
            ca_dir_path = CA_path
    if munkicommon.pref('SoftwareRepoCACertificate'):
        ca_cert_path = munkicommon.pref('SoftwareRepoCACertificate')
    if ca_cert_path == None:
        ca_cert_path = os.path.join(ManagedInstallDir, 'certs', 'ca.pem')
        if not os.path.exists(ca_cert_path):
            ca_cert_path = None

    client_cert_path = None
    client_key_path = None
    # get client cert if it exists
    if munkicommon.pref('UseClientCertificate'):
        client_cert_path = munkicommon.pref('ClientCertificatePath') or None
        client_key_path = munkicommon.pref('ClientKeyPath') or None
        if not client_cert_path:
            for name in ['cert.pem', 'client.pem', 'munki.pem']:
                client_cert_path = os.path.join(ManagedInstallDir, 'certs',
                                                                    name)
                if os.path.exists(client_cert_path):
                    break

    if (not ca_cert_path and not ca_dir_path 
        and not client_cert_path and not client_key_path):
        # no existing CA/cert info, so nothing to do
        return

    keychain_pass = (
        munkicommon.pref('KeychainPassword') or DEFAULT_KEYCHAIN_PASSWORD)
    try:
        # create a new keychain
        output = security(
                    'create-keychain', '-p', keychain_pass, abs_keychain_path)
        # make sure it's in the keychain search list
        ensure_keychain_is_in_search_list(abs_keychain_path)
        # Configure the keychain as unlocked and non-locking
        output = security(
                    'unlock-keychain', '-p', keychain_pass, abs_keychain_path)
        output = security('set-keychain-settings', abs_keychain_path)
    except SecurityError, err:
        munkicommon.display_error(
            'Error setting up keychain %s: %s' % (abs_keychain_path, err))
        return

    # CA certs
    if ca_cert_path:
        try:
            output = security(
                'add-trusted-cert', '-d', '-k', abs_keychain_path, ca_cert_path)
        except SecurityError, err:
            munkicommon.display_error(
                'Error importing %s: %s' % (ca_cert_path, err))
    if ca_dir_path:
        # import any pem files in the ca_dir_path directory
        for item in os.listdir(ca_dir_path):
            if item.endswith('.pem'):
                cert_path = os.path.join(ca_dir_path, item)
                try:
                    output = security(
                        'add-trusted-cert', '-d', '-k', abs_keychain_path, 
                        cert_path)
                except SecurityError, err:
                    munkicommon.display_error(
                                'Error importing %s: %s' % (cert_path, err))

    # client cert (and optionally key)
    if client_cert_path:
        if client_key_path:
            # combine client cert and private key before we import
            cert_data = read_file(client_cert_path)
            key_data = read_file(client_key_path)
            # write the combined data
            pem_file = os.path.join(munkicommon.tmpdir, 'combined.pem')
            if not write_file(cert_data + key_data, pem_file):
                munkicommon.display_error('Error writing %s' % pem_file)
        else:
            pem_file = client_cert_path
        try:
            output = security('import', pem_file, '-k', abs_keychain_path)
        except SecurityError, err:
            munkicommon.display_error(
                        'Error importing %s: %s' % (pem_file, err))

    munki_repo = munkicommon.pref('SoftwareRepoURL').rstrip('/') + '/'
    # Set up an identity if it doesn't exist already for our site
    # First we need to find the existing identity in our keychain
    output = security('find-identity', abs_keychain_path)
    if ' 1 identities found' in output:
        # We have a solitary match and can configure / verify 
        # the identity preference
        id_hash = re.findall(r'\W+1\)\W+([0-9A-F]+)\W', output)[0]
        create_identity = False
        # First, check to see if we have an identity already
        try:
            output = security('get-identity-preference', '-s', munki_repo, '-Z')
            # Check if it matches the one we want
            current_hash = re.match(
                                r'SHA-1 hash:\W+([A-F0-9]+)\W', output).group(1)
            if id_hash != current_hash:
                # We only care if there's a different hash being used.
                # Remove the incorrect one.
                output = security(
                            'set-identity-preference', '-n', '-s', munki_repo)
                # Signal that we want to create a new identity preference
                create_identity = True
        except SecurityError:
            # Non-zero error code
            # Signal that we want to create a new identity preference
            create_identity = True
        if create_identity:
            # This code was moved into a common block that both routes could 
            # access as it's a little complicated.
            # security will only create an identity preference in the default 
            # keychain - which means a default has to be defined/selected
            # For normal users, this is login.keychain - but for root there's 
            # no login.keychain and no default keychain configured
            # So we'll handle the case of no default keychain (just set one) 
            # as well as pre-existing default keychain
            # (in which case we set it long enough to create the preference, 
            # then set it back)
            try:
                output = security('default-keychain', '-d', 'user')
                # One is defined, remember the path
                default_keychain = [x.strip().strip('"') 
                                    for x in output.split('\n') if x.strip()][0]
            except SecurityError:
                # if there's no default keychain, SecurityError exception
                # is raised
                default_keychain = None
            # Temporarily assign the default keychain to ours
            output = security(
                    'default-keychain', '-d', 'user', '-s', abs_keychain_path)
            # Create the identity preference
            output = security(
                    'set-identity-preference', '-s', munki_repo, '-Z',
                    id_hash, abs_keychain_path)
            if default_keychain:
                # We originally had a different one, set it back
                output = security(
                    'default-keychain', '-d', 'user', '-s', default_keychain)
    if munkicommon.verbose > 2:
        debug_output()
