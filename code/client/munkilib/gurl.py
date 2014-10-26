#!/usr/bin/python
# encoding: utf-8
#
# Copyright 2009-2014 Greg Neagle.
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
gurl.py

Created by Greg Neagle on 2013-11-21.

curl replacement using NSURLConnection and friends
"""

import os
import xattr

# PyLint cannot properly find names inside Cocoa libraries, so issues bogus
# No name 'Foo' in module 'Bar' warnings. Disable them.
# pylint: disable=E0611
from Foundation import NSRunLoop, NSDate
from Foundation import NSObject, NSURL, NSURLConnection
from Foundation import NSMutableURLRequest
from Foundation import NSURLRequestReloadIgnoringLocalCacheData
from Foundation import NSURLResponseUnknownLength
from Foundation import NSLog
from Foundation import NSURLCredential, NSURLCredentialPersistenceNone
from Foundation import NSPropertyListSerialization
from Foundation import NSPropertyListMutableContainersAndLeaves
from Foundation import NSPropertyListXMLFormat_v1_0
# pylint: enable=E0611

# Disable PyLint complaining about 'invalid' names
# pylint: disable=C0103

ssl_error_codes = {
    -9800: u'SSL protocol error',
    -9801: u'Cipher Suite negotiation failure',
    -9802: u'Fatal alert',
    -9803: u'I/O would block (not fatal)',
    -9804: u'Attempt to restore an unknown session',
    -9805: u'Connection closed gracefully',
    -9806: u'Connection closed via error',
    -9807: u'Invalid certificate chain',
    -9808: u'Bad certificate format',
    -9809: u'Underlying cryptographic error',
    -9810: u'Internal error',
    -9811: u'Module attach failure',
    -9812: u'Valid cert chain, untrusted root',
    -9813: u'Cert chain not verified by root',
    -9814: u'Chain had an expired cert',
    -9815: u'Chain had a cert not yet valid',
    -9816: u'Server closed session with no notification',
    -9817: u'Insufficient buffer provided',
    -9818: u'Bad SSLCipherSuite',
    -9819: u'Unexpected message received',
    -9820: u'Bad MAC',
    -9821: u'Decryption failed',
    -9822: u'Record overflow',
    -9823: u'Decompression failure',
    -9824: u'Handshake failure',
    -9825: u'Misc. bad certificate',
    -9826: u'Bad unsupported cert format',
    -9827: u'Certificate revoked',
    -9828: u'Certificate expired',
    -9829: u'Unknown certificate',
    -9830: u'Illegal parameter',
    -9831: u'Unknown Cert Authority',
    -9832: u'Access denied',
    -9833: u'Decoding error',
    -9834: u'Decryption error',
    -9835: u'Export restriction',
    -9836: u'Bad protocol version',
    -9837: u'Insufficient security',
    -9838: u'Internal error',
    -9839: u'User canceled',
    -9840: u'No renegotiation allowed',
    -9841: u'Peer cert is valid, or was ignored if verification disabled',
    -9842: u'Server has requested a client cert',
    -9843: u'Peer host name mismatch',
    -9844: u'Peer dropped connection before responding',
    -9845: u'Decryption failure',
    -9846: u'Bad MAC',
    -9847: u'Record overflow',
    -9848: u'Configuration error',
    -9849: u'Unexpected (skipped) record in DTLS'}


class Gurl(NSObject):
    '''A class for getting content from a URL
       using NSURLConnection and friends'''

    # since we inherit from NSObject, PyLint issues a few bogus warnings
    # pylint: disable=W0232,E1002

    # Don't want to define the attributes twice that are initialized in
    # initWithOptions_(), so:
    # pylint: disable=E1101,W0201

    GURL_XATTR = 'com.googlecode.munki.downloadData'

    def initWithOptions_(self, options):
        '''Set up our Gurl object'''
        self = super(Gurl, self).init()
        if not self:
            return

        self.follow_redirects = options.get('follow_redirects', False)
        self.destination_path = options.get('file')
        self.can_resume = options.get('can_resume', False)
        self.url = options.get('url')
        self.additional_headers = options.get('additional_headers', {})
        self.username = options.get('username')
        self.password = options.get('password')
        self.download_only_if_changed = options.get(
            'download_only_if_changed', False)
        self.cache_data = options.get('cache_data')
        self.connection_timeout = options.get('connection_timeout', 10)

        self.log = options.get('logging_function', NSLog)

        self.resume = False
        self.response = None
        self.headers = None
        self.status = None
        self.error = None
        self.SSLerror = None
        self.done = False
        self.redirection = []
        self.destination = None
        self.bytesReceived = 0
        self.expectedLength = -1
        self.percentComplete = 0
        self.connection = None
        return self

    def start(self):
        '''Start the connection'''
        if not self.destination_path:
            self.log('No output file specified.')
            self.done = True
            return
        url = NSURL.URLWithString_(self.url)
        request = (
            NSMutableURLRequest.requestWithURL_cachePolicy_timeoutInterval_(
                url, NSURLRequestReloadIgnoringLocalCacheData,
                self.connection_timeout))
        if self.additional_headers:
            for header, value in self.additional_headers.items():
                request.setValue_forHTTPHeaderField_(value, header)
        # does the file already exist? See if we can resume a partial download
        if os.path.isfile(self.destination_path):
            stored_data = self.get_stored_headers()
            if (self.can_resume and 'expected-length' in stored_data and
                    ('last-modified' in stored_data or 'etag' in stored_data)):
                # we have a partial file and we're allowed to resume
                self.resume = True
                local_filesize = os.path.getsize(self.destination_path)
                byte_range = 'bytes=%s-' % local_filesize
                request.setValue_forHTTPHeaderField_(byte_range, 'Range')
        if self.download_only_if_changed and not self.resume:
            stored_data = self.cache_data or self.get_stored_headers()
            if 'last-modified' in stored_data:
                request.setValue_forHTTPHeaderField_(
                    stored_data['last-modified'], 'if-modified-since')
            if 'etag' in stored_data:
                request.setValue_forHTTPHeaderField_(
                    stored_data['etag'], 'if-none-match')
        self.connection = NSURLConnection.alloc().initWithRequest_delegate_(
            request, self)

    def cancel(self):
        '''Cancel the connection'''
        if self.connection:
            self.connection.cancel()
            self.done = True

    def isDone(self):
        '''Check if the connection request is complete. As a side effect,
        allow the delegates to work my letting the run loop run for a bit'''
        if self.done:
            return self.done
        # let the delegates do their thing
        NSRunLoop.currentRunLoop().runUntilDate_(
            NSDate.dateWithTimeIntervalSinceNow_(.1))
        return self.done

    def get_stored_headers(self):
        '''Returns any stored headers for self.destination_path'''
        # try to read stored headers
        try:
            stored_plist_str = xattr.getxattr(
                self.destination_path, self.GURL_XATTR)
        except (KeyError, IOError):
            return {}
        data = buffer(stored_plist_str)
        dataObject, plistFormat, error = (
            NSPropertyListSerialization.
            propertyListFromData_mutabilityOption_format_errorDescription_(
                data, NSPropertyListMutableContainersAndLeaves, None, None))
        if error:
            return {}
        else:
            return dataObject

    def store_headers(self, headers):
        '''Store dictionary data as an xattr for self.destination_path'''
        plistData, error = (
            NSPropertyListSerialization.
            dataFromPropertyList_format_errorDescription_(
                headers, NSPropertyListXMLFormat_v1_0, None))
        if error:
            string = ''
        else:
            string = str(plistData)
        try:
            xattr.setxattr(self.destination_path, self.GURL_XATTR, string)
        except IOError, err:
            self.log('Could not store metadata to %s: %s'
                     % (self.destination_path, err))

    def normalize_header_dict(self, a_dict):
        '''Since HTTP header names are not case-sensitive, we normalize a
        dictionary of HTTP headers by converting all the key names to
        lower case'''

        # yes, we don't use 'self'!
        # pylint: disable=R0201

        new_dict = {}
        for key, value in a_dict.items():
            new_dict[key.lower()] = value
        return new_dict

    def connection_didFailWithError_(self, connection, error):
        '''NSURLConnection delegate method
        Sent when a connection fails to load its request successfully.'''

        # we don't actually use the connection argument, so
        # pylint: disable=W0613

        self.error = error
        # If this was an SSL error, try to extract the SSL error code.
        if 'NSUnderlyingError' in error.userInfo():
            ssl_code = error.userInfo()['NSUnderlyingError'].userInfo().get(
                '_kCFNetworkCFStreamSSLErrorOriginalValue', None)
            if ssl_code:
                self.SSLerror = (ssl_code, ssl_error_codes.get(
                    ssl_code, 'Unknown SSL error'))
        self.done = True
        if self.destination and self.destination_path:
            self.destination.close()
            # delete it? Might not want to...

    def connectionDidFinishLoading_(self, connection):
        '''NSURLConnectionDataDelegat delegate method
        Sent when a connection has finished loading successfully.'''

        # we don't actually use the connection argument, so
        # pylint: disable=W0613

        self.done = True
        if self.destination and self.destination_path:
            self.destination.close()
        if str(self.status).startswith('2'):
            # remove the expected-size from the stored headers
            headers = self.get_stored_headers()
            if 'expected-length' in headers:
                del headers['expected-length']
                self.store_headers(headers)

    def connection_didReceiveResponse_(self, connection, response):
        '''NSURLConnectionDataDelegate delegate method
        Sent when the connection has received sufficient data to construct the
        URL response for its request.'''

        self.response = response
        self.bytesReceived = 0
        self.percentComplete = -1
        self.expectedLength = response.expectedContentLength()

        download_data = {}
        if response.className() == u'NSHTTPURLResponse':
            # Headers and status code only available for HTTP/S transfers
            self.status = response.statusCode()
            self.headers = dict(response.allHeaderFields())
            normalized_headers = self.normalize_header_dict(self.headers)
            if 'last-modified' in normalized_headers:
                download_data['last-modified'] = normalized_headers[
                    'last-modified']
            if 'etag' in normalized_headers:
                download_data['etag'] = normalized_headers['etag']
            download_data['expected-length'] = self.expectedLength

        # self.destination is defined in initWithOptions_
        # pylint: disable=E0203

        if not self.destination and self.destination_path:
            if self.status == 206 and self.resume:
                # 206 is Partial Content response
                stored_data = self.get_stored_headers()
                if (not stored_data or
                        stored_data.get('etag') != download_data.get('etag') or
                        stored_data.get('last-modified') != download_data.get(
                            'last-modified')):
                    # file on server is different than the one
                    # we have a partial for
                    self.log(
                        'Can\'t resume download; file on server has changed.')
                    connection.cancel()
                    self.log('Removing %s' % self.destination_path)
                    os.unlink(self.destination_path)
                    # restart and attempt to download the entire file
                    self.log(
                        'Restarting download of %s' % self.destination_path)
                    os.unlink(self.destination_path)
                    self.start()
                    return
                # try to resume
                self.log('Resuming download for %s' % self.destination_path)
                # add existing file size to bytesReceived so far
                local_filesize = os.path.getsize(self.destination_path)
                self.bytesReceived = local_filesize
                self.expectedLength += local_filesize
                # open file for append
                self.destination = open(self.destination_path, 'a')

            elif str(self.status).startswith('2'):
                # not resuming, just open the file for writing
                self.destination = open(self.destination_path, 'w')
                # store some headers with the file for use if we need to resume
                # the downloadand for future checking if the file on the server
                # has changed
                self.store_headers(download_data)

    def connection_willSendRequest_redirectResponse_(
            self, connection, request, response):
        '''NSURLConnectionDataDelegate delegate method
        Sent when the connection determines that it must change URLs in order to
        continue loading a request.'''

        # we don't actually use the connection argument, so
        # pylint: disable=W0613

        if response == None:
            # This isn't a real redirect, this is without talking to a server.
            # Pass it back as-is
            return request
        # But if we're here, it appears to be a real redirect attempt
        # Annoyingly, we apparently can't get access to the headers from the
        # site that told us to redirect. All we know is that we were told
        # to redirect and where the new location is.
        newURL = request.URL().absoluteString()
        self.redirection.append([newURL, dict(response.allHeaderFields())])
        if self.follow_redirects:
            # Allow the redirect
            self.log('Allowing redirect to: %s' % newURL)
            return request
        else:
            # Deny the redirect
            self.log('Denying redirect to: %s' % newURL)
            return None

    def connection_willSendRequestForAuthenticationChallenge_(
            self, connection, challenge):
        '''NSURLConnection delegate method
        Tells the delegate that the connection will send a request for an
        authentication challenge.
        New in 10.7.'''

        # we don't actually use the connection argument, so
        # pylint: disable=W0613

        self.log('connection_willSendRequestForAuthenticationChallenge_')
        protectionSpace = challenge.protectionSpace()
        host = protectionSpace.host()
        realm = protectionSpace.realm()
        authenticationMethod = protectionSpace.authenticationMethod()
        self.log(
            'Authentication challenge for Host: %s Realm: %s AuthMethod: %s'
            % (host, realm, authenticationMethod))
        if challenge.previousFailureCount() > 0:
            # we have the wrong credentials. just fail
            self.log('Previous authentication attempt failed.')
            challenge.sender().cancelAuthenticationChallenge_(challenge)
        if self.username and self.password and authenticationMethod in [
                'NSURLAuthenticationMethodDefault',
                'NSURLAuthenticationMethodHTTPBasic',
                'NSURLAuthenticationMethodHTTPDigest']:
            self.log('Will attempt to authenticate.')
            self.log('Username: %s Password: %s'
                     % (self.username, ('*' * len(self.password or ''))))
            credential = (
                NSURLCredential.credentialWithUser_password_persistence_(
                    self.username, self.password,
                    NSURLCredentialPersistenceNone))
            challenge.sender().useCredential_forAuthenticationChallenge_(
                credential, challenge)
        else:
            # fall back to system-provided default behavior
            self.log('Allowing OS to handle authentication request')
            challenge.sender(
                ).performDefaultHandlingForAuthenticationChallenge_(
                    challenge)

    def connection_canAuthenticateAgainstProtectionSpace_(
            self, connection, protectionSpace):
        '''NSURLConnection delegate method
        Sent to determine whether the delegate is able to respond to a
        protection space’s form of authentication.
        Deprecated in 10.10'''

        # we don't actually use the connection argument, so
        # pylint: disable=W0613

        # this is not called in 10.5.x.
        self.log('connection_canAuthenticateAgainstProtectionSpace_')
        if protectionSpace:
            host = protectionSpace.host()
            realm = protectionSpace.realm()
            authenticationMethod = protectionSpace.authenticationMethod()
            self.log('Protection space found. Host: %s Realm: %s AuthMethod: %s'
                     % (host, realm, authenticationMethod))
            if self.username and self.password and authenticationMethod in [
                    'NSURLAuthenticationMethodDefault',
                    'NSURLAuthenticationMethodHTTPBasic',
                    'NSURLAuthenticationMethodHTTPDigest']:
                # we know how to handle this
                self.log('Can handle this authentication request')
                return True
        # we don't know how to handle this; let the OS try
        self.log('Allowing OS to handle authentication request')
        return False

    def connection_didReceiveAuthenticationChallenge_(
            self, connection, challenge):
        '''NSURLConnection delegate method
        Sent when a connection must authenticate a challenge in order to
        download its request.
        Deprecated in 10.10'''

        # we don't actually use the connection argument, so
        # pylint: disable=W0613

        self.log('connection_didReceiveAuthenticationChallenge_')
        protectionSpace = challenge.protectionSpace()
        host = protectionSpace.host()
        realm = protectionSpace.realm()
        authenticationMethod = protectionSpace.authenticationMethod()
        self.log(
            'Authentication challenge for Host: %s Realm: %s AuthMethod: %s'
            % (host, realm, authenticationMethod))
        if challenge.previousFailureCount() > 0:
            # we have the wrong credentials. just fail
            self.log('Previous authentication attempt failed.')
            challenge.sender().cancelAuthenticationChallenge_(challenge)
        if self.username and self.password and authenticationMethod in [
                'NSURLAuthenticationMethodDefault',
                'NSURLAuthenticationMethodHTTPBasic',
                'NSURLAuthenticationMethodHTTPDigest']:
            self.log('Will attempt to authenticate.')
            self.log('Username: %s Password: %s'
                     % (self.username, ('*' * len(self.password or ''))))
            credential = (
                NSURLCredential.credentialWithUser_password_persistence_(
                    self.username, self.password,
                    NSURLCredentialPersistenceNone))
            challenge.sender().useCredential_forAuthenticationChallenge_(
                credential, challenge)
        else:
            # fall back to system-provided default behavior
            self.log('Continuing without credential.')
            challenge.sender(
                ).continueWithoutCredentialForAuthenticationChallenge_(
                    challenge)

    def connection_didReceiveData_(self, connection, data):
        '''NSURLConnectionDataDelegate method
        Sent as a connection loads data incrementally'''

        # we don't actually use the connection argument, so
        # pylint: disable=W0613

        if self.destination:
            self.destination.write(str(data))
        else:
            self.log(str(data).decode('UTF-8'))
        self.bytesReceived += len(data)
        if self.expectedLength != NSURLResponseUnknownLength:
            self.percentComplete = int(
                float(self.bytesReceived)/float(self.expectedLength) * 100.0)
