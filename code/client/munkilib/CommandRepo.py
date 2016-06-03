
from collections import namedtuple
from collections import OrderedDict
import os
import re
import munkicommon
import sys
import tempfile
import subprocess

class CommandRepo:
    def __init__(self, command, url):
        self.command = [command, url]

    def popen(self, *args, **kwargs):
        return subprocess.Popen(self.command + list(filter(None, args)), bufsize=-1, **kwargs)

    def run(self, *args, **kwargs):
        class Result:
            pass

        result = Result()

        proc = self.popen(*args, **kwargs)
        (result.stdout, result.stderr) = proc.communicate()
        result.returncode = proc.returncode
        return result

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
        result = self.run('remove', path)
        return result.returncode

    def unlink(self, path):
        return self.remove(path)

    def get(self, src, dest):
        result = self.run('get', src, dest)
        return result.returncode

    def put(self, src, dest):
        result = self.run('put', src, dest)
        return result.returncode

    def open(self, repo_path, mode='r'):
        class RepoFile:
            def __init__(self, path, mode):
                self.file = tempfile.NamedTemporaryFile(dir=munkicommon.tmpdir(), mode=mode,
                        delete=False)

            def read(self):
                return self.file.read()

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

