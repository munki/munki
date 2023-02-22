# encoding: utf-8
#
# Copyright 2014-2023 Greg Neagle.
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
keychain

Created by Greg Neagle on 2014-06-09.
Incorporating work and ideas from Michael Lynn here:
    https://gist.github.com/pudquick/7704254
and here:
    https://gist.github.com/pudquick/836a19b5ff17c5b7640d#file-cert_tricks-py
Updated October 2022 for compatibilty with macOS Ventura
"""
from __future__ import absolute_import, print_function

import base64
import hashlib
import os
import subprocess

from . import display
from . import munkilog
from . import osutils
from . import prefs
from .wrappers import unicode_or_str


DEFAULT_KEYCHAIN_NAME = 'munki.keychain'
DEFAULT_KEYCHAIN_PASSWORD = 'munki'
KEYCHAIN_DIRECTORY = os.path.join(
    prefs.pref('ManagedInstallDir'), 'Keychains')


def read_file(pathname):
    '''Return the contents of pathname as a string'''
    try:
        fileobj = open(pathname, mode='r')
        data = fileobj.read()
        fileobj.close()
        return data
    except (OSError, IOError) as err:
        display.display_error(
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
    except (OSError, IOError) as err:
        display.display_error(
            'Couldn\'t write %s to %s: %s', stringdata, pathname, err)
        return ''


def pem_cert_bytes(cert_path):
    '''Read in a base64 pem file, return raw bytestring of embedded
    certificate'''
    cert_data = read_file(cert_path)
    if not (('-----BEGIN CERTIFICATE-----' in cert_data) and
            ('-----END CERTIFICATE-----' in cert_data)):
        raise Exception('Certificate does not appear to be .pem file')
    core_data = cert_data.split(
        '-----BEGIN CERTIFICATE', 1)[-1].replace('\r', '\n').split(
            '-----\n', 1)[-1].split('\n-----END CERTIFICATE-----', 1)[0]
    return base64.b64decode(''.join(core_data.split('\n')))


def pem_cert_sha1_digest(cert_path):
    '''Return SHA1 digest for pem certificate at path'''
    try:
        raw_bytes = pem_cert_bytes(cert_path)
        return hashlib.sha1(raw_bytes).hexdigest().upper()
    except BaseException as err:
        display.display_error('Error reading %s: %s' % (cert_path, err))
        return None


def get_munki_server_cert_info():
    '''Attempt to get information we need from Munki's preferences or
    defaults. Returns a dictionary.'''
    cert_info = {}

    # get server CA cert if it exists so we can verify the Munki server
    cert_info['ca_cert_path'] = None
    cert_info['ca_dir_path'] = None
    if prefs.pref('SoftwareRepoCAPath'):
        ca_path = prefs.pref('SoftwareRepoCAPath')
        if os.path.isfile(ca_path):
            cert_info['ca_cert_path'] = ca_path
        elif os.path.isdir(ca_path):
            cert_info['ca_dir_path'] = ca_path
    if prefs.pref('SoftwareRepoCACertificate'):
        cert_info['ca_cert_path'] = prefs.pref(
            'SoftwareRepoCACertificate')
    if cert_info['ca_cert_path'] is None:
        ca_cert_path = os.path.join(
            prefs.pref('ManagedInstallDir'), 'certs', 'ca.pem')
        if os.path.exists(ca_cert_path):
            cert_info['ca_cert_path'] = ca_cert_path
    return cert_info


def get_munki_client_cert_info():
    '''Attempt to get information we need from Munki's preferences or
    defaults. Returns a dictionary.'''
    cert_info = {}
    cert_info['client_cert_path'] = None
    cert_info['client_key_path'] = None
    cert_info['site_urls'] = []

    # get client cert if it exists
    if prefs.pref('UseClientCertificate'):
        cert_info['client_cert_path'] = (
            prefs.pref('ClientCertificatePath') or None)
        cert_info['client_key_path'] = prefs.pref('ClientKeyPath') or None
        if not cert_info['client_cert_path']:
            for name in ['cert.pem', 'client.pem', 'munki.pem']:
                client_cert_path = os.path.join(
                    prefs.pref('ManagedInstallDir'), 'certs', name)
                if os.path.exists(client_cert_path):
                    cert_info['client_cert_path'] = client_cert_path
                    break
        site_urls = []
        for key in ['SoftwareRepoURL', 'PackageURL', 'CatalogURL',
                    'ManifestURL', 'IconURL', 'ClientResourceURL']:
            url = prefs.pref(key)
            if url:
                site_urls.append(url.rstrip('/') + '/')
        cert_info['site_urls'] = site_urls
    return cert_info


def get_client_cert_common_name():
    '''Returns the common name for the client cert, if any'''
    common_name = None
    cert_info = get_munki_client_cert_info()
    client_cert_path = cert_info['client_cert_path']
    if client_cert_path and os.path.exists(client_cert_path):
        cmd = ['/usr/bin/openssl', 'x509', '-noout', '-subject', '-in',
               client_cert_path]
        proc = subprocess.Popen(cmd,
                                bufsize=-1, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, stdin=subprocess.PIPE)
        out = proc.communicate()[0].decode("UTF-8")
        if out:
            for i in out.split('/'):
                if i.startswith('CN='):
                    common_name = i[3:].rstrip()
    return common_name


def add_ca_certs_to_system_keychain(cert_info=None):
    '''Adds any CA certs as trusted root certs to System.keychain'''

    if not cert_info:
        cert_info = get_munki_server_cert_info()

    ca_cert_path = cert_info['ca_cert_path']
    ca_dir_path = cert_info['ca_dir_path']
    if not ca_cert_path and not ca_dir_path:
        # no CA certs, so nothing to do
        display.display_debug2(
            'No CA cert info provided, so nothing to add to System keychain.')
        return
    else:
        display.display_debug2('CA cert path: %s', ca_cert_path)
        display.display_debug2('CA dir path:  %s', ca_dir_path)

    system_keychain = "/Library/Keychains/System.keychain"
    if not os.path.exists(system_keychain):
        display.display_warning('%s not found.', system_keychain)
        return

    # Deprecated in macOS Big Sur
    # Add CA certs. security add-trusted-cert does the right thing even if
    # the cert is already added, so we just do it; checking to see if the
    # cert is already added is hard.
    certs_to_add = []
    if ca_cert_path:
        certs_to_add.append(ca_cert_path)
    if ca_dir_path:
        # add any pem files in the ca_dir_path directory
        for item in os.listdir(ca_dir_path):
            if item.endswith('.pem'):
                certs_to_add.append(os.path.join(ca_dir_path, item))
    for cert in certs_to_add:
        display.display_debug1('Adding CA cert %s...', cert)
        try:
            output = security('add-trusted-cert', '-d',
                              '-k', system_keychain, cert)
            if output:
                display.display_debug2(output)
        except SecurityError as err:
            display.display_error(
                'Could not add CA cert %s into System keychain: %s', cert, err)
            os_version_tuple = osutils.getOsVersion(as_tuple=True)
            if os_version_tuple >= (11, 0):
                display.display_error(
                    "Munki can't add a trusted cert to the system keychain in "
                    "macOS Big Sur or later. Use MDM to install the cert "
                    "or use a server cert from an issuer trusted by macOS.")

    display.display_detail('System.keychain updated.')


def make_client_keychain(cert_info=None):
    '''Builds a client cert keychain from existing client certs'''

    if not cert_info:
        # just grab data from Munki's preferences/defaults
        cert_info = get_munki_client_cert_info()

    client_cert_path = cert_info['client_cert_path']
    client_key_path = cert_info['client_key_path']
    site_urls = cert_info['site_urls']
    if not client_cert_path:
        # no client, so nothing to do
        display.display_debug1(
            'No client cert info provided, '
            'so no client keychain will be created.')
        return
    else:
        display.display_debug1('Client cert path: %s', client_cert_path)
        display.display_debug1('Client key path:  %s', client_key_path)

    # to do some of the following options correctly, we need to be root
    # and have root's home.
    # check to see if we're root
    if os.geteuid() != 0:
        display.display_error(
            'Can\'t make our client keychain unless we are root!')
        return
    # switch HOME if needed to root's home
    original_home = os.environ.get('HOME')
    if original_home:
        os.environ['HOME'] = os.path.expanduser('~root')

    keychain_pass = (
        prefs.pref('KeychainPassword') or DEFAULT_KEYCHAIN_PASSWORD)
    abs_keychain_path = get_keychain_path()
    if os.path.exists(abs_keychain_path):
        os.unlink(abs_keychain_path)
    if not os.path.exists(os.path.dirname(abs_keychain_path)):
        os.makedirs(os.path.dirname(abs_keychain_path), 0o700)
    # create a new keychain
    display.display_debug1('Creating client keychain...')
    try:
        output = security('create-keychain',
                          '-p', keychain_pass, abs_keychain_path)
        if output:
            display.display_debug2(output)
    except SecurityError as err:
        display.display_error(
            'Could not create keychain %s: %s', abs_keychain_path, err)
        if original_home:
            # switch it back
            os.environ['HOME'] = original_home
        return

    # Ensure the keychain is in the search path and unlocked
    added_keychain = add_to_keychain_list(abs_keychain_path)
    unlock_and_set_nonlocking(abs_keychain_path)

    # Add client cert (and optionally key)
    client_cert_file = None
    combined_pem = None
    if client_key_path:
        # combine client cert and private key before we import
        cert_data = read_file(client_cert_path)
        key_data = read_file(client_key_path)
        # write the combined data
        combined_pem = os.path.join(osutils.tmpdir(), 'combined.pem')
        if write_file(cert_data + key_data, combined_pem):
            client_cert_file = combined_pem
        else:
            display.display_error(
                'Could not combine client cert and key for import!')
    else:
        client_cert_file = client_cert_path
    if client_cert_file:
        # client_cert_file is combined_pem or client_cert_file
        display.display_debug2('Importing client cert and key...')
        try:
            output = security(
                'import', client_cert_file, '-A', '-k', abs_keychain_path)
            if output:
                display.display_debug2(output)
        except SecurityError as err:
            display.display_error(
                'Could not import %s: %s', client_cert_file, err)
    if combined_pem:
        # we created this; we should clean it up
        try:
            os.unlink(combined_pem)
        except (OSError, IOError):
            pass

    # removed identity preferences code that was here which set up
    # identity preference(s) linking the identity (cert and key) to the
    # various urls. Not necessary with new method for clients certs in Munki 5.5

    # we're done, clean up.
    if added_keychain:
        remove_from_keychain_list(abs_keychain_path)
    if original_home:
        # switch it back
        os.environ['HOME'] = original_home
    display.display_info(
        'Completed creation of client keychain at %s' % abs_keychain_path)


def add_to_keychain_list(keychain_path):
    '''Ensure the keychain is in the search path. Returns True if we
    added the keychain to the list.'''

    added_keychain = False
    # macOS Ventura fix, use common domain for keychain search list
    output = security('list-keychains', '-d', 'common')
    # Split the output and strip it of whitespace and leading/trailing
    # quotes, the result are absolute paths to keychains
    # Preserve the order in case we need to append to them
    search_keychains = [x.strip().strip('"')
                        for x in output.split('\n') if x.strip()]
    if not keychain_path in search_keychains:
        # Keychain is not in the search paths
        display.display_debug2('Adding client keychain to search path...')
        search_keychains.append(keychain_path)
        try:
            output = security(
                'list-keychains', '-d', 'common', '-s', *search_keychains)
            if output:
                display.display_debug2(output)
            added_keychain = True
        except SecurityError as err:
            display.display_error(
                'Could not add keychain %s to keychain list: %s',
                keychain_path, err)
            added_keychain = False
    if munkilog.logging_level() > 2:
        debug_output()
    return added_keychain


def remove_from_keychain_list(keychain_path):
    '''Remove keychain from the list of keychains'''

    # macOS Ventura fix, use common domain for keychain search list
    output = security('list-keychains', '-d', 'common')
    # Split the output and strip it of whitespace and leading/trailing
    # quotes, the result are absolute paths to keychains
    # Preserve the order in case we need to append to them
    search_keychains = [x.strip().strip('"')
                        for x in output.split('\n') if x.strip()]
    if keychain_path in search_keychains:
        # Keychain is in the search path
        display.display_debug2(
            'Removing %s from search path...', keychain_path)
        filtered_keychains = [keychain for keychain in search_keychains
                              if keychain != keychain_path]
        try:
            output = security(
                'list-keychains', '-d', 'common', '-s', *filtered_keychains)
            if output:
                display.display_debug2(output)
        except SecurityError as err:
            display.display_error(
                'Could not set new keychain list: %s', err)
        if munkilog.logging_level() > 2:
            debug_output()


def unlock_and_set_nonlocking(keychain_path):
    '''Unlocks the keychain and sets it to non-locking'''
    keychain_pass = (
        prefs.pref('KeychainPassword') or DEFAULT_KEYCHAIN_PASSWORD)
    try:
        output = security(
            'unlock-keychain', '-p', keychain_pass, keychain_path)
        if output:
            display.display_debug2(output)
    except SecurityError as err:
        # some problem unlocking the keychain.
        display.display_error(
            'Could not unlock %s: %s.', keychain_path, err)
        # delete it
        try:
            os.unlink(keychain_path)
        except OSError as err:
            display.display_error(
                'Could not remove %s: %s.', keychain_path, err)
        return
    try:
        output = security('set-keychain-settings', keychain_path)
        if output:
            display.display_debug2(output)
    except SecurityError as err:
        display.display_error(
            'Could not set keychain settings for %s: %s',
            keychain_path, err)


def client_certs_exist():
    '''Returns True if there a client cert exists
    that we need to import into a keychain'''
    cert_info = get_munki_client_cert_info()
    client_cert_path = cert_info['client_cert_path']
    # we must have a client cert; we don't at this stage need
    # to check for a key
    return client_cert_path and os.path.exists(client_cert_path)


def client_certs_newer_than_keychain():
    '''Returns True if we have client certs that are newer than our
    client keychain, False otherwise'''
    # pylint: disable=invalid-name
    cert_info = get_munki_client_cert_info()
    client_cert_path = cert_info['client_cert_path']
    client_key_path = cert_info['client_key_path']
    keychain_path = get_keychain_path()
    if not client_cert_path or not os.path.exists(client_cert_path):
        return False
    if not os.path.exists(keychain_path):
        return False
    keychain_mod_time = os.stat(keychain_path).st_mtime
    if os.stat(client_cert_path).st_mtime > keychain_mod_time:
        return True
    if client_key_path and os.path.exists(client_key_path):
        if os.stat(client_key_path).st_mtime > keychain_mod_time:
            return True
    return False


def debug_output():
    '''Debugging output for keychain'''
    try:
        display.display_debug2('***Keychain search list for common domain***')
        display.display_debug2(security('list-keychains', '-d', 'common'))
        display.display_debug2('***Default keychain info***')
        display.display_debug2(security('default-keychain', '-d', 'common'))
        keychainfile = get_keychain_path()
        if os.path.exists(keychainfile):
            display.display_debug2('***Info for %s***' % keychainfile)
            display.display_debug2(
                security('show-keychain-info', keychainfile))
    except SecurityError as err:
        display.display_error(unicode_or_str(err))


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
        raise SecurityError('%s: %s' % (proc.returncode, err.decode("UTF-8")))
    return (output or err).decode("UTF-8")


def get_keychain_path():
    '''Returns an absolute path for our keychain'''
    keychain_name = (
        prefs.pref('KeychainName') or DEFAULT_KEYCHAIN_NAME)
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
    # pylint: disable=too-few-public-methods

    keychain_path = None
    added_keychain = False

    def __init__(self):
        '''Adds CA certs as trusted to System keychain.
        Unlocks the munki.keychain if it exists.
        Makes sure the munki.keychain is in the search list.
        Creates a new client keychain if needed.'''
        add_ca_certs_to_system_keychain()
        self.keychain_path = get_keychain_path()
        if client_certs_exist() and os.path.exists(self.keychain_path):
            # we have client certs; we should build a keychain using them
            try:
                os.unlink(self.keychain_path)
            except (OSError, IOError) as err:
                display.display_error(
                    'Could not remove pre-existing %s: %s'
                    % (self.keychain_path, err))
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


if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
