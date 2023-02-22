# encoding: utf-8
#
# Copyright 2022-2023 Greg Neagle.
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
updatecheck.selfservice

Created by Greg Neagle on 2022-12-08.

"""
# This code is largely still compatible with Python 2, so for now, turn off
# Python 3 style warnings
# pylint: disable=consider-using-f-string
# pylint: disable=redundant-u-string-prefix

import os

from .. import prefs
from .. import display
from .. import FoundationPlist


def manifest_path():
    '''Returns path to canonical SelfServeManifest'''
    managed_install_dir = prefs.pref('ManagedInstallDir')
    return os.path.join(
        managed_install_dir, 'manifests', 'SelfServeManifest')


def update_manifest():
    """Updates the SelfServeManifest from a user-writable copy if it exists."""
    usermanifest = '/Users/Shared/.SelfServeManifest'
    selfservemanifest = manifest_path()

    if os.path.islink(usermanifest):
        # not allowed as it could link to things not normally
        # readable by unprivileged users
        try:
            os.unlink(usermanifest)
        except OSError:
            pass
        display.display_warning(
            "Found symlink at %s. Ignoring and removing."
            % selfservemanifest)

    if os.path.exists(usermanifest):
        # copy user-generated SelfServeManifest to our
        # managed_install_dir
        try:
            plist = FoundationPlist.readPlist(usermanifest)
            if plist:
                try:
                    FoundationPlist.writePlist(plist, selfservemanifest)
                except FoundationPlist.FoundationPlistException as err:
                    display.display_error(
                        'Could not write to %s: %s', selfservemanifest, err)
                else:
                    # now remove the user-generated manifest
                    try:
                        os.unlink(usermanifest)
                    except OSError:
                        pass
        except FoundationPlist.FoundationPlistException:
            # problem reading the usermanifest
            # better remove it
            display.display_error('Could not read %s', usermanifest)
            try:
                os.unlink(usermanifest)
            except OSError:
                pass


def process_default_installs(items):
    '''Process a default installs item. Potentially add it to managed_installs
    in the SelfServeManifest'''
    selfservemanifest = manifest_path()
    manifest = {}
    if os.path.exists(selfservemanifest):
        try:
            manifest = FoundationPlist.readPlist(selfservemanifest)
        except FoundationPlist.FoundationPlistException:
            manifest = {}
            display.display_error('Could not read %s', selfservemanifest)
            return

    for key in ["default_installs", "managed_installs"]:
        if not key in manifest:
            manifest[key] = []

    manifest_changed = False
    for item in items:
        if item not in manifest["default_installs"]:
            manifest["default_installs"].append(item)
            if item not in manifest["managed_installs"]:
                manifest["managed_installs"].append(item)
            manifest_changed = True

    if manifest_changed:
        try:
            FoundationPlist.writePlist(manifest, selfservemanifest)
        except FoundationPlist.FoundationPlistException as err:
            display.display_error(
                'Could not write %s: %s', selfservemanifest, err)


def clean_up_managed_uninstalls(installinfo_removals):
    '''Removes any already-removed items from the SelfServeManifest's
    managed_uninstalls (So the user can later install them again if they
    wish)'''
    selfservemanifest = manifest_path()
    if os.path.exists(selfservemanifest):
        # filter removals to get items already removed
        # (or never installed)
        removed_items = [item.get('name', '')
                         for item in installinfo_removals
                         if item.get('installed') is False]

        # for any item in the managed_uninstalls in the self-serve
        # manifest that is not installed, we should remove it from
        # the list
        try:
            plist = FoundationPlist.readPlist(selfservemanifest)
        except FoundationPlist.FoundationPlistException:
            pass
        else:
            plist['managed_uninstalls'] = [
                item for item in plist.get('managed_uninstalls', [])
                if item not in removed_items]
            try:
                FoundationPlist.writePlist(plist, selfservemanifest)
            except FoundationPlist.FoundationPlistException:
                pass
    