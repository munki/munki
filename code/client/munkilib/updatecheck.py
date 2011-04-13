#!/usr/bin/python
# encoding: utf-8
#
# Copyright 2009-2011 Greg Neagle.
#
# Licensed under the Apache License, Version 2.0 (the 'License');
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
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

#standard libs
import calendar
import errno
import os
import re
import shutil
import subprocess
import socket
import time
import urllib2
import urlparse
import xattr
#from distutils import version
from OpenSSL.crypto import load_certificate, FILETYPE_PEM

#our libs
import munkicommon
import munkistatus
import appleupdates
import FoundationPlist


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
            munkicommon.display_warning('Bad pkginfo: %s' % item)

        # normalize the version number
        vers = trimVersionString(vers)

        # build indexes for items by name and version
        if not name in name_table:
            name_table[name] = {}
        if not vers in name_table[name]:
            name_table[name][vers] = []
        name_table[name][vers].append(itemindex)

        # build table of receipts
        if 'receipts' in item:
            for receipt in item['receipts']:
                if 'packageid' in receipt and 'version' in receipt:
                    if not receipt['packageid'] in pkgid_table:
                        pkgid_table[receipt['packageid']] = {}
                    if not (receipt['version'] in
                            pkgid_table[receipt['packageid']]):
                        pkgid_table[
                            receipt['packageid']][receipt['version']] = []
                    pkgid_table[
                        receipt['packageid']][
                            receipt['version']].append(itemindex)

    # build table of update items with a list comprehension --
    # filter all items from the catalogitems that have a non-empty
    # 'update_for' list
    updaters = [item for item in catalogitems if item.get('update_for')]

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


def addPackageids(catalogitems, pkgid_table):
    """Adds packageids from each catalogitem to a dictionary"""
    for item in catalogitems:
        name = item.get('name')
        if not name:
            continue
        if item.get('receipts'):
            if not name in pkgid_table:
                pkgid_table[name] = []

            for receipt in item['receipts']:
                if 'packageid' in receipt:
                    if not receipt['packageid'] in pkgid_table[name]:
                        pkgid_table[name].append(receipt['packageid'])


def getFirstPlist(textString):
    """Gets the next plist from a set of concatenated text-style plists.
    Returns a tuple - the first plist (if any) and the remaining
    string"""
    plistStart = textString.find('<?xml version')
    if plistStart == -1:
        # not found
        return ("", textString)
    plistEnd = textString.find('</plist>', plistStart + 13)
    if plistEnd == -1:
        # not found
        return ("", textString)
    # adjust end value
    plistEnd = plistEnd + 8
    return (textString[plistStart:plistEnd], textString[plistEnd:])


INSTALLEDPKGS = {}
def getInstalledPackages():
    """Builds a dictionary of installed receipts and their version number"""
    #global INSTALLEDPKGS

    # we use the --regexp option to pkgutil to get it to return receipt
    # info for all installed packages.  Huge speed up.
    proc = subprocess.Popen(['/usr/sbin/pkgutil', '--regexp',
                             '--pkg-info-plist', '.*'], bufsize=8192,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out, unused_err) = proc.communicate()
    while out:
        (pliststr, out) = getFirstPlist(out)
        if pliststr:
            plist = FoundationPlist.readPlistFromString(pliststr)
            if 'pkg-version' in plist and 'pkgid' in plist:
                INSTALLEDPKGS[plist['pkgid']] = \
                                        plist['pkg-version'] or '0.0.0.0.0'
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


# global pkgdata
PKGDATA  = {}
def analyzeInstalledPkgs():
    """Analyzed installed packages in an attempt to determine what is
       installed."""
    #global PKGDATA
    managed_pkgids = {}
    for catalogname in CATALOG.keys():
        catalogitems = CATALOG[catalogname]['items']
        addPackageids(catalogitems, managed_pkgids)

    if not INSTALLEDPKGS:
        getInstalledPackages()

    installed = []
    partiallyinstalled = []
    installedpkgsmatchedtoname = {}
    for name in managed_pkgids.keys():
        somepkgsfound = False
        allpkgsfound = True
        for pkg in managed_pkgids[name]:
            if pkg in INSTALLEDPKGS.keys():
                somepkgsfound = True
                if not name in installedpkgsmatchedtoname:
                    installedpkgsmatchedtoname[name] = []
                installedpkgsmatchedtoname[name].append(pkg)
            else:
                allpkgsfound = False
        if allpkgsfound:
            installed.append(name)
        elif somepkgsfound:
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

    # build our reference table
    references = {}
    for name in installed:
        for pkg in installedpkgsmatchedtoname[name]:
            if not pkg in references:
                references[pkg] = []
            references[pkg].append(name)

    PKGDATA['receipts_for_name'] = installedpkgsmatchedtoname
    PKGDATA['installed_names'] = installed
    PKGDATA['pkg_references'] = references


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
      Boolean.
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
    if 'path' in app and 'CFBundleShortVersionString' in app:
        filepath = os.path.join(app['path'], 'Contents', 'Info.plist')
        if os.path.exists(filepath):
            return compareBundleVersion(app)

    # not in default location, so let's search:
    name = app.get('CFBundleName','')
    bundleid = app.get('CFBundleIdentifier','')
    versionstring = app.get('CFBundleShortVersionString')

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
            if bundleid and item['bundleid'] == bundleid:
                appinfo.append(item)
            elif name and item['name'] == name:
                appinfo.append(item)

    if not appinfo:
        # app isn't present!
        munkicommon.display_debug1(
            '\tDid not find this application on the startup disk.')
        return 0

    for item in appinfo:
        if 'name' in item:
            munkicommon.display_debug2(
                '\tName: \t %s' % item['name'].encode('UTF-8'))
        if 'path' in item:
            munkicommon.display_debug2(
                '\tPath: \t %s' % item['path'].encode('UTF-8'))
            munkicommon.display_debug2(
                '\tCFBundleIdentifier: \t %s' %
                                        item['bundleid'].encode('UTF-8'))
        if 'version' in item:
            munkicommon.display_debug2(
                '\tVersion: \t %s' % item['version'].encode('UTF-8'))
            if compareVersions(item['version'], versionstring) == 1:
                # version is the same
                return 1
            if compareVersions(item['version'], versionstring) == 2:
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
    if 'path' in item and 'CFBundleShortVersionString' in item:
        vers = item['CFBundleShortVersionString']
    else:
        raise munkicommon.Error('Missing bundle path or version!')

    munkicommon.display_debug1('Checking bundle %s for version %s...' %
                                (item['path'], vers))
    filepath = os.path.join(item['path'], 'Contents', 'Info.plist')
    if not os.path.exists(filepath):
        munkicommon.display_debug1('\tNo Info.plist found at %s' % filepath)
        filepath = os.path.join(item['path'], 'Resources', 'Info.plist')
        if not os.path.exists(filepath):
            munkicommon.display_debug1(
                                '\tNo Info.plist found at %s' % filepath)
            return 0

    munkicommon.display_debug1('\tFound Info.plist at %s' % filepath)
    try:
        plist = FoundationPlist.readPlist(filepath)
    except FoundationPlist.NSPropertyListSerializationException:
        munkicommon.display_debug1('\t%s may not be a plist!' % filepath)
        return 0

    installedvers = munkicommon.getVersionString(plist)
    if installedvers:
        return compareVersions(installedvers, vers)
    else:
        munkicommon.display_debug1('\tNo version info in %s.' % filepath)
        return 0


def comparePlistVersion(item):
    """Gets the version string from the plist at path and compares versions.

    Returns  0 if the plist isn't installed
            -1 if it's older
             1 if the version is the same
             2 if the version is newer

    Raises munkicommon.Error if there's an error in the input
    """
    if 'path' in item and 'CFBundleShortVersionString' in item:
        filepath = item['path']
        vers = item['CFBundleShortVersionString']
    else:
        raise munkicommon.Error('Missing plist path or version!')

    munkicommon.display_debug1('Checking %s for version %s...' %
                                (filepath, vers))
    if not os.path.exists(filepath):
        munkicommon.display_debug1('\tNo plist found at %s' % filepath)
        return 0

    try:
        plist = FoundationPlist.readPlist(filepath)
    except FoundationPlist.NSPropertyListSerializationException:
        munkicommon.display_debug1('\t%s may not be a plist!' % filepath)
        return 0

    installedvers = munkicommon.getVersionString(plist)
    if installedvers:
        return compareVersions(installedvers, vers)
    else:
        munkicommon.display_debug1('\tNo version info in %s.' % filepath)
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
        munkicommon.display_debug1('Checking existence of %s...' % filepath)
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
                        'Checksums differ: expected %s, got %s' %
                         (storedchecksum, ondiskchecksum))
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
    itemtype = item.get('type')
    if itemtype == 'application':
        return compareApplicationVersion(item)
    if itemtype == 'bundle':
        return compareBundleVersion(item)
    if itemtype == 'plist':
        return comparePlistVersion(item)
    if itemtype == 'file':
        return filesystemItemExists(item)
    raise munkicommon.Error('Unknown installs item type: %s' % itemtype)


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
    if not INSTALLEDPKGS:
        getInstalledPackages()
    if 'packageid' in item and 'version' in item:
        pkgid = item['packageid']
        vers = item['version']
    else:
        raise munkicommon.Error('Missing packageid or version info!')

    munkicommon.display_debug1('Looking for package %s, version %s' %
                                (pkgid, vers))
    installedvers = INSTALLEDPKGS.get(pkgid)
    if installedvers:
        return compareVersions(installedvers, vers)
    else:
        munkicommon.display_debug1(
            '\tThis package is not currently installed.')
        return 0


def getInstalledVersion(item_plist):
    """Attempts to determine the currently installed version an item.

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
                'Using receipt %s to determine installed version of %s'
                % (pkgid, item_plist['name']))
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
                    'Looking for application %s, version %s' %
                    (name, install_item.get('CFBundleIdentifier')))
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
                    'Using bundle %s to determine installed version of %s'
                    % (install_item['path'], item_plist['name']))
                filepath = os.path.join(install_item['path'],
                                        'Contents', 'Info.plist')
                try:
                    plist = FoundationPlist.readPlist(filepath)
                    return plist.get('CFBundleShortVersionString', 'UNKNOWN')
                except FoundationPlist.NSPropertyListSerializationException:
                    return "UNKNOWN"
            elif install_item['type'] == 'plist':
                munkicommon.display_debug2(
                    'Using plist %s to determine installed version of %s'
                    % (install_item['path'], item_plist['name']))
                try:
                    plist = FoundationPlist.readPlist(install_item['path'])
                    return plist.get('CFBundleShortVersionString', 'UNKNOWN')
                except FoundationPlist.NSPropertyListSerializationException:
                    return "UNKNOWN"
    # if we fall through to here we have no idea what version we have
    return 'UNKNOWN'

class MunkiDownloadError(Exception):
    """Base exception for download errors"""
    pass

class CurlDownloadError(MunkiDownloadError):
    """Curl failed to download the item"""
    pass

class PackageVerificationError(MunkiDownloadError):
    """Download failed because it could not be verified"""
    pass

class FileCopyError(MunkiDownloadError):
    """Download failed because of file copy errors."""
    pass

def download_installeritem(item_pl, installinfo, uninstalling=False):
    """Downloads an (un)installer item.
    Raises an error if there are issues..."""

    download_item_key = 'installer_item_location'
    item_hash_key = 'installer_item_hash'
    if uninstalling and 'uninstaller_item_location' in item_pl:
        download_item_key = 'uninstaller_item_location'
        item_hash_key = 'uninstaller_item_hash'

    location = item_pl.get(download_item_key)
    if not location:
        raise MunkiDownloadError("No %s in item info." % download_item_key)

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
        pkgurl = downloadbaseurl + urllib2.quote(location)

    pkgname = getInstallerItemBasename(location)
    munkicommon.display_debug2('Download base URL is: %s' % downloadbaseurl)
    munkicommon.display_debug2('Package name is: %s' % pkgname)
    munkicommon.display_debug2('Download URL is: %s' % pkgurl)

    ManagedInstallDir = munkicommon.pref('ManagedInstallDir')
    mycachedir = os.path.join(ManagedInstallDir, 'Cache')
    destinationpath = getDownloadCachePath(mycachedir, location)
    munkicommon.display_debug2('Downloading to: %s' % destinationpath)

    munkicommon.display_detail('Downloading %s from %s' % (pkgname, location))

    if not os.path.exists(destinationpath):
        # check to see if there is enough free space to download and install
        if not enoughDiskSpace(item_pl, installinfo['managed_installs']):
            raise MunkiDownloadError(
                'Insufficient disk space to download and install %s'
                % pkgname)
        else:
            munkicommon.display_detail(
                'Downloading %s from %s' % (pkgname, location))

    # bump up verboseness so we get download percentage done feedback.
    # this is kind of a hack...
    oldverbose = munkicommon.verbose
    munkicommon.verbose = oldverbose + 1
    dl_message = 'Downloading %s...' % pkgname
    try:
        changed = getResourceIfChangedAtomically(pkgurl, destinationpath,
                                                 resume=True,
                                                 message=dl_message)
    except MunkiDownloadError:
        munkicommon.verbose = oldverbose
        raise

    # set verboseness back.
    munkicommon.verbose = oldverbose
    if changed:
        package_verified = verifySoftwarePackageIntegrity(destinationpath,
                                                          item_pl,
                                                          item_hash_key)
        if not package_verified:
            raise PackageVerificationError()


def isItemInInstallInfo(manifestitem_pl, thelist, vers=''):
    """Determines if an item is in a manifest plist.

    Returns True if the manifest item has already
    been processed (it's in the list) and, optionally,
    the version is the same or greater.
    """
    for item in thelist:
        try:
            if (item['name'] == manifestitem_pl['name']):
                if not vers:
                    return True
                if item.get('installed'):
                    return True
                #if the version already processed is the same or greater,
                #then we're good
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

    munkicommon.display_debug1('Looking for all items matching: %s...' % name)
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
                             'Adding item %s, version %s from catalog %s...' %
                                 (name, thisitem['version'], catalogname))
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
        del(version_parts[-1])
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

    (name, includedversion) = nameAndVersion(name)
    if vers == '':
        if includedversion:
            vers = includedversion
    if vers:
        vers = trimVersionString(vers)
    else:
        vers = 'latest'

    munkicommon.display_debug1('Looking for detail for: %s, version %s...' %
                                (name, vers))
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
                # now check to see if it meets os and cpu requirements
                if 'minimum_os_version' in item:
                    min_os_vers = item['minimum_os_version']
                    munkicommon.display_debug1(
                        'Considering item %s, ' % item['name'] +
                        'version %s ' % item['version'] +
                        'with minimum os version required %s' % min_os_vers)
                    munkicommon.display_debug1('Our OS version is %s' %
                                                MACHINE['os_vers'])
                    if (munkicommon.MunkiLooseVersion(MACHINE['os_vers']) <
                       munkicommon.MunkiLooseVersion(min_os_vers)):
                        # skip this one, go to the next
                        reason = (('Rejected item %s, version %s '
                                  'with minimum os version required %s. '
                                  "Our OS version is %s.")
                                  % (item['name'], item['version'],
                                     item['minimum_os_version'],
                                     MACHINE['os_vers']))
                        rejected_items.append(reason)
                        continue

                if 'maximum_os_version' in item:
                    max_os_vers = item['maximum_os_version']
                    munkicommon.display_debug1(
                        'Considering item %s, ' % item['name'] +
                        'version %s ' % item['version'] +
                        'with maximum os version supported %s' % max_os_vers)
                    munkicommon.display_debug1('Our OS version is %s' %
                                                MACHINE['os_vers'])
                    if (munkicommon.MunkiLooseVersion(MACHINE['os_vers']) >
                        munkicommon.MunkiLooseVersion(max_os_vers)):
                        # skip this one, go to the next
                        reason = (('Rejected item %s, version %s '
                                  'with maximum os version required %s. '
                                  'Our OS version is %s.')
                                  % (item['name'], item['version'],
                                     item['maximum_os_version'],
                                     MACHINE['os_vers']))
                        rejected_items.append(reason)
                        continue

                if 'supported_architectures' in item:
                    supported_arch_found = False
                    munkicommon.display_debug1(
                        'Considering item %s, ' % item['name'] +
                        'version %s ' % item['version'] +
                        'with supported architectures: %s' %
                                            item['supported_architectures'])
                    munkicommon.display_debug1('Our architecture is %s' %
                                                MACHINE['arch'])
                    for arch in item['supported_architectures']:
                        if arch == MACHINE['arch']:
                            # we found a supported architecture that matches
                            # this machine, so we can use it
                            supported_arch_found = True
                            break

                    if not supported_arch_found:
                        # we didn't find a supported architecture that
                        # matches this machine
                        reason = (('Rejected item %s, version %s '
                                  'with supported architectures: %s. '
                                  'Our architecture is %s.')
                                  % (item['name'], item['version'],
                                     item['supported_architectures'],
                                     MACHINE['arch']))
                        rejected_items.append(reason)
                        continue

                # item name, version, minimum_os_version, and
                # supported_architecture are all OK
                munkicommon.display_debug1(
                    'Found %s, version %s in catalog %s' %
                    (item['name'], item['version'], catalogname))
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
        cachedir = os.path.join(munkicommon.pref('ManagedInstallDir'),'Cache')
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
                                     item.get('installed_size',0)

    if availablediskspace > diskspaceneeded:
        return True
    elif warn:
        if uninstalling:
            munkicommon.display_warning('There is insufficient disk space to '
                                        'download the uninstaller for %s.' %
                                        manifestitem_pl.get('name'))
        else:
            munkicommon.display_warning('There is insufficient disk space to '
                                        'download and install %s.' %
                                        manifestitem_pl.get('name'))
        munkicommon.display_warning('    %sMB needed; %sMB available' %
                                                  (diskspaceneeded/1024,
                                                   availablediskspace/1024))
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

    if item_pl.get('softwareupdatename'):
        availableAppleUpdates = appleupdates.softwareUpdateList()
        munkicommon.display_debug2(
            'Available Apple updates:\n%s' % availableAppleUpdates)
        if item_pl['softwareupdatename'] in availableAppleUpdates:
            munkicommon.display_debug1(
                '%s is in available Apple Software Updates' %
                item_pl['softwareupdatename'])
            # return 0 so we're marked as needing to be installed
            return 0
        else:
            munkicommon.display_debug1(
                 '%s is not in available Apple Software Updates' %
                 item_pl['softwareupdatename'])
            # return 1 so we're marked as not needing to be installed
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
                munkicommon.display_error(errmsg)
                return 0

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
                munkicommon.display_error(errmsg)
                return 0

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
    """
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
                munkicommon.display_error(errmsg)
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
                munkicommon.display_error(errmsg)
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
    """
    if ('installs' in item_pl and
          item_pl.get('uninstall_method') != 'removepackages'):
        installitems = item_pl['installs']
        foundallinstallitems = True
        for item in installitems:
            if 'path' in item:
                # we can only check by path; if the item has been moved
                # we're not clever enough to find it, and our removal
                # methods are currently even less clever
                if not os.path.exists(item['path']):
                    # this item isn't on disk
                    foundallinstallitems = False
        if foundallinstallitems:
            return True
    if item_pl.get('receipts'):
        if PKGDATA == {}:
            # build our database of installed packages
            analyzeInstalledPkgs()
        if item_pl['name'] in PKGDATA['installed_names']:
            return True

    # if we got this far, we failed all the tests, so the item
    # must not be installed (or we dont't have the right info...)
    return False


def verifySoftwarePackageIntegrity(file_path, item_pl, item_key):
    """Verifies the integrity of the given software package.

    The feature is controlled through the PackageVerificationMode key in
    the ManagedInstalls.plist. Following modes currently exist:
        none: No integrity check is performed.
        hash: Integrity check is performed by calcualting a SHA-256 hash of
            the given file and comparing it against the reference value in
            catalog. Only applies for package plists that contain the
            item_key; for packages without the item_key, verifcation always
            returns True.
        hash_strict: Same as hash, but returns False for package plists that
            do not contain the item_key.

    Args:
        file_path: The file to check integrity on.
        item_pl: The item plist which contains the reference values.
        item_key: The name of the key in plist which contains the hash.

    Returns:
        True if the package integrity could be validated. Otherwise, False.
    """
    mode = munkicommon.pref('PackageVerificationMode')
    if not mode:
        return True
    elif mode.lower() == 'none':
        munkicommon.display_warning('Package integrity checking is disabled.')
        return True
    elif mode.lower() == 'hash' or mode.lower() == 'hash_strict':
        if item_key in item_pl:
            munkicommon.display_status('Verifying package integrity...')
            item_hash = item_pl[item_key]
            if (item_hash is not 'N/A' and
                item_hash == munkicommon.getsha256hash(file_path)):
                return True
            else:
                munkicommon.display_error(
                    'Hash value integrity check for %s failed.' %
                    item_pl.get('name'))
                return False
        else:
            if mode.lower() == 'hash_strict':
                munkicommon.display_error(
                    'Reference hash value for %s is missing in catalog.'
                    % item_pl.get('name'))
                return False
            else:
                munkicommon.display_warning(
                    'Reference hash value missing for %s -- package '
                    'integrity verification skipped.' % item_pl.get('name'))
                return True
    else:
        munkicommon.display_error(
            'The PackageVerificationMode in the ManagedInstalls.plist has an '
            'illegal value: %s' % munkicommon.pref('PackageVerificationMode'))

    return False


def getAutoRemovalItems(installinfo, cataloglist):
    """Gets a list of items marked for automatic removal from the catalogs
    in cataloglist. Filters those against items in the processed_installs
    list, which should contain everything that is supposed to be installed.
    Then filters against the removals list, which contains all the removals
    that have already been processed.
    """
    autoremovalnames = []
    for catalogname in (cataloglist or []):
        if catalogname in CATALOG.keys():
            autoremovalnames += CATALOG[catalogname]['autoremoveitems']

    processed_installs_names = [nameAndVersion(item)[0]
                                for item in installinfo['processed_installs']]
    autoremovalnames = [item for item in autoremovalnames
                        if item not in processed_installs_names
                        and item not in installinfo['processed_uninstalls']]
    return autoremovalnames


def lookForUpdates(manifestitem, cataloglist):
    """Looks for updates for a given manifest item that is either
    installed or scheduled to be installed. This handles not only
    specific application updates, but also updates that aren't simply
    later versions of the manifest item.
    For example, AdobeCameraRaw is an update for Adobe Photoshop, but
    doesn't update the version of Adobe Photoshop.
    Returns a list of manifestitem names that are updates for
    manifestitem.
    """
    nameWithVersion = os.path.split(manifestitem)[1]
    (name, unused_includedversion) = nameAndVersion(nameWithVersion)
    # get a list of catalog items that are updates for other items
    update_list = []
    for catalogname in cataloglist:
        if not catalogname in CATALOG.keys():
            # in case the list refers to a non-existant catalog
            continue

        updaters = CATALOG[catalogname]['updaters']
        # list comprehension coming up...
        update_items = [catalogitem['name']
                            for catalogitem in updaters
                            if (name in catalogitem.get('update_for',[]) or
                                nameWithVersion in
                                catalogitem.get('update_for',[]))]
        if update_items:
            update_list.extend(update_items)

    if update_list:
        # make sure the list has only unique items:
        update_list = list(set(update_list))

    return update_list


def processManagedUpdate(manifestitem, cataloglist, installinfo):
    """Process a managed_updates item to see if it is installed, and if so,
    if it needs an update.
    """
    manifestitemname = os.path.split(manifestitem)[1]
    munkicommon.display_debug1(
        '* Processing manifest item %s for update' % manifestitemname)

    # check to see if item is already in the update list:
    if manifestitemname in installinfo['managed_updates']:
        munkicommon.display_debug1(
            '%s has already been processed for update.' % manifestitemname)
        return
    # check to see if item is already in the installlist:
    if manifestitemname in installinfo['processed_installs']:
        munkicommon.display_debug1(
            '%s has already been processed for install.' % manifestitemname)
        return
    # check to see if item is already in the removallist:
    if manifestitemname in installinfo['processed_uninstalls']:
        munkicommon.display_debug1(
            '%s has already been processed for uninstall.' % manifestitemname)
        return

    item_pl = getItemDetail(manifestitem, cataloglist)
    if not item_pl:
        munkicommon.display_warning(
            'Could not process item %s for update: ' % manifestitem)
        munkicommon.display_warning(
            'No pkginfo for %s found in catalogs: %s' %
            (manifestitem, ', '.join(cataloglist)))
        return

    # we only offer to update if some version of the item is already
    # installed, so let's check
    if someVersionInstalled(item_pl):
        # add to the list of processed managed_updates
        installinfo['managed_updates'].append(manifestitemname)
        unused_result = processInstall(manifestitem, cataloglist, installinfo)
    else:
        munkicommon.display_debug1(
            '%s does not appear to be installed, so no managed updates...'
            % manifestitemname)


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
            '%s has already been processed for optional install.' %
                manifestitemname)
        return
    elif manifestitemname in installinfo['processed_installs']:
        munkicommon.display_debug1(
            '%s has already been processed for install.' %
            manifestitemname)
        return
    elif manifestitemname in installinfo['processed_uninstalls']:
        munkicommon.display_debug1(
            '%s has already been processed for uninstall.' % manifestitemname)
        return

    # check to see if item (any version) is already in the
    # optional_install list:
    for item in installinfo['optional_installs']:
        if manifestitemname == item['name']:
            munkicommon.display_debug1(
                '%s has already been processed for optional install.' %
                    manifestitemname)
            return

    item_pl = getItemDetail(manifestitem, cataloglist)
    if not item_pl:
        munkicommon.display_warning(
            'Could not process item %s for optional install: ' % manifestitem)
        munkicommon.display_warning(
            'No pkginfo for %s found in catalogs: %s' %
            (manifestitem, ', '.join(cataloglist)))
        return

    # if we get to this point we can add this item
    # to the list of optional installs
    iteminfo = {}
    iteminfo['name'] = item_pl.get('name', manifestitemname)
    iteminfo['description'] = item_pl.get('description', '')
    iteminfo['version_to_install'] = item_pl.get('version', 'UNKNOWN')
    iteminfo['display_name'] = item_pl.get('display_name', '')
    iteminfo['installed'] = someVersionInstalled(item_pl)
    if iteminfo['installed']:
        iteminfo['needs_update'] = (installedState(item_pl) == 0)
    iteminfo['uninstallable'] = item_pl.get('uninstallable', False)
    if (not iteminfo['installed']) or (iteminfo.get('needs_update')):
        iteminfo['installer_item_size'] = \
            item_pl.get('installer_item_size', 0)
        iteminfo['installed_size'] = item_pl.get('installer_item_size',
                                        iteminfo['installer_item_size'])
        if not enoughDiskSpace(item_pl,
                               installinfo.get('managed_installs', []),
                               warn=False):
            iteminfo['note'] = \
                'Insufficient disk space to download and install.'

    munkicommon.display_debug1(
        "Adding %s to the optional install list" %   iteminfo['name'])
    installinfo['optional_installs'].append(iteminfo)


def processInstall(manifestitem, cataloglist, installinfo):
    """Processes a manifest item. Determines if it needs to be
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
        '* Processing manifest item %s for install' % manifestitemname)
    (manifestitemname_withoutversion, includedversion) = nameAndVersion(
                                            manifestitemname)
    # have we processed this already?
    if manifestitemname in installinfo['processed_installs']:
        munkicommon.display_debug1(
                '%s has already been processed for install.' %
                manifestitemname)
        return True
    elif (manifestitemname_withoutversion in
          installinfo['processed_uninstalls']):
        munkicommon.display_warning(
            ('Will not process %s for install because it has already '
             'been processed for uninstall!') % manifestitemname)
        return False
    elif manifestitemname in installinfo['managed_updates']:
        # we're processing this as a managed update, so don't
        # add it to the processed_installs list
        pass
    else:
        installinfo['processed_installs'].append(manifestitemname)

    item_pl = getItemDetail(manifestitem, cataloglist)
    if not item_pl:
        munkicommon.display_warning(
            'Could not process item %s for install: ' % manifestitem)
        munkicommon.display_warning(
            'No pkginfo for %s found in catalogs: %s' %
            (manifestitem, ', '.join(cataloglist)))
        return False

    if isItemInInstallInfo(item_pl, installinfo['managed_installs'],
                           vers=item_pl.get('version')):
        # has this item already been added to the list of things to install?
        munkicommon.display_debug1(
                '%s is or will be installed.' % manifestitemname)
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
        for item in dependencies:
            munkicommon.display_detail('%s-%s requires %s. '
                                    'Getting info on %s...' %
                                    (item_pl.get('name', manifestitemname),
                                    item_pl.get('version',''), item, item))
            success = processInstall(item, cataloglist, installinfo)
            if not success:
                dependenciesMet = False

    if not dependenciesMet:
        munkicommon.display_warning('Didn\'t attempt to install %s '
                                    'because could not resolve all '
                                    'dependencies.' % manifestitemname)
        return False

    iteminfo = {}
    iteminfo['name'] = item_pl.get('name', '')
    iteminfo['display_name'] = item_pl.get('display_name', iteminfo['name'])
    iteminfo['description'] = item_pl.get('description', '')

    installed_state = installedState(item_pl)
    if installed_state == 0:
        munkicommon.display_detail('Need to install %s' % manifestitemname)
        iteminfo['installer_item_size'] = item_pl.get(
                                                'installer_item_size', 0)
        iteminfo['installed_size'] = item_pl.get('installed_size',
                                            iteminfo['installer_item_size'])
        try:
            download_installeritem(item_pl, installinfo)
            filename = getInstallerItemBasename(
                item_pl['installer_item_location'])
            # required keys
            iteminfo['installer_item'] = filename
            iteminfo['installed'] = False
            iteminfo['version_to_install'] = item_pl.get(
                                                 'version','UNKNOWN')

            # we will ignore the unattended_install key if the item needs a
            # restart or logout...
            if (item_pl.get('unattended_install') or        
                item_pl.get('forced_install')):
                if item_pl.get('RestartAction'):
                    munkicommon.display_warning(
                        'Ignoring unattended_install key for %s '
                        'because RestartAction is %s.'
                        % (item_pl['name'], item_pl.get('RestartAction')))
                else:
                    iteminfo['unattended_install'] = True

            # optional keys
            optional_keys = ['suppress_bundle_relocation',
                             'installer_choices_xml',
                             'adobe_install_info',
                             'RestartAction',
                             'installer_type',
                             'adobe_package_name',
                             'package_path',
                             'blocking_applications',
                             'installs',
                             'requires',
                             'update_for',
                             'preinstall_script',
                             'postinstall_script',
                             'items_to_copy',  # used w/ copy_from_dmg
                             'copy_local']     # used w/ AdobeCS5 Updaters

            for key in optional_keys:
                if key in item_pl:
                    iteminfo[key] = item_pl[key]

            installinfo['managed_installs'].append(iteminfo)
            if nameAndVersion(manifestitemname)[1] == '':
                # didn't specify a specific version, so
                # now look for updates for this item
                update_list = lookForUpdates(iteminfo['name'],
                                             cataloglist)
                for update_item in update_list:
                    # call processInstall recursively so we get the
                    # latest version and dependencies
                    unused_result = processInstall(update_item,
                                                   cataloglist,
                                                   installinfo)
            return True
        except PackageVerificationError:
            munkicommon.display_warning(
                'Can\'t install %s because the integrity check failed.'
                % manifestitem)
            iteminfo['installed'] = False
            iteminfo['note'] = 'Integrity check failed'
            installinfo['managed_installs'].append(iteminfo)
            return False
        except CurlDownloadError, errmsg:
            munkicommon.display_warning(
                'Download of %s failed: %s' % (manifestitem, errmsg))
            iteminfo['installed'] = False
            iteminfo['note'] = 'Download failed'
            installinfo['managed_installs'].append(iteminfo)
            return False
        except MunkiDownloadError, errmsg:
            munkicommon.display_warning('Can\'t install %s because: %s'
                                        % (manifestitemname, errmsg))
            iteminfo['installed'] = False
            iteminfo['note'] = '%s' % errmsg
            installinfo['managed_installs'].append(iteminfo)
            return False
    else:
        iteminfo['installed'] = True
        # record installed size for reporting
        iteminfo['installed_size'] = item_pl.get('installed_size',
            item_pl.get('installer_item_size',0))
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
                                    'installed.' % (name, item_pl['version']))
        if not includedversion:
            # no specific version is specified;
            # the item is already installed;
            # now look for updates for this item
            update_list = lookForUpdates(iteminfo['name'], cataloglist)
            for update_item in update_list:
                # call processInstall recursively so we get the latest version
                # and any dependencies
                unused_result = processInstall(update_item, cataloglist,
                                               installinfo)
        return True


def processManifestForKey(manifestpath, manifest_key, installinfo,
                          parentcatalogs=None):
    """Processes keys in manifests to build the lists of items to install and
    remove.

    Can be recursive if manifests include other manifests.
    Probably doesn't handle circular manifest references well.
    """
    munkicommon.display_debug1(
        "** Processing manifest %s for %s" %
        (os.path.basename(manifestpath), manifest_key))

    cataloglist = getManifestValueForKey(manifestpath, 'catalogs')
    if cataloglist:
        getCatalogs(cataloglist)
    elif parentcatalogs:
        cataloglist = parentcatalogs

    if cataloglist:
        nestedmanifests = getManifestValueForKey(manifestpath,
                                                 'included_manifests')
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

        items = getManifestValueForKey(manifestpath, manifest_key)
        if items:
            for item in items:
                if munkicommon.stopRequested():
                    return {}
                if manifest_key == 'managed_installs':
                    unused_result = processInstall(item, cataloglist,
                                                   installinfo)
                elif manifest_key == 'managed_updates':
                    processManagedUpdate(item, cataloglist, installinfo)
                elif manifest_key == 'optional_installs':
                    processOptionalInstall(item, cataloglist, installinfo)
                elif manifest_key == 'managed_uninstalls':
                    unused_result = processRemoval(item, cataloglist,
                                                   installinfo)

    else:
        munkicommon.display_warning('Manifest %s has no catalogs' %
                                    manifestpath)


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
                                    'install.' %
                                    manifestitemname)
        return False
    elif manifestitemname in installinfo['processed_uninstalls']:
        munkicommon.display_debug1(
            '%s has already been processed for removal.' %
            manifestitemname)
        return True
    else:
        installinfo['processed_uninstalls'].append(manifestitemname)

    infoitems = []
    if includedversion:
        # a specific version was specified
        item_pl = getItemDetail(manifestitemname, cataloglist,
                                                            includedversion)
        if item_pl:
            infoitems.append(item_pl)
    else:
        # get all items matching the name provided
        infoitems = getAllItemsWithName(manifestitemname, cataloglist)

    if not infoitems:
        munkicommon.display_warning(
            'Could not process item %s for removal: ' % manifestitemname)
        munkicommon.display_warning(
            'No pkginfo for %s found in catalogs: %s' %
            (manifestitemname, ', '.join(cataloglist)))
        return False

    installEvidence = False
    for item in infoitems:
        munkicommon.display_debug2('Considering item %s-%s for removal info'
                                    % (item['name'], item['version']))
        if evidenceThisIsInstalled(item):
            installEvidence = True
            break
        else:
            munkicommon.display_debug2('%s-%s not installed.'
                                       % (item['name'], item['version']))

    if not installEvidence:
        munkicommon.display_detail('%s doesn\'t appear to be installed.' %
                                    manifestitemname_withversion)
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
            # Adobe CS3/CS4/CS5 product
            uninstall_item = item
        elif uninstallmethod in ['remove_copied_items',
                                 'remove_app',
                                 'uninstall_script']:
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
        munkicommon.display_warning('Could not find uninstall info for %s.' %
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
    ManagedInstallDir = munkicommon.pref('ManagedInstallDir')
    catalogsdir = os.path.join(ManagedInstallDir, 'catalogs')

    uninstall_item_name = uninstall_item.get('name')
    processednames = []
    for catalogname in cataloglist:
        localcatalog = os.path.join(catalogsdir, catalogname)
        catalog_pl = FoundationPlist.readPlist(localcatalog)
        for item_pl in catalog_pl:
            name = item_pl.get('name')
            if name not in processednames:
                if 'requires' in item_pl:
                    if uninstall_item_name in item_pl['requires']:
                        munkicommon.display_debug1('%s requires %s, checking '
                                                   'to see if it\'s '
                                                   'installed...' %
                                                   (item_pl.get('name'),
                                                    manifestitemname))
                        if evidenceThisIsInstalled(item_pl):
                            munkicommon.display_detail('%s requires %s. '
                                                     '%s must be removed '
                                                     'as well.' %
                                                     (item_pl.get('name'),
                                                      manifestitemname,
                                                      item_pl.get('name')))
                            success = processRemoval(item_pl.get('name'),
                                                     cataloglist, installinfo)
                            if not success:
                                dependentitemsremoved = False
                                break
                # record this name so we don't process it again
                processednames.append(name)

    if not dependentitemsremoved:
        munkicommon.display_warning('Will not attempt to remove %s because '
                                    'could not remove all items dependent '
                                    'on it.' % manifestitemname_withversion)
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
        if uninstall_item.get('RestartAction'):
            munkicommon.display_warning(
                'Ignoring unattended_uninstall key for %s '
                'because RestartAction is %s.'
                % (uninstall_item['name'],
                   uninstall_item.get('RestartAction')))
        else:
            iteminfo['unattended_uninstall'] = True

    # some keys we'll copy if they exist
    optionalKeys = ['blocking_applications',
                    'installs',
                    'requires',
                    'update_for']
    for key in optionalKeys:
        if key in uninstall_item:
            iteminfo[key] = uninstall_item[key]

    if packagesToRemove:
        # remove references for each package
        packagesToReallyRemove = []
        for pkg in packagesToRemove:
            munkicommon.display_debug1('Considering %s for removal...' % pkg)
            # find pkg in PKGDATA['pkg_references'] and remove the reference
            # so we only remove packages if we're the last reference to it
            if pkg in PKGDATA['pkg_references']:
                munkicommon.display_debug1('%s references are: %s' %
                                            (pkg,
                                             PKGDATA['pkg_references'][pkg]))
                PKGDATA['pkg_references'][pkg].remove(iteminfo['name'])
                if len(PKGDATA['pkg_references'][pkg]) == 0:
                    munkicommon.display_debug1('Adding %s to removal list.' %
                                                pkg)
                    packagesToReallyRemove.append(pkg)
            else:
                # This shouldn't happen
                munkicommon.display_warning('pkg id %s missing from pkgdata' %
                                             pkg)
        if packagesToReallyRemove:
            iteminfo['packages'] = packagesToReallyRemove
        else:
            # no packages that belong to this item only.
            munkicommon.display_warning('could not find unique packages to '
                                        'remove for %s' % iteminfo['name'])
            return False

    iteminfo['uninstall_method'] = uninstallmethod
    if uninstallmethod.startswith('Adobe'):
        if 'adobe_install_info' in item:
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
                iteminfo['adobe_package_name'] = \
                        uninstall_item.get('adobe_package_name','')
            except PackageVerificationError:
                munkicommon.display_warning(
                    'Can\'t uninstall %s because the integrity check '
                    'failed.' % iteminfo['name'])
                return False
            except MunkiDownloadError, errmsg:
                munkicommon.display_warning('Failed to download the '
                                            'uninstaller for %s because %s'
                                            % (iteminfo['name'], errmsg))
                return False
    elif uninstallmethod == 'remove_copied_items':
        iteminfo['items_to_remove'] = item.get('items_to_copy', [])
    elif uninstallmethod == 'remove_app':
        if uninstall_item.get('installs', None):
            iteminfo['remove_app_info'] = uninstall_item['installs'][0]
    elif uninstallmethod == 'uninstall_script':
        iteminfo['uninstall_script'] = item.get('uninstall_script','')

    # before we add this removal to the list,
    # check for installed updates and add them to the
    # removal list as well:
    update_list = lookForUpdates(iteminfo['name'], cataloglist)
    for update_item in update_list:
        # call us recursively...
        unused_result = processRemoval(update_item, cataloglist, installinfo)

    # finish recording info for this removal
    iteminfo['installed'] = True
    iteminfo['installed_version'] = uninstall_item.get('version')
    if 'RestartAction' in uninstall_item:
        iteminfo['RestartAction'] = uninstall_item['RestartAction']
    installinfo['removals'].append(iteminfo)
    munkicommon.display_detail(
        'Removal of %s added to ManagedInstaller tasks.' %
         manifestitemname_withversion)
    return True


def getManifestValueForKey(manifestpath, keyname):
    """Returns a value for keyname in manifestpath"""
    try:
        plist = FoundationPlist.readPlist(manifestpath)
    except FoundationPlist.NSPropertyListSerializationException:
        munkicommon.display_error('Could not read plist %s' % manifestpath)
        return None
    if keyname in plist:
        return plist[keyname]
    else:
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
    munkicommon.display_debug2('Catalog base URL is: %s' % catalogbaseurl)
    catalog_dir = os.path.join(munkicommon.pref('ManagedInstallDir'),
                               'catalogs')

    for catalogname in cataloglist:
        if not catalogname in CATALOG:
            catalogurl = catalogbaseurl + urllib2.quote(catalogname)
            catalogpath = os.path.join(catalog_dir, catalogname)
            munkicommon.display_detail('Getting catalog %s...' % catalogname)
            message = 'Retreiving catalog "%s"...' % catalogname
            try:
                unused_value = getResourceIfChangedAtomically(catalogurl,
                                                              catalogpath,
                                                              message=message)
            except MunkiDownloadError, err:
                munkicommon.display_error(
                    'Could not retrieve catalog %s from server.' %
                     catalogname)
                munkicommon.display_error(err)

            else:
                try:
                    catalogdata = FoundationPlist.readPlist(catalogpath)
                except FoundationPlist.NSPropertyListSerializationException:
                    munkicommon.display_error(
                        'Retreived catalog %s is invalid.' % catalogname)
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
    manifestbaseurl = munkicommon.pref('ManifestURL') or \
                      munkicommon.pref('SoftwareRepoURL') + '/manifests/'
    if not manifestbaseurl.endswith('?') and \
       not manifestbaseurl.endswith('/'):
        manifestbaseurl = manifestbaseurl + '/'
    manifest_dir = os.path.join(munkicommon.pref('ManagedInstallDir'),
                                'manifests')

    if (partialurl.startswith('http://') or partialurl.startswith('https://')
        or partialurl.startswith('file:/')):
        # then it's really a request for the client's primary manifest
        manifesturl = partialurl
        partialurl = 'client_manifest'
        manifestname = 'client_manifest.plist'
    else:
        # request for nested manifest
        manifestname = os.path.split(partialurl)[1]
        manifesturl = manifestbaseurl + urllib2.quote(partialurl)

    if manifestname in MANIFESTS:
        return MANIFESTS[manifestname]

    munkicommon.display_debug2('Manifest base URL is: %s' % manifestbaseurl)
    munkicommon.display_detail('Getting manifest %s...' % partialurl)
    manifestpath = os.path.join(manifest_dir, manifestname)
    message = 'Retreiving list of software for this machine...'
    try:
        unused_value = getResourceIfChangedAtomically(manifesturl,
                                                      manifestpath,
                                                      message=message)
    except MunkiDownloadError, err:
        if not suppress_errors:
            munkicommon.display_error(
                'Could not retrieve manifest %s from the server.' %
                 partialurl)
            munkicommon.display_error(str(err))
        return None

    try:
        # read plist to see if it is valid
        unused_data = FoundationPlist.readPlist(manifestpath)
    except FoundationPlist.NSPropertyListSerializationException:
        errormsg = 'manifest returned for %s is invalid.' % partialurl
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


def getPrimaryManifest(alternate_id):
    """Gets the client manifest from the server."""
    manifest = ""
    manifesturl = munkicommon.pref('ManifestURL') or \
                  munkicommon.pref('SoftwareRepoURL') + '/manifests/'
    if not manifesturl.endswith('?') and not manifesturl.endswith('/'):
        manifesturl = manifesturl + '/'
    munkicommon.display_debug2('Manifest base URL is: %s' % manifesturl)

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
            clientidentifier = hostname
            munkicommon.display_detail('No client id specified. '
                                       'Requesting %s...' % clientidentifier)
            manifest = getmanifest(manifesturl + clientidentifier,
                                   suppress_errors=True)
            if not manifest:
                # try the short hostname
                clientidentifier = hostname.split('.')[0]
                munkicommon.display_detail('Request failed. Trying %s...' %
                                            clientidentifier)
                manifest = getmanifest(manifesturl + clientidentifier,
                                        suppress_errors=True)
                if not manifest:
                    # last resort - try for the site_default manifest
                    clientidentifier = 'site_default'
                    munkicommon.display_detail('Request failed. ' +
                                               'Trying %s...' %
                                                clientidentifier)

        if not manifest:
            manifest = getmanifest(
                manifesturl + urllib2.quote(clientidentifier.encode('utf-8')))
        if manifest:
            # record this info for later
            munkicommon.report['ManifestName'] = clientidentifier
            munkicommon.display_detail('Using manifest: %s' %
                                        clientidentifier)
    except ManifestException:
        # bad manifests throw an exception
        pass
    return manifest


def checkServer(url):
    """A function we can call to check to see if the server is
    available before we kick off a full run. This can be fooled by
    ISPs that return results for non-existent web servers..."""
    # deconstruct URL so we can check availability
    (scheme, netloc,
     path, unused_query, unused_fragment) = urlparse.urlsplit(url)
    if scheme == 'http':
        port = 80
    elif scheme == 'https':
        port = 443
    elif scheme == 'file':
        if os.path.exists(path):
            return (0, 'OK')
        else:
            return (-1, '%s does not exist' % path)
    else:
        return (-1, 'Unsupported URL scheme')

    # get rid of any embedded username/password
    netlocparts = netloc.split('@')
    netloc = netlocparts[-1]
    # split into host and port if present
    netlocparts = netloc.split(':')
    host = netlocparts[0]
    if host == "":
        return (-1, 'Bad URL')
    if len(netlocparts) == 2:
        port = int(netlocparts[1])
    sock = socket.socket()
    # set timeout to 5 secs
    sock.settimeout(5.0)
    try:
        sock.connect((host, port))
        sock.close()
        return (0, 'OK')
    except socket.error, err:
        if type(err) == str:
            return (-1, err)
        else:
            return err
    except socket.timeout, err:
        return (-1, err)
    except Exception, err:
        # common errors
        # (50, 'Network is down')
        # (8, 'nodename nor servname provided, or not known')
        # (61, 'Connection refused')
        return tuple(err)


###########################################
# New HTTP download code
# using curl
###########################################

class CurlError(Exception):
    pass


class HTTPError(Exception):
    pass


WARNINGSLOGGED = {}
def curl(url, destinationpath, onlyifnewer=False, etag=None, resume=False,
         cacert=None, capath=None, cert=None, key=None, message=None,
         donotrecurse=False):
    """Gets an HTTP or HTTPS URL and stores it in
    destination path. Returns a dictionary of headers, which includes
    http_result_code and http_result_description.
    Will raise CurlError if curl returns an error.
    Will raise HTTPError if HTTP Result code is not 2xx or 304.
    If destinationpath already exists, you can set 'onlyifnewer' to true to
    indicate you only want to download the file only if it's newer on the
    server.
    If you have an ETag from the current destination path, you can pass that
    to download the file only if it is different.
    Finally, if you set resume to True, curl will attempt to resume an
    interrupted download. You'll get an error if the existing file is
    complete; if the file has changed since the first download attempt, you'll
    get a mess."""

    header = {}
    header['http_result_code'] = '000'
    header['http_result_description'] = ""

    curldirectivepath = os.path.join(munkicommon.tmpdir,'curl_temp')
    tempdownloadpath = destinationpath + '.download'

    # we're writing all the curl options to a file and passing that to
    # curl so we avoid the problem of URLs showing up in a process listing
    try:
        fileobj = open(curldirectivepath, mode='w')
        print >> fileobj, 'silent'         # no progress meter
        print >> fileobj, 'show-error'     # print error msg to stderr
        print >> fileobj, 'no-buffer'      # don't buffer output
        print >> fileobj, 'fail'           # throw error if download fails
        print >> fileobj, 'dump-header -'  # dump headers to stdout
        print >> fileobj, 'speed-time = 30' # give up if too slow d/l
        print >> fileobj, 'output = "%s"' % tempdownloadpath
        print >> fileobj, 'ciphers = HIGH,!ADH' # use only secure >=128 bit SSL
        print >> fileobj, 'url = "%s"' % url

        if cacert:
            if not os.path.isfile(cacert):
                raise CurlError(-1, 'No CA cert at %s' % cacert)
            print >> fileobj, 'cacert = "%s"' % cacert
        if capath:
            if not os.path.isdir(capath):
                raise CurlError(-2, 'No CA directory at %s' % capath)
            print >> fileobj, 'capath = "%s"' % capath
        if cert:
            if not os.path.isfile(cert):
                raise CurlError(-3, 'No client cert at %s' % cert)
            print >> fileobj, 'cert = "%s"' % cert
        if key:
            if not os.path.isfile(key):
                raise CurlError(-4, 'No client key at %s' % key)
            print >> fileobj, 'key = "%s"' % key

        if os.path.exists(destinationpath):
            if etag:
                escaped_etag = etag.replace('"','\\"')
                print >> fileobj, ('header = "If-None-Match: %s"'
                                                        % escaped_etag)
            elif onlyifnewer:
                print >> fileobj, 'time-cond = "%s"' % destinationpath
            else:
                os.remove(destinationpath)

        if os.path.exists(tempdownloadpath):
            if resume and not os.path.exists(destinationpath):
                # let's try to resume this download
                print >> fileobj, 'continue-at -'
                # if an existing etag, only resume if etags still match.
                tempetag = None
                if ('com.googlecode.munki.etag' in
                        xattr.listxattr(tempdownloadpath)):
                    tempetag = xattr.getxattr(tempdownloadpath,
                        'com.googlecode.munki.etag')
                if tempetag:
                    # Note: If-Range is more efficient, but the response
                    # confuses curl (Error: 33 if etag not match).
                    escaped_etag = tempetag.replace('"','\\"')
                    print >> fileobj, ('header = "If-Match: %s"'
                                        % escaped_etag)
            else:
                os.remove(tempdownloadpath)

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
        if custom_headers:
            for custom_header in custom_headers:
                custom_header = custom_header.strip().encode('utf-8')
                if re.search(r'^[\w-]+:.+', custom_header):
                    print >> fileobj, ('header = "%s"' % custom_header)
                else:
                    munkicommon.display_warning(
                        'Skipping invalid HTTP header: %s' % custom_header)

        fileobj.close()
    except Exception, e:
        raise CurlError(-5, 'Error writing curl directive: %s' % str(e))

    cmd = ['/usr/bin/curl',
            '-q',                    # don't read .curlrc file
            '--config',              # use config file
            curldirectivepath]

    proc = subprocess.Popen(cmd, shell=False, bufsize=1,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    targetsize = 0
    downloadedpercent = -1
    donewithheaders = False

    while True:
        if not donewithheaders:
            info =  proc.stdout.readline().strip('\r\n')
            if info:
                if info.startswith('HTTP/'):
                    header['http_result_code'] = info.split(None, 2)[1]
                    header['http_result_description'] = info.split(None, 2)[2]
                elif ': ' in info:
                    part = info.split(None, 1)
                    fieldname = part[0].rstrip(':').lower()
                    header[fieldname] = part[1]
            else:
                # we got an empty line; end of headers (or curl exited)
                donewithheaders = True
                try:
                    targetsize = int(header.get('content-length'))
                except (ValueError, TypeError):
                    targetsize = 0
                if header.get('http_result_code') == '206':
                    # partial content because we're resuming
                    munkicommon.display_detail(
                        'Resuming partial download for %s' %
                                        os.path.basename(destinationpath))
                    contentrange = header.get('content-range')
                    if contentrange.startswith('bytes'):
                        try:
                            targetsize = int(contentrange.split('/')[1])
                        except (ValueError, TypeError):
                            targetsize = 0

                if message and header.get('http_result_code') != '304':
                    if message:
                        # log always, display if verbose is 2 or more
                        munkicommon.display_detail(message)
                        if munkicommon.munkistatusoutput:
                            # send to detail field on MunkiStatus
                            munkistatus.detail(message)

        elif targetsize and header.get('http_result_code').startswith('2'):
            # display progress if we get a 2xx result code
            if os.path.exists(tempdownloadpath):
                downloadedsize = os.path.getsize(tempdownloadpath)
                percent = int(float(downloadedsize)
                                    /float(targetsize)*100)
                if percent != downloadedpercent:
                    # percent changed; update display
                    downloadedpercent = percent
                    munkicommon.display_percent_done(downloadedpercent, 100)
            time.sleep(0.1)

        if (proc.poll() != None):
            break

    retcode = proc.poll()
    if retcode:
        curlerr = ''
        try:
            curlerr = proc.stderr.read().rstrip('\n')
            curlerr = curlerr.split(None, 2)[2]
        except IndexError:
            pass
        if retcode == 22:
            # 22 means any 400 series return code. Note: header seems not to
            # be dumped to STDOUT for immediate failures. Hence
            # http_result_code is likely blank/000. Read it from stderr.
            if re.search(r'URL returned error: [0-9]+$', curlerr):
                header['http_result_code'] = curlerr[curlerr.rfind(' ')+1:]

        if os.path.exists(tempdownloadpath):
            if not resume:
                os.remove(tempdownloadpath)
            elif retcode == 33 or header.get('http_result_code') == '412':
                # 33: server doesn't support range requests
                # 412: Etag didn't match (precondition failed), could not
                #   resume partial download as file on server has changed.
                if retcode == 33 and not 'HTTPRange' in WARNINGSLOGGED:
                    munkicommon.display_warning('Web server refused ' +
                            'partial/range request. Munki cannot run ' +
                            'efficiently when this support is absent for ' +
                            'pkg urls. URL: %s'
                            % url)
                    WARNINGSLOGGED['HTTPRange'] = 1
                os.remove(tempdownloadpath)
                # The partial failed immediately as not supported.
                # Try a full download again immediately.
                if not donotrecurse:
                    return curl(url, destinationpath, onlyifnewer=onlyifnewer,
                                etag=etag, resume=resume, cacert=cacert,
                                capath=capath, cert=cert, key=key,
                                message=message, donotrecurse=True)
            elif retcode == 22:
                # TODO: Made http(s) connection but 400 series error. What should we do?
                # 403 could be ok, just that someone is currently offsite and the server is refusing the service them while there.
                # 404 could be an interception proxy at a public wifi point. The partial may still be ok later.
                # 416 could be dangerous - the targeted resource may now be different / smaller. We need to delete the temp or retrying will never work.
                if header.get('http_result_code') == 416:
                    # Bad range request.
                    os.remove(tempdownloadpath)
                elif header.get('http_result_code') == 503:
                    # Web server temporarily unavailable.
                    pass
                elif not header.get('http_result_code').startswith('4'):
                    # 500 series, or no error code parsed.
                    # Perhaps the webserver gets really confused by partial
                    # requests. It is likely majorly misconfigured so we won't
                    # try asking it anything challenging.
                    os.remove(tempdownloadpath)
            elif header.get('etag'):
                xattr.setxattr(tempdownloadpath,
                               'com.googlecode.munki.etag', header['etag'])
        # TODO: should we log this diagnostic here (we didn't previously)?
        # Currently for a pkg all that is logged on failure is:
        # "WARNING: Download of Firefox failed." with no detail. Logging at
        # the place where this exception is caught has to be done in many places.
        munkicommon.display_detail('Download error: %s. Failed (%s) with: %s'
                                    % (url,retcode,curlerr))
        raise CurlError(retcode, curlerr)
    else:
        temp_download_exists = os.path.isfile(tempdownloadpath)
        http_result = header.get('http_result_code')
        if http_result.startswith('2') and \
            temp_download_exists:
            downloadedsize = os.path.getsize(tempdownloadpath)
            if downloadedsize >= targetsize:
                if not downloadedpercent == 100:
                    munkicommon.display_percent_done(100, 100)
                os.rename(tempdownloadpath, destinationpath)
                if resume and not header.get('etag') and not 'HTTPetag' in WARNINGSLOGGED:
                    munkicommon.display_warning('Web server did not return an etag. Munki cannot safely resume downloads without etag support on the web server. URL: %s' % url)
                    WARNINGSLOGGED['HTTPetag'] = 1
                return header
            else:
                # not enough bytes retreived
                if not resume and temp_download_exists:
                    os.remove(tempdownloadpath)
                raise CurlError(-5, 'Expected %s bytes, got: %s' %
                                        (targetsize, downloadedsize))
        elif http_result == '304':
            return header
        else:
            # there was a download error of some sort; clean all relevant
            # downloads that may be in a bad state.
            for f in [tempdownloadpath, destinationpath]:
                try:
                    os.unlink(f)
                except OSError:
                    pass
            raise HTTPError(http_result,
                                header.get('http_result_description',''))


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


def getResourceIfChangedAtomically(url, destinationpath,
                                 message=None, resume=False):
    """Gets file from a URL, checking first to see if it has changed on the
       server.

       Supported schemes are http, https, file.

       Returns True if a new download was required; False if the
       item is already in the local cache.

       Raises a MunkiDownloadError derived class if there is an error."""

    url_parse = urlparse.urlparse(url)

    if url_parse.scheme in ['http', 'https']:
        return getHTTPfileIfChangedAtomically(
                url, destinationpath, message, resume)
    elif url_parse.scheme in ['file']:
        return getFileIfChangedAtomically(
                url_parse.path, destinationpath)
    # TODO: in theory NFS, AFP, or SMB could be supported here.
    else:
        raise MunkiDownloadError(
                'Unsupported scheme for %s: %s' % (url, url_parse.scheme))


def getFileIfChangedAtomically(path, destinationpath):
    """Gets file from path, checking first to see if it has changed on the
       source.

       Returns True if a new copy was required; False if the
       item is already in the local cache.

       Raises FileCopyError if there is an error."""

    try:
        st_src = os.stat(path)
    except OSError:
        raise FileCopyError('Source does not exist: %s' % path)

    try:
        st_dst = os.stat(destinationpath)
    except OSError:
        st_dst = None

    # if the destination exists, with same mtime and size, already cached
    if st_dst is not None and (
        st_src.st_mtime == st_dst.st_mtime and
        st_src.st_size == st_dst.st_size):
        return False

    # write to a temporary destination
    tmp_destinationpath = '%s.download' % destinationpath

    # remove the temporary destination if it exists
    try:
        if st_dst:
            os.unlink(tmp_destinationpath)
    except OSError, e:
        if e.args[0] == errno.ENOENT:
            pass  # OK
        else:
            raise FileCopyError('Removing %s: %s' % (
                tmp_destinationpath, str(e)))

    # copy from source to temporary destination
    try:
        shutil.copy2(path, tmp_destinationpath)
    except IOError, e:
        raise FileCopyError('Copy IOError: %s' % str(e))

    # rename temp destination to final destination
    try:
        os.rename(tmp_destinationpath, destinationpath)
    except OSError, e:
        raise FileCopyError('Renaming %s: %s' % (destinationpath, str(e)))

    return True


def getHTTPfileIfChangedAtomically(url, destinationpath,
                                 message=None, resume=False):
    """Gets file from HTTP URL, checking first to see if it has changed on the
       server.

       Returns True if a new download was required; False if the
       item is already in the local cache.

       Raises CurlDownloadError if there is an error."""

    ManagedInstallDir = munkicommon.pref('ManagedInstallDir')
    # get server CA cert if it exists so we can verify the munki server
    ca_cert_path = None
    ca_dir_path = None
    if munkicommon.pref('SoftwareRepoCAPath'):
        CA_path = munkicommon.pref('SoftwareRepoCAPath')
        if os.path.isfile(CA_path):
            ca_cert_path = CA_path
        elif os.path.isdir(CA_path):
            ca_dir_path = CA_path
    if munkicommon.pref('SoftwareRepoCACertificate'):
        ca_cert_path = munkicommon.pref('SoftwareRepoCACertificate')
    if ca_cert_path == None:
        ca_cert_path = os.path.join(ManagedInstallDir, 'certs', 'ca.pem')
        if not os.path.exists(ca_cert_path):
            ca_cert_path = None

    client_cert_path = None
    client_key_path = None
    # get client cert if it exists
    if munkicommon.pref('UseClientCertificate'):
        client_cert_path = munkicommon.pref('ClientCertificatePath') or None
        client_key_path = munkicommon.pref('ClientKeyPath') or None
        if not client_cert_path:
            for name in ['cert.pem', 'client.pem', 'munki.pem']:
                client_cert_path = os.path.join(ManagedInstallDir, 'certs',
                                                                    name)
                if os.path.exists(client_cert_path):
                    break

    etag = None
    getonlyifnewer = False
    if os.path.exists(destinationpath):
        getonlyifnewer = True
        # see if we have an etag attribute
        if 'com.googlecode.munki.etag' in xattr.listxattr(destinationpath):
            getonlyifnewer = False
            etag = xattr.getxattr(destinationpath,
                                  'com.googlecode.munki.etag')

    try:
        header = curl(url,
                      destinationpath,
                      cert=client_cert_path,
                      key=client_key_path,
                      cacert=ca_cert_path,
                      capath=ca_dir_path,
                      onlyifnewer=getonlyifnewer,
                      etag=etag,
                      resume=resume,
                      message=message)

    except CurlError, err:
        err = 'Error %s: %s' % tuple(err)
        raise CurlDownloadError(err)

    except HTTPError, err:
        err = 'HTTP result %s: %s' % tuple(err)
        raise CurlDownloadError(err)

    err = None
    if header['http_result_code'] == '304':
        # not modified, return existing file
        munkicommon.display_debug1('%s already exists and is up-to-date.'
                                        % destinationpath)
        # file is in cache and is unchanged, so we return False
        return False
    else:
        if header.get('last-modified'):
            # set the modtime of the downloaded file to the modtime of the
            # file on the server
            modtimestr = header['last-modified']
            modtimetuple = time.strptime(modtimestr,
                                         '%a, %d %b %Y %H:%M:%S %Z')
            modtimeint = calendar.timegm(modtimetuple)
            os.utime(destinationpath, (time.time(), modtimeint))
        if header.get('etag'):
            # store etag in extended attribute for future use
            xattr.setxattr(destinationpath,
                           'com.googlecode.munki.etag', header['etag'])

    return True


# we only want to call sw_vers and the like once. Since these values don't
# change often, we store the info in MACHINE.
MACHINE = {}
def getMachineFacts():
    """Gets some facts about this machine we use to determine if a given
    installer is applicable to this OS or hardware"""
    #global MACHINE

    MACHINE['hostname'] = os.uname()[1]
    MACHINE['arch'] = os.uname()[4]
    cmd = ['/usr/bin/sw_vers', '-productVersion']
    proc = subprocess.Popen(cmd, shell=False, bufsize=1,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (output, unused_err) = proc.communicate()
    MACHINE['os_vers'] = str(output).rstrip('\n')


def check(client_id='', localmanifestpath=None):
    """Checks for available new or updated managed software, downloading
    installer items if needed. Returns 1 if there are available updates,
    0 if there are no available updates, and -1 if there were errors."""
    getMachineFacts()
    munkicommon.report['MachineInfo'] = MACHINE

    ManagedInstallDir = munkicommon.pref('ManagedInstallDir')

    if munkicommon.munkistatusoutput:
        munkistatus.activate()
        munkistatus.message('Checking for available updates...')
        munkistatus.detail('')
        munkistatus.percent('-1')

    munkicommon.log('### Beginning managed software check ###')

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
            unused_result = processRemoval(item, cataloglist, installinfo)

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

        # now process any self-serve choices
        usermanifest = '/Users/Shared/.SelfServeManifest'
        selfservemanifest = os.path.join(ManagedInstallDir, 'manifests',
                                                'SelfServeManifest')
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
                pass

        if os.path.exists(selfservemanifest):
            # use catalogs from main manifest for self-serve manifest
            cataloglist = getManifestValueForKey(
                                            mainmanifestpath, 'catalogs')
            munkicommon.display_detail(
                '**Processing self-serve choices**')
            selfserveinstalls = getManifestValueForKey(selfservemanifest,
                                                       'managed_installs')
            available_optional_installs = [item['name']
                for item in installinfo.get('optional_installs',[])]
            # filter the list, removing any items not in the current list
            # of available self-serve installs
            selfserveinstalls = [item for item in selfserveinstalls
                                 if item in available_optional_installs]
            for item in selfserveinstalls:
                unused_result = processInstall(
                    item, cataloglist, installinfo)
            # we don't need to filter uninstalls
            processManifestForKey(selfservemanifest, 'managed_uninstalls',
                                  installinfo, cataloglist)

            # update optional_installs with install/removal info
            for item in installinfo['optional_installs']:
                if (not item.get('installed') and
                    isItemInInstallInfo(item,
                                        installinfo['managed_installs'])):
                    item['will_be_installed'] = True
                elif (item.get('installed') and
                      isItemInInstallInfo(item,
                                          installinfo['removals'])):
                    item['will_be_removed'] = True

        # filter managed_installs to get items already installed
        installed_items = [item.get('name','')
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
        removed_items = [item.get('name','')
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
                plist['managed_uninstalls'] = \
                    [item for item in plist.get('managed_uninstalls',[])
                        if item not in removed_items]
                try:
                    FoundationPlist.writePlist(plist, selfservemanifest)
                except FoundationPlist.FoundationPlistException:
                    pass

        # record detail before we throw it away...
        munkicommon.report['ManagedInstalls'] = \
            installinfo['managed_installs']
        munkicommon.report['InstalledItems'] = installed_items
        munkicommon.report['ProblemInstalls'] = problem_items
        munkicommon.report['RemovedItems'] = removed_items

        munkicommon.report['managed_installs_list'] = \
            installinfo['processed_installs']
        munkicommon.report['managed_uninstalls_list'] = \
            installinfo['processed_uninstalls']
        munkicommon.report['managed_updates_list'] = \
            installinfo['managed_updates']

        # filter managed_installs and removals lists
        # so they have only items that need action
        installinfo['managed_installs'] = \
            [item for item in installinfo['managed_installs']
                    if item.get('installer_item')]
        installinfo['removals'] = \
            [item for item in installinfo['removals']
                if item.get('installed')]

        # record the filtered lists
        munkicommon.report['ItemsToInstall'] = installinfo['managed_installs']
        munkicommon.report['ItemsToRemove'] = installinfo['removals']

        # clean up catalogs directory
        cleanUpCatalogs()

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
                munkicommon.display_detail(
                                        'Removing %s from cache' % item)
                os.unlink(os.path.join(cachedir, item))

        # write out install list so our installer
        # can use it to install things in the right order
        installinfochanged = True
        installinfopath = os.path.join(ManagedInstallDir, 'InstallInfo.plist')
        if os.path.exists(installinfopath):
            oldinstallinfo = FoundationPlist.readPlist(installinfopath)
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


    installcount = len(installinfo.get('managed_installs', []))
    removalcount = len(installinfo.get('removals', []))

    munkicommon.log('')
    if installcount:
        munkicommon.display_info(
            'The following items will be installed or upgraded:')
    for item in installinfo['managed_installs']:
        if item.get('installer_item'):
            munkicommon.display_info('    + %s-%s' %
                                     (item.get('name',''),
                                      item.get('version_to_install','')))
            if item.get('description'):
                munkicommon.display_info('        %s' % item['description'])
            if item.get('RestartAction') == 'RequireRestart' or \
               item.get('RestartAction') == 'RecommendRestart':
                munkicommon.display_info('       *Restart required')
                munkicommon.report['RestartRequired'] = True
            if item.get('RestartAction') == 'RequireLogout':
                munkicommon.display_info('       *Logout required')
                munkicommon.report['LogoutRequired'] = True

    if removalcount:
        munkicommon.display_info('The following items will be removed:')
    for item in installinfo['removals']:
        if item.get('installed'):
            munkicommon.display_info('    - %s' % item.get('name'))
            if item.get('RestartAction') == 'RequireRestart' or \
               item.get('RestartAction') == 'RecommendRestart':
                munkicommon.display_info('       *Restart required')
                munkicommon.report['RestartRequired'] = True
            if item.get('RestartAction') == 'RequireLogout':
                munkicommon.display_info('       *Logout required')
                munkicommon.report['LogoutRequired'] = True

    if installcount == 0 and removalcount == 0:
        munkicommon.display_info(
            'No changes to managed software are available.')

    munkicommon.savereport()
    munkicommon.log('###    End managed software check    ###')

    if installcount or removalcount:
        return 1
    else:
        return 0


def main():
    """Placeholder"""
    pass


if __name__ == '__main__':
    main()

