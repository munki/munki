<<<<<<< HEAD
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
CommandRepo

Created by Centrify Corporation 2016-06-02.

Implementation for accessing a repo via an external command.
"""
=======
>>>>>>> 851ea6703c8409c6727c01b9dc625f9433df4a92

from collections import namedtuple
from collections import OrderedDict
import os
import re
import munkicommon
import sys
import tempfile
import subprocess

class CommandRepo:
<<<<<<< HEAD
    '''Repo implementation that runs an external command to access the repo.'''
=======
>>>>>>> 851ea6703c8409c6727c01b9dc625f9433df4a92
    def __init__(self, command, url):
        self.command = [command, url]

    def popen(self, *args, **kwargs):
<<<<<<< HEAD
        '''Open a pipe to the external command.'''
        return subprocess.Popen(self.command + list(filter(None, args)), bufsize=-1, **kwargs)

    def run(self, *args, **kwargs):
        '''Run the external command and return its exit status.'''
=======
        return subprocess.Popen(self.command + list(filter(None, args)), bufsize=-1, **kwargs)

    def run(self, *args, **kwargs):
>>>>>>> 851ea6703c8409c6727c01b9dc625f9433df4a92
        class Result:
            pass

        result = Result()

        proc = self.popen(*args, **kwargs)
        (result.stdout, result.stderr) = proc.communicate()
        result.returncode = proc.returncode
        return result

<<<<<<< HEAD
    def exists(self, path=None):
        '''Returns true if the specified path exists in the repo'''
        result = self.run('exists', path)
        return result.returncode == 0

    def isdir(self, path=None):
        '''Returns true if the specified path exists in the repo
        and is a directory.'''
        result = self.run('isdir', path)
        return result.returncode == 0

    def isfile(self, path=None):
        '''Returns true if the specified path exists in the repo
        and is a regular file.'''
        result = self.run('isfile', path)
        return result.returncode == 0

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
        result = self.run('mkdir', path, mode)
        return result.returncode

    def makedirs(self, path, mode=0777):
        '''Creates a directory within the repo, including parent directories.'''
        result = self.run('makedirs', path, mode)
        return result.returncode

    def listdir(self, path):
        '''Lists the contents of a repo directory.'''
=======
    def exists(self, subdir = None):
        result = self.run('exists', subdir)
        return result.returncode == 0

    def isfile(self, subdir = None):
        result = self.run('isfile', subdir)
        return result.returncode == 0

    def join(self, *args):
        return os.path.join(*args)

    def dirname(self, path):
        return os.path.dirname(path)

    def basename(self, path):
        return os.path.basename(path)

    def splitext(self, path):
        return os.path.splitext(path)

    def makedirs(self, path):
        result = self.run('makedirs', path)
        return result.returncode

    def listdir(self, path):
>>>>>>> 851ea6703c8409c6727c01b9dc625f9433df4a92
        proc = self.popen('listdir', path, stdout=subprocess.PIPE)
        if proc:
            files = []
            while True:
                line = proc.stdout.readline().rstrip('\n')
                if not line:
                    break
                files.append(line)

            return files
        else:
            return None

    def remove(self, path):
<<<<<<< HEAD
        '''Removes a file from the repo.'''
=======
>>>>>>> 851ea6703c8409c6727c01b9dc625f9433df4a92
        result = self.run('remove', path)
        return result.returncode

    def unlink(self, path):
<<<<<<< HEAD
        '''Removes a file from the repo.'''
        return self.remove(path)

    def get(self, src, dest):
        '''Copies a file from the repo to a local file.'''
=======
        return self.remove(path)

    def get(self, src, dest):
>>>>>>> 851ea6703c8409c6727c01b9dc625f9433df4a92
        result = self.run('get', src, dest)
        return result.returncode

    def put(self, src, dest):
<<<<<<< HEAD
        '''Copies a local file to the repo.'''
        result = self.run('put', src, dest)
        return result.returncode

    #
    # Some callers open a file, but then use the local_path field
    # to access it rather than reading or writing through the returned
    # handle.  For local repos those callers could just use the
    # file name directly rather than opening it through this method,
    # but for the CommandRepo implementation the local_path field
    # will be a local temporary file that was copied from the remote
    # repo and/or will be copied to the remote repo on close.
    #
    def open(self, repo_path, mode='r'):
        '''Opens a file in the repo.'''
        class RepoFile:
            repo = None
            repo_path = None
            repo_mode = None
            local_path = None

            def __init__(self, repo, repo_path, mode):
                self.repo = repo
                self.repo_path = repo_path
                self.repo_mode = mode
                self.file = tempfile.NamedTemporaryFile(dir=munkicommon.tmpdir(), mode=mode,
                        delete=False, suffix=os.path.splitext(repo_path)[1])
                self.local_path = self.file.name
                if mode[0] == 'r':
                    returncode = self.repo.get(self.repo_path, self.local_path)
                    if returncode != 0:
                        raise IOError

            def __del__(self):
                if self.repo and self.repo_mode != 'r':
                    self.repo.put(self.local_path, self.repo_path)
                os.remove(self.local_path)
                return self
=======
        result = self.run('put', src, dest)
        return result.returncode

    def open(self, repo_path, mode='r'):
        class RepoFile:
            def __init__(self, path, mode):
                self.file = tempfile.NamedTemporaryFile(dir=munkicommon.tmpdir(), mode=mode,
                        delete=False)
>>>>>>> 851ea6703c8409c6727c01b9dc625f9433df4a92

            def read(self):
                return self.file.read()

<<<<<<< HEAD
        return RepoFile(self, repo_path, mode)

    def mount(self):
        '''Mounts the repo locally (not supported).'''
        return 0

    def unmount(self):
        '''Unmounts the repo (not supported).'''
        return 0

    def walk(self, path, **kwargs):
        '''Walks a path in the repo, returning all files and subdirectories.
        Only a subset of the features of os.walk() are supported.'''
=======
        handle = RepoFile(repo_path, mode)
        handle.repo_path = repo_path
        handle.repo_mode = mode
        handle.local_path = handle.file.name
        if mode[0] == 'r':
            returncode = self.get(repo_path, handle.local_path)
            if returncode != 0:
                raise IOError
        return handle

    def close(self, handle):
        if handle.repo_mode != 'r':
            return self.put(handle.local_path, handle.repo_path)
        else:
            return 0

    def mount(self):
        return 0

    def unmount(self):
        return 0

    def walk(self, path, **kwargs):
>>>>>>> 851ea6703c8409c6727c01b9dc625f9433df4a92
        match = re.compile(r'(?:\./)*(.*)/([^/\n]*)\n*')
        proc = self.popen('walk', path, stdout=subprocess.PIPE)
        dirs = OrderedDict()
        while True:
            line = proc.stdout.readline()
            if not line:
                break
            parts = match.match(line)
            if parts:
                dirpath = parts.group(1)
                base = parts.group(2)
                if not dirpath in dirs:
                    dirs[dirpath] = []
                dirs[dirpath].append(base)

        for dirpath in dirs:
            dirnames = []
            filenames = []

            for base in dirs[dirpath]:
                path = dirpath + '/' + base
                if path in dirs:
                    dirnames.append(base)
                else:
                    filenames.append(base)
            yield (dirpath, dirnames, filenames)

<<<<<<< HEAD
    def glob(self, path, *args):
        '''Expands a set of glob patterns within a repo path.'''
        matches = []
        proc = self.popen('glob', path, args, stdout=subprocess.PIPE)
        while True:
            line = proc.stdout.readline().rstrip('\n')
            if not line:
                break
            matches.append(line)

        return matches

=======
>>>>>>> 851ea6703c8409c6727c01b9dc625f9433df4a92
