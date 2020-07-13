# encoding: utf-8
'''Defines MWA2APIRepo plugin. See docstring for MWA2APIRepo class'''
from __future__ import absolute_import, print_function

import base64
import getpass
import os
import subprocess
import tempfile

try:
    # Python 2
    from urllib2 import quote
except ImportError:
    from urllib.parse import quote

from munkilib.munkirepo import Repo, RepoError
from munkilib.wrappers import get_input, readPlistFromString, PlistReadError

DEBUG = False

# TODO: make this more easily configurable
CURL_CMD = '/usr/bin/curl'


class CurlError(Exception):
    '''Error for curl operations'''
    pass


class MWA2APIRepo(Repo):
    '''Class for working with a repo accessible via the MWA2 API'''

    # pylint: disable=super-init-not-called
    def __init__(self, baseurl):
        '''Constructor'''
        self.baseurl = baseurl
        self.authtoken = None
        self._connect()
    # pylint: enable=super-init-not-called

    def _connect(self):
        '''For a fileshare repo, we'd mount the share, prompting for
        credentials if needed. For the API repo, we'll look for a stored
        authtoken; if we don't find one, we'll prompt for credentials
        and make an authtoken.'''
        if not self.authtoken:
            if 'MUNKIREPO_AUTHTOKEN' in os.environ:
                self.authtoken = os.environ['MUNKIREPO_AUTHTOKEN']
            else:
                print('Please provide credentials for %s:' % self.baseurl)
                username = get_input('Username: ')
                password = getpass.getpass()
                user_and_pass = ('%s:%s' % (username, password)).encode("UTF-8")
                self.authtoken = 'Basic %s' % base64.b64encode(
                    user_and_pass).decode("UTF-8")


    def _curl(self, relative_url, headers=None, method='GET',
              filename=None, content=None, formdata=None):
        '''Use curl to talk to MWA2 API'''
        # we use a config/directive file to avoid having the auth header show
        # up in a process listing
        contentpath = None
        fileref, directivepath = tempfile.mkstemp()
        fileobj = os.fdopen(fileref, 'w')
        print('silent', file=fileobj)         # no progress meter
        print('show-error', file=fileobj)     # print error msg to stderr
        print('fail', file=fileobj)           # throw error if download fails
        print('location', file=fileobj)       # follow redirects
        print('request = %s' % method, file=fileobj)
        if headers:
            for key in headers:
                print('header = "%s: %s"' % (key, headers[key]), file=fileobj)
        print('header = "Authorization: %s"' % self.authtoken, file=fileobj)

        if formdata:
            for line in formdata:
                print('form = "%s"' % line, file=fileobj)

        url = os.path.join(self.baseurl, relative_url)

        print('url = "%s"' % url, file=fileobj)
        fileobj.close()

        cmd = [CURL_CMD, '-q', '--config', directivepath]
        if filename and method == 'GET':
            cmd.extend(['-o', filename])
        if filename and method in ('PUT', 'POST'):
            cmd.extend(['-d', '@%s' % filename])
        elif content and method in ('PUT', 'POST'):
            if len(content) > 1024:
                # it's a lot of data; let's write it to a local file first
                # because we can't really pass it all via subprocess
                fileref, contentpath = tempfile.mkstemp()
                fileobj = os.fdopen(fileref, 'wb')
                fileobj.write(content)
                fileobj.close()
                cmd.extend(['-d', '@%s' % contentpath])
            else:
                cmd.extend(['-d', content])

        proc = subprocess.Popen(cmd, shell=False, bufsize=-1,
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output, err = proc.communicate()
        err = err.decode('UTF-8')
        if DEBUG:
            # save our curl_directives for debugging
            fileref = open(directivepath)
            curl_directives = fileref.read()
            fileref.close()
        try:
            os.unlink(directivepath)
            if contentpath:
                os.unlink(contentpath)
        except OSError:
            pass
        if proc.returncode:
            if DEBUG:
                raise CurlError((proc.returncode, err, curl_directives, cmd))
            else:
                raise CurlError((proc.returncode, err))
        return output

    def itemlist(self, kind):
        '''Returns a list of identifiers for each item of kind.
        Kind might be 'catalogs', 'manifests', 'pkgsinfo', 'pkgs', or 'icons'.
        For a file-backed repo this would be a list of pathnames.'''
        url = quote(kind.encode('UTF-8')) + '?api_fields=filename'
        headers = {'Accept': 'application/xml'}
        try:
            data = self._curl(url, headers=headers)
        except CurlError as err:
            raise RepoError(err)
        try:
            plist = readPlistFromString(data)
        except PlistReadError as err:
            raise RepoError(err)
        if kind in ['catalogs', 'manifests', 'pkgsinfo']:
            # it's a list of dicts containing 'filename' key/values
            return [item['filename'] for item in plist]

        # it's a list of filenames (pkgs, icons)
        return plist

    def get(self, resource_identifier):
        '''Returns the content of item with given resource_identifier.
        For a file-backed repo, a resource_identifier of
        'pkgsinfo/apps/Firefox-52.0.plist' would return the contents of
        <repo_root>/pkgsinfo/apps/Firefox-52.0.plist.
        Avoid using this method with the 'pkgs' kind as it might return a
        really large blob of data.'''
        url = quote(resource_identifier.encode('UTF-8'))
        if resource_identifier.startswith(
                ('catalogs/', 'manifests/', 'pkgsinfo/')):
            headers = {'Accept': 'application/xml'}
        else:
            headers = {}
        try:
            return self._curl(url, headers=headers)
        except CurlError as err:
            raise RepoError(err)

    def get_to_local_file(self, resource_identifier, local_file_path):
        '''Gets the contents of item with given resource_identifier and saves
        it to local_file_path.
        For a file-backed repo, a resource_identifier
        of 'pkgsinfo/apps/Firefox-52.0.plist' would copy the contents of
        <repo_root>/pkgsinfo/apps/Firefox-52.0.plist to a local file given by
        local_file_path.'''
        url = quote(resource_identifier.encode('UTF-8'))
        if resource_identifier.startswith(
                ('catalogs/', 'manifests/', 'pkgsinfo/')):
            headers = {'Accept': 'application/xml'}
        else:
            headers = {}
        try:
            self._curl(url, headers=headers, filename=local_file_path)
        except CurlError as err:
            raise RepoError(err)

    def put(self, resource_identifier, content):
        '''Stores content on the repo based on resource_identifier.
        For a file-backed repo, a resource_identifier of
        'pkgsinfo/apps/Firefox-52.0.plist' would result in the content being
        saved to <repo_root>/pkgsinfo/apps/Firefox-52.0.plist.'''
        url = quote(resource_identifier.encode('UTF-8'))
        if resource_identifier.startswith(
                ('catalogs/', 'manifests/', 'pkgsinfo/')):
            headers = {'Content-type': 'application/xml'}
        else:
            headers = {}
        try:
            self._curl(url, headers=headers, method='PUT', content=content)
        except CurlError as err:
            raise RepoError(err)

    def put_from_local_file(self, resource_identifier, local_file_path):
        '''Copies the content of local_file_path to the repo based on
        resource_identifier. For a file-backed repo, a resource_identifier
        of 'pkgsinfo/apps/Firefox-52.0.plist' would result in the content
        being saved to <repo_root>/pkgsinfo/apps/Firefox-52.0.plist.'''
        url = quote(resource_identifier.encode('UTF-8'))

        if resource_identifier.startswith(('pkgs/', 'icons/')):
            # MWA2API only supports POST for pkgs and icons
            # and file uploads need to be form encoded
            formdata = ['filedata=@%s' % local_file_path]
            try:
                self._curl(url, method='POST', formdata=formdata)
            except CurlError as err:
                raise RepoError(err)
        else:
            headers = {'Content-type': 'application/xml'}
            try:
                self._curl(url, headers=headers, method='PUT',
                           filename=local_file_path)
            except CurlError as err:
                raise RepoError(err)

    def delete(self, resource_identifier):
        '''Deletes a repo object located by resource_identifier.
        For a file-backed repo, a resource_identifier of
        'pkgsinfo/apps/Firefox-52.0.plist' would result in the deletion of
        <repo_root>/pkgsinfo/apps/Firefox-52.0.plist.'''
        url = quote(resource_identifier.encode('UTF-8'))
        try:
            self._curl(url, method='DELETE')
        except CurlError as err:
            raise RepoError(err)
        