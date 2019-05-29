'''Base bits for repo plugins'''
from __future__ import absolute_import, print_function

import imp
import os
import sys

from ._baseclasses import RepoError, Repo
from .FileRepo import FileRepo


def import_plugins(dirpath=None):
    """Imports plugins from dirpath or the directory this file is in"""
    plugin_names = []

    if not dirpath:
        # get the directory this __init__.py file is in
        dirpath = os.path.dirname(os.path.abspath(__file__))

    # find all the .py files (minus __init__.py)
    plugin_files = [
        os.path.splitext(name)[0]
        for name in os.listdir(dirpath)
        if name.endswith(".py") and not name.startswith("_")
    ]

    for name in plugin_files:
        if name in globals():
            # we already imported it
            plugin_names.append(name)
            continue
        plugin_filename = os.path.join(dirpath, name + ".py")
        try:
            # attempt to import the module
            _tmp = imp.load_source(name, plugin_filename)
            # look for an attribute with the plugin name
            plugin = getattr(_tmp, name)
            # add the processor to munkirepo's namespace
            globals()[name] = plugin
            plugin_names.append(name)
        except (ImportError, AttributeError) as err:
            # if we aren't successful, print a warning
            print(
                "WARNING: %s: %s" % (plugin_filename, err), file=sys.stderr
            )
    return plugin_names

__all__ = import_plugins()


# Helper functions for munkirepo plugins

def plugin_named(some_name):
    '''Returns a plugin object given a name'''
    try:
        return globals()[some_name]
    except (KeyError, AttributeError):
        print("ERROR: %s repo plugin not found." % some_name, file=sys.stderr)
        return None


def connect(repo_url, plugin_name):
    '''Return a repo object for operations on our Munki repo'''
    plugin = plugin_named(plugin_name or 'FileRepo')
    if plugin:
        return plugin(repo_url)
    else:
        raise RepoError('Could not find repo plugin named: %s' % plugin_name)
