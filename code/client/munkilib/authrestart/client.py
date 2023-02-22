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
authrestart.client.py

Created by Greg Neagle on 2017-04-15.

Routines for communicating with authrestartd.
Socket communications code adapted from autopkg's PkgCreator by Per Olofsson
"""
from __future__ import absolute_import, print_function

import os
import select
import socket

from .. import prefs
from ..wrappers import writePlistToString

AUTHRESTARTD_SOCKET = "/var/run/authrestartd"


class AuthRestartClientError(Exception):
    '''Exception to raise for errors in AuthRestartClient'''
    pass


class AuthRestartClient(object):
    '''Handles communication with authrestartd daemon'''
    def connect(self):
        '''Connect to authrestartd'''
        try:
            #pylint: disable=attribute-defined-outside-init
            self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            #pylint: enable=attribute-defined-outside-init
            self.socket.connect(AUTHRESTARTD_SOCKET)
        except socket.error as err:
            raise AuthRestartClientError(
                "Couldn't connect to authrestartd: %s" % err.strerror)

    def send_request(self, request):
        '''Send a request to authrestartd'''
        self.socket.send(writePlistToString(request))
        # use select so we don't hang indefinitely if authrestartd dies
        ready = select.select([self.socket.fileno()], [], [], 2)
        if ready[0]:
            reply = self.socket.recv(8192).decode("UTF-8")
        else:
            reply = ''

        if reply:
            return reply.rstrip()
        return "ERROR:No reply"

    def disconnect(self):
        '''Disconnect from authrestartd'''
        self.socket.close()

    def process(self, request):
        '''Send a request and return the result'''
        try:
            self.connect()
            result = self.send_request(request)
        finally:
            self.disconnect()
        return result

    def fv_is_active(self):
        '''Returns a boolean to indicate if FileVault is active'''
        result = self.process({'task': 'verify_filevault'})
        return result.startswith('OK')

    def verify_user(self, username):
        '''Returns True if username can unlock the FV volume'''
        request = {'task': 'verify_user', 'username': username}
        result = self.process(request)
        return result.startswith('OK')

    def verify_recovery_key_present(self):
        '''Returns True if plist containing a FV recovery key is present'''
        request = {'task': 'verify_recovery_key_present'}
        result = self.process(request)
        return result.startswith('OK')

    def verify_can_attempt_auth_restart(self):
        '''Returns True if we are ready to attempt an auth restart'''
        request = {'task': 'verify_can_attempt_auth_restart'}
        result = self.process(request)
        return result.startswith('OK')

    def store_password(self, password, username=None):
        '''Stores a FV password with authrestartd'''
        request = {'task': 'store_password', 'password': password}
        if username:
            request['username'] = username
        result = self.process(request)
        if not result.startswith('OK'):
            raise AuthRestartClientError(result)

    def restart(self):
        '''Returns True if restart was successful'''
        result = self.process({'task': 'restart'})
        if not result.startswith('OK'):
            raise AuthRestartClientError(result)

    def setup_delayed_authrestart(self, delayminutes=-1):
        '''Sets up a delayed auth restart'''
        request = {'task': 'delayed_authrestart', 'delayminutes': delayminutes}
        result = self.process(request)
        if not result.startswith('OK'):
            raise AuthRestartClientError(result)


# Higher-level wrapper functions that swallow AuthRestartClientErrors
def fv_is_active():
    '''Returns True if FileVault can be verified to be active,
    False otherwise'''
    try:
        return AuthRestartClient().fv_is_active()
    except AuthRestartClientError:
        return False


def verify_user(username):
    '''Returns True if user can be verified to be able to perform an
    authrestart, False otherwise'''
    try:
        return AuthRestartClient().verify_user(username)
    except AuthRestartClientError:
        return False


def verify_recovery_key_present():
    '''Returns True if we have a plist with a FileVault recovery key,
    False otherwise'''
    try:
        return AuthRestartClient().verify_recovery_key_present()
    except AuthRestartClientError:
        return False


def verify_can_attempt_auth_restart():
    '''Returns True if we have what we need to attempt an auth restart'''
    try:
        return AuthRestartClient().verify_can_attempt_auth_restart()
    except AuthRestartClientError:
        return False


def store_password(password, username=None):
    '''Stores a password for later authrestart usage.
    Returns boolean to indicate success/failure'''
    try:
        AuthRestartClient().store_password(password, username=username)
        return True
    except AuthRestartClientError:
        return False


def restart():
    '''Performs a restart -- authenticated if possible.
    Returns boolean to indicate success/failure'''
    try:
        AuthRestartClient().restart()
        return True
    except AuthRestartClientError:
        return False


def setup_delayed_authrestart():
    '''Sets up a delayed authrestart.
    Returns boolean to indicate success/failure'''
    try:
        AuthRestartClient().setup_delayed_authrestart()
        return True
    except AuthRestartClientError:
        return False


def test():
    '''A function for doing some basic testing'''
    import getpass
    import pwd
    from ..wrappers import get_input

    print('PerformAuthRestarts preference is: %s'
          % prefs.pref('PerformAuthRestarts'))
    print('FileVault is active: %s' % fv_is_active())
    print('Recovery key is present: %s' % verify_recovery_key_present())
    username = pwd.getpwuid(os.getuid()).pw_name
    if username == 'root':
        username = get_input('Enter name of FV-enabled user: ')
    print('%s is FV user: %s' % (username, verify_user(username)))
    password = getpass.getpass('Enter password: ')
    if password:
        if username == 'root':
            username = None
        if store_password(password, username=username):
            print('store_password was successful')
        else:
            print('store_password failed')
    print('Can attempt auth restart: %s' % verify_can_attempt_auth_restart())
    answer = get_input('Test setup of delayed auth restart (y/n)? ')
    if answer.lower().startswith('y'):
        print('Successfully set up delayed authrestart: %s'
              % setup_delayed_authrestart())
    answer = get_input('Test auth restart (y/n)? ')
    if answer.lower().startswith('y'):
        print('Attempting auth restart...')
        if restart():
            print('restart was successfully triggered')
        else:
            print('restart failed')
