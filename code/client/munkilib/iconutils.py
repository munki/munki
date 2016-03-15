#!/usr/bin/python
# encoding: utf-8
#
# Copyright 2010-2016 Greg Neagle.
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
iconutils

Created by Greg Neagle on 2014-05-15.

Functions to work with product images ('icons') for Managed Software Center
"""

import glob
import os
import shutil
import subprocess
import tempfile

import munkicommon
import FoundationPlist

# PyLint cannot properly find names inside Cocoa libraries, so issues bogus
# No name 'Foo' in module 'Bar' warnings. Disable them.
# pylint: disable=E0611
from Foundation import NSData
from AppKit import NSBitmapImageRep, NSPNGFileType
# pylint: enable=E0611

# we use lots of camelCase-style names. Deal with it.
# pylint: disable=C0103


def convertIconToPNG(icon_path, destination_path, desired_pixel_height=350):
    '''Converts an icns file to a png file, choosing the representation
    closest to (but >= if possible) the desired_pixel_height.
    Returns True if successful, False otherwise'''
    if os.path.exists(icon_path):
        image_data = NSData.dataWithContentsOfFile_(icon_path)
        bitmap_reps = NSBitmapImageRep.imageRepsWithData_(image_data)
        chosen_rep = None
        for bitmap_rep in bitmap_reps:
            if not chosen_rep:
                chosen_rep = bitmap_rep
            elif (bitmap_rep.pixelsHigh() >= desired_pixel_height
                  and bitmap_rep.pixelsHigh() < chosen_rep.pixelsHigh()):
                chosen_rep = bitmap_rep
        if chosen_rep:
            png_data = chosen_rep.representationUsingType_properties_(
                NSPNGFileType, None)
            png_data.writeToFile_atomically_(destination_path, False)
            return True
    return False


def findIconForApp(app_path):
    '''Finds the icon file for app_path. Returns a path or None.'''
    if not os.path.exists(app_path):
        return None
    try:
        info = FoundationPlist.readPlist(
            os.path.join(app_path, u'Contents/Info.plist'))
    except FoundationPlist.FoundationPlistException:
        return None
    app_name = os.path.basename(app_path)
    icon_filename = info.get('CFBundleIconFile', app_name)
    icon_path = os.path.join(app_path, u'Contents/Resources', icon_filename)
    if not os.path.splitext(icon_path)[1]:
        # no file extension, so add '.icns'
        icon_path += '.icns'
    if os.path.exists(icon_path):
        return icon_path
    return None


def extractAppBitsFromPkgArchive(archive_path, target_dir):
    '''Extracts application Info.plist and .icns files into target_dir
       from a package archive file. Returns the result code of the
       pax extract operation.'''
    result = -999
    if os.path.exists(archive_path):
        original_dir = os.getcwd()
        os.chdir(target_dir)
        cmd = ['/bin/pax', '-rzf', archive_path,
               '*.app/Contents/Info.plist',
               '*.app/Contents/Resources/*.icns']
        result = subprocess.call(cmd)
        os.chdir(original_dir)
    return result


def extractAppIconsFromFlatPkg(pkg_path):
    '''Extracts application icons from a flat package.
       Returns a list of paths to icns files.'''
    cmd = ['/usr/sbin/pkgutil', '--bom', pkg_path]
    proc = subprocess.Popen(cmd, shell=False, bufsize=-1,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)
    output = proc.communicate()[0]
    if proc.returncode:
        munkicommon.display_error(u'Could not get bom files from %s', pkg_path)
        return []
    bomfilepaths = output.splitlines()
    pkg_dict = {}
    for bomfile in bomfilepaths:
        # bomfile path is of the form:
        # /tmp/FlashPlayer.pkg.boms.2Rxa1z/AdobeFlashPlayerComponent.pkg/Bom
        pkgname = os.path.basename(os.path.dirname(bomfile))
        if not pkgname.endswith(u'.pkg'):
            # no subpackages; this is a component pkg
            pkgname = ''
        cmd = ['/usr/bin/lsbom', '-s', bomfile]
        proc = subprocess.Popen(cmd, shell=False, bufsize=-1,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT)
        output = proc.communicate()[0]
        if proc.returncode:
            munkicommon.display_error(u'Could not lsbom %s', bomfile)
        # record paths to all app Info.plist files
        pkg_dict[pkgname] = [
            os.path.normpath(line)
            for line in output.decode('utf-8').splitlines()
            if line.endswith(u'.app/Contents/Info.plist')]
        if not pkg_dict[pkgname]:
            # remove empty lists
            del pkg_dict[pkgname]
    if not pkg_dict:
        return []
    icon_paths = []
    pkgtmp = os.path.join(tempfile.mkdtemp(dir=u'/tmp'), u'pkg')
    exporttmp = tempfile.mkdtemp(dir='/tmp')
    cmd = ['/usr/sbin/pkgutil', '--expand', pkg_path, pkgtmp]
    result = subprocess.call(cmd)
    if result == 0:
        for pkg in pkg_dict:
            archive_path = os.path.join(pkgtmp, pkg, u'Payload')
            err = extractAppBitsFromPkgArchive(archive_path, exporttmp)
            if err == 0:
                for info_path in pkg_dict[pkg]:
                    full_path = os.path.join(exporttmp, info_path)
                    # convert path to Info.plist to path to app
                    app_path = os.path.dirname(os.path.dirname(full_path))
                    icon_path = findIconForApp(app_path)
                    if icon_path:
                        icon_paths.append(icon_path)
            else:
                munkicommon.display_error(
                    u'pax could not read files from %s', archive_path)
                return []
    else:
        munkicommon.display_error(u'Could not expand %s', pkg_path)
    # clean up our expanded flat package; we no longer need it
    shutil.rmtree(pkgtmp)
    return icon_paths


def findInfoPlistPathsInBundlePkg(pkg_path):
    '''Returns a dict with pkg paths as keys and filename lists
    as values'''
    pkg_dict = {}
    bomfile = os.path.join(pkg_path, u'Contents/Archive.bom')
    if os.path.exists(bomfile):
        info_paths = getAppInfoPathsFromBundleComponentPkg(pkg_path)
        if info_paths:
            pkg_dict[pkg_path] = info_paths
    else:
        # mpkg or dist pkg; look for component pkgs within
        pkg_dict = {}
        original_dir = os.getcwd()
        pkg_contents_dir = os.path.join(pkg_path, u'Contents')
        if os.path.isdir(pkg_contents_dir):
            os.chdir(pkg_contents_dir)
            pkgs = (glob.glob('*.pkg') + glob.glob('*/*.pkg')
                    + glob.glob('*/*/*.pkg') + glob.glob('*.mpkg') +
                    glob.glob('*/*.mpkg') + glob.glob('*/*/*.mpkg'))
            os.chdir(original_dir)
        else:
            pkgs = []
        for pkg in pkgs:
            full_path = os.path.join(pkg_contents_dir, pkg)
            pkg_dict.update(findInfoPlistPathsInBundlePkg(full_path))
    return pkg_dict


def extractAppIconsFromBundlePkg(pkg_path):
    '''Returns a list of paths for application icons found
    inside the bundle pkg at pkg_path'''
    pkg_dict = findInfoPlistPathsInBundlePkg(pkg_path)
    icon_paths = []
    exporttmp = tempfile.mkdtemp(dir='/tmp')
    for pkg in pkg_dict:
        archive_path = os.path.join(pkg, u'Contents/Archive.pax.gz')
        err = extractAppBitsFromPkgArchive(archive_path, exporttmp)
        if err == 0:
            for info_path in pkg_dict[pkg]:
                full_path = os.path.normpath(os.path.join(exporttmp, info_path))
                app_path = os.path.dirname(os.path.dirname(full_path))
                icon_path = findIconForApp(app_path)
                if icon_path:
                    icon_paths.append(icon_path)
    return icon_paths


def getAppInfoPathsFromBundleComponentPkg(pkg_path):
    '''Returns a list of paths to application Info.plists'''
    bomfile = os.path.join(pkg_path, u'Contents/Archive.bom')
    if os.path.exists(bomfile):
        cmd = ['/usr/bin/lsbom', '-s', bomfile]
        proc = subprocess.Popen(cmd, shell=False, bufsize=-1,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT)
        output = proc.communicate()[0]
        return [line for line in output.splitlines()
                if line.endswith('.app/Contents/Info.plist')]
    return []
