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
Repo
Created by Centrify Corporation 2016-06-02.
Interface for accessing a repo.
"""

import re
import sys
import imp
import os

def Open(path, url, plugin):
    #looks for installtion path for munki
    # first look for a plugin in the same dir as us in munkilib/plugins
    munkilib_path = os.path.dirname(os.path.abspath(__file__))
    munkilib_path = os.path.join(munkilib_path, 'plugins')
    if not os.path.exists(munkilib_path):
        # didn't find it; assume the default install path
        command = "munkiimport"
        commandPath = os.popen("/usr/bin/which %s" % command).read().strip() 
        commandPath = os.path.split(commandPath)
        munkilib_path = commandPath[0]
        #use default munki location if munki installation path is not found
        if munkilib_path == None or munkilib_path == "":
            munkilib_path = '/usr/local/munki/munkilib/plugins'
        else:
            munkilib_path = munkilib_path + '/munkilib/plugins'
    #looks for plugin in /usr/local/munki/munkilib/plugins (installation of munki)
    if plugin == None or plugin == "":
        #default is FileRepo
        plugin = 'FileRepo'
    module = imp.load_source(plugin, munkilib_path + "/" + plugin + ".py")
    import_class = getattr(module, plugin)
    parent = import_class

    class Repo(parent):
        mounted = False

        def available(self):
            #if path does not exist, mount to local filesystem 
            if not self.exists():
                retcode = self.mount()
                if retcode == 0:
                    self.mounted = True
            #if path still doesn't exist, then cannot find munki_repo
            if not self.exists():
                print >> sys.stderr, "repo is missing"
                return False
            #checks if all subdirectories are there
            for subdir in ['catalogs', 'manifests', 'pkgs', 'pkgsinfo']:
                if not self.exists(subdir):
                    print >> sys.stderr, "repo is missing %s" % subdir
                    return False
            # if we get this far, the repo path looks OK
            return True

    return Repo(path, url)
