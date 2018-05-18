#!/usr/bin/python
# encoding: utf-8
#
# Copyright 2018 Greg Neagle.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
precached

Created by Greg Neagle on 2018-05-06.

Module for precacheing optional installs with installed=False and precache=True.
"""
import os

from . import download

from .. import FoundationPlist
from .. import display
from .. import fetch
from .. import prefs


def _installinfo():
    '''Get the install info from InstallInfo.plist'''
    managed_install_dir = prefs.pref('ManagedInstallDir')
    install_info_plist = os.path.join(managed_install_dir, 'InstallInfo.plist')
    try:
        return FoundationPlist.readPlist(install_info_plist)
    except FoundationPlist.FoundationPlistException:
        return {}


def _items_to_precache(install_info):
    '''Returns a list of items from InstallInfo.plist's optional_installs
    that have precache=True and installed=False'''
    optional_install_items = install_info.get('optional_installs', [])
    precache_items = [item for item in optional_install_items
                      if item.get('precache') and not item.get('installed')]
    return precache_items


def cache():
    '''Download any applicable precache items into our Cache folder'''
    install_info = _installinfo()
    for item in _items_to_precache(install_info):
        try:
            download.download_installeritem(item, install_info)
        except fetch.Error, err:
            display.display_warning(
                'Failed to precache the installer for %s because %s',
                item['name'], unicode(err))


if __name__ == '__main__':
    print 'This is a library of support tools for the Munki Suite.'
