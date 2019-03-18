# encoding: utf-8
#
#  msclib.py
#
#  Created by Greg Neagle on 12/10/13.
#  Copyright 2010-2019 Greg Neagle.
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
'''Some functions used a few places that don't (yet) have an obvious home'''


import os
import sys

import shutil

from zipfile import ZipFile, BadZipfile

from Foundation import *
from AppKit import *

import msclog
import munki

_html_dir = None


def updateCountMessage(count):
    '''Return a localized message describing the count of updates to install'''
    if count == 0:
        return NSLocalizedString(u"No pending updates", u"No Updates message")
    if count == 1:
        return NSLocalizedString(u"1 pending update", u"One Update message")
    else:
        return (NSLocalizedString(u"%s pending updates", u"Multiple Updates message") % count)


def getInstallAllButtonTextForCount(count):
    '''Return localized display text for action button in Updates view'''
    if count == 0:
        return NSLocalizedString(u"Check Again", u"Check Again button title")
    elif count == 1:
        return NSLocalizedString(u"Update", u"Update button title/action text")
    else:
        return NSLocalizedString(u"Update All", u"Update All button title")


def get_custom_resources():
    '''copies custom resources into our html dir'''
    if not _html_dir:
        return
    managed_install_dir = munki.pref('ManagedInstallDir')
    source_path = os.path.join(managed_install_dir, 'client_resources/custom.zip')
    if os.path.exists(source_path):
        dest_path = os.path.join(_html_dir, 'custom')
        if os.path.exists(dest_path):
            try:
                shutil.rmtree(dest_path, ignore_errors=True)
            except (OSError, IOError), err:
                msclog.debug_log('Error clearing %s: %s' % (dest_path, err))
        if not os.path.exists(dest_path):
            try:
                os.mkdir(dest_path)
            except (OSError, IOError), err:
                msclog.debug_log('Error creating %s: %s' % (dest_path, err))
        try:
            archive = ZipFile(source_path)
        except BadZipfile:
            # ignore it
            return
        archive_files = archive.namelist()
        # sanity checking in case the archive is not built correctly
        files_to_extract = [filename for filename in archive_files
                            if filename.startswith('resources/')
                            or filename.startswith('templates/')]
        if not files_to_extract:
            msclog.debug_log('Invalid client resources archive.')
        for filename in files_to_extract:
            try:
                if filename.endswith('/'):
                    # it's a directory. The extract method in Python 2.6 handles this wrong
                    # do we'll do it ourselves
                    os.makedirs(os.path.join(dest_path, filename))
                else:
                    archive.extract(filename, dest_path)
            except (OSError, IOError), err:
                msclog.debug_log('Error expanding %s from archive: %s' % (filename, err))


def html_dir():
    '''sets up our local html cache directory'''
    global _html_dir
    if _html_dir:
        return _html_dir
    bundle_id = NSBundle.mainBundle().bundleIdentifier()
    cache_dir_urls = NSFileManager.defaultManager().URLsForDirectory_inDomains_(
        NSCachesDirectory, NSUserDomainMask)
    if cache_dir_urls:
        cache_dir = cache_dir_urls[0].path()
    else:
        cache_dir = u'/private/tmp'
    our_cache_dir = os.path.join(cache_dir, bundle_id)
    if not os.path.exists(our_cache_dir):
         os.makedirs(our_cache_dir)
    _html_dir = os.path.join(our_cache_dir, 'html')
    if os.path.exists(_html_dir):
        # empty it
        shutil.rmtree(_html_dir)
    os.mkdir(_html_dir)
    
    # symlink our static files dir
    resourcesPath = NSBundle.mainBundle().resourcePath()
    source_path = os.path.join(resourcesPath, 'WebResources')
    link_path = os.path.join(_html_dir, 'static')
    os.symlink(source_path, link_path)
    
    # symlink the Managed Installs icons dir
    managed_install_dir = munki.pref('ManagedInstallDir')
    source_path = os.path.join(managed_install_dir, 'icons')
    link_path = os.path.join(_html_dir, 'icons')
    os.symlink(source_path, link_path)
    
    # unzip any custom client resources
    get_custom_resources()
    
    return _html_dir
