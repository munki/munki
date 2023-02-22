# encoding: utf-8
#
# Copyright 2009-2023 Greg Neagle.
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
from __future__ import absolute_import, print_function

import os
import shutil
import stat
import subprocess
import tempfile
import xattr

from .. import display
from .. import dmgutils
from .. import osutils
from .. import pkgutils


def set_permissions(item, full_destpath):
    '''Sets owner, group and mode for full_destpath from info in item.
    Returns 0 on success, non-zero otherwise'''
    # set owner and group
    user = item.get('user', 'root')
    group = item.get('group', 'admin')
    display.display_detail(
        "Setting owner and group for '%s' to '%s:%s'" % (full_destpath, user, group))
    retcode = subprocess.call(
        ['/usr/sbin/chown', '-R', user + ':' + group, full_destpath])
    if retcode:
        display.display_error(
            "Error setting owner and group for %s" % (full_destpath))
        return retcode

    # set mode
    mode = item.get('mode', 'o-w,go+rX')
    display.display_detail(
        "Setting mode for '%s' to '%s'" % (full_destpath, mode))
    retcode = subprocess.call(['/bin/chmod', '-R', mode, full_destpath])
    if retcode:
        display.display_error(
            "Error setting mode for %s" % (full_destpath))
        return retcode

    # no errors!
    return 0


def create_missing_dirs(destpath):
    '''Creates any missing intermediate directories so we can copy item.
    Returns non-zero if there is an error, 0 otherwise'''
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
                "There was an IO error in creating the path %s!", destpath)
            return -1
        except BaseException:
            display.display_error(
                "There was an unknown error in creating the path %s!"
                % destpath)
            return -1

        # chown each new dir
        for new_path in new_paths:
            os.chown(new_path, parent_uid, parent_gid)
        return 0


def remove_quarantine_from_item(some_path):
    '''Removes com.apple.quarantine from some_path'''
    try:
        if ("com.apple.quarantine" in
                xattr.xattr(some_path).list(options=xattr.XATTR_NOFOLLOW)):
            xattr.xattr(some_path).remove("com.apple.quarantine",
                                          options=xattr.XATTR_NOFOLLOW)
    except BaseException as err:
        display.display_warning(
            "Error removing com.apple.quarantine from %s: %s", some_path, err)


def remove_quarantine(some_path):
    '''Removes com.apple.quarantine from some_path, recursively'''
    remove_quarantine_from_item(some_path)
    if os.path.isdir(some_path):
        for (dirpath, dirnames, filenames) in os.walk(some_path, topdown=True):
            for filename in filenames:
                remove_quarantine_from_item(os.path.join(dirpath, filename))
            for dirname in dirnames:
                remove_quarantine_from_item(os.path.join(dirpath, dirname))


def validate_source_and_destination(mountpoint, item):
    '''Validates source and destination for item to be copied from a mounted
    disk image. Returns a tuple of (errorcode, source_path, destination_path)'''
    # get source itemname
    source_itemname = item.get("source_item")
    if not source_itemname:
        display.display_error("Missing name of item to copy!")
        return (-1, None, None)

    # check source path to see if it's present
    source_itempath = os.path.join(mountpoint, source_itemname)
    if not os.path.exists(source_itempath):
        display.display_error(
            "Source item %s does not exist!", source_itemname)
        return (-1, None, None)

    # get destination path and item name
    destpath = item.get('destination_path')
    dest_itemname = item.get("destination_item")
    if not destpath:
        destpath = item.get('destination_item')
        if destpath:
            # split it into path and name
            dest_itemname = os.path.basename(destpath)
            destpath = os.path.dirname(destpath)
    if not destpath:
        display.display_error("Missing destination path for item!")
        return (-1, None, None)

    # create any needed intermediate directories for the destpath
    retcode = create_missing_dirs(destpath)
    if retcode:
        return (retcode, None, None)

    # setup full destination path using 'destination_item', if supplied,
    # source_item if not.
    full_destpath = os.path.join(
        destpath, os.path.basename(dest_itemname or source_itemname))

    return (0, source_itempath, full_destpath)


def get_size(pathname):
    '''Recursively gets size of pathname in bytes'''
    if os.path.isdir(pathname):
        total_size = 0
        for dirpath, _, filenames in os.walk(pathname):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                # skip if it is symbolic link
                if not os.path.islink(filepath):
                    total_size += os.path.getsize(filepath)
        return total_size
    elif os.path.isfile(pathname):
        return os.path.getsize(pathname)
    return 0


def ditto_with_progress(source_path, dest_path):
    '''Uses ditto to copy an item and provides progress output'''
    source_size = get_size(source_path)
    total_bytes_copied = 0

    cmd = ["/usr/bin/ditto", "-V", "--noqtn", source_path, dest_path]
    proc = subprocess.Popen(cmd, shell=False, bufsize=-1,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)

    while True:
        output = proc.stdout.readline().decode('UTF-8')
        if not output and (proc.poll() != None):
            break
        words = output.rstrip('\n').split()
        if len(words) > 1 and words[1] == "bytes":
            try:
                bytes_copied = int(words[0])
            except TypeError:
                pass
            else:
                total_bytes_copied += bytes_copied
                display.display_percent_done(total_bytes_copied, source_size)

    return proc.returncode


def copy_items_from_mountpoint(mountpoint, itemlist):
    '''copies items from the mountpoint to the startup disk
    Returns 0 if no issues; some error code otherwise.

    If the 'destination_item' key is provided, items will be copied
    as its value.'''
    temp_destination_dir = tempfile.mkdtemp(dir=osutils.tmpdir())
    for item in itemlist:

        (errorcode,
         source_path,
         destination_path) = validate_source_and_destination(mountpoint, item)
        if errorcode:
            return errorcode

        # validation passed, OK to copy
        display.display_status_minor(
            "Copying %s to %s",
            os.path.basename(source_path), destination_path)

        temp_destination_path = os.path.join(
            temp_destination_dir, os.path.basename(destination_path))
        # copy the file or directory, removing the quarantine xattr and
        # preserving HFS+ compression
        #retcode = subprocess.call(["/usr/bin/ditto", "--noqtn",
        #                           source_path, temp_destination_path])
        retcode = ditto_with_progress(source_path, temp_destination_path)
        if retcode:
            display.display_error(
                "Error copying %s to %s", source_path, temp_destination_path)
            return retcode

        # remove com.apple.quarantine xattr since `man ditto` lies and doesn't
        # seem to actually always remove it
        remove_quarantine(temp_destination_path)

        # set desired permissions for item
        retcode = set_permissions(item, temp_destination_path)
        if retcode:
            return retcode

        # mv temp_destination_path to final destination path
        try:
            if (os.path.islink(destination_path) or
                    os.path.isfile(destination_path)):
                os.unlink(destination_path)
            elif os.path.isdir(destination_path):
                shutil.rmtree(destination_path)
        except (OSError, IOError) as err:
            display.display_error(
                "Error removing existing item at destination: %s" % err)
            return -1
        try:
            os.rename(temp_destination_path, destination_path)
        except (OSError, IOError) as err:
            display.display_error("Error moving item to destination: %s" % err)
            return -1

    # all items copied successfully!
    try:
        os.rmdir(temp_destination_dir)
    except (OSError, IOError):
        pass
    return 0


def copy_app_from_dmg(dmgpath):
    '''copies application from DMG to /Applications
    This type of installer_type is deprecated and should be
    replaced with the more generic copyFromDMG'''
    display.display_status_minor(
        'Mounting disk image %s', os.path.basename(dmgpath))
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
                "No application found on %s", os.path.basename(dmgpath))
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
        'Mounting disk image %s', os.path.basename(dmgpath))
    mountpoints = dmgutils.mountdmg(dmgpath, skip_verification=True)
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
            "No mountable filesystems on %s", os.path.basename(dmgpath))
        return -1


if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
