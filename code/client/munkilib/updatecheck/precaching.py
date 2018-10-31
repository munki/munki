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
precaching

Created by Greg Neagle on 2018-05-06.

Module for precaching optional installs with installed=False and precache=True.
"""
import os

from . import download

from .. import FoundationPlist
from .. import display
from .. import fetch
from .. import launchd
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


def uncache(space_needed_in_kb):
    '''Discard precached items to free up space for managed installs'''
    install_info = _installinfo()
    precached_items = [
        [os.path.basename(item['installer_item_location'])]
        for item in _items_to_precache(install_info)
        if item.get('installer_item_location')]
    if not precached_items:
        return

    cachedir = os.path.join(prefs.pref('ManagedInstallDir'), 'Cache')
    precached_size = 0
    for item in precached_items:
        # item is [itemname]
        item_path = os.path.join(cachedir, item[0])
        itemsize = int(os.path.getsize(item_path)/1024)
        precached_size += itemsize
        item.append(itemsize)
        # item is now [itemname, itemsize]

    if precached_size < space_needed_in_kb:
        # we can't clear enough space, so don't bother removing anything.
        # otherwise we'll clear some space, but still can't download the large
        # managed install, but then we'll have enough space to redownload the
        # precachable items and so we will (and possibly do this over and
        # over -- delete some, redownload, delete some, redownload...)
        return

    # sort reversed by size; smallest at end
    precached_items.sort(key=lambda x: x[1], reverse=True)
    deleted_kb = 0
    while precached_items:
        if deleted_kb >= space_needed_in_kb:
            break
        # remove and return last item in precached_items
        # we delete the smallest item first, proceeeding until we've freed up
        # enough space or deleted all the items
        item = precached_items.pop()
        item_path = os.path.join(cachedir, item[0])
        item_size = item[1]
        try:
            os.remove(item_path)
            deleted_kb += item_size
        except OSError, err:
            display.display_error(
                "Could not remove precached item %s: %s" % (item_path, err))


def run_agent():
    '''Kick off a run of our precaching agent, which allows the precaching to
    run in the background after a normal Munki run'''
    parent_dir = (
        os.path.dirname(
            os.path.dirname(
                os.path.dirname(
                    os.path.abspath(__file__)))))
    precache_agent_path = os.path.join(parent_dir, 'precache_agent')
    if not os.path.exists(precache_agent_path):
        # try absolute path in Munki's normal install dir
        precache_agent_path = '/usr/local/munki/precache_agent'
    if os.path.exists(precache_agent_path):
        try:
            job = launchd.Job([precache_agent_path], cleanup_at_exit=False)
            job.start()
        except launchd.LaunchdJobException as err:
            display.display_error(
                'Error with launchd job (%s): %s', precache_agent_path, err)
    else:
        display.display_error("Could not find precache_agent")


if __name__ == '__main__':
    print 'This is a library of support tools for the Munki Suite.'
