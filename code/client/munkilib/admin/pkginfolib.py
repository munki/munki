# encoding: utf-8
#
# Copyright 2017-2023 Greg Neagle.
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
pkginfolib

Created by Greg Neagle on 2017-11-18.
Routines used by makepkginfo to create pkginfo files
"""
# This code is largely still compatible with Python 2, so for now, turn off
# Python 3 style warnings
# pylint: disable=consider-using-f-string
# pylint: disable=redundant-u-string-prefix

from __future__ import absolute_import, division, print_function

# standard libs
import optparse
import os
import re
import sys
import time

# Apple frameworks via PyObjC
# PyLint cannot properly find names inside Cocoa libraries, so issues bogus
# No name 'Foo' in module 'Bar' warnings. Disable them.
# pylint: disable=E0611,E0401
from Foundation import NSDate, NSUserName
# pylint: enable=E0611,E0401

# our libs
from .common import AttributeDict

from .. import dmgutils
from .. import info
from .. import munkihash
from .. import osinstaller
from .. import osutils
from .. import pkgutils
from .. import profiles
from .. import FoundationPlist

from ..adobeutils import adobeinfo


# circumvent cfprefsd plist scanning
os.environ['__CFPREFERENCES_AVOID_DAEMON'] = "1"


class PkgInfoGenerationError(Exception):
    '''Error to raise if there is a fatal error when generating pkginfo'''
    #pass


def make_pkginfo_metadata():
    '''Records information about the environment in which the pkginfo was
created so we have a bit of an audit trail. Returns a dictionary.'''
    metadata = {}
    metadata['created_by'] = NSUserName()
    metadata['creation_date'] = NSDate.new()
    metadata['munki_version'] = info.get_version()
    metadata['os_version'] = osutils.getOsVersion(only_major_minor=False)
    return metadata


def convert_date_string_to_nsdate(datetime_string):
    '''Converts a string in the "2013-04-25T20:00:00Z" format or
    "2013-04-25 20:00:00 +0000" format to an NSDate'''
    nsdate_format = '%Y-%m-%dT%H:%M:%SZ'
    iso_format = '%Y-%m-%d %H:%M:%S +0000'
    fallback_format = '%Y-%m-%d %H:%M:%S'
    try:
        tobj = time.strptime(datetime_string, nsdate_format)
    except ValueError:
        try:
            tobj = time.strptime(datetime_string, iso_format)
        except ValueError:
            try:
                tobj = time.strptime(datetime_string, fallback_format)
            except ValueError:
                return None
    iso_date_string = time.strftime(iso_format, tobj)
    return NSDate.dateWithString_(iso_date_string)


def get_catalog_info_from_path(pkgpath, options):
    """Gets package metadata for the package at pathname.
    Returns cataloginfo"""
    cataloginfo = {}
    if os.path.exists(pkgpath):
        cataloginfo = pkgutils.getPackageMetaData(pkgpath)
        if options.installer_choices_xml:
            installer_choices_xml = pkgutils.getChoiceChangesXML(pkgpath)
            if installer_choices_xml:
                cataloginfo['installer_choices_xml'] = installer_choices_xml

    if cataloginfo:
        # we found a package, but let's see if it's an Adobe CS5 install
        # (AAMEE) or Adobe Creative Cloud Packager package
        if 'receipts' in cataloginfo:
            try:
                pkgid = cataloginfo['receipts'][0].get('packageid')
            except IndexError:
                pkgid = ""
            if pkgid.startswith("com.adobe.Enterprise.install"):
                # we have an Adobe CS5 install package, process
                # as Adobe install
                abobe_metadata = adobeinfo.getAdobeCatalogInfo(pkgpath)
                if options.adobe:
                    # use legacy Adobe install methods
                    cataloginfo = abobe_metadata
                else:
                    # copy some metadata not available directly from the pkg
                    for key in ('display_name', 'version'):
                        if key in abobe_metadata:
                            cataloginfo[key] = abobe_metadata[key]

    if not cataloginfo:
        # maybe an Adobe installer/updater/patcher?
        cataloginfo = adobeinfo.getAdobeCatalogInfo(pkgpath,
                                                    options.pkgname or '')
    return cataloginfo


class ProfileMetadataGenerationError(PkgInfoGenerationError):
    '''Error to raise when we can't generate config profile metadata'''
    #pass


def get_catalog_info_for_profile(profile_path):
    '''Populates some metadata for profile pkginfo'''
    cataloginfo = {}
    profile = profiles.read_profile(profile_path)
    if profile.get('PayloadType') == 'Configuration':
        try:
            cataloginfo['PayloadIdentifier'] = profile['PayloadIdentifier']
        except (KeyError, AttributeError):
            # this thing is broken! return the empty info
            return cataloginfo
        cataloginfo['name'] = os.path.basename(profile_path)
        cataloginfo['display_name'] = profile.get(
            'PayloadDisplayName', cataloginfo['name'])
        cataloginfo['description'] = profile.get('PayloadDescription', '')
        cataloginfo['version'] = '1.0'
        cataloginfo['installer_type'] = 'profile'
        cataloginfo['uninstallable'] = True
        cataloginfo['uninstall_method'] = 'remove_profile'
        cataloginfo['unattended_install'] = True
        cataloginfo['unattended_uninstall'] = True
        cataloginfo['minimum_os_version'] = '10.7'
        cataloginfo['minimum_munki_version'] = '2.2'
    else:
        raise ProfileMetadataGenerationError(
            'Profile PayloadType is %s' % profile.get('PayloadType'))
    return cataloginfo


def get_catalog_info_from_dmg(dmgpath, options):
    """
    * Mounts a disk image if it's not already mounted
    * Gets catalog info for the first installer item found at the root level.
    * Unmounts the disk image if it wasn't already mounted

    To-do: handle multiple installer items on a disk image(?)
    """
    cataloginfo = None
    was_already_mounted = dmgutils.diskImageIsMounted(dmgpath)
    mountpoints = dmgutils.mountdmg(dmgpath, use_existing_mounts=True)
    if not mountpoints:
        raise PkgInfoGenerationError("Could not mount %s!" % dmgpath)

    if options.pkgname:
        pkgpath = os.path.join(mountpoints[0], options.pkgname)
        cataloginfo = get_catalog_info_from_path(pkgpath, options)
        if cataloginfo:
            cataloginfo['package_path'] = options.pkgname
    elif not options.item:
        # search for first package at root
        for fsitem in osutils.listdir(mountpoints[0]):
            itempath = os.path.join(mountpoints[0], fsitem)
            if pkgutils.hasValidInstallerItemExt(itempath):
                cataloginfo = get_catalog_info_from_path(itempath, options)
                # get out of fsitem loop
                break

    if not cataloginfo and not options.item:
        # look for one of the many possible Adobe installer/updaters
        cataloginfo = adobeinfo.getAdobeCatalogInfo(
            mountpoints[0], options.pkgname or '')

    if not cataloginfo:
        # could be a wrapped Install macOS.app
        install_macos_app = osinstaller.find_install_macos_app(mountpoints[0])
        if (install_macos_app and options.print_warnings and
                osinstaller.install_macos_app_is_stub(install_macos_app)):
            print('WARNING: %s appears to be an Install macOS application, but '
                  'it does not contain Contents/SharedSupport/InstallESD.dmg '
                  'or Contents/SharedSupport/SharedSupport.dmg'
                  % os.path.basename(install_macos_app), file=sys.stderr)
        if options.installer_type_requested in ["stage_os_installer", "copy_from_dmg"]:
            # admin wants a stage_os_installer item
            # or maybe just copy the app to /Applications
            # fall through so we can process as a drag-n-drop app
            options.item = os.path.relpath(install_macos_app, mountpoints[0])
        else:
            # assume startosinstall item
            cataloginfo = osinstaller.get_startosinstall_catalog_info(mountpoints[0])

    if not cataloginfo:
        # maybe this is a drag-n-drop dmg
        # look for given item or an app at the top level of the dmg
        iteminfo = {}
        if options.item:
            item = options.item

            # Create a path by joining the mount point and the provided item
            # path.
            # The os.path.join method will intelligently take care of the
            # following scenarios:
            # ("/mountpoint", "relative/path")  -> "/mountpoint/relative/path"
            # ("/mountpoint", "/absolute/path") -> "/absolute/path"
            itempath = os.path.join(mountpoints[0], item)

            # Now check that the item actually exists and is located within the
            # mount point
            if os.path.exists(itempath) and itempath.startswith(mountpoints[0]):
                iteminfo = getiteminfo(itempath)
            else:
                if not was_already_mounted:
                    dmgutils.unmountdmg(mountpoints[0])
                raise PkgInfoGenerationError(
                    "%s not found on disk image." % item)
        else:
            # no item specified; look for an application at root of
            # mounted dmg
            item = ''
            for itemname in osutils.listdir(mountpoints[0]):
                itempath = os.path.join(mountpoints[0], itemname)
                if pkgutils.isApplication(itempath):
                    item = itemname
                    iteminfo = getiteminfo(itempath)
                    if iteminfo:
                        break

        if iteminfo:
            item_to_copy = {}
            if os.path.isabs(item):
                # Absolute path given
                # Remove the mountpoint from item path
                mountpoint_pattern = "^%s/" % mountpoints[0]
                item = re.sub(mountpoint_pattern, '', item)

            if options.destitemname:
                # An alternate 'destination_item' name has been specified
                dest_item = options.destitemname
                item_to_copy['destination_item'] = options.destitemname
            else:
                dest_item = item

            # Use only the last path component when
            # composing the path key of an installs item
            dest_item_filename = os.path.split(dest_item)[1]

            if options.destinationpath:
                iteminfo['path'] = os.path.join(
                    options.destinationpath, dest_item_filename)
            else:
                iteminfo['path'] = os.path.join(
                    "/Applications", dest_item_filename)
            cataloginfo = {}
            cataloginfo['name'] = iteminfo.get(
                'CFBundleName', os.path.splitext(item)[0])
            version_comparison_key = iteminfo.get(
                'version_comparison_key', "CFBundleShortVersionString")
            cataloginfo['version'] = \
                iteminfo.get(version_comparison_key, "0")
            cataloginfo['installs'] = [iteminfo]
            cataloginfo['installer_type'] = "copy_from_dmg"
            item_to_copy['source_item'] = item
            item_to_copy['destination_path'] = (
                options.destinationpath or "/Applications")
            if options.user:
                item_to_copy['user'] = options.user
            if options.group:
                item_to_copy['group'] = options.group
            if options.mode:
                item_to_copy['mode'] = options.mode
            cataloginfo['items_to_copy'] = [item_to_copy]
            cataloginfo['uninstallable'] = True
            cataloginfo['uninstall_method'] = "remove_copied_items"

            if options.installer_type_requested == "stage_os_installer":
                # transform this copy_from_dmg item
                # into a staged_os_installer item
                morecataloginfo = osinstaller.get_stage_os_installer_catalog_info(itempath)
                cataloginfo.update(morecataloginfo)

    #eject the dmg
    if not was_already_mounted:
        dmgutils.unmountdmg(mountpoints[0])
    return cataloginfo


# TO-DO: this (or a similar) function is defined several places. De-dupe.
def readfile(path):
    '''Reads file at path. Returns a string.'''
    try:
        fileobject = open(os.path.expanduser(path), mode='r', encoding="utf-8")
        data = fileobject.read()
        fileobject.close()
        return data
    except (OSError, IOError):
        print("Couldn't read %s" % path, file=sys.stderr)
        return ""


def read_file_or_string(option_value):
    """
    If option_value is a path to a file,
    return contents of file.

    Otherwise, return the string.
    """
    if os.path.exists(os.path.expanduser(option_value)):
        string = readfile(option_value)
    else:
        string = option_value

    return string


def getiteminfo(itempath):
    """
    Gets info for filesystem items passed to makecatalog item, to be used for
    the "installs" key.
    Determines if the item is an application, bundle, Info.plist, or a file or
    directory and gets additional metadata for later comparison.
    """
    infodict = {}
    if pkgutils.isApplication(itempath):
        infodict['type'] = 'application'
        infodict['path'] = itempath
        plist = pkgutils.getBundleInfo(itempath)
        for key in ['CFBundleName', 'CFBundleIdentifier',
                    'CFBundleShortVersionString', 'CFBundleVersion']:
            if key in plist:
                infodict[key] = plist[key]
        if 'LSMinimumSystemVersion' in plist:
            infodict['minosversion'] = plist['LSMinimumSystemVersion']
        elif 'LSMinimumSystemVersionByArchitecture' in plist:
            # just grab the highest version if more than one is listed
            versions = [item[1] for item in
                        plist['LSMinimumSystemVersionByArchitecture'].items()]
            highest_version = str(max([pkgutils.MunkiLooseVersion(version)
                                       for version in versions]))
            infodict['minosversion'] = highest_version
        elif 'SystemVersionCheck:MinimumSystemVersion' in plist:
            infodict['minosversion'] = \
                plist['SystemVersionCheck:MinimumSystemVersion']

    elif (os.path.exists(os.path.join(itempath, 'Contents', 'Info.plist')) or
          os.path.exists(os.path.join(itempath, 'Resources', 'Info.plist'))):
        infodict['type'] = 'bundle'
        infodict['path'] = itempath
        plist = pkgutils.getBundleInfo(itempath)
        for key in ['CFBundleShortVersionString', 'CFBundleVersion']:
            if key in plist:
                infodict[key] = plist[key]

    elif itempath.endswith("Info.plist") or itempath.endswith("version.plist"):
        infodict['type'] = 'plist'
        infodict['path'] = itempath
        try:
            plist = FoundationPlist.readPlist(itempath)
            for key in ['CFBundleShortVersionString', 'CFBundleVersion']:
                if key in plist:
                    infodict[key] = plist[key]
        except FoundationPlist.NSPropertyListSerializationException:
            pass

    # let's help the admin -- if CFBundleShortVersionString is empty
    # or doesn't start with a digit, and CFBundleVersion is there
    # use CFBundleVersion as the version_comparison_key
    if (not infodict.get('CFBundleShortVersionString') or
            infodict['CFBundleShortVersionString'][0]
            not in '0123456789'):
        if infodict.get('CFBundleVersion'):
            infodict['version_comparison_key'] = 'CFBundleVersion'
    elif 'CFBundleShortVersionString' in infodict:
        infodict['version_comparison_key'] = 'CFBundleShortVersionString'

    if ('CFBundleShortVersionString' not in infodict and
            'CFBundleVersion' not in infodict):
        infodict['type'] = 'file'
        infodict['path'] = itempath
        if os.path.isfile(itempath):
            infodict['md5checksum'] = munkihash.getmd5hash(itempath)
    return infodict


def makepkginfo(installeritem, options):
    '''Return a pkginfo dictionary for item'''

    if isinstance(options, dict):
        options = AttributeDict(options)

    pkginfo = {}
    installs = []
    if installeritem:
        if not os.path.exists(installeritem):
            raise PkgInfoGenerationError(
                "File %s does not exist" % installeritem)

        # Check if the item is a mount point for a disk image
        if dmgutils.pathIsVolumeMountPoint(installeritem):
            # Get the disk image path for the mount point
            # and use that instead of the original item
            installeritem = dmgutils.diskImageForMountPoint(installeritem)

        # get size of installer item
        itemsize = 0
        itemhash = "N/A"
        if os.path.isfile(installeritem):
            itemsize = int(os.path.getsize(installeritem)/1024)
            try:
                itemhash = munkihash.getsha256hash(installeritem)
            except OSError as err:
                raise PkgInfoGenerationError(err) from err

        if pkgutils.hasValidDiskImageExt(installeritem):
            if dmgutils.DMGisWritable(installeritem) and options.print_warnings:
                print("WARNING: %s is a writable disk image. "
                      "Checksum verification is not supported." % installeritem,
                      file=sys.stderr)
                print("WARNING: Consider converting %s to a read-only disk"
                      "image." % installeritem, file=sys.stderr)
                itemhash = "N/A"
            pkginfo = get_catalog_info_from_dmg(installeritem, options)
            if (pkginfo and
                    pkginfo.get('installer_type') == "AdobeCS5Installer"):
                raise PkgInfoGenerationError(
                    "This disk image appears to contain an Adobe CS5/CS6 "
                    "product install.\n"
                    "Please use Adobe Application Manager, Enterprise "
                    "Edition (AAMEE) to create an installation package "
                    "for this product.")
            if not pkginfo:
                raise PkgInfoGenerationError(
                    "Could not find a supported installer item in %s!"
                    % installeritem)

        elif pkgutils.hasValidPackageExt(installeritem):
            # we should generate pkginfo for an Apple installer
            if options.installer_type_requested and options.print_warnings:
                print("WARNING: installer_type requested is %s. Provided "
                      "installer item appears to be an Apple pkg.")
            pkginfo = get_catalog_info_from_path(installeritem, options)
            if not pkginfo:
                raise PkgInfoGenerationError(
                    "%s doesn't appear to be a valid installer item!"
                    % installeritem)
            if os.path.isdir(installeritem) and options.print_warnings:
                print("WARNING: %s is a bundle-style package!\n"
                      "To use it with Munki, you should encapsulate it "
                      "in a disk image.\n" % installeritem, file=sys.stderr)
                # need to walk the dir and add it all up
                for (path, dummy_dirs, files) in os.walk(installeritem):
                    for name in files:
                        filename = os.path.join(path, name)
                        # use os.lstat so we don't follow symlinks
                        itemsize += int(os.lstat(filename).st_size)
                # convert to kbytes
                itemsize = int(itemsize/1024)

        elif pkgutils.hasValidConfigProfileExt(installeritem):
            if (options.installer_type_requested and
                    options.installer_type_requested != 'profile' and
                    options.print_warnings):
                print("WARNING: installer_type requested is %s. Provided "
                      "installer item appears to be a configuration profile.")
            try:
                pkginfo = get_catalog_info_for_profile(installeritem)
            except ProfileMetadataGenerationError as err:
                print(err, file=sys.stderr)
                raise PkgInfoGenerationError(
                    "%s doesn't appear to be a supported configuration "
                    "profile!" % installeritem) from err
        else:
            raise PkgInfoGenerationError(
                "%s is not a valid installer item!" % installeritem)

        pkginfo['installer_item_size'] = itemsize
        if itemhash != "N/A":
            pkginfo['installer_item_hash'] = itemhash

        # try to generate the correct item location
        temppath = installeritem
        location = ""
        while len(temppath) > 4:
            if temppath.endswith('/pkgs'):
                location = installeritem[len(temppath)+1:]
                break
            #else:
            temppath = os.path.dirname(temppath)

        if not location:
            #just the filename
            location = os.path.split(installeritem)[1]
        pkginfo['installer_item_location'] = location

        # ADOBE STUFF - though maybe generalizable in the future?
        if (pkginfo.get('installer_type') == "AdobeCCPInstaller" and
                not options.uninstalleritem) and options.print_warnings:
            print("WARNING: This item appears to be an Adobe Creative "
                  "Cloud product install.\n"
                  "No uninstaller package was specified so product "
                  "removal will not be possible.", file=sys.stderr)
            pkginfo['uninstallable'] = False
            if 'uninstall_method' in pkginfo:
                del pkginfo['uninstall_method']

        if options.uninstalleritem:
            if not pkginfo.get('installer_type', '').startswith('Adobe'):
                # new in Munki 6.2
                pkginfo['uninstallable'] = True
                pkginfo['uninstall_method'] = "uninstall_package"
                minimum_munki_version = pkginfo.get("minimum_munki_version", "0")
                if (pkgutils.MunkiLooseVersion(minimum_munki_version) <
                        pkgutils.MunkiLooseVersion("6.2")):
                    pkginfo["minimum_munki_version"] = "6.2"
            uninstallerpath = options.uninstalleritem
            if os.path.exists(uninstallerpath):
                # try to generate the correct item location
                temppath = uninstallerpath
                location = ""
                while len(temppath) > 4:
                    if temppath.endswith('/pkgs'):
                        location = uninstallerpath[len(temppath)+1:]
                        break
                    #else:
                    temppath = os.path.dirname(temppath)

                if not location:
                    #just the filename
                    location = os.path.split(uninstallerpath)[1]
                pkginfo['uninstaller_item_location'] = location
                itemsize = int(os.path.getsize(uninstallerpath))
                itemhash = munkihash.getsha256hash(uninstallerpath)
                pkginfo['uninstaller_item_size'] = int(itemsize/1024)
                pkginfo['uninstaller_item_hash'] = itemhash
            else:
                raise PkgInfoGenerationError(
                    "No uninstaller item at %s" % uninstallerpath)

        # No uninstall method yet?
        # if we have receipts, assume we can uninstall using them
        if not pkginfo.get('uninstall_method'):
            if pkginfo.get('receipts'):
                pkginfo['uninstallable'] = True
                pkginfo['uninstall_method'] = "removepackages"
    else:
        if options.nopkg:
            pkginfo['installer_type'] = "nopkg"

    if options.catalog:
        pkginfo['catalogs'] = options.catalog
    else:
        pkginfo['catalogs'] = ['testing']
    if options.description:
        pkginfo['description'] = read_file_or_string(options.description)
    if options.displayname:
        pkginfo['display_name'] = options.displayname
    if options.name:
        pkginfo['name'] = options.name
    if options.pkgvers:
        pkginfo['version'] = options.pkgvers
    if options.category:
        pkginfo['category'] = options.category
    if options.developer:
        pkginfo['developer'] = options.developer
    if options.icon:
        pkginfo['icon_name'] = options.icon

    default_minosversion = "10.4.0"
    maxfileversion = "0.0.0.0.0"
    if pkginfo:
        pkginfo['autoremove'] = False
        if not 'version' in pkginfo:
            if maxfileversion != "0.0.0.0.0":
                pkginfo['version'] = maxfileversion
            else:
                pkginfo['version'] = "1.0.0.0.0 (Please edit me!)"

    if options.file:
        for fitem in options.file:
            # no trailing slashes, please.
            fitem = fitem.rstrip('/')
            if fitem.startswith('/Library/Receipts'):
                # no receipts, please!
                if options.print_warnings:
                    print("Item %s appears to be a receipt. Skipping." % fitem,
                          file=sys.stderr)
                continue
            if os.path.exists(fitem):
                iteminfodict = getiteminfo(fitem)
                if 'CFBundleShortVersionString' in iteminfodict:
                    thisitemversion = \
                        iteminfodict['CFBundleShortVersionString']
                    if (pkgutils.MunkiLooseVersion(thisitemversion) >
                            pkgutils.MunkiLooseVersion(maxfileversion)):
                        maxfileversion = thisitemversion
                installs.append(iteminfodict)
            elif options.print_warnings:
                print("Item %s doesn't exist. Skipping." % fitem,
                      file=sys.stderr)

    if installs:
        pkginfo['installs'] = installs

    # determine minimum_os_version from identified apps in the installs array
    if pkginfo.get('installer_type') != 'stage_os_installer' and 'installs' in pkginfo:
        # build a list of minosversions using a list comprehension
        item_minosversions = [
            pkgutils.MunkiLooseVersion(item['minosversion'])
            for item in pkginfo['installs']
            if 'minosversion' in item]
        # add the default in case it's an empty list
        item_minosversions.append(
            pkgutils.MunkiLooseVersion(default_minosversion))
        if 'minimum_os_version' in pkginfo:
            # handle case where value may have been set (e.g. flat package)
            item_minosversions.append(pkgutils.MunkiLooseVersion(
                pkginfo['minimum_os_version']))
        # get the maximum from the list and covert back to string
        pkginfo['minimum_os_version'] = str(max(item_minosversions))

    if not 'minimum_os_version' in pkginfo:
        # ensure a minimum_os_version is set unless using --file option only
        pkginfo['minimum_os_version'] = default_minosversion

    if options.file and not installeritem:
        # remove minimum_os_version as we don't include it for --file only
        pkginfo.pop('minimum_os_version')

    if options.installcheck_script:
        scriptstring = readfile(options.installcheck_script)
        if scriptstring:
            pkginfo['installcheck_script'] = scriptstring
    if options.uninstallcheck_script:
        scriptstring = readfile(options.uninstallcheck_script)
        if scriptstring:
            pkginfo['uninstallcheck_script'] = scriptstring
    if options.postinstall_script:
        scriptstring = readfile(options.postinstall_script)
        if scriptstring:
            pkginfo['postinstall_script'] = scriptstring
    if options.preinstall_script:
        scriptstring = readfile(options.preinstall_script)
        if scriptstring:
            pkginfo['preinstall_script'] = scriptstring
    if options.postuninstall_script:
        scriptstring = readfile(options.postuninstall_script)
        if scriptstring:
            pkginfo['postuninstall_script'] = scriptstring
    if options.preuninstall_script:
        scriptstring = readfile(options.preuninstall_script)
        if scriptstring:
            pkginfo['preuninstall_script'] = scriptstring
    if options.uninstall_script:
        scriptstring = readfile(options.uninstall_script)
        if scriptstring:
            pkginfo['uninstall_script'] = scriptstring
            pkginfo['uninstall_method'] = 'uninstall_script'
    if options.autoremove:
        pkginfo['autoremove'] = True
    if options.minimum_munki_version:
        pkginfo['minimum_munki_version'] = options.minimum_munki_version
    if options.OnDemand:
        pkginfo['OnDemand'] = True
    if options.unattended_install:
        pkginfo['unattended_install'] = True
    if options.unattended_uninstall:
        pkginfo['unattended_uninstall'] = True
    if options.minimum_os_version:
        pkginfo['minimum_os_version'] = options.minimum_os_version
    if options.maximum_os_version:
        pkginfo['maximum_os_version'] = options.maximum_os_version
    if options.arch:
        pkginfo['supported_architectures'] = options.arch
    if options.force_install_after_date:
        date_obj = convert_date_string_to_nsdate(
            options.force_install_after_date)
        if date_obj:
            pkginfo['force_install_after_date'] = date_obj
        else:
            raise PkgInfoGenerationError(
                "Invalid date format %s for force_install_after_date"
                % options.force_install_after_date)
    if options.RestartAction:
        valid_actions = ['RequireRestart', 'RequireLogout', 'RecommendRestart']
        if options.RestartAction in valid_actions:
            pkginfo['RestartAction'] = options.RestartAction
        elif 'restart' in options.RestartAction.lower():
            pkginfo['RestartAction'] = 'RequireRestart'
        elif 'logout' in options.RestartAction.lower():
            pkginfo['RestartAction'] = 'RequireLogout'
    if options.update_for:
        pkginfo['update_for'] = options.update_for
    if options.requires:
        pkginfo['requires'] = options.requires
    if options.blocking_application:
        pkginfo['blocking_applications'] = options.blocking_application
    if options.uninstall_method:
        pkginfo['uninstall_method'] = options.uninstall_method
    if options.installer_environment:
        try:
            installer_environment_dict = dict(
                (k, v) for k, v in (
                    kv.split('=') for kv in options.installer_environment))
        except Exception:
            installer_environment_dict = {}
        if installer_environment_dict:
            pkginfo['installer_environment'] = installer_environment_dict
    if options.notes:
        pkginfo['notes'] = read_file_or_string(options.notes)
    if options.apple_update:
        # remove minimum_os_version as we don't include it for this option
        pkginfo.pop('minimum_os_version')
        if options.catalog:
            pkginfo['catalogs'] = options.catalog
        else:
            pkginfo['catalogs'] = ['testing']
        if options.pkgvers:
            pkginfo['version'] = options.pkgvers
        else:
            pkginfo['version'] = "1.0"
        pkginfo['name'] = options.apple_update
        if options.displayname:
            pkginfo['display_name'] = options.displayname
        pkginfo['installer_type'] = 'apple_update_metadata'

    # add user/environment metadata
    pkginfo['_metadata'] = make_pkginfo_metadata()

    # return the info
    return pkginfo


def check_mode(option, opt, value, parser):
    '''Callback to check --mode options'''
    modes = value.replace(',', ' ').split()
    value = None
    rex = re.compile("[augo]+[=+-][rstwxXugo]+")
    for mode in modes:
        if rex.match(mode):
            value = mode if not value else (value + "," + mode)
        else:
            raise optparse.OptionValueError(
                "option %s: invalid mode: %s" % (opt, mode))
    setattr(parser.values, option.dest, value)


def add_option_groups(parser):
    '''Adds our (many) option groups to the options parser'''

    # Default override options
    default_override_options = optparse.OptionGroup(
        parser, 'Default Override Options',
        ('Options specified will override information automatically derived '
         'from the package.'))
    default_override_options.add_option(
        '--name',
        metavar='NAME',
        help='Name of the package.'
        )
    default_override_options.add_option(
        '--displayname',
        metavar='DISPLAY_NAME',
        help='Display name of the package.'
        )
    default_override_options.add_option(
        '--description',
        metavar='STRING|PATH',
        help=('Description of the package. '
              'Can be a PATH to a file (plain text or html).')
        )
    default_override_options.add_option(
        '--pkgvers',
        metavar='PACKAGE_VERSION',
        help='Version of the package.'
        )
    default_override_options.add_option(
        '--RestartAction',
        metavar='ACTION',
        help=('Specify a \'RestartAction\' for the package. '
              'Supported actions: RequireRestart, RequireLogout, or '
              'RecommendRestart')
        )
    default_override_options.add_option(
        '--uninstall_method', '--uninstall-method',
        metavar='METHOD|PATH',
        help=('Specify an \'uninstall_method\' for the package. '
              'Default method depends on the package type: i.e. '
              'drag-n-drop, Apple package, or an embedded uninstall script. '
              'Can be a path to a script on the client computer.')
        )
    parser.add_option_group(default_override_options)

    # Script options
    script_options = optparse.OptionGroup(
        parser, 'Script Options',
        'All scripts are read and embedded into the pkginfo.')
    script_options.add_option(
        '--installcheck_script', '--installcheck-script',
        metavar='SCRIPT_PATH',
        help=('Path to an optional installcheck script to be '
              'run to determine if item should be installed. '
              'An exit code of 0 indicates installation should occur. '
              'Takes precedence over installs items and receipts.')
        )
    script_options.add_option(
        '--uninstallcheck_script', '--uninstallcheck-script',
        metavar='SCRIPT_PATH',
        help=('Path to an optional uninstallcheck script to be '
              'run to determine if item should be uninstalled. '
              'An exit code of 0 indicates uninstallation should occur. '
              'Takes precedence over installs items and receipts.')
        )
    script_options.add_option(
        '--preinstall_script', '--preinstall-script',
        metavar='SCRIPT_PATH',
        help=('Path to an optional preinstall script to be '
              'run before installation of the item.')
        )
    script_options.add_option(
        '--postinstall_script', '--postinstall-script',
        metavar='SCRIPT_PATH',
        help=('Path to an optional postinstall script to be '
              'run after installation of the item.')
        )
    script_options.add_option(
        '--preuninstall_script', '--preuninstall-script',
        metavar='SCRIPT_PATH',
        help=('Path to an optional preuninstall script to be run '
              'before removal of the item.')
        )
    script_options.add_option(
        '--postuninstall_script', '--postuninstall-script',
        metavar='SCRIPT_PATH',
        help=('Path to an optional postuninstall script to be run '
              'after removal of the item.')
        )
    script_options.add_option(
        '--uninstall_script', '--uninstall-script',
        metavar='SCRIPT_PATH',
        help=('Path to an uninstall script to be run in order '
              'to uninstall this item.')
        )
    parser.add_option_group(script_options)

    # Drag-n-Drop options
    dragdrop_options = optparse.OptionGroup(
        parser, 'Drag-n-Drop Options',
        ('These options apply to installer items that are "drag-n-drop" '
         'disk images.')
        )
    dragdrop_options.add_option(
        '--itemname', '-i', '--appname', '-a',
        metavar='ITEM',
        dest='item',
        help=('Name or relative path of the item to be installed. '
              'Useful if there is more than one item at the root of the dmg '
              'or the item is located in a subdirectory. '
              'Absolute paths can be provided as well but they '
              'must point to an item located within the dmg.')
        )
    dragdrop_options.add_option(
        '--destinationpath', '-d',
        metavar='PATH',
        help=('Path to which the item should be copied. Defaults to '
              '"/Applications".')
        )
    dragdrop_options.add_option(
        '--destinationitemname', '--destinationitem',
        metavar='NAME',
        dest='destitemname',
        help=('Alternate name for which the item should be copied as. '
              'Specifying this option also alters the corresponding '
              '"installs" item\'s path with the provided name.')
        )
    dragdrop_options.add_option(
        '-o', '--owner',
        metavar='USER',
        dest='user',
        help=('Sets the owner of the copied item. '
              'The owner may be either a UID or a symbolic name. '
              'The owner will be set recursively on the item.')
        )
    dragdrop_options.add_option(
        '-g', '--group',
        metavar='GROUP',
        dest='group',
        help=('Sets the group of the copied item. '
              'The group may be either a GID or a symbolic name. '
              'The group will be set recursively on the item.')
        )
    dragdrop_options.add_option(
        '-m', '--mode',
        metavar='MODE',
        dest='mode',
        action='callback',
        type='string',
        callback=check_mode,
        help=('Sets the mode of the copied item. '
              'The specified mode must be in symbolic form. '
              'See the manpage for chmod(1) for more information. '
              'The mode is applied recursively.')
        )
    parser.add_option_group(dragdrop_options)

    # Apple package specific options
    apple_options = optparse.OptionGroup(parser, 'Package Options')
    apple_options.add_option(
        '--pkgname', '-p',
        help=('If the installer item is a disk image containing multiple '
              'packages, or the package to be installed is not at the root '
              'of the mounted disk image, PKGNAME is a relative path from '
              'the root of the mounted disk image to the specific package to '
              'be installed.\n'
              'If the installer item is a disk image containing an Adobe '
              'CS4 Deployment Toolkit installation, PKGNAME is the name of '
              'an Adobe CS4 Deployment Toolkit installer package folder at '
              'the top level of the mounted dmg.\n'
              'If this flag is missing, the AdobeUber* files should be at '
              'the top level of the mounted dmg.')
        )
    apple_options.add_option(
        '--uninstallerdmg', '--uninstallerpkg', '--uninstallpkg', '-U',
        metavar='UNINSTALLERITEM', dest='uninstalleritem',
        help=('If the uninstaller item is an Apple package or a disk image '
              'containing an Apple package, UNINSTALLERITEM is a path to the '
              'uninstall package or disk image containing an uninstall package.\n'
              'Include the --adobe option if the uninstaller item is a '
              'Creative Cloud Packager uninstall package and you want to use '
              'the legacy Adobe CCP uninstall methods (not recommended).\n'
              'If the installer item is a disk image containing an Adobe CS4 '
              'Deployment Toolkit installation package or Adobe CS3 deployment '
              'package, UNINSTALLERITEM is a path to a disk image '
              'containing an AdobeUberUninstaller for this item.')
        )
    apple_options.add_option(
        '--installer_choices_xml', '--installer-choices-xml',
        action='store_true',
        help=('Generate installer choices for metapackages. '
              'Note: Requires Mac OS X 10.6.6 or later.')
        )
    apple_options.add_option(
        '--installer_environment', '--installer-environment', '-E',
        action="append",
        metavar='KEY=VALUE',
        help=('Specifies key/value pairs to set environment variables for use '
              'by /usr/sbin/installer. A key/value pair of '
              'USER=CURRENT_CONSOLE_USER indicates that USER be set to the '
              'GUI user, otherwise root. Can be specified multiple times.')
        )
    parser.add_option_group(apple_options)

    # Adobe package specific options
    adobe_options = optparse.OptionGroup(parser, 'Adobe-specific Options')
    adobe_options.add_option(
        '--adobe',
        action='store_true',
        help=('Tell makepkginfo/munkiimport to use legacy Adobe install '
              'and uninstall methods with a package item. Not recommended, '
              'but forces legacy Munki behavior with recent Adobe installers.')
        )
    parser.add_option_group(adobe_options)

    # Forced/Unattended (install) options
    forced_unattended_options = optparse.OptionGroup(
        parser, 'Forced/Unattended Options')
    forced_unattended_options.add_option(
        '--unattended_install', '--unattended-install',
        action='store_true',
        help='Item can be installed without notifying the user.')
    forced_unattended_options.add_option(
        '--unattended_uninstall', '--unattended-uninstall',
        action='store_true',
        help='Item can be uninstalled without notifying the user.')
    forced_unattended_options.add_option(
        '--force_install_after_date', '--force-install-after-date',
        metavar='DATE',
        help=('Specify a date, in local time, after which the package will '
              'be forcefully installed. DATE format: yyyy-mm-ddThh:mm:ssZ '
              'Example: \'2011-08-11T12:55:00Z\' equates to 11 August 2011 '
              'at 12:55 PM local time.')
        )
    parser.add_option_group(forced_unattended_options)

    # 'installs' generation options
    # (by itself since no installer_item needs to be specified)
    gen_installs_options = optparse.OptionGroup(
        parser, 'Generating \'installs\' items')
    gen_installs_options.add_option(
        '--file', '-f',
        action="append",
        metavar='PATH',
        help=('Path to a filesystem item installed by this package, typically '
              'an application. This generates an "installs" item for the '
              'pkginfo, to be used to determine if this software has been '
              'installed. Can be specified multiple times.')
        )
    parser.add_option_group(gen_installs_options)

    # Apple update metadata pkg options
    # (by itself since no installer_item needs to be specified)
    apple_update_metadata_options = optparse.OptionGroup(
        parser, 'Generating Apple update metadata items')
    apple_update_metadata_options.add_option(
        '--apple_update', '--apple-update',
        metavar='PRODUCTKEY',
        help=('Specify an Apple update \'productKey\' used to manipulate '
              'the behavior of a pending Apple software update. '
              'For example, a \'force_install_after_date\' key could be added '
              'as opposed to importing the update into the munki repo.')
        )
    parser.add_option_group(apple_update_metadata_options)

    # installer type options
    installer_type_options = optparse.OptionGroup(parser, 'Installer Types')
    installer_type_options.add_option(
        '--installer-type', '--installer_type',
        choices=['copy_from_dmg', 'stage_os_installer', 'startosinstall'],
        metavar='TYPE', dest='installer_type_requested',
        help=('Specify an intended installer_type when the installeritem could '
              'be one of multiple types. Currently supported only to specify '
              'the intended type for a macOS installer (startosinstall or '
              'stage_os_installer).')
    )
    installer_type_options.add_option(
        '--nopkg',
        action='store_true',
        help=('Indicates this pkginfo should have an \'installer_type\' of '
              '\'nopkg\'. Ignored if a package or dmg argument is supplied.')
    )
    parser.add_option_group(installer_type_options)

    # Additional options - misc. options that don't fit into other categories,
    # and don't necessarily warrant the creation of their own option group
    additional_options = optparse.OptionGroup(parser, 'Additional Options')
    additional_options.add_option(
        '--autoremove',
        action='store_true',
        help=('Indicates this package should be automatically removed if it is '
              'not listed in any applicable \'managed_installs\'.')
        )
    additional_options.add_option(
        '--OnDemand',
        action='store_true',
        help=('Indicates this package should be an OnDemand package '
              'not listed in any applicable \'managed_installs\'.')
        )
    additional_options.add_option(
        '--minimum_munki_version', '--minimum-munki-version',
        metavar='VERSION',
        help=('Minimum version of munki required to perform installation. '
              'Uses format produced by \'--version\' query from any munki '
              'utility.')
        )
    additional_options.add_option(
        '--minimum_os_version', '--minimum-os-version', '--min-os-ver',
        metavar='VERSION',
        help='Minimum OS version for the installer item.'
        )
    additional_options.add_option(
        '--maximum_os_version', '--maximum-os-version', '--max-os-ver',
        metavar='VERSION',
        help='Maximum OS version for the installer item.'
        )
    additional_options.add_option(
        '--arch', '--supported_architecture', '--supported-architecture',
        action="append",
        choices=['i386', 'x86_64', 'arm64'],
        metavar='ARCH',
        help=('Declares a supported architecture for the item. '
              'Can be specified multiple times to declare multiple '
              'supported architectures.')
        )
    additional_options.add_option(
        '--update_for', '--update-for', '-u',
        action="append",
        metavar='PKG_NAME',
        help=('Specifies a package for which the current package is an update. '
              'Can be specified multiple times to build an array of packages.')
        )
    additional_options.add_option(
        '--requires', '-r',
        action="append",
        metavar='PKG_NAME',
        help=('Specifies a package required by the current package. Can be '
              'specified multiple times to build an array of required '
              'packages.')
        )
    additional_options.add_option(
        '--blocking_application', '--blocking-application', '-b',
        action="append",
        metavar='APP_NAME',
        help=('Specifies an application that blocks installation. Can be '
              'specified multiple times to build an array of blocking '
              'applications.')
        )
    additional_options.add_option(
        '--catalog', '-c',
        action="append",
        metavar='CATALOG_NAME',
        help=('Specifies in which catalog the item should appear. The default '
              'is \'testing\'. Can be specified multiple times to add the item '
              'to multiple catalogs.')
        )
    additional_options.add_option(
        '--category',
        metavar='CATEGORY',
        help='Category for display in Managed Software Center.'
        )
    additional_options.add_option(
        '--developer',
        metavar='DEVELOPER',
        help='Developer name for display in Managed Software Center.'
        )
    additional_options.add_option(
        '--icon', '--iconname', '--icon-name', '--icon_name',
        metavar='ICONNAME',
        help='Name of icon file for display in Managed Software Center.'
        )
    additional_options.add_option(
        '--notes',
        metavar='STRING|PATH',
        help=('Specifies administrator provided notes to be embedded into the '
              'pkginfo. Can be a PATH to a file.')
        )
    # secret option!
    additional_options.add_option(
        '--print-warnings',
        action='store_true', default=True,
        help=optparse.SUPPRESS_HELP
        )
    parser.add_option_group(additional_options)
