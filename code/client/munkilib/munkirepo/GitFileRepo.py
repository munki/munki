import os

from munkilib.munkirepo.FileRepo import FileRepo

class GitFileRepo(FileRepo):
    '''A subclass of FileRepo that does git commits for pkginfo files'''

    class RepoFile(object):
        def __init__(self, repo, repo_path, mode):
            self.repo = repo
            self.repo_path = repo_path
            self.repo_mode = mode
            self.file = open(self.repo_path, mode)
            self.local_path = self.repo_path

        def __del__(self):
            if 'w' in self.repo_mode:
                print "Pretending to do a git commit on %s" % self.repo_path

        def read(self):
            return self.file.read()