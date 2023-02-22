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
updatecheck.compare

Created by Greg Neagle on 2016-12-13.

Comparison/checking functions used by updatecheck
"""
from __future__ import absolute_import, print_function

import os
from operator import itemgetter

from .. import display
from .. import munkihash
from .. import info
from .. import pkgutils
from .. import utils
from .. import FoundationPlist


ITEM_DOES_NOT_MATCH = VERSION_IS_LOWER = -1
ITEM_NOT_PRESENT = 0
ITEM_MATCHES = VERSION_IS_THE_SAME = 1
VERSION_IS_HIGHER = 2


def compare_versions(thisvers, thatvers):
    """Compares two version numbers to one another.

    Returns:
      -1 if thisvers is older than thatvers
      1 if thisvers is the same as thatvers
      2 if thisvers is newer than thatvers
    """
    if (pkgutils.MunkiLooseVersion(thisvers) <
            pkgutils.MunkiLooseVersion(thatvers)):
        return VERSION_IS_LOWER
    elif (pkgutils.MunkiLooseVersion(thisvers) ==
          pkgutils.MunkiLooseVersion(thatvers)):
        return VERSION_IS_THE_SAME
    return VERSION_IS_HIGHER


def compare_application_version(app):
    """Checks the given path if it's available,
    otherwise uses LaunchServices and/or Spotlight to look for the app

    Args:
      app: dict with application bundle info

    Returns:
         0 if the app isn't installed
            or doesn't have valid Info.plist
        -1 if it's older
         1 if the version is the same
         2 if the version is newer

    Raises utils.Error if there's an error in the input
    """
    if 'path' in app:
        filepath = os.path.join(app['path'], 'Contents', 'Info.plist')
        if os.path.exists(filepath):
            return compare_bundle_version(app)
        display.display_debug2('%s doesn\'t exist.', filepath)
        return ITEM_NOT_PRESENT

    # no 'path' in dict
    display.display_debug2('No path given for application item.')
    # let's search:
    name = app.get('CFBundleName', '')
    bundleid = app.get('CFBundleIdentifier', '')
    version_comparison_key = app.get(
        'version_comparison_key', 'CFBundleShortVersionString')
    versionstring = app.get(version_comparison_key)

    if name == '' and bundleid == '':
        # no path, no name, no bundleid. Error!
        raise utils.Error(
            'No path, application name or bundleid was specified!')

    display.display_debug1(
        'Looking for application %s with bundleid: %s, version %s...' %
        (name, bundleid, versionstring))

    # find installed apps that match this item by name or bundleid
    appdata = info.filtered_app_data()
    appinfo = [item for item in appdata
               if (item['path'] and
                   (item['bundleid'] == bundleid or
                    (name and item['name'] == name)))]

    if not appinfo:
        # No matching apps found
        display.display_debug1(
            '\tFound no matching applications on the startup disk.')
        return ITEM_NOT_PRESENT

    # sort highest version first
    try:
        appinfo.sort(key=itemgetter('version'), reverse=True)
    except KeyError:
        # some item did not have a version key
        pass

    # iterate through matching applications
    end_result = ITEM_NOT_PRESENT
    for item in appinfo:
        if 'name' in item:
            display.display_debug2('\tFound name: \t %s', item['name'])
        display.display_debug2('\tFound path: \t %s', item['path'])
        display.display_debug2(
            '\tFound CFBundleIdentifier: \t %s', item['bundleid'])
        # create a test_app item with our found path
        test_app = {}
        test_app.update(app)
        test_app['path'] = item['path']
        compare_result = compare_bundle_version(test_app)
        if compare_result in (VERSION_IS_THE_SAME, VERSION_IS_HIGHER):
            return compare_result
        elif compare_result == VERSION_IS_LOWER:
            end_result = VERSION_IS_LOWER

    # didn't find an app with the same or higher version
    if end_result == VERSION_IS_LOWER:
        display.display_debug1(
            'An older version of this application is present.')
    return end_result


def compare_bundle_version(item):
    """Compares a bundle version passed item dict.

    Returns  0 if the bundle isn't installed
                or doesn't have valid Info.plist
            -1 if it's older
             1 if the version is the same
             2 if the version is newer

    Raises utils.Error if there's an error in the input
    """
    # look for an Info.plist inside the bundle
    filepath = os.path.join(item['path'], 'Contents', 'Info.plist')
    if not os.path.exists(filepath):
        display.display_debug1('\tNo Info.plist found at %s', filepath)
        filepath = os.path.join(item['path'], 'Resources', 'Info.plist')
        if not os.path.exists(filepath):
            display.display_debug1('\tNo Info.plist found at %s', filepath)
            return ITEM_NOT_PRESENT

    display.display_debug1('\tFound Info.plist at %s', filepath)
    # just let comparePlistVersion do the comparison
    saved_path = item['path']
    item['path'] = filepath
    compare_result = compare_plist_version(item)
    item['path'] = saved_path
    return compare_result


def compare_plist_version(item):
    """Gets the version string from the plist at path and compares versions.

    Returns  0 if the plist isn't installed
            -1 if it's older
             1 if the version is the same
             2 if the version is newer

    Raises utils.Error if there's an error in the input
    """
    version_comparison_key = item.get(
        'version_comparison_key', 'CFBundleShortVersionString')
    if 'path' in item and version_comparison_key in item:
        versionstring = item[version_comparison_key]
        filepath = item['path']
        minupvers = item.get('minimum_update_version')
    else:
        raise utils.Error('Missing plist path or version!')

    display.display_debug1('\tChecking %s for %s %s...',
                           filepath, version_comparison_key, versionstring)
    if not os.path.exists(filepath):
        display.display_debug1('\tNo plist found at %s', filepath)
        return ITEM_NOT_PRESENT

    try:
        plist = FoundationPlist.readPlist(filepath)
    except FoundationPlist.NSPropertyListSerializationException:
        display.display_debug1('\t%s may not be a plist!', filepath)
        return ITEM_NOT_PRESENT
    if not hasattr(plist, 'get'):
        display.display_debug1(
            'plist not parsed as NSCFDictionary: %s', filepath)
        return ITEM_NOT_PRESENT

    if 'version_comparison_key' in item:
        # specific key has been supplied,
        # so use this to determine installed version
        display.display_debug1(
            '\tUsing version_comparison_key %s', version_comparison_key)
        installedvers = pkgutils.getVersionString(
            plist, version_comparison_key)
    else:
        # default behavior
        installedvers = pkgutils.getVersionString(plist)
    if installedvers:
        display.display_debug1(
            '\tInstalled item has version %s', installedvers)
        if minupvers:
            if compare_versions(installedvers, minupvers) < 1:
                display.display_debug1(
                    '\tVersion %s too old < %s', installedvers, minupvers)
                return ITEM_NOT_PRESENT
        compare_result = compare_versions(installedvers, versionstring)
        results = ['older', 'not installed?!', 'the same', 'newer']
        display.display_debug1(
            '\tInstalled item is %s.', results[compare_result + 1])
        return compare_result
    else:
        display.display_debug1('\tNo version info in %s.', filepath)
        return ITEM_NOT_PRESENT


def filesystem_item_exists(item):
    """Checks to see if a filesystem item exists.

    If item has md5checksum attribute, compares on disk file's checksum.

    Returns 0 if the filesystem item does not exist on disk,
    Returns 1 if the filesystem item exists and the checksum matches
                (or there is no checksum)
    Returns -1 if the filesystem item exists but the checksum does not match.

    Broken symlinks are OK; we're testing for the existence of the symlink,
    not the item it points to.

    Raises utils.Error is there's a problem with the input.
    """
    if 'path' in item:
        filepath = item['path']
        display.display_debug1('Checking existence of %s...', filepath)
        if os.path.lexists(filepath):
            display.display_debug2('\tExists.')
            if 'md5checksum' in item:
                storedchecksum = item['md5checksum']
                ondiskchecksum = munkihash.getmd5hash(filepath)
                display.display_debug2('Comparing checksums...')
                if storedchecksum == ondiskchecksum:
                    display.display_debug2('Checksums match.')
                    return ITEM_MATCHES
                # storedchecksum != ondiskchecksum
                display.display_debug2(
                    'Checksums differ: expected %s, got %s',
                    storedchecksum, ondiskchecksum)
                return ITEM_DOES_NOT_MATCH
            # 'md5checksum' not in item
            return ITEM_MATCHES
        # not os.path.lexists(filepath)
        display.display_debug2('\tDoes not exist.')
        return ITEM_NOT_PRESENT
    # not 'path' in item
    raise utils.Error('No path specified for filesystem item.')


def compare_item_version(item):
    '''Compares an installs_item with what's on the startup disk.
    Wraps other comparison functions.

    For applications, bundles, and plists:
    Returns 0 if the item isn't installed
                or doesn't have valid Info.plist
            -1 if it's older
             1 if the version is the same
             2 if the version is newer

    For other filesystem items:
    Returns 0 if the filesystem item does not exist on disk,
            1 if the filesystem item exists and the checksum matches
                (or there is no checksum)
           -1 if the filesystem item exists but the checksum does not match.
    '''
    if not 'VersionString' in item and 'CFBundleShortVersionString' in item:
        # Ensure that 'VersionString', if not present, is populated
        # with the value of 'CFBundleShortVersionString' if present
        item['VersionString'] = item['CFBundleShortVersionString']
    itemtype = item.get('type')
    if itemtype == 'application':
        return compare_application_version(item)
    if itemtype == 'bundle':
        return compare_bundle_version(item)
    if itemtype == 'plist':
        return compare_plist_version(item)
    if itemtype == 'file':
        return filesystem_item_exists(item)
    raise utils.Error('Unknown installs item type: %s' % itemtype)


def compare_receipt_version(item):
    """Determines if the given package is already installed.

    Args:
      item: dict with packageid; a 'com.apple.pkg.ServerAdminTools' style id

    Returns  0 if the receipt isn't present
            -1 if it's older
             1 if the version is the same
             2 if the version is newer

    Raises utils.Error if there's an error in the input
    """
    if item.get('optional'):
        # receipt has been marked as optional, so it doesn't matter
        # if it's installed or not. Return 1
        # only check receipts not marked as optional
        display.display_debug1(
            'Skipping %s because it is marked as optional',
            item.get('packageid', item.get('name')))
        return VERSION_IS_THE_SAME
    installedpkgs = pkgutils.getInstalledPackages()
    if 'packageid' in item and 'version' in item:
        pkgid = item['packageid']
        vers = item['version']
    else:
        raise utils.Error('Missing packageid or version info!')

    display.display_debug1('Looking for package %s, version %s', pkgid, vers)
    installedvers = installedpkgs.get(pkgid)
    if installedvers:
        return compare_versions(installedvers, vers)
    # not installedvers
    display.display_debug1('\tThis package is not currently installed.')
    return ITEM_NOT_PRESENT


def get_installed_version(item_plist):
    """Attempts to determine the currently installed version of an item.

    Args:
      item_plist: pkginfo plist of an item to get the version for.

    Returns:
      String version of the item, or 'UNKNOWN' if unable to determine.

    """
    for receipt in item_plist.get('receipts', []):
        # look for a receipt whose version matches the pkginfo version
        if compare_versions(receipt.get('version', 0),
                            item_plist['version']) == 1:
            pkgid = receipt['packageid']
            display.display_debug2(
                'Using receipt %s to determine installed version of %s',
                pkgid, item_plist['name'])
            return pkgutils.getInstalledPackageVersion(pkgid)

    # try using items in the installs array to determine version
    install_items_with_versions = [item
                                   for item in item_plist.get('installs', [])
                                   if 'CFBundleShortVersionString' in item]
    for install_item in install_items_with_versions:
        # look for an installs item whose version matches the pkginfo version
        if compare_versions(install_item['CFBundleShortVersionString'],
                            item_plist['version']) == 1:
            if install_item['type'] == 'application':
                name = install_item.get('CFBundleName')
                bundleid = install_item.get('CFBundleIdentifier')
                display.display_debug2(
                    'Looking for application %s, bundleid %s',
                    name, install_item.get('CFBundleIdentifier'))
                try:
                    # check default location for app
                    filepath = os.path.join(install_item['path'],
                                            'Contents', 'Info.plist')
                    plist = FoundationPlist.readPlist(filepath)
                    return plist.get('CFBundleShortVersionString', 'UNKNOWN')
                except (KeyError,
                        FoundationPlist.NSPropertyListSerializationException):
                    # that didn't work, fall through to the slow way
                    appinfo = []
                    appdata = info.app_data()
                    if appdata:
                        for ad_item in appdata:
                            if bundleid and ad_item['bundleid'] == bundleid:
                                appinfo.append(ad_item)
                            elif name and ad_item['name'] == name:
                                appinfo.append(ad_item)

                    maxversion = '0.0.0.0.0'
                    for ai_item in appinfo:
                        if ('version' in ai_item and
                                compare_versions(
                                    ai_item['version'], maxversion) == 2):
                            # version is higher
                            maxversion = ai_item['version']
                    return maxversion
            elif install_item['type'] == 'bundle':
                display.display_debug2(
                    'Using bundle %s to determine installed version of %s',
                    install_item['path'], item_plist['name'])
                filepath = os.path.join(install_item['path'],
                                        'Contents', 'Info.plist')
                try:
                    plist = FoundationPlist.readPlist(filepath)
                    return plist.get('CFBundleShortVersionString', 'UNKNOWN')
                except FoundationPlist.NSPropertyListSerializationException:
                    pass
            elif install_item['type'] == 'plist':
                display.display_debug2(
                    'Using plist %s to determine installed version of %s',
                    install_item['path'], item_plist['name'])
                try:
                    plist = FoundationPlist.readPlist(install_item['path'])
                    return plist.get('CFBundleShortVersionString', 'UNKNOWN')
                except FoundationPlist.NSPropertyListSerializationException:
                    pass
    # if we fall through to here we have no idea what version we have
    return 'UNKNOWN'


if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
