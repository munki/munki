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
import subprocess

import munkicommon

# we use lots of camelCase-style names. Deal with it.
# pylint: disable=C0103

DEFAULT_KEYCHAIN_NAME = 'munki.keychain'
DEFAULT_KEYCHAIN_PASSWORD = 'munki'
KEYCHAIN_DIRECTORY = os.path.join(
    munkicommon.pref('ManagedInstallDir'), 'Keychains')


def read_file(pathname):
    '''Return the contents of pathname as a string'''
    try:
        fileobj = open(pathname, mode='r')
        data = fileobj.read()
        fileobj.close()
        return data
    except (OSError, IOError), err:
        munkicommon.display_error(
            'Could not read %s: %s', pathname, err)
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
        munkicommon.display_error('Couldn\'t write %s to %s: %s',
                                  stringdata, pathname, err)
        return ''


def get_munki_server_cert_data():
    '''Attempt to get information we need from Munki's preferences or
    defaults. Returns a dictionary.'''
    ManagedInstallDir = munkicommon.pref('ManagedInstallDir')
    cert_data = {}

    # get server CA cert if it exists so we can verify the Munki server
    cert_data['ca_cert_path'] = None
    cert_data['ca_dir_path'] = None
    if munkicommon.pref('SoftwareRepoCAPath'):
        CA_path = munkicommon.pref('SoftwareRepoCAPath')
        if os.path.isfile(CA_path):
            cert_data['ca_cert_path'] = CA_path
        elif os.path.isdir(CA_path):
            cert_data['ca_dir_path'] = CA_path
    if munkicommon.pref('SoftwareRepoCACertificate'):
        cert_data['ca_cert_path'] = munkicommon.pref(
            'SoftwareRepoCACertificate')
    if cert_data['ca_cert_path'] == None:
        ca_cert_path = os.path.join(ManagedInstallDir, 'certs', 'ca.pem')
        if os.path.exists(ca_cert_path):
            cert_data['ca_cert_path'] = ca_cert_path
    return cert_data


def get_munki_client_cert_data():
    '''Attempt to get information we need from Munki's preferences or
    defaults. Returns a dictionary.'''
    ManagedInstallDir = munkicommon.pref('ManagedInstallDir')
    cert_data = {}

    cert_data['client_cert_path'] = None
    cert_data['client_key_path'] = None
    # get client cert if it exists
    if munkicommon.pref('UseClientCertificate'):
        cert_data['client_cert_path'] = (
            munkicommon.pref('ClientCertificatePath') or None)
        cert_data['client_key_path'] = munkicommon.pref('ClientKeyPath') or None
        if not cert_data['client_cert_path']:
            for name in ['cert.pem', 'client.pem', 'munki.pem']:
                client_cert_path = os.path.join(
                    ManagedInstallDir, 'certs', name)
                if os.path.exists(client_cert_path):
                    cert_data['client_cert_path'] = client_cert_path
                    break

    cert_data['site_url'] = (
        munkicommon.pref('SoftwareRepoURL').rstrip('/') + '/')
    return cert_data


def add_ca_certs_to_system_keychain(certdata=None):
    '''Adds any CA certs as trusted root certs to System.keychain'''

    if not certdata:
        certdata = get_munki_server_cert_data()

    ca_cert_path = certdata['ca_cert_path']
    ca_dir_path = certdata['ca_dir_path']
    SYSTEM_KEYCHAIN = "/Library/Keychains/System.keychain"
    if not os.path.exists(SYSTEM_KEYCHAIN):
        munkicommon.display_warning('%s not found.', SYSTEM_KEYCHAIN)
        return

    if not ca_cert_path and not ca_dir_path:
        # no CA certs, so nothing to do
        munkicommon.display_debug2(
            'No CA cert info provided, so nothing to add to System keychain.')
        return
    else:
        munkicommon.display_debug2('CA cert path:     %s', ca_cert_path)
        munkicommon.display_debug2('CA dir path:      %s', ca_dir_path)

    # Add CA certs
    certs_to_add = []
    if ca_cert_path:
        certs_to_add.append(ca_cert_path)
    if ca_dir_path:
        # add any pem files in the ca_dir_path directory
        for item in os.listdir(ca_dir_path):
            if item.endswith('.pem'):
                certs_to_add.append(os.path.join(ca_dir_path, item))
    for cert in certs_to_add:
        munkicommon.display_debug1('Adding CA cert %s...', cert)
        try:
            output = security('add-trusted-cert', '-d',
                              '-k', SYSTEM_KEYCHAIN, cert)
            if output:
                munkicommon.display_debug2(output)
        except SecurityError, err:
            munkicommon.display_error(
                'Could not add CA cert %s into System keychain: %s', cert, err)

    munkicommon.display_info('System.keychain updated.')


def make_client_keychain(certdata=None):
    '''Builds a client cert keychain from existing client certs'''

    if not certdata:
        # jusr grab data from Munki's preferences/defaults
        certdata = get_munki_client_cert_data()

    client_cert_path = certdata['client_cert_path']
    client_key_path = certdata['client_key_path']
    site_url = certdata['site_url']
    if not client_cert_path:
        # no client, so nothing to do
        munkicommon.display_debug1(
            'No client cert info provided, '
            'so no client keychain will be created.')
        return
    else:
        munkicommon.display_debug1('Client cert path: %s', client_cert_path)
        munkicommon.display_debug1('Client key path:  %s', client_key_path)

    # to do some of the following options correctly, we need to be root
    # and have root's home.
    # check to see if we're root
    if os.geteuid() != 0:
        munkicommon.display_error(
            'Can\'t make our client keychain unless we are root!')
        return
    # switch HOME if needed to root's home
    original_home = os.environ.get('HOME')
    if original_home:
        os.environ['HOME'] = os.path.expanduser('~root')

    keychain_pass = (
        munkicommon.pref('KeychainPassword') or DEFAULT_KEYCHAIN_PASSWORD)
    abs_keychain_path = get_keychain_path()
    if os.path.exists(abs_keychain_path):
        os.unlink(abs_keychain_path)
    if not os.path.exists(os.path.dirname(abs_keychain_path)):
        os.makedirs(os.path.dirname(abs_keychain_path))
    # create a new keychain
    munkicommon.display_debug1('Creating client keychain...')
    try:
        output = security('create-keychain',
                          '-p', keychain_pass, abs_keychain_path)
        if output:
            munkicommon.display_debug2(output)
    except SecurityError, err:
        munkicommon.display_error(
            'Could not create keychain %s: %s', abs_keychain_path, err)
        if original_home:
            # switch it back
            os.environ['HOME'] = original_home
        return

    # Ensure the keychain is in the search path and unlocked
    added_keychain = add_to_keychain_list(abs_keychain_path)
    unlock_and_set_nonlocking(abs_keychain_path)

    # Add client cert (and optionally key)
    if client_key_path:
        # combine client cert and private key before we import
        cert_data = read_file(client_cert_path)
        key_data = read_file(client_key_path)
        # write the combined data
        combined_pem = os.path.join(munkicommon.tmpdir(), 'combined.pem')
        if write_file(cert_data + key_data, combined_pem):
            munkicommon.display_debug1('Importing client cert and key...')
            try:
                output = security(
                    'import', combined_pem, '-A', '-k', abs_keychain_path)
                if output:
                    munkicommon.display_debug2(output)
            except SecurityError, err:
                munkicommon.display_error(
                    'Could not import %s: %s', combined_pem, err)
            os.unlink(combined_pem)
        else:
            munkicommon.display_error(
                'Could not combine client cert and key for import!')
    else:
        munkicommon.display_debug2('Importing client cert and key...')
        try:
            output = security(
                'import', client_cert_path, '-A', '-k', abs_keychain_path)
            if output:
                munkicommon.display_debug2(output)
        except SecurityError, err:
            munkicommon.display_error(
                'Could not import %s: %s', client_cert_path, err)

    # set up identity preference linking the identity (cert and key)
    # to the site_url
    # First we need to find the existing identity in our keychain
    try:
        output = security('find-identity', abs_keychain_path)
        if output:
            munkicommon.display_debug2(output)
    except SecurityError:
        pass
    if not ' 1 identities found' in output:
        munkicommon.display_error('No identities found!')
    else:
        # We have a solitary match and can configure / verify
        # the identity preference
        id_hash = re.findall(r'\W+1\)\W+([0-9A-F]+)\W', output)[0]
        # First, check to see if we have an identity already
        create_identity = False
        try:
            output = security(
                'get-identity-preference', '-s', site_url, '-Z')
            if output:
                munkicommon.display_debug2(output)
            # No error, we found an identity
            # Check if it matches the one we want
            current_hash = re.match(
                r'SHA-1 hash:\W+([A-F0-9]+)\W', output).group(1)
            if id_hash != current_hash:
                # We only care if there's a different hash being used.
                # Remove the incorrect one.
                output = security(
                    'set-identity-preference', '-n', '-s', site_url)
                if output:
                    munkicommon.display_debug2(output)
                # Signal that we want to create a new identity preference
                create_identity = True
        except SecurityError, err:
            # error finding identity-preference
            create_identity = True
        #elif id_hash not in output:
        #    # Non-zero error code and hash not detected in output
        #    # Signal that we want to create a new identity preference
        #    create_identity = True
        if create_identity:
            # This code was moved into a common block that both routes could
            # access as it's a little complicated.
            # security will only create an identity preference in the
            # default keychain - which means a default has to be
            # defined/selected. For normal users, this is login.keychain -
            # but for root there's no login.keychain and no default keychain
            # configured. So we'll handle the case of no default keychain
            # (just set one) as well as pre-existing default keychain
            # (in which case we set it long enough to create the preference,
            # then set it back)
            munkicommon.display_debug1('Creating identity preference...')
            try:
                output = security('default-keychain')
                if output:
                    munkicommon.display_debug2(output)
                # One is defined, remember the path
                default_keychain = [
                    x.strip().strip('"')
                    for x in output.split('\n') if x.strip()][0]
            except SecurityError, err:
                # error raised if there is no default
                default_keychain = None
            # Temporarily assign the default keychain to ours
            try:
                output = security(
                    'default-keychain', '-s', abs_keychain_path)
                if output:
                    munkicommon.display_debug2(output)
            except SecurityError, err:
                munkicommon.display_error(
                    'Could not set default keychain to %s failed: %s'
                    % (abs_keychain_path, err))
                default_keychain = None
            # Create the identity preference
            try:
                output = security(
                    'set-identity-preference', '-s', site_url, '-Z',
                    id_hash, abs_keychain_path)
                if output:
                    munkicommon.display_debug2(output)
            except SecurityError, err:
                munkicommon.display_error(
                    'Setting identity preference failed: %s' % err)
            if default_keychain:
                # We originally had a different one, set it back
                output = security(
                    'default-keychain', '-s', default_keychain)
                if output:
                    munkicommon.display_debug2(output)
    # we're done, clean up.
    if added_keychain:
        remove_from_keychain_list(abs_keychain_path)
    if original_home:
        # switch it back
        os.environ['HOME'] = original_home
    munkicommon.display_info(
        'Completed creation of client keychain at %s' % abs_keychain_path)


def add_to_keychain_list(keychain_path):
    '''Ensure the keychain is in the search path. Returns True if we
    added the keychain to the list.'''

    # we use *foo to expand a list of keychain paths
    # pylint: disable=W0142

    added_keychain = False
    output = security('list-keychains', '-d', 'user')
    # Split the output and strip it of whitespace and leading/trailing
    # quotes, the result are absolute paths to keychains
    # Preserve the order in case we need to append to them
    search_keychains = [x.strip().strip('"')
                        for x in output.split('\n') if x.strip()]
    if not keychain_path in search_keychains:
        # Keychain is not in the search paths
        munkicommon.display_debug2('Adding client keychain to search path...')
        search_keychains.append(keychain_path)
        try:
            output = security(
                'list-keychains', '-d', 'user', '-s', *search_keychains)
            if output:
                munkicommon.display_debug2(output)
            added_keychain = True
        except SecurityError, err:
            munkicommon.display_error(
                'Could not add keychain %s to keychain list: %s',
                keychain_path, err)
            added_keychain = False
    return added_keychain


def remove_from_keychain_list(keychain_path):
    '''Remove keychain from the list of keychains'''

    # we use *foo to expand a list of keychain paths
    # pylint: disable=W0142

    output = security('list-keychains', '-d', 'user')
    # Split the output and strip it of whitespace and leading/trailing
    # quotes, the result are absolute paths to keychains
    # Preserve the order in case we need to append to them
    search_keychains = [x.strip().strip('"')
                        for x in output.split('\n') if x.strip()]
    if keychain_path in search_keychains:
        # Keychain is in the search path
        munkicommon.display_debug1(
            'Removing %s from search path...', keychain_path)
        filtered_keychains = [keychain for keychain in search_keychains
                              if keychain != keychain_path]
        try:
            output = security(
                'list-keychains', '-d', 'user', '-s', *filtered_keychains)
            if output:
                munkicommon.display_debug2(output)
        except SecurityError, err:
            munkicommon.display_error(
                'Could not set new keychain list: %s', err)


def unlock_and_set_nonlocking(keychain_path):
    '''Unlocks the keychain and sets it to non-locking'''
    keychain_pass = (
        munkicommon.pref('KeychainPassword') or DEFAULT_KEYCHAIN_PASSWORD)
    try:
        output = security(
            'unlock-keychain', '-p', keychain_pass, keychain_path)
        if output:
            munkicommon.display_debug2(output)
    except SecurityError, err:
        # some problem unlocking the keychain.
        munkicommon.display_error(
            'Could not unlock %s: %s.', keychain_path, err)
        # delete it
        try:
            os.unlink(keychain_path)
        except OSError, err:
            munkicommon.display_error(
                'Could not remove %s: %s.', keychain_path, err)
        return
    try:
        output = security('set-keychain-settings', keychain_path)
        if output:
            munkicommon.display_debug2(output)
    except SecurityError, err:
        munkicommon.display_error(
            'Could not set keychain settings for %s: %s',
            keychain_path, err)


def client_certs_newer_than_keychain():
    '''Returns True if we have client certs that are newer than our
    client keychain, False otherwise'''
    certdata = get_munki_client_cert_data()
    client_cert_path = certdata['client_cert_path']
    client_key_path = certdata['client_key_path']
    keychain_path = get_keychain_path()
    if not client_cert_path or not os.path.exists(client_cert_path):
        return False
    if not os.path.exists(keychain_path):
        return False
    keychain_mod_time = os.stat(keychain_path).st_mtime
    if os.stat(client_cert_path).st_mtime > keychain_mod_time:
        return True
    if os.stat(client_key_path).st_mtime > keychain_mod_time:
        return True
    return False


def debug_output():
    '''Debugging output for keychain'''
    try:
        munkicommon.display_debug1('***Keychain list***')
        munkicommon.display_debug1(security('list-keychains', '-d', 'user'))
        munkicommon.display_debug1('***Default keychain info***')
        munkicommon.display_debug1(security('default-keychain', '-d', 'user'))
        keychainfile = get_keychain_path()
        if os.path.exists(keychainfile):
            munkicommon.display_debug1('***Info for %s***' % keychainfile)
            munkicommon.display_debug1(
                security('show-keychain-info', keychainfile))
    except SecurityError, err:
        munkicommon.display_error(str(err))


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
    '''Wrapper class for handling the client keychain'''

    keychain_path = None
    added_keychain = False

    def __init__(self):
        '''Adds CA certs as trusted to System keychain.
        Unlocks the munki.keychain if it exists.
        Makes sure the munki.keychain is in the search list.
        Creates a new client keychain if needed.'''
        add_ca_certs_to_system_keychain()
        self.keychain_path = get_keychain_path()
        if client_certs_newer_than_keychain():
            # updated client certs; we should build a new keychain
            os.unlink(self.keychain_path)
        if os.path.exists(self.keychain_path):
            # ensure existing keychain is available for use
            self.added_keychain = add_to_keychain_list(self.keychain_path)
            unlock_and_set_nonlocking(self.keychain_path)
        if not os.path.exists(self.keychain_path):
            # try making a new keychain
            make_client_keychain()
            if os.path.exists(self.keychain_path):
                self.added_keychain = add_to_keychain_list(self.keychain_path)
                unlock_and_set_nonlocking(self.keychain_path)
        if not os.path.exists(self.keychain_path):
            # give up
            self.keychain_path = None
            self.added_keychain = False

    def __del__(self):
        '''Remove our keychain from the keychain list if we added it'''
        if self.added_keychain:
            remove_from_keychain_list(self.keychain_path)
