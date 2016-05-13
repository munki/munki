#!/usr/bin/python
# encoding: utf-8

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
