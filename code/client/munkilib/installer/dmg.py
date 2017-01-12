# encoding: utf-8
#
# Copyright 2009-2017 Greg Neagle.
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
installer.dmg

Created by Greg Neagle on 2017-01-03.

Routines for copying items from disk images
"""

import os
import stat
import subprocess
import xattr

from .. import display
from .. import dmgutils
from .. import osutils
from .. import pkgutils


def copy_items_from_mountpoint(mountpoint, itemlist):
    '''copies items from the mountpoint to the startup disk
    Returns 0 if no issues; some error code otherwise.

    If the 'destination_item' key is provided, items will be copied
    as its value.'''
    for item in itemlist:

        # get itemname
        source_itemname = item.get("source_item")
        dest_itemname = item.get("destination_item")
        if not source_itemname:
            display.display_error("Missing name of item to copy!")
            return -1

        # check source path
        source_itempath = os.path.join(mountpoint, source_itemname)
        if not os.path.exists(source_itempath):
            display.display_error(
                "Source item %s does not exist!" % source_itemname)
            return -1

        # check destination path
        destpath = item.get('destination_path')
        if not destpath:
            destpath = item.get('destination_item')
            if destpath:
                # split it into path and name
                dest_itemname = os.path.basename(destpath)
                destpath = os.path.dirname(destpath)

        if not destpath:
            display.display_error("Missing destination path for item!")
            return -1

        if not os.path.exists(destpath):
            display.display_detail(
                "Destination path %s does not exist, will determine "
                "owner/permissions from parent" % destpath)
            parent_path = destpath
            new_paths = []

            # work our way back up to an existing path and build a list
            while not os.path.exists(parent_path):
                new_paths.insert(0, parent_path)
                parent_path = os.path.split(parent_path)[0]

            # stat the parent, get uid/gid/mode
            parent_stat = os.stat(parent_path)
            parent_uid, parent_gid = parent_stat.st_uid, parent_stat.st_gid
            parent_mode = stat.S_IMODE(parent_stat.st_mode)

            # make the new tree with the parent's mode
            try:
                os.makedirs(destpath, mode=parent_mode)
            except IOError:
                display.display_error(
                    "There was an IO error in creating the path %s!" % destpath)
                return -1
            except BaseException:
                display.display_error(
                    "There was an unknown error in creating the path %s!"
                    % destpath)
                return -1

            # chown each new dir
            for new_path in new_paths:
                os.chown(new_path, parent_uid, parent_gid)


        # setup full destination path using 'destination_item', if supplied
        if dest_itemname:
            full_destpath = os.path.join(
                destpath, os.path.basename(dest_itemname))
        else:
            full_destpath = os.path.join(
                destpath, os.path.basename(source_itemname))

        # remove item if it already exists
        if os.path.exists(full_destpath):
            retcode = subprocess.call(["/bin/rm", "-rf", full_destpath])
            if retcode:
                display.display_error(
                    "Error removing existing %s" % full_destpath)
                return retcode

        # all tests passed, OK to copy
        display.display_status_minor(
            "Copying %s to %s" % (source_itemname, full_destpath))
        retcode = subprocess.call(["/usr/bin/ditto", "--noqtn",
                                   source_itempath, full_destpath])
        if retcode:
            display.display_error(
                "Error copying %s to %s" % (source_itempath, full_destpath))
            return retcode

        # remove com.apple.quarantine xattr since `man ditto` lies and doesn't
        # seem to actually always remove it
        try:
            if "com.apple.quarantine" in xattr.xattr(full_destpath).list():
                xattr.xattr(full_destpath).remove("com.apple.quarantine")
        except BaseException as err:
            display.display_warning(
                "Error removing com.apple.quarantine from %s: %s",
                full_destpath, err)

        # set owner
        user = item.get('user', 'root')
        display.display_detail(
            "Setting owner for '%s' to '%s'" % (full_destpath, user))
        retcode = subprocess.call(
            ['/usr/sbin/chown', '-R', user, full_destpath])
        if retcode:
            display.display_error(
                "Error setting owner for %s" % (full_destpath))
            return retcode

        # set group
        group = item.get('group', 'admin')
        display.display_detail(
            "Setting group for '%s' to '%s'" % (full_destpath, group))
        retcode = subprocess.call(
            ['/usr/bin/chgrp', '-R', group, full_destpath])
        if retcode:
            display.display_error(
                "Error setting group for %s" % (full_destpath))
            return retcode

        # set mode
        mode = item.get('mode', 'o-w')
        display.display_detail(
            "Setting mode for '%s' to '%s'" % (full_destpath, mode))
        retcode = subprocess.call(['/bin/chmod', '-R', mode, full_destpath])
        if retcode:
            display.display_error(
                "Error setting mode for %s" % (full_destpath))
            return retcode

    # all items copied successfully!
    return 0


def copy_app_from_dmg(dmgpath):
    '''copies application from DMG to /Applications
    This type of installer_type is deprecated and should be
    replaced with the more generic copyFromDMG'''
    display.display_status_minor(
        'Mounting disk image %s' % os.path.basename(dmgpath))
    mountpoints = dmgutils.mountdmg(dmgpath)
    if mountpoints:
        retcode = 0
        appname = None
        mountpoint = mountpoints[0]
        # find an app at the root level, copy it to /Applications
        for item in osutils.listdir(mountpoint):
            itempath = os.path.join(mountpoint, item)
            if pkgutils.isApplication(itempath):
                appname = item
                break

        if appname:
            # make an itemlist we can pass to copyItemsFromMountpoint
            itemlist = []
            item = {}
            item['source_item'] = appname
            item['destination_path'] = "/Applications"
            itemlist.append(item)
            retcode = copy_items_from_mountpoint(mountpoint, itemlist)
            if retcode == 0:
                # let the user know we completed successfully
                display.display_status_minor(
                    "The software was successfully installed.")
        else:
            display.display_error(
                "No application found on %s" % os.path.basename(dmgpath))
            retcode = -2
        dmgutils.unmountdmg(mountpoint)
        return retcode
    else:
        display.display_error(
            "No mountable filesystems on %s", os.path.basename(dmgpath))
        return -1


def copy_from_dmg(dmgpath, itemlist):
    '''copies items from DMG to local disk'''
    if not itemlist:
        display.display_error("No items to copy!")
        return -1

    display.display_status_minor(
        'Mounting disk image %s' % os.path.basename(dmgpath))
    mountpoints = dmgutils.mountdmg(dmgpath)
    if mountpoints:
        mountpoint = mountpoints[0]
        retcode = copy_items_from_mountpoint(mountpoint, itemlist)
        if retcode == 0:
            # let the user know we completed successfully
            display.display_status_minor(
                "The software was successfully installed.")
        dmgutils.unmountdmg(mountpoint)
        return retcode
    else:
        display.display_error(
            "No mountable filesystems on %s" % os.path.basename(dmgpath))
        return -1


if __name__ == '__main__':
    print 'This is a library of support tools for the Munki Suite.'
