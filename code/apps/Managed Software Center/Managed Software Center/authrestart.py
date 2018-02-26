# -*- coding: utf-8 -*-
#
#  authrestart.py
#  Managed Software Center
#
#  Created by Greg Neagle on 4/17/17.
#  Copyright (c) 2018 The Munki Project. All rights reserved.
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
    authrestart.py
    
    Created by Greg Neagle on 2017-04-15.
    
    Routines for communicating with authrestartd.
    Socket communications code adapted from autopkg's PkgCreator by Per Olofsson
"""

import os
import plistlib
import select
import socket
import sys


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
        self.socket.send(plistlib.writePlistToString(request))
        with os.fdopen(self.socket.fileno()) as fileref:
            # use select so we don't hang indefinitely if authrestartd dies
            ready = select.select([fileref], [], [], 2)
            if ready[0]:
                reply = fileref.read()
            else:
                reply = ''

        if reply:
            return reply.rstrip()
        else:
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
