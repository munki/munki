# encoding: utf-8
'''Subclasses FileRepo to do git commits of file changes'''
from __future__ import absolute_import, print_function

import inspect
import os
import pwd
import subprocess
import sys

from munkilib.munkirepo.FileRepo import FileRepo

# TODO: make this more easily customized
GITCMD = '/usr/bin/git'

class MunkiGit(object):
    """A simple interface for some common interactions with the git binary"""

    def __init__(self, repo):
        self.cmd = GITCMD
        self.git_repo_dir = os.getcwd()
        self.munki_repo_dir = repo.root
        self.args = []
        self.results = {}

    def run_git(self, custom_args=None):
        """Executes the git command with the current set of arguments and
        returns a dictionary with the keys 'output', 'error', and
        'returncode'. You can optionally pass an array into customArgs to
        override the self.args value without overwriting them."""
        custom_args = self.args if custom_args is None else custom_args
        proc = subprocess.Popen([self.cmd] + custom_args,
                                shell=False,
                                bufsize=-1,
                                cwd=self.git_repo_dir,
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        (output, error) = proc.communicate()
        self.results = {
            "output": output.decode('UTF-8'),
            "error": error.decode('UTF-8'),
            "returncode": proc.returncode
        }
        return self.results

    def path_is_gitignored(self, a_path):
        """Returns True if path will be ignored by Git (usually due to being
        in a .gitignore file)"""
        self.git_repo_dir = os.path.dirname(a_path)
        self.run_git(['check-ignore', a_path])
        return self.results['returncode'] == 0

    def path_is_in_git_repo(self, a_path):
        """Returns True if the path is in a Git repo, false otherwise."""
        self.git_repo_dir = os.path.dirname(a_path)
        self.run_git(['status', '-z', a_path])
        return self.results['returncode'] == 0

    def commit_file_at_path(self, a_path):
        """Commits the file at 'a_path'. This method will also automatically
        generate the commit log appropriate for the status of a_path where
        status would be 'modified', 'new file', or 'deleted'"""

        # figure out the name of the tool in use
        try:
            toolname = os.path.basename(inspect.stack()[-1][1])
        except IndexError:
            toolname = 'Munki command-line tools'

        # get the status of the file at a_path
        self.git_repo_dir = os.path.dirname(a_path)
        status_results = self.run_git(['status', a_path])
        status_output = status_results['output']
        if status_output.find("new file:") != -1:
            action = 'created'
        elif status_output.find("modified:") != -1:
            action = 'modified'
        elif status_output.find("deleted:") != -1:
            action = 'deleted'
        else:
            action = 'did something with'

        # determine the path relative to self.munki_repo_dir
        # for the file at a_path
        itempath = a_path
        if a_path.startswith(self.munki_repo_dir):
            itempath = a_path[len(self.munki_repo_dir)+1:]

        username = pwd.getpwuid(os.getuid()).pw_name

        # generate the log message
        log_msg = (
            '%s %s \'%s\' via %s' % (username, action, itempath, toolname))
        print("Doing git commit: %s" % log_msg)
        self.run_git(['commit', '-m', log_msg])
        if self.results['returncode'] != 0:
            print("Failed to commit changes to %s" % a_path, file=sys.stderr)
            print(self.results['error'], file=sys.stderr)
            return -1
        return 0

    def _add_remove_file_at_path(self, a_path, operation):
        """Git adds or removes a file at a_path. operation must be either
        'add' or 'rm'"""
        if self.path_is_in_git_repo(a_path):
            if not self.path_is_gitignored(a_path):
                self.git_repo_dir = os.path.dirname(a_path)
                self.run_git([operation, a_path])
                if self.results['returncode'] == 0:
                    self.commit_file_at_path(a_path)
                else:
                    print("Git error: %s" % self.results['error'],
                          file=sys.stderr)
        else:
            print("%s is not in a git repo." % a_path, file=sys.stderr)

    def add_file_at_path(self, a_path):
        """Commits a file to the Git repo."""
        self._add_remove_file_at_path(a_path, 'add')

    def delete_file_at_path(self, a_path):
        """Deletes a file from the filesystem and Git repo."""
        self._add_remove_file_at_path(a_path, 'rm')


class GitFileRepo(FileRepo):
    '''A subclass of FileRepo that does git commits for pkginfo files'''

    def put(self, resource_identifier, content):
        super(GitFileRepo, self).put(resource_identifier, content)
        repo_filepath = os.path.join(self.root, resource_identifier)
        MunkiGit(self).add_file_at_path(repo_filepath)

    def put_from_local_file(self, resource_identifier, local_file_path):
        super(GitFileRepo, self).put_from_local_file(
            resource_identifier, local_file_path)
        repo_filepath = os.path.join(self.root, resource_identifier)
        MunkiGit(self).add_file_at_path(repo_filepath)

    def delete(self, resource_identifier):
        super(GitFileRepo, self).delete(resource_identifier)
        repo_filepath = os.path.join(self.root, resource_identifier)
        MunkiGit(self).delete_file_at_path(repo_filepath)
