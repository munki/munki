# encoding: utf-8

import base64
import getpass
import os
import plistlib
import subprocess
import tempfile

from munkilib.munkirepo import Repo
from munkilib import display

CURL_CMD = '/usr/bin/curl'

class CurlError(Exception):
    pass


class MWA2APIRepo(Repo):

    def __init__(self, baseurl):
        '''Constructor'''
        self.baseurl = baseurl
        self.authtoken = None

    def connect(self):
        '''For a fileshare repo, we'd mount the share, prompting for
        credentials if needed. For the API repo, well look for a stored
        authtoken; if we don't find one, we'll prompt for credentials
        and make an authtoken.'''
        print 'Please provide credentials for %s:' % self.baseurl
        username = raw_input('Username: ')
        password = getpass.getpass()
        user_and_pass = '%s:%s' % (username, password)
        self.authtoken = 'Basic %s' % base64.b64encode(user_and_pass)

    def _curl(self, relative_url, headers=None, method='GET',
             filename=None, content=None):
        '''Use curl to talk to MWA2 API'''
        # we use a config/directive file to avoid having the auth header show
        # up in a process listing
        fileref, directivepath = tempfile.mkstemp()
        fileobj = os.fdopen(fileref, 'w')
        print >> fileobj, 'silent'         # no progress meter
        print >> fileobj, 'show-error'     # print error msg to stderr
        print >> fileobj, 'fail'           # throw error if download fails
        print >> fileobj, 'location'       # follow redirects
        print >> fileobj, 'request = %s' % method
        if headers:
            for key in headers:
                print >> fileobj, 'header = "%s: %s"' % (key, headers[key])
        print >> fileobj, 'header = "Authorization: %s"' % self.authtoken
        if method == 'GET':
            print >> fileobj, 'header = "Accept: application/xml"'
        else:
            print >> fileobj, 'header = "Content-type: application/xml"'
        url = os.path.join(self.baseurl, relative_url)
        print >> fileobj, 'url = "%s"' % url
        fileobj.close()

        cmd = [CURL_CMD, '-q', '--config', directivepath]
        if filename and method == 'GET':
            cmd.extend(['-o', filename])
        if filename and method == 'PUT':
            cmd.extend(['-d', '@%s' % filename])
        elif content and method == 'PUT':
            cmd.extend(['-d', content])

        #display.display_debug1('Curl command is %s', cmd)
        proc = subprocess.Popen(cmd, shell=False, bufsize=-1,
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output, err = proc.communicate()
        try:
            os.unlink(directivepath)
        except OSError:
            pass
        if proc.returncode:
            raise CurlError((proc.returncode, err))
        return output

    def itemlist(self, kind):
        '''Returns a list of identifiers for each item of kind.
        Kind might be 'catalogs', 'manifests', 'pkgsinfo', 'pkgs', or 'icons'.
        For a file-backed repo this would be a list of pathnames.'''
        url = kind + '?api_fields=filename'
        try:
            data = self._curl(url)
        except CurlError, err:
            raise
        plist = plistlib.readPlistFromString(data)
        if kind in ['catalogs', 'manifests', 'pkgsinfo']:
            # it's a list of dicts containing 'filename' key/values
            return [item['filename'] for item in plist]
        else:
            # it's a list of filenames
            return plist

    def get(self, resource_identifier):
        '''Returns the content of item with given resource_identifier.
        For a file-backed repo, a resource_identifier of
        'pkgsinfo/apps/Firefox-52.0.plist' would return the contents of
        <repo_root>/pkgsinfo/apps/Firefox-52.0.plist.
        Avoid using this method with the 'pkgs' kind as it might return a
        really large blob of data.'''
        try:
            return self._curl(resource_identifier)
        except CurlError, err:
            raise

    def get_to_local_file(self, resource_identifier, local_file_path):
        '''Gets the contents of item with given resource_identifier and saves
        it to local_file_path.
        For a file-backed repo, a resource_identifier
        of 'pkgsinfo/apps/Firefox-52.0.plist' would copy the contents of
        <repo_root>/pkgsinfo/apps/Firefox-52.0.plist to a local file given by
        local_file_path.'''
        try:
            result = self._curl(resource_identifier, filename=local_file_path)
        except CurlError, err:
            raise

    def put(self, resource_identifier, content):
        '''Stores content on the repo based on resource_identifier.
        For a file-backed repo, a resource_identifier of
        'pkgsinfo/apps/Firefox-52.0.plist' would result in the content being
        saved to <repo_root>/pkgsinfo/apps/Firefox-52.0.plist.'''
        try:
            result = self._curl(
                resource_identifier, method='PUT', content=content)
        except CurlError, err:
            raise

    def put_from_local_file(self, resource_identifier, local_file_path):
        '''Copies the content of local_file_path to the repo based on
        resource_identifier. For a file-backed repo, a resource_identifier
        of 'pkgsinfo/apps/Firefox-52.0.plist' would result in the content
        being saved to <repo_root>/pkgsinfo/apps/Firefox-52.0.plist.'''
        try:
            result = self._curl(
                resource_identifier, method='PUT', filename=local_file_path)
        except CurlError, err:
            raise

    def delete(self, resource_identifier):
        '''Deletes a repo object located by resource_identifier.
        For a file-backed repo, a resource_identifier of
        'pkgsinfo/apps/Firefox-52.0.plist' would result in the deletion of
        <repo_root>/pkgsinfo/apps/Firefox-52.0.plist.'''
        try:
            result = self._curl(resource_identifier, method='DELETE')
        except CurlError, err:
            raise
        