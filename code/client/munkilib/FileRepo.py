#!/usr/bin/python
# encoding: utf-8
#
# Copyright 2016 Centrify Corporation.
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
FileRepo
Created by Centrify Corporation 2016-06-02.
Implementation for accessing a repo via direct file access, including
a remote repo mounted via AFP, SMB, or NFS.
"""

from collections import namedtuple
import sys
sys.path.append("/usr/local/munki/munkilib")
import munkilib.munkicommon
from munkicommon import listdir
import os
import sys
import subprocess

class FileRepo:
    '''Repo implementation that access a local or locally-mounted repo.'''
    def __init__(self, path, url):
        self.path = path
        self.url = url

    def exists(self, subdir = None):
        '''Returns true if the specified path exists in the repo'''
        full_path = self.path
        if subdir:
            full_path = os.path.join(full_path, subdir)
        return os.path.exists(full_path)

    def isdir(self, path):
        '''Returns true if the specified path exists in the repo
        and is a directory.'''
        return os.path.isdir(os.path.join(self.path, path))

    def isfile(self, path):
        '''Returns true if the specified path exists in the repo
        and is a regular file.'''
        return os.path.isfile(os.path.join(self.path, path))

    def join(self, *args):
        '''Combines path elements within the repo.'''
        return os.path.join(*args)

    def dirname(self, path):
        '''Returns the directory portion of a path.'''
        return os.path.dirname(path)

    def basename(self, path):
        '''Returns the filename portion of a path.'''
        return os.path.basename(path)

    def splitext(self, path):
        '''Splits the base and extention parts of a path.'''
        return os.path.splitext(path)

    def mkdir(self, path, mode=0777):
        '''Creates a directory within the repo.'''
        return os.mkdir(os.path.join(self.path, path), mode)

    def makedirs(self, path, mode=0777):
        '''Creates a directory within the repo, including parent directories.'''
        return os.makedirs(os.path.join(self.path, path), mode)

    def listdir(self, path):
        '''Lists the contents of a repo directory.'''
        return listdir(os.path.join(self.path, path))

    def remove(self, path):
        '''Removes a file from the repo.'''
        return os.remove(os.path.join(self.path, path))

    def unlink(self, path):
        '''Removes a file from the repo.'''
        return os.unlink(os.path.join(self.path, path))

    def get(self, src, dest):
        '''Copies a file from the repo to a local file.'''
        cmd = ['/bin/cp', os.path.join(self.path, src), dest]
        return subprocess.call(cmd)

    def put(self, src, dest):
        '''Copies a local file to the repo.'''
        cmd = ['/bin/cp', src, os.path.join(self.path, dest)]
        return subprocess.call(cmd)

    #
    # Some callers open a file, but then use the local_path field
    # to access it rather than reading or writing through the returned
    # handle.  For local repos those callers could just use the
    # file name directly rather than opening it through this method,
    # but for the CommandRepo implementation the local_path field
    # will be a local temporary file that was copied from the remote
    # repo and/or will be copied to the remote repo on close.
    #
    def open(self, path, mode='r'):
        '''Opens a file in the repo.'''
        class RepoFile:
            def __init__(self, repo, repo_path, mode):
                self.repo = repo
                self.repo_path = repo_path
                self.repo_mode = mode
                self.file = open(self.repo_path, mode)
                self.local_path = self.repo_path

            def read(self):
                return self.file.read()

        return RepoFile(self, os.path.join(self.path, path), mode)

    def mount(self):
        '''Mounts the repo locally.'''
        if os.path.exists(self.path):
            return
        os.mkdir(self.path)
        print self.url
        print 'Attempting to mount fileshare %s:' % self.url
        if self.url.startswith('afp:'):
            cmd = ['/sbin/mount_afp', '-i', self.url, self.path]
        elif self.url.startswith('smb:'):
            cmd = ['/sbin/mount_smbfs', self.url[4:], self.path]
        elif self.url.startswith('nfs://'):
            cmd = ['/sbin/mount_nfs', self.url[6:], self.path]
        else:
            print >> sys.stderr, 'Unsupported filesystem URL!'
            return
        retcode = subprocess.call(cmd)
        if retcode:
            os.rmdir(self.path)
        return retcode

    def unmount(self):
        '''Unmounts the repo.'''
        retcode = 0
        if os.path.exists(self.path):
            cmd = ['/sbin/umount', self.path]
            retcode = subprocess.call(cmd)
            os.rmdir(self.path)
        return retcode

    def walk(self, path, **kwargs):
        '''Walks a path in the repo, returning all files and subdirectories.
        Only a subset of the features of os.walk() are supported.'''
        for (dirpath, dirnames, filenames) in os.walk(os.path.join(self.path, path), **kwargs):
            dirpath = dirpath[len(self.path) + 1:]
            yield (dirpath, dirnames, filenames)

    def glob(self, path, *args):
        '''Expands a set of glob patterns within a repo path.'''
        matches = []
        original_dir = os.getcwd()
        os.chdir(path)
        for arg in args:
            pkgs += glob.glob(arg)
        os.chdir(original_dir)