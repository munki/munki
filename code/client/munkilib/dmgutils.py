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
dmgutils.py

Created by Greg Neagle on 2016-12-13.

Utilities for working with disk images.
"""
from __future__ import absolute_import, print_function

import os
import subprocess

from . import display
from . import utils
from .wrappers import readPlistFromString, PlistReadError


# we use lots of camelCase-style names. Deal with it.
# pylint: disable=C0103


# dmg helpers

def DMGisWritable(dmgpath):
    '''Attempts to determine if the given disk image is writable'''
    proc = subprocess.Popen(
        ['/usr/bin/hdiutil', 'imageinfo', dmgpath, '-plist'],
        bufsize=-1, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out, err) = proc.communicate()
    if err:
        display.display_error(
            u'hdiutil error %s with image %s.', err, dmgpath)
    (pliststr, out) = utils.getFirstPlist(out)
    if pliststr:
        try:
            plist = readPlistFromString(pliststr)
            dmg_format = plist.get('Format')
            if dmg_format in ['UDSB', 'UDSP', 'UDRW', 'RdWr']:
                return True
        except PlistReadError:
            pass
    return False


def dmg_has_sla(dmgpath):
    '''Returns true if dmg has a Software License Agreement.
    These dmgs normally cannot be attached without user intervention'''
    has_sla = False
    proc = subprocess.Popen(
        ['/usr/bin/hdiutil', 'imageinfo', dmgpath, '-plist'],
        bufsize=-1, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out, err) = proc.communicate()
    if err:
        display.display_error(
            u'hdiutil error %s with image %s.', err, dmgpath)
    (pliststr, out) = utils.getFirstPlist(out)
    if pliststr:
        try:
            plist = readPlistFromString(pliststr)
            properties = plist.get('Properties')
            if properties:
                has_sla = properties.get('Software License Agreement', False)
        except PlistReadError:
            pass

    return has_sla


def hdiutil_info():
    """
    Convenience method for running 'hdiutil info -plist'

    Returns the root object parsed with readPlistFromString()
    """
    proc = subprocess.Popen(
        ['/usr/bin/hdiutil', 'info', '-plist'],
        bufsize=-1, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out, err) = proc.communicate()
    if err:
        display.display_error(u'hdiutil info error: %s', err.decode("UTF-8"))
    (pliststr, out) = utils.getFirstPlist(out)
    if pliststr:
        try:
            plist = readPlistFromString(pliststr)
            return plist
        except PlistReadError:
            pass
    return None


def diskImageIsMounted(dmgpath):
    """
    Returns true if the given disk image is currently mounted
    """
    isMounted = False
    infoplist = hdiutil_info()
    for imageProperties in infoplist.get('images'):
        if 'image-path' in imageProperties:
            imagepath = imageProperties['image-path']
            if imagepath == dmgpath:
                for entity in imageProperties.get('system-entities', []):
                    if entity.get('mount-point'):
                        isMounted = True
                        break
    return isMounted


def pathIsVolumeMountPoint(path):
    """
    Checks if the given path is a volume for an attached disk image

    Returns true if the given path is a mount point or false if it isn't
    """
    isMountPoint = False
    infoplist = hdiutil_info()
    for imageProperties in infoplist.get('images'):
        if 'image-path' in imageProperties:
            for entity in imageProperties.get('system-entities', []):
                if 'mount-point' in entity:
                    mountpoint = entity['mount-point']
                    if path == mountpoint:
                        isMountPoint = True
                        break
    return isMountPoint


def diskImageForMountPoint(path):
    """
    Resolves the given mount point path to an attached disk image path

    Returns a path to a disk image file or None if the path is not
    a valid mount point
    """
    dmgpath = None
    infoplist = hdiutil_info()
    for imageProperties in infoplist.get('images'):
        if 'image-path' in imageProperties:
            imagepath = imageProperties['image-path']
            for entity in imageProperties.get('system-entities', []):
                if 'mount-point' in entity:
                    mountpoint = entity['mount-point']
                    if os.path.samefile(path, mountpoint):
                        dmgpath = imagepath
    return dmgpath


def mount_points_for_disk_image(dmgpath):
    """
    Returns a list of mountpoints for the given disk image
    """
    mountpoints = []
    infoplist = hdiutil_info()
    for imageProperties in infoplist.get('images'):
        if 'image-path' in imageProperties:
            imagepath = imageProperties['image-path']
            if imagepath == dmgpath:
                for entity in imageProperties.get('system-entities', []):
                    if 'mount-point' in entity:
                        mountpoints.append(entity['mount-point'])
                break
    return mountpoints


def mountdmg(dmgpath, use_shadow=False, use_existing_mounts=False,
             random_mountpoint=True, skip_verification=False):
    """
    Attempts to mount the dmg at dmgpath
    and returns a list of mountpoints
    If use_shadow is true, mount image with shadow file
    If random_mountpoint, mount at random dir under /tmp
    """
    mountpoints = []
    dmgname = os.path.basename(dmgpath)

    if use_existing_mounts:
        # Check if this dmg is already mounted
        # and if so, bail out and return the mountpoints
        if diskImageIsMounted(dmgpath):
            mountpoints = mount_points_for_disk_image(dmgpath)
            return mountpoints

    # Attempt to mount the dmg
    stdin = b''
    if dmg_has_sla(dmgpath):
        stdin = b'Y\n'
        display.display_detail(
            'NOTE: %s has embedded Software License Agreement' % dmgname)
    cmd = ['/usr/bin/hdiutil', 'attach', dmgpath, '-nobrowse', '-plist']
    if random_mountpoint:
        cmd.extend(['-mountRandom', '/tmp'])
    if use_shadow:
        cmd.append('-shadow')
    if skip_verification:
        cmd.append('-noverify')
    proc = subprocess.Popen(cmd,
                            bufsize=-1, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, stdin=subprocess.PIPE)
    (out, err) = proc.communicate(stdin)
    if proc.returncode:
        display.display_error(
            u'Error: "%s" while mounting %s.'
            % (err.decode('UTF-8').rstrip(), dmgname))
    (pliststr, out) = utils.getFirstPlist(out)
    if pliststr:
        try:
            plist = readPlistFromString(pliststr)
            for entity in plist.get('system-entities', []):
                if 'mount-point' in entity:
                    mountpoints.append(entity['mount-point'])
        except PlistReadError as err:
            display.display_error("%s" % err)
            display.display_error(
                'Bad plist string returned when mounting diskimage %s:\n%s'
                % (dmgname, pliststr))
    return mountpoints


def unmountdmg(mountpoint):
    """
    Unmounts the dmg at mountpoint
    """
    cmd = ['/usr/bin/hdiutil', 'detach', mountpoint]
    proc = subprocess.Popen(cmd, bufsize=-1, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    (dummy_output, err) = proc.communicate()
    if proc.returncode:
        # ordinary unmount unsuccessful, try forcing
        display.display_warning('Polite unmount failed: %s' % err)
        display.display_warning('Attempting to force unmount %s' % mountpoint)
        cmd.append('-force')
        proc = subprocess.Popen(cmd, bufsize=-1, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        (dummy_output, err) = proc.communicate()
        if proc.returncode:
            display.display_warning(
                'Failed to unmount %s: %s', mountpoint, err.decode("UTF-8"))


if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
