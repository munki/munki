#!/usr/bin/python
# encoding: utf-8
"""
generate_msu_test_data.py

Created by Greg Neagle on 2014-01-12.
"""

import sys
import os

import plistlib
from random import shuffle, randint
import subprocess


def get_random(the_list):
    return the_list
    shuffle(the_list)
    return the_list[0:randint(0, len(the_list))]

def main():
    thisdir = os.path.dirname(os.path.abspath(__file__))
    
    install_info = plistlib.readPlist(os.path.join(thisdir, 'InstallInfo.plist'))
    for key in ['managed_installs', 'removals', 'optional_installs']:
        install_info[key] = get_random(install_info[key])
    plistlib.writePlist(install_info, '/Library/Managed Installs/InstallInfo.plist')
        
    apple_updates = plistlib.readPlist(os.path.join(thisdir, 'AppleUpdates.plist'))
    apple_updates['AppleUpdates'] = [] #get_random(apple_updates['AppleUpdates'])
    plistlib.writePlist(apple_updates, '/Library/Managed Installs/AppleUpdates.plist')
    
    self_service = plistlib.readPlist(os.path.join(thisdir, 'SelfServeManifest'))
    for key in ['managed_installs', 'managed_uninstalls']:
        self_service[key] = get_random(self_service[key])
    plistlib.writePlist(self_service, '/Library/Managed Installs/manifests/SelfServeManifest')
    
    
if __name__ == '__main__':
	main()

