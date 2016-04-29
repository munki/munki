#!/usr/bin/python
# encoding: utf-8
#
# Copyright 2009-2016 Greg Neagle.
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
updatecheck

Created by Greg Neagle on 2008-11-13.

"""

# standard libs
import datetime
import os
import subprocess
import socket
import urllib2
import urlparse
from urllib import quote_plus
from OpenSSL.crypto import load_certificate, FILETYPE_PEM

# our libs
import appleupdates
import fetch
import keychain
import munkicommon
import munkistatus
import profiles
import FoundationPlist

# Apple's libs
# PyLint cannot properly find names inside Cocoa libraries, so issues bogus
# No name 'Foo' in module 'Bar' warnings. Disable them.
# pylint: disable=E0611
from Foundation import NSDate, NSPredicate, NSTimeZone
# pylint: enable=E0611

# Disable PyLint complaining about 'invalid' camelCase names
# pylint: disable=C0103

# This many hours before a force install deadline, start notifying the user.
FORCE_INSTALL_WARNING_HOURS = 4


def makeCatalogDB(catalogitems):
    """Takes an array of catalog items and builds some indexes so we can
    get our common data faster. Returns a dict we can use like a database"""
    name_table = {}
    pkgid_table = {}

    itemindex = -1
    for item in catalogitems:
        itemindex = itemindex + 1
        name = item.get('name', 'NO NAME')
        vers = item.get('version', 'NO VERSION')

        if name == 'NO NAME' or vers == 'NO VERSION':
            munkicommon.display_warning('Bad pkginfo: %s', item)

        # normalize the version number
        vers = trimVersionString(vers)

        # build indexes for items by name and version
        if not name in name_table:
            name_table[name] = {}
        if not vers in name_table[name]:
            name_table[name][vers] = []
        name_table[name][vers].append(itemindex)

        # build table of receipts
        for receipt in item.get('receipts', []):
            if 'packageid' in receipt and 'version' in receipt:
                pkg_id = receipt['packageid']
                version = receipt['version']
                if not pkg_id in pkgid_table:
                    pkgid_table[pkg_id] = {}
                if not version in pkgid_table[pkg_id]:
                    pkgid_table[pkg_id][version] = []
                pkgid_table[pkg_id][version].append(itemindex)

    # build table of update items with a list comprehension --
    # filter all items from the catalogitems that have a non-empty
    # 'update_for' list
    updaters = [item for item in catalogitems if item.get('update_for')]

    # now fix possible admin errors where 'update_for' is a string instead
    # of a list of strings
    for update in updaters:
        if isinstance(update['update_for'], basestring):
            # convert to list of strings
            update['update_for'] = [update['update_for']]

    # build table of autoremove items with a list comprehension --
    # filter all items from the catalogitems that have a non-empty
    # 'autoremove' list
    # autoremove items are automatically removed if they are not in the
    # managed_install list (either directly or indirectly via included
    # manifests)
    autoremoveitems = [item.get('name') for item in catalogitems
                       if item.get('autoremove')]
    # convert to set and back to list to get list of unique names
    autoremoveitems = list(set(autoremoveitems))

    pkgdb = {}
    pkgdb['named'] = name_table
    pkgdb['receipts'] = pkgid_table
    pkgdb['updaters'] = updaters
    pkgdb['autoremoveitems'] = autoremoveitems
    pkgdb['items'] = catalogitems

    return pkgdb


def addPackageids(catalogitems, itemname_to_pkgid, pkgid_to_itemname):
    """Adds packageids from each catalogitem to two dictionaries.
    One maps itemnames to receipt pkgids, the other maps receipt pkgids
    to itemnames"""
    for item in catalogitems:
        name = item.get('name')
        if not name:
            continue
        if item.get('receipts'):
            if not name in itemname_to_pkgid:
                itemname_to_pkgid[name] = {}

            for receipt in item['receipts']:
                if 'packageid' in receipt:
                    pkgid = receipt['packageid']
                    vers = receipt['version']
                    if not pkgid in itemname_to_pkgid[name]:
                        itemname_to_pkgid[name][pkgid] = []
                    if not vers in itemname_to_pkgid[name][pkgid]:
                        itemname_to_pkgid[name][pkgid].append(vers)

                    if not pkgid in pkgid_to_itemname:
                        pkgid_to_itemname[pkgid] = {}
                    if not name in pkgid_to_itemname[pkgid]:
                        pkgid_to_itemname[pkgid][name] = []
                    if not vers in pkgid_to_itemname[pkgid][name]:
                        pkgid_to_itemname[pkgid][name].append(vers)


INSTALLEDPKGS = {}
def getInstalledPackages():
    """Builds a dictionary of installed receipts and their version number"""
    #global INSTALLEDPKGS

    # we use the --regexp option to pkgutil to get it to return receipt
    # info for all installed packages.  Huge speed up.
    proc = subprocess.Popen(['/usr/sbin/pkgutil', '--regexp',
                             '--pkg-info-plist', '.*'], bufsize=8192,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out, dummy_err) = proc.communicate()
    while out:
        (pliststr, out) = munkicommon.getFirstPlist(out)
        if pliststr:
            plist = FoundationPlist.readPlistFromString(pliststr)
            if 'pkg-version' in plist and 'pkgid' in plist:
                INSTALLEDPKGS[plist['pkgid']] = (
                    plist['pkg-version'] or '0.0.0.0.0')
        else:
            break

    # Now check /Library/Receipts
    receiptsdir = '/Library/Receipts'
    if os.path.exists(receiptsdir):
        installitems = munkicommon.listdir(receiptsdir)
        for item in installitems:
            if item.endswith('.pkg'):
                pkginfo = munkicommon.getOnePackageInfo(
                    os.path.join(receiptsdir, item))
                pkgid = pkginfo.get('packageid')
                thisversion = pkginfo.get('version')
                if pkgid:
                    if not pkgid in INSTALLEDPKGS:
                        INSTALLEDPKGS[pkgid] = thisversion
                    else:
                        # pkgid is already in our list. There must be
                        # multiple receipts with the same pkgid.
                        # in this case, we want the highest version
                        # number, since that's the one that's
                        # installed, since presumably
                        # the newer package replaced the older one
                        storedversion = INSTALLEDPKGS[pkgid]
                        if (munkicommon.MunkiLooseVersion(thisversion) >
                                munkicommon.MunkiLooseVersion(storedversion)):
                            INSTALLEDPKGS[pkgid] = thisversion

    #ManagedInstallDir = munkicommon.pref('ManagedInstallDir')
    #receiptsdatapath = os.path.join(ManagedInstallDir, 'FoundReceipts.plist')
    #try:
    #   FoundationPlist.writePlist(INSTALLEDPKGS, receiptsdatapath)
    #except FoundationPlist.NSPropertyListWriteException:
    #   pass


def bestVersionMatch(vers_num, item_dict):
    '''Attempts to find the best match in item_dict for vers_num'''
    vers_tuple = vers_num.split('.')
    precision = 1
    while precision <= len(vers_tuple):
        test_vers = '.'.join(vers_tuple[0:precision])
        match_names = []
        for item in item_dict.keys():
            for item_version in item_dict[item]:
                if (item_version.startswith(test_vers) and
                        item not in match_names):
                    match_names.append(item)
        if len(match_names) == 1:
            return match_names[0]
        precision = precision + 1

    return None


# global pkgdata
PKGDATA = {}
def analyzeInstalledPkgs():
    """Analyzed installed packages in an attempt to determine what is
       installed."""
    #global PKGDATA
    itemname_to_pkgid = {}
    pkgid_to_itemname = {}
    for catalogname in CATALOG.keys():
        catalogitems = CATALOG[catalogname]['items']
        addPackageids(catalogitems, itemname_to_pkgid, pkgid_to_itemname)
    # itemname_to_pkgid now contains all receipts (pkgids) we know about
    # from items in all available catalogs

    if not INSTALLEDPKGS:
        getInstalledPackages()
    # INSTALLEDPKGS now contains all receipts found on this machine

    installed = []
    partiallyinstalled = []
    installedpkgsmatchedtoname = {}
    for name in itemname_to_pkgid.keys():
        # name is a Munki install item name
        somepkgsfound = False
        allpkgsfound = True
        for pkgid in itemname_to_pkgid[name].keys():
            if pkgid in INSTALLEDPKGS.keys():
                somepkgsfound = True
                if not name in installedpkgsmatchedtoname:
                    installedpkgsmatchedtoname[name] = []
                # record this pkgid for Munki install item name
                installedpkgsmatchedtoname[name].append(pkgid)
            else:
                # didn't find pkgid in INSTALLEDPKGS
                allpkgsfound = False
        if allpkgsfound:
            # we found all receipts by pkgid on disk
            installed.append(name)
        elif somepkgsfound:
            # we found only some receipts for the item
            # on disk
            partiallyinstalled.append(name)

    # we pay special attention to the items that seem partially installed.
    # we need to see if there are any packages that are unique to this item
    # if there aren't, then this item probably isn't installed, and we're
    # just finding receipts that are shared with other items.
    for name in partiallyinstalled:
        # get a list of pkgs for this item that are installed
        pkgsforthisname = installedpkgsmatchedtoname[name]
        # now build a list of all the pkgs referred to by all the other
        # items that are either partially or entirely installed
        allotherpkgs = []
        for othername in installed:
            allotherpkgs.extend(installedpkgsmatchedtoname[othername])
        for othername in partiallyinstalled:
            if othername != name:
                allotherpkgs.extend(installedpkgsmatchedtoname[othername])
        # use Python sets to find pkgs that are unique to this name
        uniquepkgs = list(set(pkgsforthisname) - set(allotherpkgs))
        if uniquepkgs:
            installed.append(name)

    # now filter partiallyinstalled to remove those items we moved to installed
    partiallyinstalled = [item for item in partiallyinstalled
                          if item not in installed]

    # build our reference table. For each item we think is installed,
    # record the receipts on disk matched to the item
    references = {}
    for name in installed:
        for pkgid in installedpkgsmatchedtoname[name]:
            if not pkgid in references:
                references[pkgid] = []
            references[pkgid].append(name)

    # look through all our INSTALLEDPKGS, looking for ones that have not been
    # attached to any Munki names yet
    orphans = [pkgid for pkgid in INSTALLEDPKGS.keys()
               if pkgid not in references]

    # attempt to match orphans to Munki item names
    matched_orphans = []
    for pkgid in orphans:
        if pkgid in pkgid_to_itemname:
            installed_pkgid_version = INSTALLEDPKGS[pkgid]
            possible_match_items = pkgid_to_itemname[pkgid]
            best_match = bestVersionMatch(
                installed_pkgid_version, possible_match_items)
            if best_match:
                matched_orphans.append(best_match)

    # process matched_orphans
    for name in matched_orphans:
        if name not in installed:
            installed.append(name)
        if name in partiallyinstalled:
            partiallyinstalled.remove(name)
        for pkgid in installedpkgsmatchedtoname[name]:
            if not pkgid in references:
                references[pkgid] = []
            if not name in references[pkgid]:
                references[pkgid].append(name)

    PKGDATA['receipts_for_name'] = installedpkgsmatchedtoname
    PKGDATA['installed_names'] = installed
    PKGDATA['pkg_references'] = references

    # left here for future debugging/testing use....
    #PKGDATA['itemname_to_pkgid'] = itemname_to_pkgid
    #PKGDATA['pkgid_to_itemname'] = pkgid_to_itemname
    #PKGDATA['partiallyinstalled_names'] = partiallyinstalled
    #PKGDATA['orphans'] = orphans
    #PKGDATA['matched_orphans'] = matched_orphans
    #ManagedInstallDir = munkicommon.pref('ManagedInstallDir')
    #pkgdatapath = os.path.join(ManagedInstallDir, 'PackageData.plist')
    #try:
    #    FoundationPlist.writePlist(PKGDATA, pkgdatapath)
    #except FoundationPlist.NSPropertyListWriteException:
    #    pass
    #catalogdbpath =  os.path.join(ManagedInstallDir, 'CatalogDB.plist')
    #try:
    #    FoundationPlist.writePlist(CATALOG, catalogdbpath)
    #except FoundationPlist.NSPropertyListWriteException:
    #    pass


def getAppBundleID(path):
    """Returns CFBundleIdentifier if available for application at path."""
    infopath = os.path.join(path, 'Contents', 'Info.plist')
    if os.path.exists(infopath):
        try:
            plist = FoundationPlist.readPlist(infopath)
            if 'CFBundleIdentifier' in plist:
                return plist['CFBundleIdentifier']
        except (AttributeError,
                FoundationPlist.NSPropertyListSerializationException):
            pass

    return None


def compareVersions(thisvers, thatvers):
    """Compares two version numbers to one another.

    Returns:
      -1 if thisvers is older than thatvers
      1 if thisvers is the same as thatvers
      2 if thisvers is newer than thatvers
    """
    if (munkicommon.MunkiLooseVersion(thisvers) <
            munkicommon.MunkiLooseVersion(thatvers)):
        return -1
    elif (munkicommon.MunkiLooseVersion(thisvers) ==
          munkicommon.MunkiLooseVersion(thatvers)):
        return 1
    else:
        return 2


def compareApplicationVersion(app):
    """First checks the given path if it's available,
    then uses system profiler data to look for the app

    Args:
      app: dict with application bundle info

    Returns:
      Boolean.
             0 if the app isn't installed
                or doesn't have valid Info.plist
            -1 if it's older
             1 if the version is the same
             2 if the version is newer

    Raises munkicommon.Error if there's an error in the input
    """
    if 'path' in app:
        filepath = os.path.join(app['path'], 'Contents', 'Info.plist')
        if os.path.exists(filepath):
            return compareBundleVersion(app)

    # not in default location, or no path specified, so let's search:
    name = app.get('CFBundleName', '')
    bundleid = app.get('CFBundleIdentifier', '')
    version_comparison_key = app.get(
        'version_comparison_key', 'CFBundleShortVersionString')
    versionstring = app.get(version_comparison_key)
    minupvers = app.get('minimum_update_version')

    if name == '' and bundleid == '':
        if 'path' in app:
            # already looked at default path, and we don't have
            # any additional info, so we have to assume it's not installed.
            return 0
        else:
            # no path, no name, no bundleid. Error!
            raise munkicommon.Error(
                'No application name or bundleid was specified!')

    munkicommon.display_debug1(
        'Looking for application %s with bundleid: %s, version %s...' %
        (name, bundleid, versionstring))
    appinfo = []
    appdata = munkicommon.getAppData()
    if appdata:
        for item in appdata:
            # Skip applications in /Users but not /Users/Shared, for now.
            if 'path' in item:
                if item['path'].startswith('/Users/') and \
                    not item['path'].startswith('/Users/Shared/'):
                    munkicommon.display_debug2(
                        'Skipped app %s with path %s',
                        item['name'], item['path'])
                    continue
            if bundleid:
                if item['bundleid'] == bundleid:
                    appinfo.append(item)
            elif name and item['name'] == name:
                appinfo.append(item)

    if not appinfo:
        # app isn't present!
        munkicommon.display_debug1(
            '\tDid not find this application on the startup disk.')
        return 0

    # iterate through matching applications
    for item in appinfo:
        if 'name' in item:
            munkicommon.display_debug2(
                '\tName: \t %s', item['name'])
        if 'path' in item:
            apppath = item['path']
            munkicommon.display_debug2(
                '\tPath: \t %s', apppath)
            munkicommon.display_debug2(
                '\tCFBundleIdentifier: \t %s', item['bundleid'])

        if apppath and version_comparison_key != 'CFBundleShortVersionString':
            # if a specific plist version key has been supplied,
            # if we're suppose to compare against a key other than
            # 'CFBundleShortVersionString' we can't use item['version']
            installed_version = munkicommon.getBundleVersion(
                apppath, version_comparison_key)
        else:
            # item['version'] is CFBundleShortVersionString
            installed_version = item['version']

        if minupvers:
            if compareVersions(installed_version, minupvers) < 1:
                munkicommon.display_debug1(
                    '\tVersion %s too old < %s', installed_version, minupvers)
                # installed version is < minimum_update_version,
                # too old to match
                return 0

        if 'version' in item:
            munkicommon.display_debug2(
                '\tVersion: \t %s', installed_version)
            if compareVersions(installed_version, versionstring) == 1:
                # version is the same
                return 1
            if compareVersions(installed_version, versionstring) == 2:
                # version is newer
                return 2

    # if we got this far, must only be older
    munkicommon.display_debug1(
        'An older version of this application is present.')
    return -1


def compareBundleVersion(item):
    """Compares a bundle version passed item dict.

    Returns  0 if the bundle isn't installed
                or doesn't have valid Info.plist
            -1 if it's older
             1 if the version is the same
             2 if the version is newer

    Raises munkicommon.Error if there's an error in the input
    """
    # look for an Info.plist inside the bundle
    filepath = os.path.join(item['path'], 'Contents', 'Info.plist')
    if not os.path.exists(filepath):
        munkicommon.display_debug1('\tNo Info.plist found at %s', filepath)
        filepath = os.path.join(item['path'], 'Resources', 'Info.plist')
        if not os.path.exists(filepath):
            munkicommon.display_debug1('\tNo Info.plist found at %s', filepath)
            return 0

    munkicommon.display_debug1('\tFound Info.plist at %s', filepath)
    # just let comparePlistVersion do the comparison
    saved_path = item['path']
    item['path'] = filepath
    compare_result = comparePlistVersion(item)
    item['path'] = saved_path
    return compare_result


def comparePlistVersion(item):
    """Gets the version string from the plist at path and compares versions.

    Returns  0 if the plist isn't installed
            -1 if it's older
             1 if the version is the same
             2 if the version is newer

    Raises munkicommon.Error if there's an error in the input
    """
    version_comparison_key = item.get(
        'version_comparison_key', 'CFBundleShortVersionString')
    if 'path' in item and version_comparison_key in item:
        versionstring = item[version_comparison_key]
        filepath = item['path']
        minupvers = item.get('minimum_update_version')
    else:
        raise munkicommon.Error('Missing plist path or version!')

    munkicommon.display_debug1('\tChecking %s for %s %s...',
                               filepath, version_comparison_key, versionstring)
    if not os.path.exists(filepath):
        munkicommon.display_debug1('\tNo plist found at %s', filepath)
        return 0

    try:
        plist = FoundationPlist.readPlist(filepath)
    except FoundationPlist.NSPropertyListSerializationException:
        munkicommon.display_debug1('\t%s may not be a plist!', filepath)
        return 0
    if not hasattr(plist, 'get'):
        munkicommon.display_debug1(
            'plist not parsed as NSCFDictionary: %s', filepath)
        return 0

    if 'version_comparison_key' in item:
        # specific key has been supplied,
        # so use this to determine installed version
        munkicommon.display_debug1(
            '\tUsing version_comparison_key %s', version_comparison_key)
        installedvers = munkicommon.getVersionString(
            plist, version_comparison_key)
    else:
        # default behavior
        installedvers = munkicommon.getVersionString(plist)
    if installedvers:
        munkicommon.display_debug1(
            '\tInstalled item has version %s', installedvers)
        if minupvers:
            if compareVersions(installedvers, minupvers) < 1:
                munkicommon.display_debug1(
                    '\tVersion %s too old < %s', installedvers, minupvers)
                return 0
        compare_result = compareVersions(installedvers, versionstring)
        results = ['older', 'not installed?!', 'the same', 'newer']
        munkicommon.display_debug1('\tInstalled item is %s.',
                                   results[compare_result + 1])
        return compare_result
    else:
        munkicommon.display_debug1('\tNo version info in %s.', filepath)
        return 0


def filesystemItemExists(item):
    """Checks to see if a filesystem item exists.

    If item has md5checksum attribute, compares on disk file's checksum.

    Returns 0 if the filesystem item does not exist on disk,
    Returns 1 if the filesystem item exists and the checksum matches
                (or there is no checksum)
    Returns -1 if the filesystem item exists but the checksum does not match.

    Broken symlinks are OK; we're testing for the existence of the symlink,
    not the item it points to.

    Raises munkicommon.Error is there's a problem with the input.
    """
    if 'path' in item:
        filepath = item['path']
        munkicommon.display_debug1('Checking existence of %s...', filepath)
        if os.path.lexists(filepath):
            munkicommon.display_debug2('\tExists.')
            if 'md5checksum' in item:
                storedchecksum = item['md5checksum']
                ondiskchecksum = munkicommon.getmd5hash(filepath)
                munkicommon.display_debug2('Comparing checksums...')
                if storedchecksum == ondiskchecksum:
                    munkicommon.display_debug2('Checksums match.')
                    return 1
                else:
                    munkicommon.display_debug2(
                        'Checksums differ: expected %s, got %s',
                        storedchecksum, ondiskchecksum)
                    return -1
            else:
                return 1
        else:
            munkicommon.display_debug2('\tDoes not exist.')
            return 0
    else:
        raise munkicommon.Error('No path specified for filesystem item.')


def compareItemVersion(item):
    '''Compares an installs_item with what's on the startup disk.
    Wraps other comparsion functions.

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
        return compareApplicationVersion(item)
    if itemtype == 'bundle':
        return compareBundleVersion(item)
    if itemtype == 'plist':
        return comparePlistVersion(item)
    if itemtype == 'file':
        return filesystemItemExists(item)
    raise munkicommon.Error('Unknown installs item type: %s', itemtype)


def compareReceiptVersion(item):
    """Determines if the given package is already installed.

    Args:
      item: dict with packageid; a 'com.apple.pkg.ServerAdminTools' style id

    Returns  0 if the receipt isn't present
            -1 if it's older
             1 if the version is the same
             2 if the version is newer

    Raises munkicommon.Error if there's an error in the input
    """
    if item.get('optional'):
        # receipt has been marked as optional, so it doesn't matter
        # if it's installed or not. Return 1
        # only check receipts not marked as optional
        munkicommon.display_debug1(
            'Skipping %s because it is marked as optional',
            item.get('packageid', item.get('name')))
        return 1
    if not INSTALLEDPKGS:
        getInstalledPackages()
    if 'packageid' in item and 'version' in item:
        pkgid = item['packageid']
        vers = item['version']
    else:
        raise munkicommon.Error('Missing packageid or version info!')

    munkicommon.display_debug1('Looking for package %s, version %s',
                               pkgid, vers)
    installedvers = INSTALLEDPKGS.get(pkgid)
    if installedvers:
        return compareVersions(installedvers, vers)
    else:
        munkicommon.display_debug1(
            '\tThis package is not currently installed.')
        return 0


def getInstalledVersion(item_plist):
    """Attempts to determine the currently installed version of an item.

    Args:
      item_plist: pkginfo plist of an item to get the version for.

    Returns:
      String version of the item, or 'UNKNOWN' if unable to determine.

    """
    for receipt in item_plist.get('receipts', []):
        # look for a receipt whose version matches the pkginfo version
        if compareVersions(receipt.get('version', 0),
                           item_plist['version']) == 1:
            pkgid = receipt['packageid']
            munkicommon.display_debug2(
                'Using receipt %s to determine installed version of %s',
                pkgid, item_plist['name'])
            return munkicommon.getInstalledPackageVersion(pkgid)

    install_items_with_versions = [item
                                   for item in item_plist.get('installs', [])
                                   if 'CFBundleShortVersionString' in item]
    for install_item in install_items_with_versions:
        # look for an installs item whose version matches the pkginfo version
        if compareVersions(install_item['CFBundleShortVersionString'],
                           item_plist['version']) == 1:
            if install_item['type'] == 'application':
                name = install_item.get('CFBundleName')
                bundleid = install_item.get('CFBundleIdentifier')
                munkicommon.display_debug2(
                    'Looking for application %s, bundleid %s',
                    name, install_item.get('CFBundleIdentifier'))
                try:
                    # check default location for app
                    filepath = os.path.join(install_item['path'],
                                            'Contents', 'Info.plist')
                    plist = FoundationPlist.readPlist(filepath)
                    return plist.get('CFBundleShortVersionString', 'UNKNOWN')
                except FoundationPlist.NSPropertyListSerializationException:
                    # that didn't work, fall through to the slow way
                    appinfo = []
                    appdata = munkicommon.getAppData()
                    if appdata:
                        for ad_item in appdata:
                            if bundleid and ad_item['bundleid'] == bundleid:
                                appinfo.append(ad_item)
                            elif name and ad_item['name'] == name:
                                appinfo.append(ad_item)

                    maxversion = '0.0.0.0.0'
                    for ai_item in appinfo:
                        if 'version' in ai_item:
                            if compareVersions(ai_item['version'],
                                               maxversion) == 2:
                                # version is higher
                                maxversion = ai_item['version']
                    return maxversion
            elif install_item['type'] == 'bundle':
                munkicommon.display_debug2(
                    'Using bundle %s to determine installed version of %s',
                    install_item['path'], item_plist['name'])
                filepath = os.path.join(install_item['path'],
                                        'Contents', 'Info.plist')
                try:
                    plist = FoundationPlist.readPlist(filepath)
                    return plist.get('CFBundleShortVersionString', 'UNKNOWN')
                except FoundationPlist.NSPropertyListSerializationException:
                    return "UNKNOWN"
            elif install_item['type'] == 'plist':
                munkicommon.display_debug2(
                    'Using plist %s to determine installed version of %s',
                    install_item['path'], item_plist['name'])
                try:
                    plist = FoundationPlist.readPlist(install_item['path'])
                    return plist.get('CFBundleShortVersionString', 'UNKNOWN')
                except FoundationPlist.NSPropertyListSerializationException:
                    return "UNKNOWN"
    # if we fall through to here we have no idea what version we have
    return 'UNKNOWN'


def download_installeritem(item_pl, installinfo, uninstalling=False):
    """Downloads an (un)installer item.
    Returns True if the item was downloaded, False if it was already cached.
    Raises an error if there are issues..."""

    download_item_key = 'installer_item_location'
    item_hash_key = 'installer_item_hash'
    if uninstalling and 'uninstaller_item_location' in item_pl:
        download_item_key = 'uninstaller_item_location'
        item_hash_key = 'uninstaller_item_hash'

    location = item_pl.get(download_item_key)
    if not location:
        raise fetch.MunkiDownloadError(
            "No %s in item info." % download_item_key)

    # allow pkginfo preferences to override system munki preferences
    downloadbaseurl = item_pl.get('PackageCompleteURL') or \
                      item_pl.get('PackageURL') or \
                      munkicommon.pref('PackageURL') or \
                      munkicommon.pref('SoftwareRepoURL') + '/pkgs/'

    # build a URL, quoting the the location to encode reserved characters
    if item_pl.get('PackageCompleteURL'):
        pkgurl = downloadbaseurl
    else:
        if not downloadbaseurl.endswith('/'):
            downloadbaseurl = downloadbaseurl + '/'
        pkgurl = downloadbaseurl + urllib2.quote(location.encode('UTF-8'))

    pkgname = getInstallerItemBasename(location)
    munkicommon.display_debug2('Download base URL is: %s', downloadbaseurl)
    munkicommon.display_debug2('Package name is: %s', pkgname)
    munkicommon.display_debug2('Download URL is: %s', pkgurl)

    ManagedInstallDir = munkicommon.pref('ManagedInstallDir')
    mycachedir = os.path.join(ManagedInstallDir, 'Cache')
    destinationpath = getDownloadCachePath(mycachedir, location)
    munkicommon.display_debug2('Downloading to: %s', destinationpath)

    munkicommon.display_detail('Downloading %s from %s', pkgname, location)

    if not os.path.exists(destinationpath):
        # check to see if there is enough free space to download and install
        if not enoughDiskSpace(item_pl, installinfo['managed_installs'],
                               uninstalling=uninstalling):
            raise fetch.MunkiDownloadError(
                'Insufficient disk space to download and install %s' % pkgname)
        else:
            munkicommon.display_detail(
                'Downloading %s from %s', pkgname, location)

    dl_message = 'Downloading %s...' % pkgname
    expected_hash = item_pl.get(item_hash_key, None)
    try:
        return getResourceIfChangedAtomically(pkgurl, destinationpath,
                                              resume=True,
                                              message=dl_message,
                                              expected_hash=expected_hash,
                                              verify=True)
    except fetch.MunkiDownloadError:
        raise


def isItemInInstallInfo(manifestitem_pl, thelist, vers=''):
    """Determines if an item is in a manifest plist.

    Returns True if the manifest item has already
    been processed (it's in the list) and, optionally,
    the version is the same or greater.
    """
    for item in thelist:
        try:
            if item['name'] == manifestitem_pl['name']:
                if not vers:
                    return True
                #if the version already installed or processed to be
                #installed is the same or greater, then we're good.
                if item.get('installed') and (compareVersions(
                        item.get('installed_version'), vers) in (1, 2)):
                    return True
                if (compareVersions(
                        item.get('version_to_install'), vers) in (1, 2)):
                    return True
        except KeyError:
            # item is missing 'name', so doesn't match
            pass

    return False


def nameAndVersion(aString):
    """Splits a string into the name and version number.

    Name and version must be seperated with a hyphen ('-')
    or double hyphen ('--').
    'TextWrangler-2.3b1' becomes ('TextWrangler', '2.3b1')
    'AdobePhotoshopCS3--11.2.1' becomes ('AdobePhotoshopCS3', '11.2.1')
    'MicrosoftOffice2008-12.2.1' becomes ('MicrosoftOffice2008', '12.2.1')
    """
    for delim in ('--', '-'):
        if aString.count(delim) > 0:
            chunks = aString.split(delim)
            vers = chunks.pop()
            name = delim.join(chunks)
            if vers[0] in '0123456789':
                return (name, vers)

    return (aString, '')


def getAllItemsWithName(name, cataloglist):
    """Searches the catalogs in a list for all items matching a given name.

    Returns:
      list of pkginfo items; sorted with newest version first. No precedence
      is given to catalog order.
    """
    def compare_item_versions(a, b):
        """Internal comparison function for use with sorting"""
        return cmp(munkicommon.MunkiLooseVersion(b['version']),
                   munkicommon.MunkiLooseVersion(a['version']))

    itemlist = []
    # we'll throw away any included version info
    name = nameAndVersion(name)[0]

    munkicommon.display_debug1('Looking for all items matching: %s...', name)
    for catalogname in cataloglist:
        if not catalogname in CATALOG.keys():
            # in case catalogname refers to a non-existent catalog...
            continue
        # is name in the catalog name table?
        if name in CATALOG[catalogname]['named']:
            versionsmatchingname = CATALOG[catalogname]['named'][name]
            for vers in versionsmatchingname.keys():
                if vers != 'latest':
                    indexlist = CATALOG[catalogname]['named'][name][vers]
                    for index in indexlist:
                        thisitem = CATALOG[catalogname]['items'][index]
                        if not thisitem in itemlist:
                            munkicommon.display_debug1(
                                'Adding item %s, version %s from catalog %s...',
                                name, thisitem['version'], catalogname)
                            itemlist.append(thisitem)

    if itemlist:
        # sort so latest version is first
        itemlist.sort(compare_item_versions)
    return itemlist


def trimVersionString(version_string):
    """Trims all lone trailing zeros in the version string after major/minor.

    Examples:
      10.0.0.0 -> 10.0
      10.0.0.1 -> 10.0.0.1
      10.0.0-abc1 -> 10.0.0-abc1
      10.0.0-abc1.0 -> 10.0.0-abc1
    """
    if version_string == None or version_string == '':
        return ''
    version_parts = version_string.split('.')
    # strip off all trailing 0's in the version, while over 2 parts.
    while len(version_parts) > 2 and version_parts[-1] == '0':
        del version_parts[-1]
    return '.'.join(version_parts)


def getItemDetail(name, cataloglist, vers=''):
    """Searches the catalogs in list for an item matching the given name.

    If no version is supplied, but the version is appended to the name
    ('TextWrangler--2.3.0.0.0') that version is used.
    If no version is given at all, the latest version is assumed.
    Returns a pkginfo item.
    """
    def compare_version_keys(a, b):
        """Internal comparison function for use in sorting"""
        return cmp(munkicommon.MunkiLooseVersion(b),
                   munkicommon.MunkiLooseVersion(a))

    if vers == 'apple_update_metadata':
        vers = 'latest'
    else:
        (name, includedversion) = nameAndVersion(name)
        if vers == '':
            if includedversion:
                vers = includedversion
        if vers:
            vers = trimVersionString(vers)
        else:
            vers = 'latest'

    munkicommon.display_debug1(
        'Looking for detail for: %s, version %s...', name, vers)
    rejected_items = []
    for catalogname in cataloglist:
        if not catalogname in CATALOG.keys():
            # in case the list refers to a non-existent catalog
            continue

        # is name in the catalog?
        if name in CATALOG[catalogname]['named']:
            itemsmatchingname = CATALOG[catalogname]['named'][name]
            indexlist = []
            if vers == 'latest':
                # order all our items, latest first
                versionlist = itemsmatchingname.keys()
                versionlist.sort(compare_version_keys)
                for versionkey in versionlist:
                    indexlist.extend(itemsmatchingname[versionkey])

            elif vers in itemsmatchingname:
                # get the specific requested version
                indexlist = itemsmatchingname[vers]

            munkicommon.display_debug1(
                'Considering %s items with name %s from catalog %s' %
                (len(indexlist), name, catalogname))
            for index in indexlist:
                item = CATALOG[catalogname]['items'][index]
                # we have an item whose name and version matches the request.
                if item.get('minimum_munki_version'):
                    min_munki_vers = item['minimum_munki_version']
                    munkicommon.display_debug1(
                        'Considering item %s, version %s '
                        'with minimum Munki version required %s',
                        item['name'], item['version'], min_munki_vers)
                    munkicommon.display_debug1(
                        'Our Munki version is %s', MACHINE['munki_version'])
                    if (munkicommon.MunkiLooseVersion(MACHINE['munki_version'])
                            < munkicommon.MunkiLooseVersion(min_munki_vers)):
                        # skip this one, go to the next
                        reason = ('Rejected item %s, version %s '
                                  'with minimum Munki version required %s. '
                                  'Our Munki version is %s.'
                                  % (item['name'], item['version'],
                                     item['minimum_munki_version'],
                                     MACHINE['munki_version']))
                        rejected_items.append(reason)
                        continue

                # now check to see if it meets os and cpu requirements
                if item.get('minimum_os_version', ''):
                    min_os_vers = item['minimum_os_version']
                    munkicommon.display_debug1(
                        'Considering item %s, version %s '
                        'with minimum os version required %s',
                        item['name'], item['version'], min_os_vers)
                    munkicommon.display_debug1(
                        'Our OS version is %s', MACHINE['os_vers'])
                    if (munkicommon.MunkiLooseVersion(MACHINE['os_vers']) <
                            munkicommon.MunkiLooseVersion(min_os_vers)):
                        # skip this one, go to the next
                        reason = ('Rejected item %s, version %s '
                                  'with minimum os version required %s. '
                                  "Our OS version is %s."
                                  % (item['name'], item['version'],
                                     item['minimum_os_version'],
                                     MACHINE['os_vers']))
                        rejected_items.append(reason)
                        continue

                if item.get('maximum_os_version', ''):
                    max_os_vers = item['maximum_os_version']
                    munkicommon.display_debug1(
                        'Considering item %s, version %s '
                        'with maximum os version supported %s',
                        item['name'], item['version'], max_os_vers)
                    munkicommon.display_debug1(
                        'Our OS version is %s', MACHINE['os_vers'])
                    if (munkicommon.MunkiLooseVersion(MACHINE['os_vers']) >
                            munkicommon.MunkiLooseVersion(max_os_vers)):
                        # skip this one, go to the next
                        reason = ('Rejected item %s, version %s '
                                  'with maximum os version required %s. '
                                  'Our OS version is %s.'
                                  % (item['name'], item['version'],
                                     item['maximum_os_version'],
                                     MACHINE['os_vers']))
                        rejected_items.append(reason)
                        continue

                if 'supported_architectures' in item:
                    supported_arch_found = False
                    munkicommon.display_debug1(
                        'Considering item %s, version %s '
                        'with supported architectures: %s',
                        item['name'], item['version'],
                        item['supported_architectures'])
                    munkicommon.display_debug1(
                        'Our architecture is %s', MACHINE['arch'])
                    for arch in item['supported_architectures']:
                        if arch == MACHINE['arch']:
                            # we found a supported architecture that matches
                            # this machine, so we can use it
                            supported_arch_found = True
                            break
                    if (not supported_arch_found and
                            len(item['supported_architectures']) == 1 and
                            item['supported_architectures'][0] == 'x86_64' and
                            MACHINE['arch'] == 'i386' and
                            MACHINE['x86_64_capable'] == True):
                        supported_arch_found = True

                    if not supported_arch_found:
                        # we didn't find a supported architecture that
                        # matches this machine
                        reason = ('Rejected item %s, version %s '
                                  'with supported architectures: %s. '
                                  'Our architecture is %s.'
                                  % (item['name'], item['version'],
                                     item['supported_architectures'],
                                     MACHINE['arch']))
                        rejected_items.append(reason)
                        continue

                if item.get('installable_condition'):
                    pkginfo_predicate = item['installable_condition']
                    if not predicateEvaluatesAsTrue(pkginfo_predicate):
                        reason = ('Rejected item %s, version %s '
                                  'with installable_condition: %s.'
                                  % (item['name'], item['version'],
                                     item['installable_condition']))
                        rejected_items.append(reason)
                        continue

                # item name, version, minimum_os_version, and
                # supported_architecture are all OK
                munkicommon.display_debug1(
                    'Found %s, version %s in catalog %s',
                    item['name'], item['version'], catalogname)
                return item

    # if we got this far, we didn't find it.
    munkicommon.display_debug1('Not found')
    if rejected_items:
        for reason in rejected_items:
            munkicommon.display_warning(reason)

    return None


def enoughDiskSpace(manifestitem_pl, installlist=None,
                    uninstalling=False, warn=True):
    """Determine if there is enough disk space to
    download the manifestitem."""
    # fudgefactor is set to 100MB
    fudgefactor = 102400
    installeritemsize = 0
    installedsize = 0
    alreadydownloadedsize = 0
    if 'installer_item_location' in manifestitem_pl:
        cachedir = os.path.join(munkicommon.pref('ManagedInstallDir'), 'Cache')
        download = getDownloadCachePath(
            cachedir,
            manifestitem_pl['installer_item_location'])
        if os.path.exists(download):
            alreadydownloadedsize = os.path.getsize(download)
    if 'installer_item_size' in manifestitem_pl:
        installeritemsize = int(manifestitem_pl['installer_item_size'])
    if 'installed_size' in manifestitem_pl:
        installedsize = int(manifestitem_pl['installed_size'])
    else:
        # fudge this value
        installedsize = installeritemsize
    if uninstalling:
        installedsize = 0
        if 'uninstaller_item_size' in manifestitem_pl:
            installeritemsize = int(manifestitem_pl['uninstaller_item_size'])
    diskspaceneeded = (installeritemsize - alreadydownloadedsize +
                       installedsize + fudgefactor)

    # munkicommon.getAvailableDiskSpace() returns KB
    availablediskspace = munkicommon.getAvailableDiskSpace()
    if installlist:
        for item in installlist:
            # subtract space needed for other items that are to be installed
            if item.get('installer_item'):
                availablediskspace = availablediskspace - \
                                     int(item.get('installed_size', 0))

    if availablediskspace > diskspaceneeded:
        return True
    elif warn:
        if uninstalling:
            munkicommon.display_warning('There is insufficient disk space to '
                                        'download the uninstaller for %s.',
                                        manifestitem_pl.get('name'))
        else:
            munkicommon.display_warning('There is insufficient disk space to '
                                        'download and install %s.',
                                        manifestitem_pl.get('name'))
        munkicommon.display_warning(
            '    %sMB needed; %sMB available',
            diskspaceneeded/1024, availablediskspace/1024)
    return False


def installedState(item_pl):
    """Checks to see if the item described by item_pl (or a newer version) is
    currently installed

    All tests must pass to be considered installed.
    Returns 1 if it looks like this version is installed
    Returns 2 if it looks like a newer version is installed.
    Returns 0 otherwise.
    """
    foundnewer = False

    if item_pl.get('OnDemand'):
        # always install these items -- retcode 0 means install is needed
        munkicommon.display_debug1('This is an OnDemand item. Must install.')
        return 0

    if item_pl.get('installcheck_script'):
        retcode = munkicommon.runEmbeddedScript(
            'installcheck_script', item_pl, suppress_error=True)
        munkicommon.display_debug1('installcheck_script returned %s', retcode)
        # retcode 0 means install is needed
        if retcode == 0:
            return 0
        # non-zero could be an error or successfully indicating
        # that an install is not needed. We hope it's the latter.
        # return 1 so we're marked as not needing to be installed
        return 1

    if item_pl.get('softwareupdatename'):
        availableAppleUpdates = appleupdates.softwareUpdateList()
        munkicommon.display_debug2(
            'Available Apple updates:\n%s', availableAppleUpdates)
        if item_pl['softwareupdatename'] in availableAppleUpdates:
            munkicommon.display_debug1(
                '%s is in available Apple Software Updates',
                item_pl['softwareupdatename'])
            # return 0 so we're marked as needing to be installed
            return 0
        else:
            munkicommon.display_debug1(
                '%s is not in available Apple Software Updates',
                item_pl['softwareupdatename'])
            # return 1 so we're marked as not needing to be installed
            return 1

    if item_pl.get('installer_type') == 'profile':
        identifier = item_pl.get('PayloadIdentifier')
        hash_value = item_pl.get('installer_item_hash')
        if profiles.profile_needs_to_be_installed(identifier, hash_value):
            return 0
        else:
            return 1

     # does 'installs' exist and is it non-empty?
    if item_pl.get('installs', None):
        installitems = item_pl['installs']
        for item in installitems:
            try:
                comparison = compareItemVersion(item)
                if comparison in (-1, 0):
                    return 0
                elif comparison == 2:
                    # this item is newer
                    foundnewer = True
            except munkicommon.Error, errmsg:
                # some problem with the installs data
                munkicommon.display_error(unicode(errmsg))
                # return 1 so we're marked as not needing to be installed
                return 1

    # if there is no 'installs' key, then we'll use receipt info
    # to determine install status.
    elif 'receipts' in item_pl:
        receipts = item_pl['receipts']
        for item in receipts:
            try:
                comparison = compareReceiptVersion(item)
                if comparison in (-1, 0):
                    # not there or older
                    return 0
                elif comparison == 2:
                    foundnewer = True
            except munkicommon.Error, errmsg:
                # some problem with the receipts data
                munkicommon.display_error(unicode(errmsg))
                # return 1 so we're marked as not needing to be installed
                return 1

    # if we got this far, we passed all the tests, so the item
    # must be installed (or we don't have enough info...)
    if foundnewer:
        return 2
    else:
        return 1


def someVersionInstalled(item_pl):
    """Checks to see if some version of an item is installed.

    Args:
      item_pl: item plist for the item to check for version of.

    Returns a boolean.
    """
    if item_pl.get('OnDemand'):
        # These should never be counted as installed
        munkicommon.display_debug1('This is an OnDemand item.')
        return False

    if item_pl.get('installcheck_script'):
        retcode = munkicommon.runEmbeddedScript(
            'installcheck_script', item_pl, suppress_error=True)
        munkicommon.display_debug1(
            'installcheck_script returned %s', retcode)
        # retcode 0 means install is needed
        # (ie, item is not installed)
        if retcode == 0:
            return False
        # non-zero could be an error or successfully indicating
        # that an install is not needed. We hope it's the latter.
        return True

    if item_pl.get('installer_type') == 'profile':
        identifier = item_pl.get('PayloadIdentifier')
        if profiles.profile_is_installed(identifier):
            return True
        else:
            return False

    # does 'installs' exist and is it non-empty?
    if item_pl.get('installs'):
        installitems = item_pl['installs']
        # check each item for existence
        for item in installitems:
            try:
                if compareItemVersion(item) == 0:
                    # not there
                    return False
            except munkicommon.Error, errmsg:
                # some problem with the installs data
                munkicommon.display_error(unicode(errmsg))
                return False

    # if there is no 'installs' key, then we'll use receipt info
    # to determine install status.
    elif 'receipts' in item_pl:
        receipts = item_pl['receipts']
        for item in receipts:
            try:
                if compareReceiptVersion(item) == 0:
                    # not there
                    return False
            except munkicommon.Error, errmsg:
                # some problem with the installs data
                munkicommon.display_error(unicode(errmsg))
                return False

    # if we got this far, we passed all the tests, so the item
    # must be installed (or we don't have enough info...)
    return True


def evidenceThisIsInstalled(item_pl):
    """Checks to see if there is evidence that the item described by item_pl
    (any version) is currently installed.

    If any tests pass, the item might be installed.
    This is used when determining if we can remove the item, thus
    the attention given to the uninstall method.

    Returns a boolean.
    """
    if item_pl.get('OnDemand'):
        # These should never be counted as installed
        munkicommon.display_debug1('This is an OnDemand item.')
        return False

    if item_pl.get('uninstallcheck_script'):
        retcode = munkicommon.runEmbeddedScript(
            'uninstallcheck_script', item_pl, suppress_error=True)
        munkicommon.display_debug1(
            'uninstallcheck_script returned %s', retcode)
        # retcode 0 means uninstall is needed
        # (ie, item is installed)
        if retcode == 0:
            return True
        # non-zero could be an error or successfully indicating
        # that an uninstall is not needed
        return False

    if item_pl.get('installcheck_script'):
        retcode = munkicommon.runEmbeddedScript(
            'installcheck_script', item_pl, suppress_error=True)
        munkicommon.display_debug1(
            'installcheck_script returned %s', retcode)
        # retcode 0 means install is needed
        # (ie, item is not installed)
        if retcode == 0:
            return False
        # non-zero could be an error or successfully indicating
        # that an install is not needed
        return True

    if item_pl.get('installer_type') == 'profile':
        identifier = item_pl.get('PayloadIdentifier')
        if profiles.profile_is_installed(identifier):
            return True
        else:
            return False

    foundallinstallitems = False
    if ('installs' in item_pl and
            item_pl.get('uninstall_method') != 'removepackages'):
        munkicommon.display_debug2("Checking 'installs' items...")
        installitems = item_pl['installs']
        foundallinstallitems = True
        for item in installitems:
            if 'path' in item:
                # we can only check by path; if the item has been moved
                # we're not clever enough to find it, and our removal
                # methods are currently even less clever
                if not os.path.exists(item['path']):
                    # this item isn't on disk
                    munkicommon.display_debug2(
                        '%s not found on disk.', item['path'])
                    foundallinstallitems = False
        if (foundallinstallitems and
                item_pl.get('uninstall_method') != 'removepackages'):
            return True
    if item_pl.get('receipts'):
        munkicommon.display_debug2("Checking receipts...")
        if PKGDATA == {}:
            # build our database of installed packages
            analyzeInstalledPkgs()
        if item_pl['name'] in PKGDATA['installed_names']:
            return True
        else:
            munkicommon.display_debug2("Installed receipts don't match.")

    # if we got this far, we failed all the tests, so the item
    # must not be installed (or we dont't have the right info...)
    return False


def getAutoRemovalItems(installinfo, cataloglist):
    """Gets a list of items marked for automatic removal from the catalogs
    in cataloglist. Filters those against items in the processed_installs
    list, which should contain everything that is supposed to be installed.
    Then filters against the removals list, which contains all the removals
    that have already been processed.
    """
    autoremovalnames = []
    for catalogname in cataloglist or []:
        if catalogname in CATALOG.keys():
            autoremovalnames += CATALOG[catalogname]['autoremoveitems']

    processed_installs_names = [nameAndVersion(item)[0]
                                for item in installinfo['processed_installs']]
    autoremovalnames = [item for item in autoremovalnames
                        if item not in processed_installs_names
                        and item not in installinfo['processed_uninstalls']]
    return autoremovalnames


def lookForUpdates(itemname, cataloglist):
    """Looks for updates for a given manifest item that is either
    installed or scheduled to be installed or removed. This handles not only
    specific application updates, but also updates that aren't simply
    later versions of the manifest item.
    For example, AdobeCameraRaw is an update for Adobe Photoshop, but
    doesn't update the version of Adobe Photoshop.
    Returns a list of manifestitem names that are updates for
    manifestitem.
    """

    munkicommon.display_debug1('Looking for updates for: %s', itemname)
    # get a list of catalog items that are updates for other items
    update_list = []
    for catalogname in cataloglist:
        if not catalogname in CATALOG.keys():
            # in case the list refers to a non-existent catalog
            continue

        updaters = CATALOG[catalogname]['updaters']
        # list comprehension coming up...
        update_items = [catalogitem['name']
                        for catalogitem in updaters
                        if itemname in catalogitem.get('update_for', [])]
        if update_items:
            update_list.extend(update_items)

    # make sure the list has only unique items:
    update_list = list(set(update_list))

    if update_list:
        # updates were found, so let's display them
        num_updates = len(update_list)
        # format the update list for better on-screen viewing
        update_list_display = ", ".join(str(x) for x in update_list)
        munkicommon.display_debug1(
            'Found %s update(s): %s', num_updates, update_list_display)

    return update_list


def lookForUpdatesForVersion(itemname, itemversion, cataloglist):
    """Looks for updates for a specific version of an item. Since these
    can appear in manifests and pkginfo as item-version or item--version
    we have to search twice."""

    name_and_version = '%s-%s' % (itemname, itemversion)
    alt_name_and_version = '%s--%s' % (itemname, itemversion)
    update_list = lookForUpdates(name_and_version, cataloglist)
    update_list.extend(lookForUpdates(alt_name_and_version, cataloglist))

    # make sure the list has only unique items:
    update_list = list(set(update_list))

    return update_list


def isAppleItem(item_pl):
    """Returns True if the item to be installed or removed appears to be from
    Apple. If we are installing or removing any Apple items in a check/install
    cycle, we skip checking/installing Apple updates from an Apple Software
    Update server so we don't stomp on each other"""
    # check receipts
    for receipt in item_pl.get('receipts', []):
        if receipt.get('packageid', '').startswith('com.apple.'):
            return True
    # check installs items
    for install_item in item_pl.get('installs', []):
        if install_item.get('CFBundleIdentifier', '').startswith('com.apple.'):
            return True
    # if we get here, no receipts or installs items have Apple
    # identifiers
    return False


def processManagedUpdate(manifestitem, cataloglist, installinfo):
    """Process a managed_updates item to see if it is installed, and if so,
    if it needs an update.
    """
    manifestitemname = os.path.split(manifestitem)[1]
    munkicommon.display_debug1(
        '* Processing manifest item %s for update', manifestitemname)

    # check to see if item is already in the update list:
    if manifestitemname in installinfo['managed_updates']:
        munkicommon.display_debug1(
            '%s has already been processed for update.', manifestitemname)
        return
    # check to see if item is already in the installlist:
    if manifestitemname in installinfo['processed_installs']:
        munkicommon.display_debug1(
            '%s has already been processed for install.', manifestitemname)
        return
    # check to see if item is already in the removallist:
    if manifestitemname in installinfo['processed_uninstalls']:
        munkicommon.display_debug1(
            '%s has already been processed for uninstall.', manifestitemname)
        return

    item_pl = getItemDetail(manifestitem, cataloglist)
    if not item_pl:
        munkicommon.display_warning(
            'Could not process item %s for update. '
            'No pkginfo found in catalogs: %s ',
            manifestitem, ', '.join(cataloglist))
        return

    # we only offer to update if some version of the item is already
    # installed, so let's check
    if someVersionInstalled(item_pl):
        # add to the list of processed managed_updates
        installinfo['managed_updates'].append(manifestitemname)
        dummy_result = processInstall(manifestitem, cataloglist, installinfo,
                                      is_managed_update=True)
    else:
        munkicommon.display_debug1(
            '%s does not appear to be installed, so no managed updates...',
            manifestitemname)


def processOptionalInstall(manifestitem, cataloglist, installinfo):
    """Process an optional install item to see if it should be added to
    the list of optional installs.
    """
    manifestitemname = os.path.split(manifestitem)[1]
    munkicommon.display_debug1(
        "* Processing manifest item %s for optional install" %
        manifestitemname)

    # have we already processed this?
    if manifestitemname in installinfo['optional_installs']:
        munkicommon.display_debug1(
            '%s has already been processed for optional install.',
            manifestitemname)
        return
    elif manifestitemname in installinfo['processed_installs']:
        munkicommon.display_debug1(
            '%s has already been processed for install.', manifestitemname)
        return
    elif manifestitemname in installinfo['processed_uninstalls']:
        munkicommon.display_debug1(
            '%s has already been processed for uninstall.', manifestitemname)
        return

    # check to see if item (any version) is already in the
    # optional_install list:
    for item in installinfo['optional_installs']:
        if manifestitemname == item['name']:
            munkicommon.display_debug1(
                '%s has already been processed for optional install.',
                manifestitemname)
            return

    item_pl = getItemDetail(manifestitem, cataloglist)
    if not item_pl:
        munkicommon.display_warning(
            'Could not process item %s for optional install. '
            'No pkginfo found in catalogs: %s ',
            manifestitem, ', '.join(cataloglist))
        return

    # if we get to this point we can add this item
    # to the list of optional installs
    iteminfo = {}
    iteminfo['name'] = item_pl.get('name', manifestitemname)
    iteminfo['description'] = item_pl.get('description', '')
    iteminfo['version_to_install'] = item_pl.get('version', 'UNKNOWN')
    iteminfo['display_name'] = item_pl.get('display_name', '')
    for key in ['category', 'developer', 'icon_name', 'icon_hash',
                'requires', 'RestartAction']:
        if key in item_pl:
            iteminfo[key] = item_pl[key]
    iteminfo['installed'] = someVersionInstalled(item_pl)
    if iteminfo['installed']:
        iteminfo['needs_update'] = (installedState(item_pl) == 0)
    iteminfo['licensed_seat_info_available'] = item_pl.get(
        'licensed_seat_info_available', False)
    iteminfo['uninstallable'] = (
        item_pl.get('uninstallable', False)
        and (item_pl.get('uninstall_method', '') != ''))
    iteminfo['installer_item_size'] = \
        item_pl.get('installer_item_size', 0)
    iteminfo['installed_size'] = item_pl.get(
        'installer_item_size', iteminfo['installer_item_size'])
    if (not iteminfo['installed']) or (iteminfo.get('needs_update')):
        if not enoughDiskSpace(item_pl,
                               installinfo.get('managed_installs', []),
                               warn=False):
            iteminfo['note'] = (
                'Insufficient disk space to download and install.')
    optional_keys = ['preinstall_alert',
                     'preuninstall_alert',
                     'preupgrade_alert',
                     'OnDemand']
    for key in optional_keys:
        if key in item_pl:
            iteminfo[key] = item_pl[key]

    munkicommon.display_debug1(
        'Adding %s to the optional install list', iteminfo['name'])
    installinfo['optional_installs'].append(iteminfo)


def updateAvailableLicenseSeats(installinfo):
    '''Records # of available seats for each optional install'''
    license_info_url = munkicommon.pref('LicenseInfoURL')
    if not license_info_url:
        # nothing to do!
        return
    if not installinfo.get('optional_installs'):
        # nothing to do!
        return

    license_info = {}
    items_to_check = [item['name']
                      for item in installinfo['optional_installs']
                      if item.get('licensed_seat_info_available')
                      and not item['installed']]

    # complicated logic here to 'batch' process our GET requests but
    # keep them under 256 characters each
    start_index = 0
    # Use ampersand when the license_info_url contains a ?
    q_char = "?"
    if "?" in license_info_url:
        q_char = "&"
    while start_index < len(items_to_check):
        end_index = len(items_to_check)
        while True:
            query_items = ['name=' + quote_plus(item)
                           for item in items_to_check[start_index:end_index]]
            querystring = q_char + '&'.join(query_items)
            url = license_info_url + querystring
            if len(url) < 256:
                break
            # drop an item and see if we're under 256 characters
            end_index = end_index - 1

        munkicommon.display_debug1('Fetching licensed seat data from %s', url)
        try:
            license_data = getDataFromURL(url)
            munkicommon.display_debug1('Got: %s', license_data)
            license_dict = FoundationPlist.readPlistFromString(
                license_data)
        except (fetch.MunkiDownloadError, fetch.GurlDownloadError), err:
            # problem fetching from URL
            munkicommon.display_error('Error from %s: %s', url, err)
        except FoundationPlist.FoundationPlistException:
            # no data or bad data from URL
            munkicommon.display_error(
                'Bad license data from %s: %s', url, license_data)
        else:
            # merge data from license_dict into license_info
            license_info.update(license_dict)
        start_index = end_index

    # use license_info to update our remaining seats
    for item in installinfo['optional_installs']:
        if item['name'] in items_to_check:
            munkicommon.display_debug2(
                'Looking for license info for %s', item['name'])
            # record available seats for this item
            seats_available = False
            seat_info = license_info.get(item['name'], 0)
            try:
                seats_available = int(seat_info) > 0
                munkicommon.display_debug1(
                    'Recording available seats for %s: %s',
                    item['name'], seats_available)
            except ValueError:
                munkicommon.display_warning(
                    'Bad license data for %s: %s', item['name'], seat_info)

            item['licensed_seats_available'] = seats_available


def processInstall(manifestitem, cataloglist, installinfo,
                   is_managed_update=False):
    """Processes a manifest item for install. Determines if it needs to be
    installed, and if so, if any items it is dependent on need to
    be installed first.  Installation detail is added to
    installinfo['managed_installs']
    Calls itself recursively as it processes dependencies.
    Returns a boolean; when processing dependencies, a false return
    will stop the installation of a dependent item
    """

    if munkicommon.munkistatusoutput:
        # reset progress indicator and detail field
        munkistatus.percent('-1')
        munkistatus.detail('')

    manifestitemname = os.path.split(manifestitem)[1]
    munkicommon.display_debug1(
        '* Processing manifest item %s for install', manifestitemname)
    (manifestitemname_withoutversion, includedversion) = nameAndVersion(
        manifestitemname)
    # have we processed this already?
    if manifestitemname in installinfo['processed_installs']:
        munkicommon.display_debug1(
            '%s has already been processed for install.', manifestitemname)
        return True
    elif (manifestitemname_withoutversion in
          installinfo['processed_uninstalls']):
        munkicommon.display_warning(
            'Will not process %s for install because it has already '
            'been processed for uninstall!', manifestitemname)
        return False

    item_pl = getItemDetail(manifestitem, cataloglist)
    if not item_pl:
        munkicommon.display_warning(
            'Could not process item %s for install. '
            'No pkginfo found in catalogs: %s ',
            manifestitem, ', '.join(cataloglist))
        return False
    elif is_managed_update:
        # we're processing this as a managed update, so don't
        # add it to the processed_installs list
        pass
    else:
        # we found it, so add it to our list of procssed installs
        # so we don't process it again in the future
        munkicommon.display_debug2('Adding %s to list of processed installs'
                                   % manifestitemname)
        installinfo['processed_installs'].append(manifestitemname)

    if isItemInInstallInfo(item_pl, installinfo['managed_installs'],
                           vers=item_pl.get('version')):
        # has this item already been added to the list of things to install?
        munkicommon.display_debug1(
            '%s is or will be installed.', manifestitemname)
        return True

    # check dependencies
    dependenciesMet = True

    # there are two kinds of dependencies/relationships.
    #
    # 'requires' are prerequistes:
    #  package A requires package B be installed first.
    #  if package A is removed, package B is unaffected.
    #  requires can be a one to many relationship.
    #
    #  The second type of relationship is 'update_for'.
    #  This signifies that that current package should be considered an update
    #  for the packages listed in the 'update_for' array. When processing a
    #  package, we look through the catalogs for other packages that declare
    #  they are updates for the current package and install them if needed.
    #  This can be a one-to-many relationship - one package can be an update
    #  for several other packages; for example, 'PhotoshopCS4update-11.0.1'
    #  could be an update for PhotoshopCS4 and for AdobeCS4DesignSuite.
    #
    #  When removing an item, any updates for that item are removed as well.

    if 'requires' in item_pl:
        dependencies = item_pl['requires']
        # fix things if 'requires' was specified as a string
        # instead of an array of strings
        if isinstance(dependencies, basestring):
            dependencies = [dependencies]
        for item in dependencies:
            munkicommon.display_detail(
                '%s-%s requires %s. Getting info on %s...'
                % (item_pl.get('name', manifestitemname),
                   item_pl.get('version', ''), item, item))
            success = processInstall(item, cataloglist, installinfo,
                                     is_managed_update=is_managed_update)
            if not success:
                dependenciesMet = False

    iteminfo = {}
    iteminfo['name'] = item_pl.get('name', '')
    iteminfo['display_name'] = item_pl.get('display_name', iteminfo['name'])
    iteminfo['description'] = item_pl.get('description', '')

    if not dependenciesMet:
        munkicommon.display_warning('Didn\'t attempt to install %s '
                                    'because could not resolve all '
                                    'dependencies.', manifestitemname)
        # add information to managed_installs so we have some feedback
        # to display in MSC.app
        iteminfo['installed'] = False
        iteminfo['note'] = ('Can\'t install %s because could not resolve all '
                            'dependencies.' % iteminfo['display_name'])
        installinfo['managed_installs'].append(iteminfo)
        return False

    installed_state = installedState(item_pl)
    if installed_state == 0:
        munkicommon.display_detail('Need to install %s', manifestitemname)
        iteminfo['installer_item_size'] = item_pl.get(
            'installer_item_size', 0)
        iteminfo['installed_size'] = item_pl.get(
            'installed_size', iteminfo['installer_item_size'])
        try:
            # Get a timestamp, then download the installer item.
            start = datetime.datetime.now()
            if item_pl.get('installer_type', 0) == 'nopkg':
                # Packageless install
                download_speed = 0
                filename = 'packageless_install'
            else:
                if download_installeritem(item_pl, installinfo):
                    # Record the download speed to the InstallResults output.
                    end = datetime.datetime.now()
                    download_seconds = (end - start).seconds
                    try:
                        if iteminfo['installer_item_size'] < 1024:
                            # ignore downloads under 1 MB or speeds will
                            # be skewed.
                            download_speed = 0
                        else:
                            # installer_item_size is KBytes, so divide
                            # by seconds.
                            download_speed = int(
                                iteminfo['installer_item_size'] /
                                download_seconds)
                    except (TypeError, ValueError, ZeroDivisionError):
                        download_speed = 0
                else:
                    # Item was already in cache; set download_speed to 0.
                    download_speed = 0

                filename = getInstallerItemBasename(
                    item_pl['installer_item_location'])

            iteminfo['download_kbytes_per_sec'] = download_speed
            if download_speed:
                munkicommon.display_detail(
                    '%s downloaded at %d KB/s', filename, download_speed)

            # required keys
            iteminfo['installer_item'] = filename
            iteminfo['installed'] = False
            iteminfo['version_to_install'] = item_pl.get('version', 'UNKNOWN')

            # we will ignore the unattended_install key if the item needs a
            # restart or logout...
            if (item_pl.get('unattended_install') or
                    item_pl.get('forced_install')):
                if item_pl.get('RestartAction', 'None') != 'None':
                    munkicommon.display_warning(
                        'Ignoring unattended_install key for %s '
                        'because RestartAction is %s.',
                        item_pl['name'], item_pl.get('RestartAction'))
                else:
                    iteminfo['unattended_install'] = True

            # optional keys
            optional_keys = ['suppress_bundle_relocation',
                             'installer_choices_xml',
                             'installer_environment',
                             'adobe_install_info',
                             'RestartAction',
                             'installer_type',
                             'adobe_package_name',
                             'package_path',
                             'blocking_applications',
                             'installs',
                             'requires',
                             'update_for',
                             'payloads',
                             'preinstall_script',
                             'postinstall_script',
                             'items_to_copy',  # used w/ copy_from_dmg
                             'copy_local',     # used w/ AdobeCS5 Updaters
                             'force_install_after_date',
                             'apple_item',
                             'category',
                             'developer',
                             'icon_name',
                             'PayloadIdentifier',
                             'icon_hash',
                             'OnDemand']

            for key in optional_keys:
                if key in item_pl:
                    iteminfo[key] = item_pl[key]

            if not 'apple_item' in iteminfo:
                # admin did not explicitly mark this item; let's determine if
                # it's from Apple
                if isAppleItem(item_pl):
                    munkicommon.log(
                        'Marking %s as apple_item - this will block '
                        'Apple SUS updates' % iteminfo['name'])
                    iteminfo['apple_item'] = True

            installinfo['managed_installs'].append(iteminfo)

            update_list = []
            # (manifestitemname_withoutversion, includedversion) =
            # nameAndVersion(manifestitemname)
            if includedversion:
                # a specific version was specified in the manifest
                # so look only for updates for this specific version
                update_list = lookForUpdatesForVersion(
                    manifestitemname_withoutversion,
                    includedversion, cataloglist)
            else:
                # didn't specify a specific version, so
                # now look for all updates for this item
                update_list = lookForUpdates(manifestitemname_withoutversion,
                                             cataloglist)
                # now append any updates specifically
                # for the version to be installed
                update_list.extend(
                    lookForUpdatesForVersion(
                        manifestitemname_withoutversion,
                        iteminfo['version_to_install'],
                        cataloglist))

            for update_item in update_list:
                # call processInstall recursively so we get the
                # latest version and dependencies
                dummy_result = processInstall(
                    update_item, cataloglist, installinfo,
                    is_managed_update=is_managed_update)
            return True
        except fetch.PackageVerificationError:
            munkicommon.display_warning(
                'Can\'t install %s because the integrity check failed.',
                manifestitem)
            iteminfo['installed'] = False
            iteminfo['note'] = 'Integrity check failed'
            installinfo['managed_installs'].append(iteminfo)
            if manifestitemname in installinfo['processed_installs']:
                installinfo['processed_installs'].remove(manifestitemname)
            return False
        except fetch.GurlDownloadError, errmsg:
            munkicommon.display_warning(
                'Download of %s failed: %s', manifestitem, errmsg)
            iteminfo['installed'] = False
            iteminfo['note'] = 'Download failed (%s)' % errmsg
            installinfo['managed_installs'].append(iteminfo)
            if manifestitemname in installinfo['processed_installs']:
                installinfo['processed_installs'].remove(manifestitemname)
            return False
        except fetch.MunkiDownloadError, errmsg:
            munkicommon.display_warning(
                'Can\'t install %s because: %s', manifestitemname, errmsg)
            iteminfo['installed'] = False
            iteminfo['note'] = '%s' % errmsg
            installinfo['managed_installs'].append(iteminfo)
            if manifestitemname in installinfo['processed_installs']:
                installinfo['processed_installs'].remove(manifestitemname)
            return False
    else:
        iteminfo['installed'] = True
        # record installed size for reporting
        iteminfo['installed_size'] = item_pl.get(
            'installed_size', item_pl.get('installer_item_size', 0))
        if installed_state == 1:
            # just use the version from the pkginfo
            iteminfo['installed_version'] = item_pl['version']
        else:
            # might be newer; attempt to figure out the version
            installed_version = getInstalledVersion(item_pl)
            if installed_version == "UNKNOWN":
                installed_version = '(newer than %s)' % item_pl['version']
            iteminfo['installed_version'] = installed_version
        installinfo['managed_installs'].append(iteminfo)
        # remove included version number if any
        (name, includedversion) = nameAndVersion(manifestitemname)
        munkicommon.display_detail('%s version %s (or newer) is already '
                                   'installed.', name, item_pl['version'])
        update_list = []
        if not includedversion:
            # no specific version is specified;
            # the item is already installed;
            # now look for updates for this item
            update_list = lookForUpdates(name, cataloglist)
            # and also any for this specific version
            installed_version = iteminfo['installed_version']
            if not installed_version.startswith('(newer than '):
                update_list.extend(
                    lookForUpdatesForVersion(
                        name, installed_version, cataloglist))
        elif compareVersions(
                includedversion, iteminfo['installed_version']) == 1:
            # manifest specifies a specific version
            # if that's what's installed, look for any updates
            # specific to this version
            update_list = lookForUpdatesForVersion(
                manifestitemname_withoutversion, includedversion, cataloglist)
        # if we have any updates, process them
        for update_item in update_list:
            # call processInstall recursively so we get updates
            # and any dependencies
            dummy_result = processInstall(
                update_item, cataloglist, installinfo,
                is_managed_update=is_managed_update)

        return True


INFO_OBJECT = {}
def makePredicateInfoObject():
    '''Builds our info object used for predicate comparisons'''
    if INFO_OBJECT:
        return
    for key in MACHINE.keys():
        INFO_OBJECT[key] = MACHINE[key]
    # use our start time for "current" date (if we have it)
    # and add the timezone offset to it so we can compare
    # UTC dates as though they were local dates.
    INFO_OBJECT['date'] = addTimeZoneOffsetToDate(
        NSDate.dateWithString_(
            munkicommon.report.get('StartTime', munkicommon.format_time())))
    os_vers = MACHINE['os_vers']
    os_vers = os_vers + '.0.0'
    INFO_OBJECT['os_vers_major'] = int(os_vers.split('.')[0])
    INFO_OBJECT['os_vers_minor'] = int(os_vers.split('.')[1])
    INFO_OBJECT['os_vers_patch'] = int(os_vers.split('.')[2])
    if 'Book' in MACHINE.get('machine_model', ''):
        INFO_OBJECT['machine_type'] = 'laptop'
    else:
        INFO_OBJECT['machine_type'] = 'desktop'
    for key in CONDITIONS.keys():
        INFO_OBJECT[key] = CONDITIONS[key]


def predicateEvaluatesAsTrue(predicate_string):
    '''Evaluates predicate against our info object'''
    munkicommon.display_debug1('Evaluating predicate: %s', predicate_string)
    try:
        p = NSPredicate.predicateWithFormat_(predicate_string)
    except BaseException, err:
        munkicommon.display_warning('%s', err)
        # can't parse predicate, so return False
        return False

    result = p.evaluateWithObject_(INFO_OBJECT)
    munkicommon.display_debug1('Predicate %s is %s', predicate_string, result)
    return result


def processManifestForKey(manifest, manifest_key, installinfo,
                          parentcatalogs=None):
    """Processes keys in manifests to build the lists of items to install and
    remove.

    Can be recursive if manifests include other manifests.
    Probably doesn't handle circular manifest references well.

    manifest can be a path to a manifest file or a dictionary object.
    """
    if isinstance(manifest, basestring):
        munkicommon.display_debug1(
            "** Processing manifest %s for %s" %
            (os.path.basename(manifest), manifest_key))
        manifestdata = getManifestData(manifest)
    else:
        manifestdata = manifest
        manifest = 'embedded manifest'

    cataloglist = manifestdata.get('catalogs')
    if cataloglist:
        getCatalogs(cataloglist)
    elif parentcatalogs:
        cataloglist = parentcatalogs

    if not cataloglist:
        munkicommon.display_warning('Manifest %s has no catalogs', manifest)
        return

    nestedmanifests = manifestdata.get('included_manifests')
    if nestedmanifests:
        for item in nestedmanifests:
            try:
                nestedmanifestpath = getmanifest(item)
            except ManifestException:
                nestedmanifestpath = None
            if munkicommon.stopRequested():
                return {}
            if nestedmanifestpath:
                processManifestForKey(nestedmanifestpath, manifest_key,
                                      installinfo, cataloglist)

    conditionalitems = manifestdata.get('conditional_items')
    if conditionalitems:
        munkicommon.display_debug1(
            '** Processing conditional_items in %s', manifest)
        # conditionalitems should be an array of dicts
        # each dict has a predicate; the rest consists of the
        # same keys as a manifest
        for item in conditionalitems:
            try:
                predicate = item['condition']
            except (AttributeError, KeyError):
                munkicommon.display_warning(
                    'Missing predicate for conditional_item %s', item)
                continue
            except BaseException:
                munkicommon.display_warning(
                    'Conditional item is malformed: %s', item)
                continue
            INFO_OBJECT['catalogs'] = cataloglist
            if predicateEvaluatesAsTrue(predicate):
                conditionalmanifest = item
                processManifestForKey(conditionalmanifest, manifest_key,
                                      installinfo, cataloglist)

    items = manifestdata.get(manifest_key)
    if items:
        for item in items:
            if munkicommon.stopRequested():
                return {}
            if manifest_key == 'managed_installs':
                dummy_result = processInstall(
                    item, cataloglist, installinfo)
            elif manifest_key == 'managed_updates':
                processManagedUpdate(item, cataloglist, installinfo)
            elif manifest_key == 'optional_installs':
                processOptionalInstall(item, cataloglist, installinfo)
            elif manifest_key == 'managed_uninstalls':
                dummy_result = processRemoval(
                    item, cataloglist, installinfo)


def getReceiptsToRemove(item):
    """Returns a list of receipts to remove for item"""
    name = item['name']
    if name in PKGDATA['receipts_for_name']:
        return PKGDATA['receipts_for_name'][name]
    return []


def processRemoval(manifestitem, cataloglist, installinfo):
    """Processes a manifest item; attempts to determine if it
    needs to be removed, and if it can be removed.

    Unlike installs, removals aren't really version-specific -
    If we can figure out how to remove the currently installed
    version, we do, unless the admin specifies a specific version
    number in the manifest. In that case, we only attempt a
    removal if the version installed matches the specific version
    in the manifest.

    Any items dependent on the given item need to be removed first.
    Items to be removed are added to installinfo['removals'].

    Calls itself recursively as it processes dependencies.
    Returns a boolean; when processing dependencies, a false return
    will stop the removal of a dependent item.
    """
    manifestitemname_withversion = os.path.split(manifestitem)[1]
    munkicommon.display_debug1(
        '* Processing manifest item %s for removal' %
        manifestitemname_withversion)

    (manifestitemname, includedversion) = nameAndVersion(
        manifestitemname_withversion)

    # have we processed this already?
    if manifestitemname in [nameAndVersion(item)[0]
                            for item in installinfo['processed_installs']]:
        munkicommon.display_warning('Will not attempt to remove %s '
                                    'because some version of it is in '
                                    'the list of managed installs, or '
                                    'it is required by another managed '
                                    'install.', manifestitemname)
        return False
    elif manifestitemname in installinfo['processed_uninstalls']:
        munkicommon.display_debug1(
            '%s has already been processed for removal.', manifestitemname)
        return True
    else:
        installinfo['processed_uninstalls'].append(manifestitemname)

    infoitems = []
    if includedversion:
        # a specific version was specified
        item_pl = getItemDetail(manifestitemname, cataloglist, includedversion)
        if item_pl:
            infoitems.append(item_pl)
    else:
        # get all items matching the name provided
        infoitems = getAllItemsWithName(manifestitemname, cataloglist)

    if not infoitems:
        munkicommon.display_warning(
            'Could not process item %s for removal. '
            'No pkginfo found in catalogs: %s ',
            manifestitemname, ', '.join(cataloglist))
        return False

    installEvidence = False
    for item in infoitems:
        munkicommon.display_debug2('Considering item %s-%s for removal info',
                                   item['name'], item['version'])
        if evidenceThisIsInstalled(item):
            installEvidence = True
            break
        else:
            munkicommon.display_debug2(
                '%s-%s not installed.', item['name'], item['version'])

    if not installEvidence:
        munkicommon.display_detail(
            '%s doesn\'t appear to be installed.', manifestitemname_withversion)
        iteminfo = {}
        iteminfo['name'] = manifestitemname
        iteminfo['installed'] = False
        installinfo['removals'].append(iteminfo)
        return True

    # if we get here, installEvidence is true, and item
    # holds the item we found install evidence for, so we
    # should use that item to do the removal
    uninstall_item = None
    packagesToRemove = []
    # check for uninstall info
    # and grab the first uninstall method we find.
    if item.get('uninstallable') and 'uninstall_method' in item:
        uninstallmethod = item['uninstall_method']
        if uninstallmethod == 'removepackages':
            packagesToRemove = getReceiptsToRemove(item)
            if packagesToRemove:
                uninstall_item = item
        elif uninstallmethod.startswith('Adobe'):
            # Adobe CS3/CS4/CS5/CS6/CC product
            uninstall_item = item
        elif uninstallmethod in ['remove_copied_items',
                                 'remove_app',
                                 'uninstall_script',
                                 'remove_profile']:
            uninstall_item = item
        else:
            # uninstall_method is a local script.
            # Check to see if it exists and is executable
            if os.path.exists(uninstallmethod) and \
               os.access(uninstallmethod, os.X_OK):
                uninstall_item = item

    if not uninstall_item:
        # the uninstall info for the item couldn't be matched
        # to what's on disk
        munkicommon.display_warning('Could not find uninstall info for %s.',
                                    manifestitemname_withversion)
        return False

    # if we got this far, we have enough info to attempt an uninstall.
    # the pkginfo is in uninstall_item
    # Now check for dependent items
    #
    # First, look through catalogs for items that are required by this item;
    # if any are installed, we need to remove them as well
    #
    # still not sure how to handle references to specific versions --
    # if another package says it requires SomePackage--1.0.0.0.0
    # and we're supposed to remove SomePackage--1.0.1.0.0... what do we do?
    #
    dependentitemsremoved = True

    uninstall_item_name = uninstall_item.get('name')
    uninstall_item_name_with_version = (
        '%s-%s' % (uninstall_item.get('name'), uninstall_item.get('version')))
    alt_uninstall_item_name_with_version = (
        '%s--%s' % (uninstall_item.get('name'), uninstall_item.get('version')))
    processednames = []
    for catalogname in cataloglist:
        if not catalogname in CATALOG.keys():
            # in case the list refers to a non-existent catalog
            continue
        for item_pl in CATALOG[catalogname]['items']:
            name = item_pl.get('name')
            if name not in processednames:
                if 'requires' in item_pl:
                    if (uninstall_item_name in item_pl['requires'] or
                            uninstall_item_name_with_version
                            in item_pl['requires'] or
                            alt_uninstall_item_name_with_version
                            in item_pl['requires']):
                        munkicommon.display_debug1(
                            '%s requires %s, checking to see if it\'s '
                            'installed...', item_pl.get('name'),
                            manifestitemname)
                        if evidenceThisIsInstalled(item_pl):
                            munkicommon.display_detail(
                                '%s requires %s. %s must be removed as well.',
                                item_pl.get('name'), manifestitemname,
                                item_pl.get('name'))
                            success = processRemoval(
                                item_pl.get('name'), cataloglist, installinfo)
                            if not success:
                                dependentitemsremoved = False
                                break
                # record this name so we don't process it again
                processednames.append(name)

    if not dependentitemsremoved:
        munkicommon.display_warning('Will not attempt to remove %s because '
                                    'could not remove all items dependent '
                                    'on it.', manifestitemname_withversion)
        return False

    # Finally! We can record the removal information!
    iteminfo = {}
    iteminfo['name'] = uninstall_item.get('name', '')
    iteminfo['display_name'] = uninstall_item.get('display_name', '')
    iteminfo['description'] = 'Will be removed.'

    # we will ignore the unattended_uninstall key if the item needs a restart
    # or logout...
    if (uninstall_item.get('unattended_uninstall') or
            uninstall_item.get('forced_uninstall')):
        if uninstall_item.get('RestartAction', 'None') != 'None':
            munkicommon.display_warning(
                'Ignoring unattended_uninstall key for %s '
                'because RestartAction is %s.',
                uninstall_item['name'],
                uninstall_item.get('RestartAction'))
        else:
            iteminfo['unattended_uninstall'] = True

    # some keys we'll copy if they exist
    optionalKeys = ['blocking_applications',
                    'installs',
                    'requires',
                    'update_for',
                    'payloads',
                    'preuninstall_script',
                    'postuninstall_script',
                    'apple_item',
                    'category',
                    'developer',
                    'icon_name',
                    'PayloadIdentifier']
    for key in optionalKeys:
        if key in uninstall_item:
            iteminfo[key] = uninstall_item[key]

    if not 'apple_item' in iteminfo:
        # admin did not explicitly mark this item; let's determine if
        # it's from Apple
        if isAppleItem(item_pl):
            iteminfo['apple_item'] = True

    if packagesToRemove:
        # remove references for each package
        packagesToReallyRemove = []
        for pkg in packagesToRemove:
            munkicommon.display_debug1('Considering %s for removal...', pkg)
            # find pkg in PKGDATA['pkg_references'] and remove the reference
            # so we only remove packages if we're the last reference to it
            if pkg in PKGDATA['pkg_references']:
                munkicommon.display_debug1('%s references are: %s', pkg,
                                           PKGDATA['pkg_references'][pkg])
                if iteminfo['name'] in PKGDATA['pkg_references'][pkg]:
                    PKGDATA['pkg_references'][pkg].remove(iteminfo['name'])
                    if len(PKGDATA['pkg_references'][pkg]) == 0:
                        munkicommon.display_debug1(
                            'Adding %s to removal list.', pkg)
                        packagesToReallyRemove.append(pkg)
            else:
                # This shouldn't happen
                munkicommon.display_warning(
                    'pkg id %s missing from pkgdata', pkg)
        if packagesToReallyRemove:
            iteminfo['packages'] = packagesToReallyRemove
        else:
            # no packages that belong to this item only.
            munkicommon.display_warning('could not find unique packages to '
                                        'remove for %s', iteminfo['name'])
            return False

    iteminfo['uninstall_method'] = uninstallmethod
    if uninstallmethod.startswith('Adobe'):
        if (uninstallmethod == "AdobeCS5AAMEEPackage" and
                'adobe_install_info' in item):
            iteminfo['adobe_install_info'] = item['adobe_install_info']
        else:
            if 'uninstaller_item_location' in item:
                location = uninstall_item['uninstaller_item_location']
            else:
                location = uninstall_item['installer_item_location']
            try:
                download_installeritem(item, installinfo, uninstalling=True)
                filename = os.path.split(location)[1]
                iteminfo['uninstaller_item'] = filename
                iteminfo['adobe_package_name'] = uninstall_item.get(
                    'adobe_package_name', '')
            except fetch.PackageVerificationError:
                munkicommon.display_warning(
                    'Can\'t uninstall %s because the integrity check '
                    'failed.', iteminfo['name'])
                return False
            except fetch.MunkiDownloadError, errmsg:
                munkicommon.display_warning(
                    'Failed to download the uninstaller for %s because %s',
                    iteminfo['name'], errmsg)
                return False
    elif uninstallmethod == 'remove_copied_items':
        iteminfo['items_to_remove'] = item.get('items_to_copy', [])
    elif uninstallmethod == 'remove_app':
        if uninstall_item.get('installs', None):
            iteminfo['remove_app_info'] = uninstall_item['installs'][0]
    elif uninstallmethod == 'uninstall_script':
        iteminfo['uninstall_script'] = item.get('uninstall_script', '')

    # before we add this removal to the list,
    # check for installed updates and add them to the
    # removal list as well:
    update_list = lookForUpdates(uninstall_item_name, cataloglist)
    update_list.extend(
        lookForUpdates(uninstall_item_name_with_version, cataloglist))
    update_list.extend(
        lookForUpdates(alt_uninstall_item_name_with_version, cataloglist))
    for update_item in update_list:
        # call us recursively...
        dummy_result = processRemoval(update_item, cataloglist, installinfo)

    # finish recording info for this removal
    iteminfo['installed'] = True
    iteminfo['installed_version'] = uninstall_item.get('version')
    if 'RestartAction' in uninstall_item:
        iteminfo['RestartAction'] = uninstall_item['RestartAction']
    installinfo['removals'].append(iteminfo)
    munkicommon.display_detail(
        'Removal of %s added to ManagedInstaller tasks.',
        manifestitemname_withversion)
    return True


def getManifestData(manifestpath):
    '''Reads a manifest file, returns a dictionary-like object.'''
    plist = {}
    try:
        plist = FoundationPlist.readPlist(manifestpath)
    except FoundationPlist.NSPropertyListSerializationException:
        munkicommon.display_error('Could not read plist: %s', manifestpath)
        if os.path.exists(manifestpath):
            try:
                os.unlink(manifestpath)
            except OSError, err:
                munkicommon.display_error(
                    'Failed to delete plist: %s', unicode(err))
        else:
            munkicommon.display_error('plist does not exist.')
    return plist


def getManifestValueForKey(manifestpath, keyname):
    """Returns a value for keyname in manifestpath"""
    plist = getManifestData(manifestpath)
    try:
        return plist.get(keyname, None)
    except AttributeError, err:
        munkicommon.display_error(
            'Failed to get manifest value for key: %s (%s)',
            manifestpath, keyname)
        munkicommon.display_error(
            'Manifest is likely corrupt: %s', unicode(err))
        return None


# global to hold our catalog DBs
CATALOG = {}
def getCatalogs(cataloglist):
    """Retrieves the catalogs from the server and populates our catalogs
    dictionary.
    """
    #global CATALOG
    catalogbaseurl = munkicommon.pref('CatalogURL') or \
                     munkicommon.pref('SoftwareRepoURL') + '/catalogs/'
    if not catalogbaseurl.endswith('?') and not catalogbaseurl.endswith('/'):
        catalogbaseurl = catalogbaseurl + '/'
    munkicommon.display_debug2('Catalog base URL is: %s', catalogbaseurl)
    catalog_dir = os.path.join(munkicommon.pref('ManagedInstallDir'),
                               'catalogs')

    for catalogname in cataloglist:
        if not catalogname in CATALOG:
            catalogurl = catalogbaseurl + urllib2.quote(
                catalogname.encode('UTF-8'))
            catalogpath = os.path.join(catalog_dir, catalogname)
            munkicommon.display_detail('Getting catalog %s...', catalogname)
            message = 'Retrieving catalog "%s"...' % catalogname
            try:
                dummy_value = getResourceIfChangedAtomically(
                    catalogurl, catalogpath, message=message)
            except fetch.MunkiDownloadError, err:
                munkicommon.display_error(
                    'Could not retrieve catalog %s from server: %s',
                    catalogname, err)
            else:
                try:
                    catalogdata = FoundationPlist.readPlist(catalogpath)
                except FoundationPlist.NSPropertyListSerializationException:
                    munkicommon.display_error(
                        'Retreived catalog %s is invalid.', catalogname)
                    try:
                        os.unlink(catalogpath)
                    except (OSError, IOError):
                        pass
                else:
                    CATALOG[catalogname] = makeCatalogDB(catalogdata)


def cleanUpCatalogs():
    """Removes any catalog files that are no longer in use by this client"""
    catalog_dir = os.path.join(munkicommon.pref('ManagedInstallDir'),
                               'catalogs')
    for item in os.listdir(catalog_dir):
        if item not in CATALOG.keys():
            os.unlink(os.path.join(catalog_dir, item))


class ManifestException(Exception):
    """Lets us raise an exception when we get an invalid
    manifest."""
    pass


MANIFESTS = {}
def getmanifest(partialurl, suppress_errors=False):
    """Gets a manifest from the server.

    Returns:
      string local path to the downloaded manifest.
    """
    #global MANIFESTS
    manifestbaseurl = (munkicommon.pref('ManifestURL') or
                       munkicommon.pref('SoftwareRepoURL') + '/manifests/')
    if (not manifestbaseurl.endswith('?') and
            not manifestbaseurl.endswith('/')):
        manifestbaseurl = manifestbaseurl + '/'
    manifest_dir = os.path.join(munkicommon.pref('ManagedInstallDir'),
                                'manifests')

    if (partialurl.startswith('http://') or
            partialurl.startswith('https://') or
            partialurl.startswith('file:/')):
        # then it's really a request for the client's primary manifest
        manifestdisplayname = os.path.basename(partialurl)
        manifesturl = partialurl
        partialurl = 'client_manifest'
        manifestname = 'client_manifest.plist'
    else:
        # request for nested manifest
        manifestdisplayname = partialurl
        manifestname = partialurl
        manifesturl = manifestbaseurl + urllib2.quote(partialurl)

    if manifestname in MANIFESTS:
        return MANIFESTS[manifestname]

    munkicommon.display_debug2('Manifest base URL is: %s', manifestbaseurl)
    munkicommon.display_detail('Getting manifest %s...', manifestdisplayname)
    manifestpath = os.path.join(manifest_dir, manifestname)

    # Create the folder the manifest shall be stored in
    destinationdir = os.path.dirname(manifestpath)
    try:
        os.makedirs(destinationdir)
    except OSError as e:
        # OSError will be raised if destinationdir exists, ignore this case
        if not os.path.isdir(destinationdir):
            if not suppress_errors:
                munkicommon.display_error(
                    'Could not create folder to store manifest %s: %s',
                    manifestdisplayname, e
                )

            return None

    message = 'Retrieving list of software for this machine...'
    try:
        dummy_value = getResourceIfChangedAtomically(
            manifesturl, manifestpath, message=message)
    except fetch.MunkiDownloadError, err:
        if not suppress_errors:
            munkicommon.display_error(
                'Could not retrieve manifest %s from the server: %s',
                manifestdisplayname, err)
        return None

    try:
        # read plist to see if it is valid
        dummy_data = FoundationPlist.readPlist(manifestpath)
    except FoundationPlist.NSPropertyListSerializationException:
        errormsg = 'manifest returned for %s is invalid.' % manifestdisplayname
        munkicommon.display_error(errormsg)
        try:
            os.unlink(manifestpath)
        except (OSError, IOError):
            pass
        raise ManifestException(errormsg)
    else:
        # plist is valid
        MANIFESTS[manifestname] = manifestpath
        return manifestpath

def cleanUpManifests():
    """Removes any manifest files that are no longer in use by this client"""
    manifest_dir = os.path.join(
        munkicommon.pref('ManagedInstallDir'), 'manifests')

    exceptions = [
        "SelfServeManifest"
    ]

    for (dirpath, dirnames, filenames) in os.walk(manifest_dir, topdown=False):
        for name in filenames:

            if name in exceptions:
                continue

            abs_path = os.path.join(dirpath, name)
            rel_path = abs_path[len(manifest_dir):].lstrip("/")

            if rel_path not in MANIFESTS.keys():
                os.unlink(abs_path)

        # Try to remove the directory
        # (rmdir will fail if directory is not empty)
        try:
            if dirpath != manifest_dir:
                os.rmdir(dirpath)
        except OSError:
            pass



def getPrimaryManifest(alternate_id):
    """Gets the client manifest from the server."""
    manifest = ""
    manifesturl = munkicommon.pref('ManifestURL') or \
                  munkicommon.pref('SoftwareRepoURL') + '/manifests/'
    if not manifesturl.endswith('?') and not manifesturl.endswith('/'):
        manifesturl = manifesturl + '/'
    munkicommon.display_debug2('Manifest base URL is: %s', manifesturl)

    clientidentifier = alternate_id or munkicommon.pref('ClientIdentifier')

    if not alternate_id and munkicommon.pref('UseClientCertificate') and \
        munkicommon.pref('UseClientCertificateCNAsClientIdentifier'):
        # we're to use the client cert CN as the clientidentifier
        if munkicommon.pref('UseClientCertificate'):
            # find the client cert
            client_cert_path = munkicommon.pref('ClientCertificatePath')
            if not client_cert_path:
                ManagedInstallDir = munkicommon.pref('ManagedInstallDir')
                for name in ['cert.pem', 'client.pem', 'munki.pem']:
                    client_cert_path = os.path.join(ManagedInstallDir,
                                                    'certs', name)
                    if os.path.exists(client_cert_path):
                        break
            if client_cert_path and os.path.exists(client_cert_path):
                fileobj = open(client_cert_path)
                data = fileobj.read()
                fileobj.close()
                x509 = load_certificate(FILETYPE_PEM, data)
                clientidentifier = x509.get_subject().commonName

    try:
        if not clientidentifier:
            # no client identifier specified, so use the hostname
            hostname = os.uname()[1]
            # there shouldn't be any characters in a hostname that need quoting,
            # but see https://code.google.com/p/munki/issues/detail?id=276
            clientidentifier = urllib2.quote(hostname)
            munkicommon.display_detail(
                'No client id specified. Requesting %s...', clientidentifier)
            manifest = getmanifest(
                manifesturl + clientidentifier, suppress_errors=True)
            if not manifest:
                # try the short hostname
                clientidentifier = urllib2.quote(hostname.split('.')[0])
                munkicommon.display_detail(
                    'Request failed. Trying %s...', clientidentifier)
                manifest = getmanifest(
                    manifesturl + clientidentifier, suppress_errors=True)
            if not manifest:
                # try the machine serial number
                clientidentifier = MACHINE['serial_number']
                if clientidentifier != 'UNKNOWN':
                    munkicommon.display_detail(
                        'Request failed. Trying %s...', clientidentifier)
                    manifest = getmanifest(
                        manifesturl + clientidentifier, suppress_errors=True)
            if not manifest:
                # last resort - try for the site_default manifest
                clientidentifier = 'site_default'
                munkicommon.display_detail(
                    'Request failed. Trying %s...', clientidentifier)

        if not manifest:
            manifest = getmanifest(
                manifesturl + urllib2.quote(clientidentifier.encode('UTF-8')))
        if manifest:
            # record this info for later
            munkicommon.report['ManifestName'] = clientidentifier
            munkicommon.display_detail('Using manifest: %s', clientidentifier)
    except ManifestException:
        # bad manifests throw an exception
        pass
    return manifest


def checkServer(url):
    """A function we can call to check to see if the server is
    available before we kick off a full run. This can be fooled by
    ISPs that return results for non-existent web servers..."""
    # rewritten 24 Jan 2013 to attempt to support IPv6

    # deconstruct URL so we can check availability
    url_parts = urlparse.urlsplit(url)
    if url_parts.scheme == 'http':
        default_port = 80
    elif url_parts.scheme == 'https':
        default_port = 443
    elif url_parts.scheme == 'file':
        if url_parts.hostname not in [None, '', 'localhost']:
            return (-1, 'Non-local hostnames not supported for file:// URLs')
        if os.path.exists(url_parts.path):
            return (0, 'OK')
        else:
            return (-1, 'File %s does not exist' % url_parts.path)
    else:
        return (-1, 'Unsupported URL scheme')

    # get hostname and port
    host = url_parts.hostname
    if not host:
        return (-1, 'Bad URL')
    port = url_parts.port or default_port

    # following code based on the IPv6-ready example code here
    # http://docs.python.org/2/library/socket.html#example
    s = None
    socket_err = None
    addr_info = []
    try:
        addr_info = socket.getaddrinfo(
            host, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.error, err:
        socket_err = err
    else:
        for res in addr_info:
            af, socktype, proto, dummy_canonname, sa = res
            try:
                s = socket.socket(af, socktype, proto)
            except socket.error, err:
                s = None
                socket_err = err
                continue
            s.settimeout(5.0)
            try:
                s.connect(sa)
                s.close()
            except (socket.error, socket.timeout), err:
                s = None
                socket_err = err
                continue
            except BaseException, err:
                s = None
                socket_err = tuple(err)
                continue
            break
    if s:
        return (0, 'OK')
    else:
        if type(socket_err) == str:
            return (-1, socket_err)
        else:
            return socket_err


def getInstallerItemBasename(url):
    """For a URL, absolute or relative, return the basename string.

    e.g. "http://foo/bar/path/foo.dmg" => "foo.dmg"
         "/path/foo.dmg" => "foo.dmg"
    """

    url_parse = urlparse.urlparse(url)
    return os.path.basename(url_parse.path)


def getDownloadCachePath(destinationpathprefix, url):
    """For a URL, return the path that the download should cache to.

    Returns a string."""

    return os.path.join(
        destinationpathprefix, getInstallerItemBasename(url))


def download_icons(item_list):
    '''Attempts to download icons (actually png files) for items in
       item_list'''
    icon_list = []
    icon_known_exts = ['.bmp', '.gif', '.icns', '.jpg', '.jpeg', '.png', '.psd',
                       '.tga', '.tif', '.tiff', '.yuv']
    icon_base_url = (munkicommon.pref('IconURL') or
                     munkicommon.pref('SoftwareRepoURL') + '/icons/')
    icon_base_url = icon_base_url.rstrip('/') + '/'
    icon_dir = os.path.join(munkicommon.pref('ManagedInstallDir'), 'icons')
    munkicommon.display_debug2('Icon base URL is: %s', icon_base_url)
    for item in item_list:
        icon_name = item.get('icon_name') or item['name']
        pkginfo_icon_hash = item.get('icon_hash')
        if not os.path.splitext(icon_name)[1] in icon_known_exts:
            icon_name += '.png'
        icon_list.append(icon_name)
        icon_url = icon_base_url + urllib2.quote(icon_name.encode('UTF-8'))
        icon_path = os.path.join(icon_dir, icon_name)
        if os.path.isfile(icon_path):
            xattr_hash = fetch.getxattr(icon_path, fetch.XATTR_SHA)
            if not xattr_hash:
                xattr_hash = munkicommon.getsha256hash(icon_path)
                fetch.writeCachedChecksum(icon_path, xattr_hash)
        else:
            xattr_hash = 'nonexistent'
        icon_subdir = os.path.dirname(icon_path)
        if not os.path.isdir(icon_subdir):
            try:
                os.makedirs(icon_subdir, 0755)
            except OSError, err:
                munkicommon.display_error(
                    'Could not create %s' % icon_subdir)
                return
        if pkginfo_icon_hash != xattr_hash:
            item_name = item.get('display_name') or item['name']
            message = 'Getting icon %s for %s...' % (icon_name, item_name)
            try:
                dummy_value = getResourceIfChangedAtomically(
                    icon_url, icon_path, message=message)
            except fetch.MunkiDownloadError, err:
                munkicommon.display_debug1(
                    'Could not retrieve icon %s from the server: %s',
                    icon_name, err)
            else:
                if os.path.isfile(icon_path):
                    fetch.writeCachedChecksum(icon_path)
    # remove no-longer needed icons from the local directory
    for (dirpath, dummy_dirnames, filenames) in os.walk(
            icon_dir, topdown=False):
        for filename in filenames:
            icon_path = os.path.join(dirpath, filename)
            rel_path = icon_path[len(icon_dir):].lstrip('/')
            if rel_path not in icon_list:
                try:
                    os.unlink(icon_path)
                except (IOError, OSError), err:
                    pass
        if len(munkicommon.listdir(dirpath)) == 0:
            # did we empty out this directory (or is it already empty)?
            # if so, remove it
            try:
                os.rmdir(dirpath)
            except (IOError, OSError), err:
                pass


def download_client_resources():
    """Download client customization resources (if any)."""
    # Munki's preferences can specify an explicit name
    # under ClientResourcesFilename
    # if that doesn't exist, use the primary manifest name as the
    # filename. If that fails, try site_default.zip
    filenames = []
    resources_name = munkicommon.pref('ClientResourcesFilename')
    if resources_name:
        if os.path.splitext(resources_name)[1] != '.zip':
            resources_name += '.zip'
        filenames.append(resources_name)
    else:
        filenames.append(munkicommon.report['ManifestName'] + '.zip')
    filenames.append('site_default.zip')

    resource_base_url = (
        munkicommon.pref('ClientResourceURL') or
        munkicommon.pref('SoftwareRepoURL') + '/client_resources/')
    resource_base_url = resource_base_url.rstrip('/') + '/'
    resource_dir = os.path.join(
        munkicommon.pref('ManagedInstallDir'), 'client_resources')
    munkicommon.display_debug2(
        'Client resources base URL is: %s', resource_base_url)
    # make sure local resource directory exists
    if not os.path.isdir(resource_dir):
        try:
            os.makedirs(resource_dir, 0755)
        except OSError, err:
            munkicommon.display_error(
                'Could not create %s' % resource_dir)
            return
    resource_archive_path = os.path.join(resource_dir, 'custom.zip')
    message = 'Getting client resources...'
    downloaded_resource_path = None
    for filename in filenames:
        resource_url = resource_base_url + filename
        try:
            dummy_value = getResourceIfChangedAtomically(
                resource_url, resource_archive_path, message=message)
            downloaded_resource_path = resource_archive_path
            break
        except fetch.MunkiDownloadError, err:
            munkicommon.display_debug1(
                'Could not retrieve client resources with name %s: %s',
                filename, err)
    if downloaded_resource_path is None:
        # make sure we don't have an old custom.zip hanging around
        if os.path.exists(resource_archive_path):
            try:
                os.unlink(resource_archive_path)
            except (OSError, IOError), err:
                munkicommon.display_error(
                    'Could not remove stale %s: %s', resource_archive_path, err)


MACHINE = {}
CONDITIONS = {}
def check(client_id='', localmanifestpath=None):
    """Checks for available new or updated managed software, downloading
    installer items if needed. Returns 1 if there are available updates,
    0 if there are no available updates, and -1 if there were errors."""

    global MACHINE
    munkicommon.getMachineFacts()
    MACHINE = munkicommon.getMachineFacts()
    munkicommon.report['MachineInfo'] = MACHINE

    global CONDITIONS
    munkicommon.getConditions()
    CONDITIONS = munkicommon.getConditions()

    keychain_obj = keychain.MunkiKeychain()

    ManagedInstallDir = munkicommon.pref('ManagedInstallDir')
    if munkicommon.munkistatusoutput:
        munkistatus.activate()

    munkicommon.log('### Beginning managed software check ###')
    munkicommon.display_status_major('Checking for available updates...')

    if localmanifestpath:
        mainmanifestpath = localmanifestpath
    else:
        mainmanifestpath = getPrimaryManifest(client_id)
    if munkicommon.stopRequested():
        return 0

    installinfo = {}

    if mainmanifestpath:
        # initialize our installinfo record
        installinfo['processed_installs'] = []
        installinfo['processed_uninstalls'] = []
        installinfo['managed_updates'] = []
        installinfo['optional_installs'] = []
        installinfo['managed_installs'] = []
        installinfo['removals'] = []

        # set up INFO_OBJECT for conditional item comparisons
        makePredicateInfoObject()
        munkicommon.report['Conditions'] = INFO_OBJECT

        munkicommon.display_detail('**Checking for installs**')
        processManifestForKey(mainmanifestpath, 'managed_installs',
                              installinfo)
        if munkicommon.stopRequested():
            return 0

        if munkicommon.munkistatusoutput:
            # reset progress indicator and detail field
            munkistatus.message('Checking for additional changes...')
            munkistatus.percent('-1')
            munkistatus.detail('')

        # now generate a list of items to be uninstalled
        munkicommon.display_detail('**Checking for removals**')
        processManifestForKey(mainmanifestpath, 'managed_uninstalls',
                              installinfo)
        if munkicommon.stopRequested():
            return 0

        # now check for implicit removals
        # use catalogs from main manifest
        cataloglist = getManifestValueForKey(mainmanifestpath, 'catalogs')
        autoremovalitems = getAutoRemovalItems(installinfo, cataloglist)
        if autoremovalitems:
            munkicommon.display_detail('**Checking for implicit removals**')
        for item in autoremovalitems:
            if munkicommon.stopRequested():
                return 0
            dummy_result = processRemoval(item, cataloglist, installinfo)

        # look for additional updates
        munkicommon.display_detail('**Checking for managed updates**')
        processManifestForKey(mainmanifestpath, 'managed_updates',
                              installinfo)
        if munkicommon.stopRequested():
            return 0

        # build list of optional installs
        processManifestForKey(mainmanifestpath, 'optional_installs',
                              installinfo)
        if munkicommon.stopRequested():
            return 0

        # verify available license seats for optional installs
        if installinfo.get('optional_installs'):
            updateAvailableLicenseSeats(installinfo)

        # process LocalOnlyManifest installs
        localonlymanifestname = munkicommon.pref('LocalOnlyManifest')
        if localonlymanifestname:
            localonlymanifest = os.path.join(
                ManagedInstallDir, 'manifests', localonlymanifestname)

            # if the manifest already exists, the name is being reused
            if localonlymanifestname in MANIFESTS:
                munkicommon.display_error(
                    "LocalOnlyManifest %s has the same name as an existing " \
                     "manifest, skipping...", localonlymanifestname
                )
            else:
                MANIFESTS[localonlymanifestname] = localonlymanifest
                if os.path.exists(localonlymanifest):
                    # use catalogs from main manifest for local only manifest
                    cataloglist = getManifestValueForKey(
                        mainmanifestpath, 'catalogs')
                    munkicommon.display_detail(
                        '**Processing local-only choices**'
                    )

                    localonlyinstalls = getManifestValueForKey(
                        localonlymanifest, 'managed_installs') or []
                    for item in localonlyinstalls:
                        dummy_result = processInstall(
                            item,
                            cataloglist,
                            installinfo
                        )

                    localonlyuninstalls = getManifestValueForKey(
                        localonlymanifest, 'managed_uninstalls') or []
                    for item in localonlyuninstalls:
                        dummy_result = processRemoval(
                            item,
                            cataloglist,
                            installinfo
                        )

        # now process any self-serve choices
        usermanifest = '/Users/Shared/.SelfServeManifest'
        selfservemanifest = os.path.join(
            ManagedInstallDir, 'manifests', 'SelfServeManifest')
        if os.path.exists(usermanifest):
            # copy user-generated SelfServeManifest to our
            # ManagedInstallDir
            try:
                plist = FoundationPlist.readPlist(usermanifest)
                if plist:
                    FoundationPlist.writePlist(plist, selfservemanifest)
                    # now remove the user-generated manifest
                    try:
                        os.unlink(usermanifest)
                    except OSError:
                        pass
            except FoundationPlist.FoundationPlistException:
                # problem reading the usermanifest
                # better remove it
                munkicommon.display_error('Could not read %s', usermanifest)
                try:
                    os.unlink(usermanifest)
                except OSError:
                    pass

        if os.path.exists(selfservemanifest):
            # use catalogs from main manifest for self-serve manifest
            cataloglist = getManifestValueForKey(
                mainmanifestpath, 'catalogs')
            munkicommon.display_detail('**Processing self-serve choices**')
            selfserveinstalls = getManifestValueForKey(selfservemanifest,
                                                       'managed_installs')

            # build list of items in the optional_installs list
            # that have not exceeded available seats
            available_optional_installs = [
                item['name']
                for item in installinfo.get('optional_installs', [])
                if (not 'licensed_seats_available' in item
                    or item['licensed_seats_available'])]
            if selfserveinstalls:
                # filter the list, removing any items not in the current list
                # of available self-serve installs
                selfserveinstalls = [item for item in selfserveinstalls
                                     if item in available_optional_installs]
                for item in selfserveinstalls:
                    dummy_result = processInstall(
                        item, cataloglist, installinfo)

            # we don't need to filter uninstalls
            selfserveuninstalls = getManifestValueForKey(
                selfservemanifest, 'managed_uninstalls') or []
            for item in selfserveuninstalls:
                dummy_result = processRemoval(item, cataloglist, installinfo)

            # update optional_installs with install/removal info
            for item in installinfo['optional_installs']:
                if (not item.get('installed') and
                        isItemInInstallInfo(
                            item, installinfo['managed_installs'])):
                    item['will_be_installed'] = True
                elif (item.get('installed') and
                      isItemInInstallInfo(item, installinfo['removals'])):
                    item['will_be_removed'] = True

        # filter managed_installs to get items already installed
        installed_items = [item.get('name', '')
                           for item in installinfo['managed_installs']
                           if item.get('installed')]
        # filter managed_installs to get problem items:
        # not installed, but no installer item
        problem_items = [item
                         for item in installinfo['managed_installs']
                         if item.get('installed') == False and
                         not item.get('installer_item')]
        # filter removals to get items already removed
        # (or never installed)
        removed_items = [item.get('name', '')
                         for item in installinfo['removals']
                         if item.get('installed') == False]

        if os.path.exists(selfservemanifest):
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

        # record detail before we throw it away...
        munkicommon.report['ManagedInstalls'] = installinfo['managed_installs']
        munkicommon.report['InstalledItems'] = installed_items
        munkicommon.report['ProblemInstalls'] = problem_items
        munkicommon.report['RemovedItems'] = removed_items

        munkicommon.report['managed_installs_list'] = installinfo[
            'processed_installs']
        munkicommon.report['managed_uninstalls_list'] = installinfo[
            'processed_uninstalls']
        munkicommon.report['managed_updates_list'] = installinfo[
            'managed_updates']

        # filter managed_installs and removals lists
        # so they have only items that need action
        installinfo['managed_installs'] = [
            item for item in installinfo['managed_installs']
            if item.get('installer_item')]
        installinfo['removals'] = [
            item for item in installinfo['removals']
            if item.get('installed')]

        # also record problem items so MSC.app can provide feedback
        installinfo['problem_items'] = problem_items

        # download display icons for optional installs
        # and active installs/removals
        item_list = list(installinfo.get('optional_installs', []))
        item_list.extend(installinfo['managed_installs'])
        item_list.extend(installinfo['removals'])
        download_icons(item_list)

        # get any custom client resources
        download_client_resources()

        # record the filtered lists
        munkicommon.report['ItemsToInstall'] = installinfo['managed_installs']
        munkicommon.report['ItemsToRemove'] = installinfo['removals']

        # clean up catalogs directory
        cleanUpCatalogs()

        # clean up manifests directory
        cleanUpManifests()

        # clean up cache dir
        # remove any item in the cache that isn't scheduled
        # to be used for an install or removal
        # this could happen if an item is downloaded on one
        # updatecheck run, but later removed from the manifest
        # before it is installed or removed - so the cached item
        # is no longer needed.
        cache_list = [item['installer_item']
                      for item in installinfo.get('managed_installs', [])]
        cache_list.extend([item['uninstaller_item']
                           for item in installinfo.get('removals', [])
                           if item.get('uninstaller_item')])
        cachedir = os.path.join(ManagedInstallDir, 'Cache')
        for item in munkicommon.listdir(cachedir):
            if item.endswith('.download'):
                # we have a partial download here
                # remove the '.download' from the end of the filename
                fullitem = os.path.splitext(item)[0]
                if os.path.exists(os.path.join(cachedir, fullitem)):
                    # we have a partial and a full download
                    # for the same item. (This shouldn't happen.)
                    # remove the partial download.
                    os.unlink(os.path.join(cachedir, item))
                elif problem_items == []:
                    # problem items is our list of items
                    # that need to be installed but are missing
                    # the installer_item; these might be partial
                    # downloads. So if we have no problem items, it's
                    # OK to get rid of any partial downloads hanging
                    # around.
                    os.unlink(os.path.join(cachedir, item))
            elif item not in cache_list:
                munkicommon.display_detail('Removing %s from cache', item)
                os.unlink(os.path.join(cachedir, item))

        # write out install list so our installer
        # can use it to install things in the right order
        installinfochanged = True
        installinfopath = os.path.join(ManagedInstallDir, 'InstallInfo.plist')
        if os.path.exists(installinfopath):
            try:
                oldinstallinfo = FoundationPlist.readPlist(installinfopath)
            except FoundationPlist.NSPropertyListSerializationException:
                oldinstallinfo = None
                munkicommon.display_error(
                    'Could not read InstallInfo.plist. Deleting...')
                try:
                    os.unlink(installinfopath)
                except OSError, e:
                    munkicommon.display_error(
                        'Failed to delete InstallInfo.plist: %s', str(e))
            if oldinstallinfo == installinfo:
                installinfochanged = False
                munkicommon.display_detail('No change in InstallInfo.')

        if installinfochanged:
            FoundationPlist.writePlist(installinfo,
                                       os.path.join(ManagedInstallDir,
                                                    'InstallInfo.plist'))
    else:
        # couldn't get a primary manifest. Check to see if we have a valid
        # install/remove list from an earlier run.
        munkicommon.display_error(
            'Could not retrieve managed install primary manifest.')
        installinfopath = os.path.join(ManagedInstallDir, 'InstallInfo.plist')
        if os.path.exists(installinfopath):
            try:
                installinfo = FoundationPlist.readPlist(installinfopath)
            except FoundationPlist.NSPropertyListSerializationException:
                installinfo = {}
            munkicommon.report['ItemsToInstall'] = \
                installinfo.get('managed_installs', [])
            munkicommon.report['ItemsToRemove'] = \
                installinfo.get('removals', [])

    munkicommon.savereport()
    munkicommon.log('###    End managed software check    ###')

    installcount = len(installinfo.get('managed_installs', []))
    removalcount = len(installinfo.get('removals', []))

    if installcount or removalcount:
        return 1
    else:
        return 0


def displayUpdateInfo():
    '''Prints info about available updates'''
    ManagedInstallDir = munkicommon.pref('ManagedInstallDir')
    installinfopath = os.path.join(ManagedInstallDir, 'InstallInfo.plist')
    try:
        installinfo = FoundationPlist.readPlist(installinfopath)
    except FoundationPlist.NSPropertyListSerializationException:
        installinfo = {}

    installcount = len(installinfo.get('managed_installs', []))
    removalcount = len(installinfo.get('removals', []))

    if installcount:
        munkicommon.display_info('')
        munkicommon.display_info(
            'The following items will be installed or upgraded:')
    for item in installinfo.get('managed_installs', []):
        if item.get('installer_item'):
            munkicommon.display_info(
                '    + %s-%s', item.get('name', ''),
                item.get('version_to_install', ''))
            if item.get('description'):
                munkicommon.display_info('        %s', item['description'])
            if (item.get('RestartAction') == 'RequireRestart' or
                    item.get('RestartAction') == 'RecommendRestart'):
                munkicommon.display_info('       *Restart required')
                munkicommon.report['RestartRequired'] = True
            if item.get('RestartAction') == 'RequireLogout':
                munkicommon.display_info('       *Logout required')
                munkicommon.report['LogoutRequired'] = True

    if removalcount:
        munkicommon.display_info('The following items will be removed:')
    for item in installinfo.get('removals', []):
        if item.get('installed'):
            munkicommon.display_info('    - %s', item.get('name'))
            if (item.get('RestartAction') == 'RequireRestart' or
                    item.get('RestartAction') == 'RecommendRestart'):
                munkicommon.display_info('       *Restart required')
                munkicommon.report['RestartRequired'] = True
            if item.get('RestartAction') == 'RequireLogout':
                munkicommon.display_info('       *Logout required')
                munkicommon.report['LogoutRequired'] = True

    if installcount == 0 and removalcount == 0:
        munkicommon.display_info(
            'No changes to managed software are available.')


def subtractTimeZoneOffsetFromDate(the_date):
    """Input: NSDate object
    Output: NSDate object with same date and time as the UTC.
    In Los Angeles (PDT), '2011-06-20T12:00:00Z' becomes
    '2011-06-20 12:00:00 -0700'.
    In New York (EDT), it becomes '2011-06-20 12:00:00 -0400'.
    This allows a pkginfo item to reference a time in UTC that
    gets translated to the same relative local time.
    A force_install_after_date for '2011-06-20T12:00:00Z' will happen
    after 2011-06-20 12:00:00 local time.
    """
    # find our time zone offset in seconds
    tz = NSTimeZone.defaultTimeZone()
    seconds_offset = tz.secondsFromGMTForDate_(the_date)
    # return new NSDate minus local_offset
    return NSDate.alloc(
        ).initWithTimeInterval_sinceDate_(-seconds_offset, the_date)


def addTimeZoneOffsetToDate(the_date):
    """Input: NSDate object
    Output: NSDate object with timezone difference added
    to the date. This allows conditional_item conditions to
    be written like so:

    <Key>condition</key>
    <string>date > CAST("2012-12-17T16:00:00Z", "NSDate")</string>

    with the intent being that the comparision is against local time.

    """
    # find our time zone offset in seconds
    tz = NSTimeZone.defaultTimeZone()
    seconds_offset = tz.secondsFromGMTForDate_(the_date)
    # return new NSDate minus local_offset
    return NSDate.alloc(
        ).initWithTimeInterval_sinceDate_(seconds_offset, the_date)


def checkForceInstallPackages():
    """Check installable packages and applicable Apple updates
    for force install parameters.

    This method modifies InstallInfo and/or AppleUpdates in one scenario:
    It enables the unattended_install flag on all packages which need to be
    force installed and do not have a RestartAction.

    The return value may be one of:
        'now': a force install is about to occur
        'soon': a force install will occur within FORCE_INSTALL_WARNING_HOURS
        'logout': a force install is about to occur and requires logout
        'restart': a force install is about to occur and requires restart
        None: no force installs are about to occur
    """
    result = None

    ManagedInstallDir = munkicommon.pref('ManagedInstallDir')

    installinfo_types = {
        'InstallInfo.plist' : 'managed_installs',
        'AppleUpdates.plist': 'AppleUpdates'
    }

    now = NSDate.date()
    now_xhours = NSDate.dateWithTimeIntervalSinceNow_(
        FORCE_INSTALL_WARNING_HOURS * 3600)

    for installinfo_plist in installinfo_types.keys():
        pl_dict = installinfo_types[installinfo_plist]
        installinfopath = os.path.join(ManagedInstallDir, installinfo_plist)
        try:
            installinfo = FoundationPlist.readPlist(installinfopath)
        except FoundationPlist.NSPropertyListSerializationException:
            continue

        writeback = False

        for i in xrange(len(installinfo.get(pl_dict, []))):
            install = installinfo[pl_dict][i]
            force_install_after_date = install.get('force_install_after_date')

            if force_install_after_date:
                force_install_after_date = subtractTimeZoneOffsetFromDate(
                    force_install_after_date)
                munkicommon.display_debug1(
                    'Forced install for %s at %s',
                    install['name'], force_install_after_date)
                if now >= force_install_after_date:
                    result = 'now'
                    if install.get('RestartAction'):
                        if install['RestartAction'] == 'RequireLogout':
                            result = 'logout'
                        elif (install['RestartAction'] == 'RequireRestart' or
                              install['RestartAction'] == 'RecommendRestart'):
                            result = 'restart'
                    elif not install.get('unattended_install', False):
                        munkicommon.display_debug1(
                            'Setting unattended install for %s',
                            install['name'])
                        install['unattended_install'] = True
                        installinfo[pl_dict][i] = install
                        writeback = True

                if now_xhours >= force_install_after_date:
                    if not result:
                        result = 'soon'

        if writeback:
            FoundationPlist.writePlist(installinfo, installinfopath)

    return result


def getDataFromURL(url):
    '''Returns data from url as string. We use the existing
    getResourceIfChangedAtomically function so any custom
    authentication/authorization headers are reused'''
    urldata = os.path.join(munkicommon.tmpdir(), 'urldata')
    if os.path.exists(urldata):
        try:
            os.unlink(urldata)
        except (IOError, OSError), err:
            munkicommon.display_warning('Error in getDataFromURL: %s', err)
    dummy_result = getResourceIfChangedAtomically(url, urldata)
    try:
        fdesc = open(urldata)
        data = fdesc.read()
        fdesc.close()
        os.unlink(urldata)
        return data
    except (IOError, OSError), err:
        munkicommon.display_warning('Error in getDataFromURL: %s', err)
        return ''


def getResourceIfChangedAtomically(
        url, destinationpath, message=None, resume=False, expected_hash=None,
        verify=False):

    '''Gets a given URL from the Munki server.
    Adds any additional headers to the request if present'''

    # Add any additional headers specified in ManagedInstalls.plist.
    # AdditionalHttpHeaders must be an array of strings with valid HTTP
    # header format. For example:
    # <key>AdditionalHttpHeaders</key>
    # <array>
    #   <string>Key-With-Optional-Dashes: Foo Value</string>
    #   <string>another-custom-header: bar value</string>
    # </array>
    custom_headers = munkicommon.pref(
        munkicommon.ADDITIONAL_HTTP_HEADERS_KEY)

    return fetch.getResourceIfChangedAtomically(url,
                                                destinationpath,
                                                custom_headers=custom_headers,
                                                expected_hash=expected_hash,
                                                message=message,
                                                resume=resume,
                                                verify=verify)


def getPrimaryManifestCatalogs(client_id='', force_refresh=False):
    """Return list of catalogs from primary client manifest

    Args:
      force_refresh: Boolean. If True, downloads primary manifest
      and listed catalogs; False, uses locally cached information.
    Returns:
      cataloglist: list of catalogs from primary manifest
    """
    global MACHINE
    if not MACHINE:
        MACHINE = munkicommon.getMachineFacts()

    cataloglist = []
    if force_refresh:
        # Fetch manifest from repo
        manifest = getPrimaryManifest(client_id)
    else:
        # Use locally stored manifest
        manifest_dir = os.path.join(munkicommon.pref('ManagedInstallDir'),
                                    'manifests')
        manifestname = 'client_manifest.plist'
        manifest = os.path.join(manifest_dir, manifestname)

    if manifest:
        manifestdata = getManifestData(manifest)
        cataloglist = manifestdata.get('catalogs')
        if cataloglist and force_refresh:
            getCatalogs(cataloglist)
    return cataloglist


def main():
    """Placeholder"""
    pass


if __name__ == '__main__':
    main()
