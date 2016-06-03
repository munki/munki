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
from FileRepo import FileRepo
from CommandRepo import CommandRepo

def Open(path, url):
    result = re.match(r'^ *\! *(.*)', path)
    if result:
        path = result.group(1)
        parent = CommandRepo
    else:
        parent = FileRepo

    class Repo(parent):
        mounted = False

        def available(self):
            if not self.exists():
                retcode = self.mount()
                if retcode == 0:
                    self.mounted = True
            if not self.exists():
                print >> sys.stderr, "repo is missing"
                return False
            for subdir in ['catalogs', 'manifests', 'pkgs', 'pkgsinfo']:
                if not self.exists(subdir):
                    print >> sys.stderr, "repo is missing %s" % subdir
                    return False
            # if we get this far, the repo path looks OK
            return True

    return Repo(path, url)
