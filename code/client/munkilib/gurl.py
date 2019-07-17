# encoding: utf-8
#
# Copyright 2009-2019 Greg Neagle.
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
gurl.py

Created by Greg Neagle on 2013-11-21.
Modified in Feb 2016 to add support for NSURLSession.
Updated June 2019 for compatibility with Python 3 and PyObjC 5.1.2+

curl replacement using NSURLConnection and friends

Tested with PyObjC 2.5.1 (inlcuded with macOS)
and with PyObjC 5.2b1. Should also work with PyObjC 5.1.2.
May fail with other versions of PyObjC due to issues with completion handler
signatures.
"""
from __future__ import absolute_import, print_function

import os
import xattr

try:
    # Python 2
    from urlparse import urlparse
except ImportError:
    # Python 3
    from urllib.parse import urlparse


# builtin super doesn't work with Cocoa classes in recent PyObjC releases.
# pylint: disable=redefined-builtin,no-name-in-module
from objc import super
# pylint: enable=redefined-builtin,no-name-in-module

# PyLint cannot properly find names inside Cocoa libraries, so issues bogus
# No name 'Foo' in module 'Bar' warnings. Disable them.
# pylint: disable=E0611


from Foundation import (NSBundle, NSRunLoop, NSData, NSDate,
                        NSObject, NSURL, NSURLConnection,
                        NSMutableURLRequest,
                        NSURLRequestReloadIgnoringLocalCacheData,
                        NSURLResponseUnknownLength,
                        NSLog,
                        NSURLCredential, NSURLCredentialPersistenceNone,
                        NSPropertyListSerialization,
                        NSPropertyListMutableContainersAndLeaves,
                        NSPropertyListXMLFormat_v1_0)

try:
    from Foundation import NSURLSession, NSURLSessionConfiguration
    from CFNetwork import (kCFNetworkProxiesHTTPSEnable,
                           kCFNetworkProxiesHTTPEnable)
    NSURLSESSION_AVAILABLE = True
except ImportError:
    NSURLSESSION_AVAILABLE = False

# Disable PyLint complaining about 'invalid' names
# pylint: disable=C0103

if NSURLSESSION_AVAILABLE:
    # NSURLSessionAuthChallengeDisposition enum constants
    NSURLSessionAuthChallengeUseCredential = 0
    NSURLSessionAuthChallengePerformDefaultHandling = 1
    NSURLSessionAuthChallengeCancelAuthenticationChallenge = 2
    NSURLSessionAuthChallengeRejectProtectionSpace = 3

    # NSURLSessionResponseDisposition enum constants
    NSURLSessionResponseCancel = 0
    NSURLSessionResponseAllow = 1
    NSURLSessionResponseBecomeDownload = 2

    # TLS/SSLProtocol enum constants
    kSSLProtocolUnknown = 0
    kSSLProtocol3 = 2
    kTLSProtocol1 = 4
    kTLSProtocol11 = 7
    kTLSProtocol12 = 8
    kDTLSProtocol1 = 9

    # define a helper function for block callbacks
    import ctypes
    import objc
    CALLBACK_HELPER_AVAILABLE = True
    try:
        _objc_so = ctypes.cdll.LoadLibrary(
            os.path.join(objc.__path__[0], '_objc.so'))
    except OSError:
        # could not load _objc.so
        CALLBACK_HELPER_AVAILABLE = False
    else:
        PyObjCMethodSignature_WithMetaData = (
            _objc_so.PyObjCMethodSignature_WithMetaData)
        PyObjCMethodSignature_WithMetaData.restype = ctypes.py_object

        def objc_method_signature(signature_str):
            '''Return a PyObjCMethodSignature given a call signature in string
            format'''
            return PyObjCMethodSignature_WithMetaData(
                ctypes.create_string_buffer(signature_str), None, False)

# pylint: enable=E0611

# disturbing hack warning!
# this works around an issue with App Transport Security on 10.11
bundle = NSBundle.mainBundle()
info = bundle.localizedInfoDictionary() or bundle.infoDictionary()
info['NSAppTransportSecurity'] = {'NSAllowsArbitraryLoads': True}


def NSLogWrapper(message):
    '''A wrapper function for NSLog to prevent format string errors'''
    NSLog('%@', message)


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
       using NSURLConnection/NSURLSession and friends'''

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
            return None

        self.follow_redirects = options.get('follow_redirects', False)
        self.ignore_system_proxy = options.get('ignore_system_proxy', False)
        self.destination_path = options.get('file')
        self.can_resume = options.get('can_resume', False)
        self.url = options.get('url')
        self.additional_headers = options.get('additional_headers', {})
        self.username = options.get('username')
        self.password = options.get('password')
        self.download_only_if_changed = options.get(
            'download_only_if_changed', False)
        self.cache_data = options.get('cache_data')
        self.connection_timeout = options.get('connection_timeout', 60)
        if NSURLSESSION_AVAILABLE:
            self.minimum_tls_protocol = options.get(
                'minimum_tls_protocol', kTLSProtocol1)

        self.log = options.get('logging_function', NSLogWrapper)

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
        self.session = None
        self.task = None
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
            stored_data = self.getStoredHeaders()
            if (self.can_resume and 'expected-length' in stored_data and
                    ('last-modified' in stored_data or 'etag' in stored_data)):
                # we have a partial file and we're allowed to resume
                self.resume = True
                local_filesize = os.path.getsize(self.destination_path)
                byte_range = 'bytes=%s-' % local_filesize
                request.setValue_forHTTPHeaderField_(byte_range, 'Range')
        if self.download_only_if_changed and not self.resume:
            stored_data = self.cache_data or self.getStoredHeaders()
            if 'last-modified' in stored_data:
                request.setValue_forHTTPHeaderField_(
                    stored_data['last-modified'], 'if-modified-since')
            if 'etag' in stored_data:
                request.setValue_forHTTPHeaderField_(
                    stored_data['etag'], 'if-none-match')
        if NSURLSESSION_AVAILABLE:
            configuration = (
                NSURLSessionConfiguration.defaultSessionConfiguration())

            # optional: ignore system http/https proxies (10.9+ only)
            if self.ignore_system_proxy is True:
                configuration.setConnectionProxyDictionary_(
                    {kCFNetworkProxiesHTTPEnable: False,
                     kCFNetworkProxiesHTTPSEnable: False})

            # set minimum supported TLS protocol (defaults to TLS1)
            configuration.setTLSMinimumSupportedProtocol_(
                self.minimum_tls_protocol)

            self.session = (
                NSURLSession.sessionWithConfiguration_delegate_delegateQueue_(
                    configuration, self, None))
            self.task = self.session.dataTaskWithRequest_(request)
            self.task.resume()
        else:
            self.connection = NSURLConnection.alloc().initWithRequest_delegate_(
                request, self)

    def cancel(self):
        '''Cancel the connection'''
        if self.connection:
            if NSURLSESSION_AVAILABLE:
                self.session.invalidateAndCancel()
            else:
                self.connection.cancel()
            self.done = True

    def isDone(self):
        '''Check if the connection request is complete. As a side effect,
        allow the delegates to work by letting the run loop run for a bit'''
        if self.done:
            return self.done
        # let the delegates do their thing
        NSRunLoop.currentRunLoop().runUntilDate_(
            NSDate.dateWithTimeIntervalSinceNow_(.1))
        return self.done

    def getStoredHeaders(self):
        '''Returns any stored headers for self.destination_path'''
        # try to read stored headers
        try:
            stored_plist_bytestr = xattr.getxattr(
                self.destination_path, self.GURL_XATTR)
        except (KeyError, IOError):
            return {}
        data = NSData.dataWithBytes_length_(
            stored_plist_bytestr, len(stored_plist_bytestr))
        dataObject, _plistFormat, error = (
            NSPropertyListSerialization.
            propertyListFromData_mutabilityOption_format_errorDescription_(
                data, NSPropertyListMutableContainersAndLeaves, None, None))
        if error:
            return {}
        return dataObject

    def storeHeaders_(self, headers):
        '''Store dictionary data as an xattr for self.destination_path'''
        plistData, error = (
            NSPropertyListSerialization.
            dataFromPropertyList_format_errorDescription_(
                headers, NSPropertyListXMLFormat_v1_0, None))
        if error:
            byte_string = b''
        else:
            try:
                byte_string = bytes(plistData)
            except NameError:
                byte_string = str(plistData)
        try:
            xattr.setxattr(self.destination_path, self.GURL_XATTR, byte_string)
        except IOError as err:
            self.log('Could not store metadata to %s: %s'
                     % (self.destination_path, err))

    def normalizeHeaderDict_(self, a_dict):
        '''Since HTTP header names are not case-sensitive, we normalize a
        dictionary of HTTP headers by converting all the key names to
        lower case'''

        # yes, we don't use 'self'!
        # pylint: disable=R0201

        new_dict = {}
        for key, value in a_dict.items():
            new_dict[key.lower()] = value
        return new_dict

    def recordError_(self, error):
        '''Record any error info from completed connection/session'''
        self.error = error
        # If this was an SSL error, try to extract the SSL error code.
        if 'NSUnderlyingError' in error.userInfo():
            ssl_code = error.userInfo()['NSUnderlyingError'].userInfo().get(
                '_kCFNetworkCFStreamSSLErrorOriginalValue', None)
            if ssl_code:
                self.SSLerror = (ssl_code, ssl_error_codes.get(
                    ssl_code, 'Unknown SSL error'))

    def removeExpectedSizeFromStoredHeaders(self):
        '''If a successful transfer, clear the expected size so we
        don\'t attempt to resume the download next time'''
        if str(self.status).startswith('2'):
            # remove the expected-size from the stored headers
            headers = self.getStoredHeaders()
            if 'expected-length' in headers:
                del headers['expected-length']
                self.storeHeaders_(headers)

    def URLSession_task_didCompleteWithError_(self, _session, _task, error):
        '''NSURLSessionTaskDelegate method.'''
        if self.destination and self.destination_path:
            self.destination.close()
            self.removeExpectedSizeFromStoredHeaders()
        if error:
            self.recordError_(error)
        self.done = True

    def connection_didFailWithError_(self, _connection, error):
        '''NSURLConnectionDelegate method
        Sent when a connection fails to load its request successfully.'''
        self.recordError_(error)
        self.done = True
        if self.destination and self.destination_path:
            self.destination.close()

    def connectionDidFinishLoading_(self, _connection):
        '''NSURLConnectionDataDelegate method
        Sent when a connection has finished loading successfully.'''
        self.done = True
        if self.destination and self.destination_path:
            self.destination.close()
            self.removeExpectedSizeFromStoredHeaders()

    def handleResponse_withCompletionHandler_(
            self, response, completionHandler):
        '''Handle the response to the connection'''
        self.response = response
        self.bytesReceived = 0
        self.percentComplete = -1
        self.expectedLength = response.expectedContentLength()

        download_data = {}
        if response.className() == u'NSHTTPURLResponse':
            # Headers and status code only available for HTTP/S transfers
            self.status = response.statusCode()
            self.headers = dict(response.allHeaderFields())
            normalized_headers = self.normalizeHeaderDict_(self.headers)
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
                stored_data = self.getStoredHeaders()
                if (not stored_data or
                        stored_data.get('etag') != download_data.get('etag') or
                        stored_data.get('last-modified') != download_data.get(
                            'last-modified')):
                    # file on server is different than the one
                    # we have a partial for
                    self.log(
                        'Can\'t resume download; file on server has changed.')
                    if completionHandler:
                        # tell the session task to cancel
                        completionHandler(NSURLSessionResponseCancel)
                    else:
                        # cancel the connection
                        self.connection.cancel()
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
                self.destination = open(self.destination_path, 'ab')

            elif str(self.status).startswith('2'):
                # not resuming, just open the file for writing
                self.destination = open(self.destination_path, 'wb')
                # store some headers with the file for use if we need to resume
                # the download and for future checking if the file on the server
                # has changed
                self.storeHeaders_(download_data)

        if completionHandler:
            # tell the session task to continue
            completionHandler(NSURLSessionResponseAllow)

    def URLSession_dataTask_didReceiveResponse_completionHandler_(
            self, _session, _task, response, completionHandler):
        '''NSURLSessionDataDelegate method'''
        if CALLBACK_HELPER_AVAILABLE:
            completionHandler.__block_signature__ = objc_method_signature(b'v@i')
        self.handleResponse_withCompletionHandler_(response, completionHandler)

    def connection_didReceiveResponse_(self, _connection, response):
        '''NSURLConnectionDataDelegate delegate method
        Sent when the connection has received sufficient data to construct the
        URL response for its request.'''
        self.handleResponse_withCompletionHandler_(response, None)

    def handleRedirect_newRequest_withCompletionHandler_(
            self, response, request, completionHandler):
        '''Handle the redirect request'''
        def allowRedirect():
            '''Allow the redirect'''
            if completionHandler:
                completionHandler(request)
                return None
            return request

        def denyRedirect():
            '''Deny the redirect'''
            if completionHandler:
                completionHandler(None)
            return None

        newURL = request.URL().absoluteString()
        if response is None:
            # the request has changed the NSURLRequest in order to standardize
            # its format, for example, changing a request for
            # http://www.apple.com to http://www.apple.com/. This occurs because
            # the standardized, or canonical, version of the request is used for
            # cache management. Pass the request back as-is
            # (it appears that at some point Apple also defined a redirect like
            # http://developer.apple.com to https://developer.apple.com to be
            # 'merely' a change in the canonical URL.)
            # Further -- it appears that this delegate method isn't called at
            # all in this scenario, unlike NSConnectionDelegate method
            # connection:willSendRequest:redirectResponse:
            # we'll leave this here anyway in case we're wrong about that
            self.log('Allowing redirect to: %s' % newURL)
            return allowRedirect()
        # If we get here, it appears to be a real redirect attempt
        # Annoyingly, we apparently can't get access to the headers from the
        # site that told us to redirect. All we know is that we were told
        # to redirect and where the new location is.
        self.redirection.append([newURL, dict(response.allHeaderFields())])
        newParsedURL = urlparse(newURL)
        # This code was largely based on the work of Andreas Fuchs
        # (https://github.com/munki/munki/pull/465)
        if self.follow_redirects is True or self.follow_redirects == 'all':
            # Allow the redirect
            self.log('Allowing redirect to: %s' % newURL)
            return allowRedirect()
        elif (self.follow_redirects == 'https'
              and newParsedURL.scheme == 'https'):
            # Once again, allow the redirect
            self.log('Allowing redirect to: %s' % newURL)
            return allowRedirect()
        # If we're down here either the preference was set to 'none',
        # the url we're forwarding on to isn't https or follow_redirects
        # was explicitly set to False
        self.log('Denying redirect to: %s' % newURL)
        return denyRedirect()

    # we don't control the API, so
    # pylint: disable=too-many-arguments
    def URLSession_task_willPerformHTTPRedirection_newRequest_completionHandler_(
            self, _session, _task, response, request, completionHandler):
        '''NSURLSessionTaskDelegate method'''
        self.log(
            'URLSession_task_willPerformHTTPRedirection_newRequest_'
            'completionHandler_')
        if CALLBACK_HELPER_AVAILABLE:
            completionHandler.__block_signature__ = objc_method_signature(b'v@@')
        self.handleRedirect_newRequest_withCompletionHandler_(
            response, request, completionHandler)
    # pylint: enable=too-many-arguments

    def connection_willSendRequest_redirectResponse_(
            self, _connection, request, response):
        '''NSURLConnectionDataDelegate method
        Sent when the connection determines that it must change URLs in order
        to continue loading a request.'''
        self.log('connection_willSendRequest_redirectResponse_')
        return self.handleRedirect_newRequest_withCompletionHandler_(
            response, request, None)

    def connection_canAuthenticateAgainstProtectionSpace_(
            self, _connection, protectionSpace):
        '''NSURLConnection delegate method
        Sent to determine whether the delegate is able to respond to a
        protection space’s form of authentication.
        Deprecated in 10.10'''
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

    def handleChallenge_withCompletionHandler_(
            self, challenge, completionHandler):
        '''Handle an authentication challenge'''
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
            if completionHandler:
                completionHandler(
                    NSURLSessionAuthChallengeCancelAuthenticationChallenge,
                    None)
            else:
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
            if completionHandler:
                completionHandler(
                    NSURLSessionAuthChallengeUseCredential, credential)
            else:
                challenge.sender().useCredential_forAuthenticationChallenge_(
                    credential, challenge)
        else:
            # fall back to system-provided default behavior
            self.log('Allowing OS to handle authentication request')
            if completionHandler:
                completionHandler(
                    NSURLSessionAuthChallengePerformDefaultHandling, None)
            else:
                if (challenge.sender().respondsToSelector_(
                        'performDefaultHandlingForAuthenticationChallenge:')):
                    self.log('Allowing OS to handle authentication request')
                    challenge.sender(
                        ).performDefaultHandlingForAuthenticationChallenge_(
                            challenge)
                else:
                    # Mac OS X 10.6 doesn't support
                    # performDefaultHandlingForAuthenticationChallenge:
                    self.log('Continuing without credential.')
                    challenge.sender(
                        ).continueWithoutCredentialForAuthenticationChallenge_(
                            challenge)

    def connection_willSendRequestForAuthenticationChallenge_(
            self, _connection, challenge):
        '''NSURLConnection delegate method
        Tells the delegate that the connection will send a request for an
        authentication challenge. New in 10.7.'''
        self.log('connection_willSendRequestForAuthenticationChallenge_')
        self.handleChallenge_withCompletionHandler_(challenge, None)

    def URLSession_task_didReceiveChallenge_completionHandler_(
            self, _session, _task, challenge, completionHandler):
        '''NSURLSessionTaskDelegate method'''
        if CALLBACK_HELPER_AVAILABLE:
            completionHandler.__block_signature__ = objc_method_signature(b'v@i@')
        self.log('URLSession_task_didReceiveChallenge_completionHandler_')
        self.handleChallenge_withCompletionHandler_(
            challenge, completionHandler)

    def connection_didReceiveAuthenticationChallenge_(
            self, _connection, challenge):
        '''NSURLConnection delegate method
        Sent when a connection must authenticate a challenge in order to
        download its request. Deprecated in 10.10'''
        self.log('connection_didReceiveAuthenticationChallenge_')
        self.handleChallenge_withCompletionHandler_(challenge, None)

    def handleReceivedData_(self, data):
        '''Handle received data'''
        if self.destination:
            self.destination.write(data)
        else:
            try:
                self.log(str(data))
            except Exception:
                pass
        self.bytesReceived += len(data)
        if self.expectedLength != NSURLResponseUnknownLength:
            # pylint: disable=old-division
            self.percentComplete = int(
                float(self.bytesReceived)/float(self.expectedLength) * 100.0)
            # pylint: enable=old-division

    def URLSession_dataTask_didReceiveData_(self, _session, _task, data):
        '''NSURLSessionDataDelegate method'''
        self.handleReceivedData_(data)

    def connection_didReceiveData_(self, _connection, data):
        '''NSURLConnectionDataDelegate method
        Sent as a connection loads data incrementally'''
        self.handleReceivedData_(data)


if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
