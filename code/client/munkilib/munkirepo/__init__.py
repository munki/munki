import imp
import os
import sys


class RepoError(Exception):
    '''Base exception for repo errors'''
    pass


class Repo(object):
    '''Abstract base class for repo'''
    def __init__(self, url):
        '''Override in subclasses'''
        pass


def plugin_named(name):
    '''Returns a plugin object given a name'''
    try:
        module = globals()[name]
        return getattr(module, name)
    except (KeyError, AttributeError):
        print >> sys.stderr, (
            "ERROR: %s repo plugin not found." % name)
        return None


def connect(repo_url, plugin_name):
    '''Return a repo object for operations on our Munki repo'''
    plugin = plugin_named(plugin_name or 'FileRepo')
    if plugin:
        return plugin(repo_url)
    else:
        raise RepoError('Could not find repo plugin named %s' % plugin_name)


# yes, having this at the end is weird. But it allows us to dynamically import
# additional modules from our directory
__all__ = [os.path.splitext(name)[0]
           for name in os.listdir(os.path.dirname(os.path.abspath(__file__)))
           if name.endswith('.py') and not name == '__init__.py']
from . import *
