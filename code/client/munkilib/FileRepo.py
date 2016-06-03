
from collections import namedtuple
from munkicommon import listdir
import os
import sys
import subprocess

class FileRepo:
    def __init__(self, path, url):
        self.path = path
        self.url = url

    def exists(self, subdir = None):
        full_path = self.path
        if subdir:
            full_path = os.path.join(full_path, subdir)
        return os.path.exists(full_path)

    def isfile(self, path):
        return os.path.isfile(os.path.join(self.path, path))

    def join(self, *args):
        return os.path.join(*args)

    def dirname(self, path):
        return os.path.dirname(path)

    def basename(self, path):
        return os.path.basename(path)

    def splitext(self, path):
        return os.path.splitext(path)

    def mkdir(self, path):
        return os.mkdir(os.path.join(self.path, path))

    def makedirs(self, path):
        return os.makedirs(os.path.join(self.path, path))

    def listdir(self, path):
        return listdir(os.path.join(self.path, path))

    def remove(self, path):
        return os.remove(os.path.join(self.path, path))

    def unlink(self, path):
        return os.unlink(os.path.join(self.path, path))

    def get(self, src, dest):
        cmd = ['/bin/cp', os.path.join(self.path, src), dest]
        return subprocess.call(cmd)

    def put(self, src, dest):
        cmd = ['/bin/cp', src, os.path.join(self.path, dest)]
        return subprocess.call(cmd)

    def open(self, path, mode='r'):
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
        if os.path.exists(self.path):
            return
        os.mkdir(self.path)
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
        retcode = 0
        if os.path.exists(self.path):
            cmd = ['/sbin/umount', self.path]
            retcode = subprocess.call(cmd)
            os.rmdir(self.path)
        return retcode

    def walk(self, path, **kwargs):
        for (dirpath, dirnames, filenames) in os.walk(os.path.join(self.path, path), **kwargs):
            dirpath = dirpath[len(self.path) + 1:]
            yield (dirpath, dirnames, filenames)
