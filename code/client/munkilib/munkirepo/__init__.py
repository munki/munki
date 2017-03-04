import imp
import os
import sys


class Repo(object):
    '''Abstract base class for repo'''
    mounted = False

    def __init__(self, path, url):
        self.root = path
        self.url = url

    def available(self):
        '''if path does not exist, mount to local filesystem'''
        if not self.exists():
            retcode = self.mount()
            if retcode == 0:
                self.mounted = True
        #if path still doesn't exist, then cannot find munki_repo
        if not self.exists():
            print >> sys.stderr, "repo is missing"
            return False
        #check if all subdirectories are there
        for subdir in ['catalogs', 'manifests', 'pkgs', 'pkgsinfo']:
            if not self.exists(subdir):
                print >> sys.stderr, "repo is missing %s" % subdir
                return False
        # if we get this far, the repo path looks OK
        return True

    def exists(self):
        '''Must be overriden in subclass'''
        return False

    def mount(self):
        '''Must be overridden in subclasses'''
        return -1


class MissingRepo(Repo):
    '''Stub object to return when we can't find the one requsted'''
    def available(self):
        return False


def plugin_named(name):
    '''Returns a plugin object given a name'''
    try:
        module = globals()[name]
        return getattr(module, name)
    except (KeyError, AttributeError):
        print >> sys.stderr, (
            "ERROR: %s repo plugin not found." % name)
        return None


def connect(repo_path, repo_url, plugin_name):
    '''Return a repo object for operations on our Munki repo'''
    if plugin_name is None:
        plugin_name = 'FileRepo'
    plugin = plugin_named(plugin_name)
    if plugin:
        return plugin(repo_path, repo_url)
    else:
        return MissingRepo(repo_path, repo_url)


# yes, having this at the end is weird. But it allows us to dynamically import
# additional modules from our directory
__all__ = [os.path.splitext(name)[0]
           for name in os.listdir(os.path.dirname(os.path.abspath(__file__)))
           if name.endswith('.py') and not name == '__init__.py']
from . import *
