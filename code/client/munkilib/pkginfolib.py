# encoding: utf-8
#
# Copyright 2017 Greg Neagle.
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

# standard libs
import os
import re
import sys
import time

# Apple frameworks via PyObjC
# PyLint cannot properly find names inside Cocoa libraries, so issues bogus
# No name 'Foo' in module 'Bar' warnings. Disable them.
# pylint: disable=E0611
from Foundation import NSDate, NSUserName
# pylint: enable=E0611

# our libs
from . import dmgutils
from . import info
from . import munkihash
from . import osinstaller
from . import osutils
from . import pkgutils
from . import profiles

from . import FoundationPlist

from .adobeutils import adobeinfo


# circumvent cfprefsd plist scanning
os.environ['__CFPREFERENCES_AVOID_DAEMON'] = "1"


class PkgInfoGenerationError(Exception):
    '''Error to raise if there is a fatal error when generating pkginfo'''
    pass


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
        # (AAMEE) package
        if 'receipts' in cataloginfo:
            try:
                pkgid = cataloginfo['receipts'][0].get('packageid')
            except IndexError:
                pkgid = ""
            if pkgid.startswith("com.adobe.Enterprise.install"):
                # we have an Adobe CS5 install package, process
                # as Adobe install
                #adobepkgname = cataloginfo['receipts'][0].get('filename')
                cataloginfo = adobeinfo.getAdobeCatalogInfo(pkgpath)
                                            #mountpoints[0], adobepkgname)

    else:
        # maybe an Adobe installer/updater/patcher?
        cataloginfo = adobeinfo.getAdobeCatalogInfo(pkgpath,
                                                    options.pkgname or '')
    return cataloginfo


class ProfileMetadataGenerationError(PkgInfoGenerationError):
    '''Error to raise when we can't generate config profile metadata'''
    pass


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
            print >> sys.stderr, (
                'WARNING: %s appears to be an Install macOS application, but '
                'it does not contain Contents/SharedSupport/InstallESD.dmg'
                % os.path.basename(install_macos_app))
        cataloginfo = osinstaller.get_catalog_info(mountpoints[0])

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

    #eject the dmg
    if not was_already_mounted:
        dmgutils.unmountdmg(mountpoints[0])
    return cataloginfo


# TO-DO: this (or a similar) function is defined several places. De-dupe.
def readfile(path):
    '''Reads file at path. Returns a string.'''
    try:
        fileobject = open(os.path.expanduser(path), mode='r', buffering=1)
        data = fileobject.read()
        fileobject.close()
        return data
    except (OSError, IOError):
        print >> sys.stderr, "Couldn't read %s" % path
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


class AtttributeDict(dict):
    '''Class that allow us to access foo['bar'] as foo.bar, and return None
    if foo.bar is not defined.'''
    def __getattr__(self, name):
        '''Allow access to dictionary keys as attribute names.'''
        try:
            return super(AtttributeDict, self).__getattr__(name)
        except AttributeError, err:
            try:
                return self[name]
            except KeyError:
                return None


def makepkginfo(installeritem, options):
    '''Return a pkginfo dictionary for item'''

    if isinstance(options, dict):
        options = AtttributeDict(options)

    pkginfo = {}
    installs = []
    if installeritem and os.path.exists(installeritem):
        # Check if the item is a mount point for a disk image
        if dmgutils.pathIsVolumeMountPoint(installeritem):
            # Get the disk image path for the mount point
            # and use that instead of the original item
            installeritem = dmgutils.diskImageForMountPoint(installeritem)

        # get size of installer item
        itemsize = 0
        itemhash = "N/A"
        if os.path.isfile(installeritem):
            itemsize = int(os.path.getsize(installeritem))
            itemhash = munkihash.getsha256hash(installeritem)

        if pkgutils.hasValidDiskImageExt(installeritem):
            if dmgutils.DMGisWritable(installeritem) and options.print_warnings:
                print >> sys.stderr, (
                    "WARNING: %s is a writable disk image. "
                    "Checksum verification is not supported." % installeritem)
                print >> sys.stderr, (
                    "WARNING: Consider converting %s to a read-only disk"
                    "image." % installeritem)
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
            pkginfo = get_catalog_info_from_path(installeritem, options)
            if not pkginfo:
                raise PkgInfoGenerationError(
                    "%s doesn't appear to be a valid installer item!"
                    % installeritem)
            if os.path.isdir(installeritem) and options.print_warnings:
                print >> sys.stderr, (
                    "WARNING: %s is a bundle-style package!\n"
                    "To use it with Munki, you should encapsulate it "
                    "in a disk image.\n") % installeritem
                # need to walk the dir and add it all up
                for (path, dummy_dirs, files) in os.walk(installeritem):
                    for name in files:
                        filename = os.path.join(path, name)
                        # use os.lstat so we don't follow symlinks
                        itemsize += int(os.lstat(filename).st_size)
                # convert to kbytes
                itemsize = int(itemsize/1024)

        elif pkgutils.hasValidConfigProfileExt(installeritem):
            try:
                pkginfo = get_catalog_info_for_profile(installeritem)
            except ProfileMetadataGenerationError, err:
                print >> sys.stderr, err
                raise PkgInfoGenerationError(
                    "%s doesn't appear to be a supported configuration "
                    "profile!" % installeritem)
        else:
            raise PkgInfoGenerationError(
                "%s is not a valid installer item!" % installeritem)

        pkginfo['installer_item_size'] = int(itemsize/1024)
        if itemhash != "N/A":
            pkginfo['installer_item_hash'] = itemhash

        # try to generate the correct item location
        temppath = installeritem
        location = ""
        while len(temppath) > 4:
            if temppath.endswith('/pkgs'):
                location = installeritem[len(temppath)+1:]
                break
            else:
                temppath = os.path.dirname(temppath)

        if not location:
            #just the filename
            location = os.path.split(installeritem)[1]
        pkginfo['installer_item_location'] = location

        # ADOBE STUFF - though maybe generalizable in the future?
        if (pkginfo.get('installer_type') == "AdobeCCPInstaller" and
                not options.uninstalleritem) and options.print_warnings:
            print >> sys.stderr, (
                "WARNING: This item appears to be an Adobe Creative "
                "Cloud product install.\n"
                "No uninstaller package was specified so product "
                "removal will not be possible.")
            pkginfo['uninstallable'] = False
            if 'uninstall_method' in pkginfo:
                del pkginfo['uninstall_method']

        if options.uninstalleritem:
            uninstallerpath = options.uninstalleritem
            if os.path.exists(uninstallerpath):
                # try to generate the correct item location
                temppath = uninstallerpath
                location = ""
                while len(temppath) > 4:
                    if temppath.endswith('/pkgs'):
                        location = uninstallerpath[len(temppath)+1:]
                        break
                    else:
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

        # if we have receipts, assume we can uninstall using them
        if pkginfo.get('receipts', None):
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
                    print >> sys.stderr, (
                        "Item %s appears to be a receipt. Skipping." % fitem)
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
                print >> sys.stderr, (
                    "Item %s doesn't exist. Skipping." % fitem)

    if installs:
        pkginfo['installs'] = installs

    # determine minimum_os_version from identified apps in the installs array
    if 'installs' in pkginfo:
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
