#!/usr/bin/python
# encoding: utf-8
#
# Copyright 2009-2010 Greg Neagle.
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
import os
import re
import subprocess
import socket
import time
import urllib2
import urlparse
import xattr
from distutils import version
from OpenSSL.crypto import load_certificate, FILETYPE_PEM

#our libs
import munkicommon
import munkistatus
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
        vers = munkicommon.padVersionString(vers, 5)

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
        installitems = os.listdir(receiptsdir)
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
                        if version.LooseVersion(thisversion) > \
                           version.LooseVersion(storedversion):
                            INSTALLEDPKGS[pkgid] = thisversion


# global pkgdata
PKGDATA  = {}
def analyzeInstalledPkgs():
    """Analyzed installed packages in an attempt to determine what is
       installed."""
    global PKGDATA
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

    PKGDATA = {}
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
    thisvers = munkicommon.padVersionString(thisvers, 5)
    thatvers = munkicommon.padVersionString(thatvers, 5)
    if version.LooseVersion(thisvers) < version.LooseVersion(thatvers):
        return -1
    elif version.LooseVersion(thisvers) == version.LooseVersion(thatvers):
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
                        munkicommon.display_debug2(('Skipped '
                            'app %s with path %s') % (
                            item['name'], item['path']))
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


    Raises munkicommon.Error is there's a problem with the input.
    """
    if 'path' in item:
        filepath = item['path']
        munkicommon.display_debug1('Checking existence of %s...' % filepath)
        if os.path.exists(filepath):
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
      item_plist: plist of an item to get the version for.

    Returns:
      String version of the item, or 'UNKNOWN' if unable to determine.

    NOTE:
      This function is too slow, and slows down the update check process so
      much that we stopped trying to figure out the currently installed
      version -- leaving this function currently unused. Maybe we can revisit
      in the future and speed it up so it's usable.
    """
    if 'receipts' in item_plist:
        for receipt in item_plist['receipts']:
            installedpkgvers = \
                munkicommon.getInstalledPackageVersion(receipt['packageid'])
            munkicommon.display_debug2('Looking for %s, version %s' %
                                        (receipt['packageid'],
                                         receipt['version']))
            if compareVersions(installedpkgvers, receipt['version']) == 2:
                # version is higher
                installedversion = 'newer than %s' % item_plist['version']
                return installedversion
            if compareVersions(installedpkgvers, receipt['version']) == -1:
                # version is lower
                installedversion = 'older than %s' % item_plist['version']
                return installedversion
        # if we get here all receipts match
        return item_plist['version']

    if 'installs' in item_plist:
        for install_item in item_plist['installs']:
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
                    installedappvers = plist.get('CFBundleShortVersionString')
                except FoundationPlist.NSPropertyListSerializationException:
                    # that didn't work, fall through to the slow way
                    # using System Profiler
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
                    installedappvers = maxversion

            if compareVersions(installedappvers,
                            install_item['CFBundleShortVersionString']) == 2:
                # version is higher
                installedversion = 'newer than %s' % plist['version']
                return installedversion

            if compareVersions(installedappvers,
                            install_item['CFBundleShortVersionString']) == -1:
                # version is lower
                installedversion = 'older than %s' % plist['version']
                return installedversion

        # if we get here all app versions match
        return item_plist['version']

    # if we fall through to here we have no idea what version we have
    return 'UNKNOWN'

class MunkiDownloadError(Exception):
    """Base exception for download errors"""
    pass

class CurlDownloadError(MunkiDownloadError):
    """Curl failed to download the item"""
    pass

class PackageVerificationError(MunkiDownloadError):
    """Download failed because it coud not be verified"""
    pass

def download_installeritem(item_pl):
    """Downloads a installer item. Raises an error if there are issues..."""
    location = item_pl.get('installer_item_location')
    if not location:
        raise MunkiDownloadError("No installer_item_location in item info.")

    ManagedInstallDir = munkicommon.pref('ManagedInstallDir')
    downloadbaseurl = munkicommon.pref('PackageURL') or \
                      munkicommon.pref('SoftwareRepoURL') + '/pkgs/'
    if not downloadbaseurl.endswith('/'):
        downloadbaseurl = downloadbaseurl + '/'
    munkicommon.display_debug2('Download base URL is: %s' % downloadbaseurl)

    mycachedir = os.path.join(ManagedInstallDir, 'Cache')

    # build a URL, quoting the the location to encode reserved characters
    pkgurl = downloadbaseurl + urllib2.quote(location)

    # grab last path component of location to derive package name.
    pkgname = os.path.basename(location)
    destinationpath = os.path.join(mycachedir, pkgname)

    munkicommon.display_detail('Downloading %s from %s' % (pkgname, location))
    # bump up verboseness so we get download percentage done feedback.
    # this is kind of a hack...
    oldverbose = munkicommon.verbose
    munkicommon.verbose = oldverbose + 1
    dl_message = 'Downloading %s...' % pkgname
    try:
        changed = getHTTPfileIfChangedAtomically(pkgurl, destinationpath,
                                                 resume=True,
                                                 message=dl_message)
    except CurlDownloadError:
        munkicommon.verbose = oldverbose
        raise

    # set verboseness back.
    munkicommon.verbose = oldverbose
    if changed:
        if not verifySoftwarePackageIntegrity(destinationpath, item_pl,
                                              'installer_item_hash'):
            raise PackageVerificationError()


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
        return cmp(version.LooseVersion(b['version']),
                   version.LooseVersion(a['version']))

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


def getItemDetail(name, cataloglist, vers=''):
    """Searches the catalogs in list for an item matching the given name.

    If no version is supplied, but the version is appended to the name
    ('TextWrangler--2.3.0.0.0') that version is used.
    If no version is given at all, the latest version is assumed.
    Returns a pkginfo item.
    """
    def compare_version_keys(a, b):
        """Internal comparison function for use in sorting"""
        return cmp(version.LooseVersion(b), version.LooseVersion(a))

    (name, includedversion) = nameAndVersion(name)
    if vers == '':
        if includedversion:
            vers = includedversion
    if vers:
        # make sure version is in 1.0.0.0.0 format
        vers = munkicommon.padVersionString(vers, 5)
    else:
        vers = 'latest'

    munkicommon.display_debug1('Looking for detail for: %s, version %s...' %
                                (name, vers))
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
                    min_os_vers = \
                        munkicommon.padVersionString(
                                                item['minimum_os_version'],3)
                    munkicommon.display_debug1(
                        'Considering item %s, ' % item['name'] +
                        'version %s ' % item['version'] +
                        'with minimum os version required %s' % min_os_vers)
                    munkicommon.display_debug2('Our OS version is %s' %
                                                MACHINE['os_vers'])
                    if version.LooseVersion(MACHINE['os_vers']) < \
                       version.LooseVersion(min_os_vers):
                        # skip this one, go to the next
                        continue

                if 'maximum_os_version' in item:
                    max_os_vers = \
                        munkicommon.padVersionString(
                                                item['maximum_os_version'],3)
                    munkicommon.display_debug1(
                        'Considering item %s, ' % item['name'] +
                        'version %s ' % item['version'] +
                        'with maximum os version supported %s' % max_os_vers)
                    munkicommon.display_debug2('Our OS version is %s' %
                                                MACHINE['os_vers'])
                    if version.LooseVersion(MACHINE['os_vers']) > \
                       version.LooseVersion(max_os_vers):
                        # skip this one, go to the next
                        continue

                if 'supported_architectures' in item:
                    supported_arch_found = False
                    munkicommon.display_debug1(
                        'Considering item %s, ' % item['name'] +
                        'version %s ' % item['version'] +
                        'with supported architectures: %s' %
                                            item['supported_architectures'])
                    for arch in item['supported_architectures']:
                        if arch == MACHINE['arch']:
                            # we found a supported architecture that matches
                            # this machine, so we can use it
                            supported_arch_found = True
                            break

                    if not supported_arch_found:
                        # we didn't find a supported architecture that
                        # matches this machine
                        continue

                # item name, version, minimum_os_version, and
                # supported_architecture are all OK
                munkicommon.display_debug1(
                    'Found %s, version %s in catalog %s' %
                    (item['name'], item['version'], catalogname))
                return item

    # if we got this far, we didn't find it.
    munkicommon.display_debug1('Nothing found')
    return None


def enoughDiskSpace(manifestitem_pl, installlist=None, 
                    uninstalling=False, warn=True):
    """Determine if there is enough disk space to download the manifestitem."""
    # fudgefactor is set to 100MB
    fudgefactor = 102400
    installeritemsize = 0
    installedsize = 0
    alreadydownloadedsize = 0
    if 'installer_item_location' in manifestitem_pl:
        cachedir = os.path.join(munkicommon.pref('ManagedInstallDir'),'Cache')
        download = os.path.join(cachedir,
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


def isInstalled(item_pl):
    """Checks to see if the item described by item_pl (or a newer version) is
    currently installed

    All tests must pass to be considered installed.
    Returns True if it looks like this or a newer version
    is installed; False otherwise.
    """
    # does 'installs' exist and is it non-empty?
    if item_pl.get('installs', None):
        installitems = item_pl['installs']
        for item in installitems:
            itemtype = item.get('type')
            try:
                if itemtype == 'application':
                    if compareApplicationVersion(item) in (-1, 0):
                        return False
                if itemtype == 'bundle':
                    if compareBundleVersion(item) in (-1, 0):
                        # not there or older
                        return False
                if itemtype == 'plist':
                    if comparePlistVersion(item) in (-1, 0):
                        # not there or older
                        return False
                if itemtype == 'file':
                    if filesystemItemExists(item) in (-1, 0):
                        # not there, or wrong checksum
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
                if compareReceiptVersion(item) in (-1, 0):
                    # not there or older
                    return False
            except munkicommon.Error, errmsg:
                # some problem with the receipts data
                munkicommon.display_error(errmsg)
                return False

    # if we got this far, we passed all the tests, so the item
    # must be installed (or we don't have enough info...)
    return True


def someVersionInstalled(item_pl):
    """Checks to see if some version of an item is installed.

    Args:
      item_pl: item plist for the item to check for version of.
    """
    # does 'installs' exist and is it non-empty?
    if item_pl.get('installs', None):
        installitems = item_pl['installs']
        for item in installitems:
            itemtype = item.get('type')
            try:
                if itemtype == 'application':
                    if compareApplicationVersion(item) == 0:
                        # not there
                        return False
                if itemtype == 'bundle':
                    if compareBundleVersion(item) == 0:
                        # not there
                        return False
                if itemtype == 'plist':
                    if comparePlistVersion(item) == 0:
                        # not there
                        return False
                if itemtype == 'file':
                    if filesystemItemExists(item) == 0 :
                        # not there, or wrong checksum
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
    So this isn't the same as isInstalled()
    This is used when determining if we can remove the item, thus
    the attention given to the uninstall method.
    """
    if item_pl.get('uninstall_method') == 'removepackages':
        # we're supposed to use receipt info to remove
        # this, so we should check for relevent receipts
        if item_pl.get('receipts'):
            if PKGDATA == {}:
                # build our database of installed packages
                analyzeInstalledPkgs()
            if item_pl['name'] in PKGDATA['installed_names']:
                return True
    elif 'installs' in item_pl:
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
    in cataloglist. Filters those against items in the managed_installs
    list, which should contain everything that is supposed to be installed.
    Then filters against the removals list, which contains all the removals
    that have already been processed.
    """
    autoremovalnames = []
    for catalogname in cataloglist:
        if catalogname in CATALOG.keys():
            autoremovalnames += CATALOG[catalogname]['autoremoveitems']

    already_processed_names = [item['name']
                              for item in
                                  installinfo.get('managed_installs',[])]
    already_processed_names += [item['manifestitem']
                                for item in installinfo.get('removals',[])]
    autoremovalnames = [item for item in autoremovalnames
                             if item not in already_processed_names]
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
    item_pl = getItemDetail(manifestitem, cataloglist)

    if not item_pl:
        munkicommon.display_warning(
            'Could not process item %s for update: ' % manifestitem)
        munkicommon.display_warning(
            'No pkginfo for %s found in catalogs: %s' %
            (manifestitem, ', '.join(cataloglist)))
        return
    # check to see if item (any version) is already in the update list:
    if isItemInInstallInfo(item_pl, installinfo['managed_updates']):
        munkicommon.display_debug1(
            '%s has already been processed for update.' % manifestitemname)
        return
    # check to see if item (any version) is already in the installlist:
    if isItemInInstallInfo(item_pl, installinfo['managed_installs']):
        munkicommon.display_debug1(
            '%s has already been processed for install.' % manifestitemname)
        return
    # check to see if item (any version) is already in the removallist:
    if isItemInInstallInfo(item_pl, installinfo['removals']):
        munkicommon.display_debug1(
            '%s has already been processed for removal.' % manifestitemname)
        return
    # we only offer to update if some version of the item is already
    # installed, so let's check
    if someVersionInstalled(item_pl):
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
    item_pl = getItemDetail(manifestitem, cataloglist)

    if not item_pl:
        munkicommon.display_warning(
            'Could not process item %s for optional install: ' % manifestitem)
        munkicommon.display_warning(
            'No pkginfo for %s found in catalogs: %s' %
            (manifestitem, ', '.join(cataloglist)))
        return
    # check to see if item (any version) is already in the installlist:
    if isItemInInstallInfo(item_pl, installinfo['managed_installs']):
        munkicommon.display_debug1(
            '%s has already been processed for install.' % manifestitemname)
        return
    # check to see if item (any version) is already in the removallist:
    if isItemInInstallInfo(item_pl, installinfo['removals']):
        munkicommon.display_debug1(
            '%s has already been processed for removal.' % manifestitemname)
        return
    # check to see if item (any version) is already in the
    # optional_install list:
    for item in installinfo['optional_installs']:
        if item_pl['name'] == item['name']:
            munkicommon.display_debug1(
                '%s has already been processed for optional install.' %
                    manifestitemname)
            return

    # if we get to this point we can add this item
    # to the list of optional installs
    iteminfo = {}
    iteminfo['name'] = item_pl.get('name', manifestitemname)
    iteminfo['manifestitem'] = manifestitemname
    iteminfo['description'] = item_pl.get('description', '')
    iteminfo['version_to_install'] = item_pl.get('version', 'UNKNOWN')
    iteminfo['display_name'] = item_pl.get('display_name', '')
    iteminfo['installed'] = someVersionInstalled(item_pl)
    if iteminfo['installed']:
        iteminfo['needs_update'] = not isInstalled(item_pl)
    iteminfo['uninstallable'] = item_pl.get('uninstallable', False)
    if (not iteminfo['installed']) or (iteminfo.get('needs_update')):
        iteminfo['installer_item_size'] = item_pl.get('installer_item_size', 0)
        iteminfo['installed_size'] = item_pl.get('installer_item_size',
                                        iteminfo['installer_item_size'])
        if not enoughDiskSpace(item_pl,
                                    installinfo.get('managed_installs', []),
                                    warn=False):
            iteminfo['note'] = \
                'Insufficient disk space to download and install.'

    installinfo['optional_installs'].append(iteminfo)


def processInstall(manifestitem, cataloglist, installinfo):
    """Processes a manifest item. Determines if it needs to be
    installed, and if so, if any items it is dependent on need to
    be installed first.  Items to be installed are added to
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
    #munkicommon.display_info('Getting detail on %s...' % manifestitemname)
    item_pl = getItemDetail(manifestitem, cataloglist)

    if not item_pl:
        munkicommon.display_warning(
            'Could not process item %s for install: ' % manifestitem)
        munkicommon.display_warning(
            'No pkginfo for %s found in catalogs: %s' %
            (manifestitem, ', '.join(cataloglist)))
        return False

    # check to see if item is already in the installlist:
    if isItemInInstallInfo(item_pl,
            installinfo['managed_installs'], item_pl.get('version')):
        munkicommon.display_debug1(
            '%s has already been processed for install.' % manifestitemname)
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
    iteminfo['manifestitem'] = manifestitemname
    iteminfo['description'] = item_pl.get('description', '')
    iteminfo['installer_item_size'] = item_pl.get('installer_item_size', 0)
    iteminfo['installed_size'] = item_pl.get('installer_item_size',
                                        iteminfo['installer_item_size'])
                                        
    # currently we will ignore the forced_install and forced_uninstall key if
    # the item is part of a dependency graph or needs a restart or logout...
    if (not item_pl.get('requires') and not item_pl.get('update_for') and
        not item_pl.get('RestartAction')):
        iteminfo['forced_install'] = item_pl.get('forced_install', False)
        iteminfo['forced_uninstall'] = item_pl.get('forced_uninstall', False)

    if not isInstalled(item_pl):
        munkicommon.display_detail('Need to install %s' % manifestitemname)
        # check to see if there is enough free space to download and install
        if not enoughDiskSpace(item_pl,
                                    installinfo.get('managed_installs',[])):
            iteminfo['installed'] = False
            iteminfo['note'] = \
                'Insufficient disk space to download and install'
            installinfo['managed_installs'].append(iteminfo)
            return False

        try:
            download_installeritem(item_pl)
            filename = os.path.split(item_pl['installer_item_location'])[1]
            # required keys
            iteminfo['installer_item'] = filename
            iteminfo['installed'] = False
            iteminfo['version_to_install'] = item_pl.get(
                                                 'version','UNKNOWN')
            iteminfo['description'] = item_pl.get('description','')
            iteminfo['display_name'] = item_pl.get('display_name','')
            # optional keys
            optional_keys = ['suppress_bundle_relocation',
                             'installer_choices_xml',
                             'adobe_install_info',
                             'RestartAction',
                             'installer_type',
                             'adobe_package_name',
                             'package_path',
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
        except CurlDownloadError:
            munkicommon.display_warning(
                'Download of %s failed.' % manifestitem)
            iteminfo['installed'] = False
            iteminfo['note'] = 'Download failed'
            installinfo['managed_installs'].append(iteminfo)
            return False
        except MunkiDownloadError, errmsg:
            munkicommon.display_warning('Can\'t install %s because of: %s'
                                        % (manifestitemname, errmsg))
            iteminfo['installed'] = False
            iteminfo['note'] = errmsg
            installinfo['managed_installs'].append(iteminfo)
            return False
    else:
        iteminfo['installed'] = True
        #iteminfo['installed_version'] = getInstalledVersion(pl)
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

    munkicommon.display_detail('Processing manifest item %s...' %
                                manifestitemname_withversion)
    (manifestitemname, includedversion) = nameAndVersion(
                                            manifestitemname_withversion)
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
        munkicommon.display_warning('Could not get information for %s' %
                                     manifestitemname_withversion)
        return False

    for item in infoitems:
        # check to see if item is already in the installlist,
        # if so, that's bad - it means it's scheduled to be installed
        # _and_ removed.  We'll warn, and do nothing with this item.
        if isItemInInstallInfo(item, installinfo['managed_installs']):
            munkicommon.display_warning('Will not attempt to remove %s '
                                        'because some version of it is in '
                                        'the list of managed installs, or '
                                        'it is required by another managed '
                                        'install.' %
                                         manifestitemname_withversion)
            return False

    for item in infoitems:
        # check to see if item is already in the removallist:
        if isItemInInstallInfo(item, installinfo['removals']):
            munkicommon.display_debug1(
                '%s has already been processed for removal.' %
                manifestitemname_withversion)
            return True

    installEvidence = False
    for item in infoitems:
        if evidenceThisIsInstalled(item):
            installEvidence = True
            break

    if not installEvidence:
        munkicommon.display_detail('%s doesn\'t appear to be installed.' %
                                    manifestitemname_withversion)
        iteminfo = {}
        iteminfo['manifestitem'] = manifestitemname_withversion
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
        elif uninstallmethod == 'remove_copied_items':
            uninstall_item = item
        elif uninstallmethod == 'remove_app':
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
    iteminfo['manifestitem'] = manifestitemname_withversion
    iteminfo['description'] = 'Will be removed.'
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
            if not enoughDiskSpace(uninstall_item, uninstalling=True):
                return False

            try:
                download_installeritem(item)
                filename = os.path.split(location)[1]
                iteminfo['uninstaller_item'] = filename
                iteminfo['adobe_package_name'] = \
                        uninstall_item.get('adobe_package_name','')
            except PackageVerificationError:
                munkicommon.display_warning(
                    'Can\'t uninstall %s because the integrity check '
                    'failed.' % iteminfo['name'])
                return False
            except MunkiDownloadError:
                munkicommon.display_warning('Failed to download the '
                                            'uninstaller for %s'
                                            % iteminfo['name'])
                return False
    elif uninstallmethod == 'remove_copied_items':
        iteminfo['items_to_remove'] = item.get('items_to_copy', [])
    elif uninstallmethod == 'remove_app':
        if uninstall_item.get('installs', None):
            iteminfo['remove_app_info'] = uninstall_item['installs'][0]

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
    """Retreives the catalogs from the server and populates our catalogs
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
                unused_value = getHTTPfileIfChangedAtomically(catalogurl,
                                                              catalogpath,
                                                              message=message)
            except MunkiDownloadError, err:
                munkicommon.display_error(
                    'Could not retrieve catalog %s from server.' %
                     catalogname)
                munkicommon.display_error(err)

            else:
                if munkicommon.validPlist(catalogpath):
                    CATALOG[catalogname] = makeCatalogDB(
                        FoundationPlist.readPlist(catalogpath))
                else:
                    munkicommon.display_error(
                        'Retreived catalog %s is invalid.' % catalogname)
                    try:
                        os.unlink(catalogpath)
                    except (OSError, IOError):
                        pass


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

    if partialurl.startswith('http://') or partialurl.startswith('https://'):
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
        unused_value = getHTTPfileIfChangedAtomically(manifesturl,
                                                      manifestpath,
                                                      message=message)
    except MunkiDownloadError, err:
        if not suppress_errors:
            munkicommon.display_error(
                'Could not retrieve manifest %s from the server.' %
                 partialurl)
            munkicommon.display_error(str(err))
        return None

    if munkicommon.validPlist(manifestpath):
        # record it for future access
        MANIFESTS[manifestname] = manifestpath
        return manifestpath
    else:
        errormsg = 'manifest returned for %s is invalid.' % partialurl
        munkicommon.display_error(errormsg)
        try:
            os.unlink(manifestpath)
        except (OSError, IOError):
            pass
        raise ManifestException(errormsg)


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
            manifest = getmanifest(manifesturl +
                                   urllib2.quote(clientidentifier))
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
     unused_path, unused_query, unused_fragment) = urlparse.urlsplit(url)
    if scheme == 'http':
        port = 80
    elif scheme == 'https':
        port = 443
    else:
        return False

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


def curl(url, destinationpath, onlyifnewer=False, etag=None, resume=False,
         cacert=None, capath=None, cert=None, key=None, message=None):
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
        if os.path.exists(tempdownloadpath) and resume:
            # let's try to resume this download
            print >> fileobj, 'continue-at -'

        if os.path.exists(destinationpath):
            if etag:
                escaped_etag = etag.replace('"','\\"')
                print >> fileobj, ('header = "If-None-Match: %s"'
                                                        % escaped_etag)
            elif onlyifnewer:
                print >> fileobj, 'time-cond = "%s"' % destinationpath
            else:
                os.remove(destinationpath)

        # Add any additional headers specified in ManagedInstalls.plist.
        # AdditionalHttpHeaders must be an array of strings with valid HTTP
        # header format. For example:
        # <key>AdditionalHttpHeaders</key>
        # <array>
        #   <string>Key-With-Optional-Dahes: Foo Value</string>
        #   <string>another-custom-header: bar value</string>
        # </array>
        custom_headers = munkicommon.pref(
            munkicommon.ADDITIONAL_HTTP_HEADERS_KEY)
        if custom_headers:
            for custom_header in custom_headers:
                custom_header = custom_header.strip()
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

                if message and header['http_result_code'] != '304':
                    if message:
                        # log always, display if verbose is 2 or more
                        munkicommon.display_detail(message)
                        if munkicommon.munkistatusoutput:
                            # send to detail field on MunkiStatus
                            munkistatus.detail(message)

        elif targetsize and header['http_result_code'].startswith('2'):
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
        curlerr = proc.stderr.read().rstrip('\n').split(None, 2)[2]
        if not resume and os.path.exists(tempdownloadpath):
            os.unlink(tempdownloadpath)
        raise CurlError(retcode, curlerr)
    else:
        temp_download_exists = os.path.isfile(tempdownloadpath)
        http_result = header['http_result_code']
        if downloadedpercent != 100 and \
            http_result.startswith('2') and \
            temp_download_exists:
            downloadedsize = os.path.getsize(tempdownloadpath)
            if downloadedsize >= targetsize:
                munkicommon.display_percent_done(100, 100)
                os.rename(tempdownloadpath, destinationpath)
                return header
            else:
                # not enough bytes retreived
                if not resume and temp_download_exists:
                    os.unlink(tempdownloadpath)
                raise CurlError(-5, 'Expected %s bytes, got: %s' %
                                        (targetsize, downloadedsize))
        elif http_result.startswith('2') and temp_download_exists:
            os.rename(tempdownloadpath, destinationpath)
            return header
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
                                header['http_result_description'])


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
    # format version string like '10.5.8', so that '10.6' becomes '10.6.0'
    MACHINE['os_vers'] = munkicommon.padVersionString(
                                                str(output).rstrip('\n'),3)


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
        installinfo['managed_installs'] = []
        installinfo['removals'] = []
        installinfo['managed_updates'] = []
        installinfo['optional_installs'] = []
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
            cataloglist = getManifestValueForKey(mainmanifestpath, 'catalogs')
            munkicommon.display_detail('**Processing self-serve choices**')
            selfserveinstalls = getManifestValueForKey(selfservemanifest,
                                                       'managed_installs')
            available_optional_installs = [item['name']
                        for item in installinfo.get('optional_installs',[])]
            # filter the list, removing any items not in the current list of
            # available self-serve installs
            selfserveinstalls = [item for item in selfserveinstalls
                                 if item in available_optional_installs]
            for item in selfserveinstalls:
                unused_result = processInstall(item, cataloglist, installinfo)
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
                        isItemInInstallInfo(item, installinfo['removals'])):
                    item['will_be_removed'] = True

        # filter managed_installs to get items already installed
        installed_items = [item
                            for item in installinfo['managed_installs']
                                if item.get('installed')]
        # filter managed_installs to get problem items:
        # not installed, but no installer item
        problem_items = [item
                            for item in installinfo['managed_installs']
                                if item.get('installed') == False and
                                    not item.get('installer_item')]
        # filter removals to get items already removed (or never installed)
        removed_items = [item.get('manifestitem')
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

        # filter managed_installs and removals lists
        # so they have only items that need action
        installinfo['managed_installs'] = \
            [item for item in installinfo['managed_installs']
                    if item.get('installer_item')]
        installinfo['removals'] = \
            [item for item in installinfo['removals']
                if item.get('installed')]

        munkicommon.report['ManagedInstalls'] = installed_items
        munkicommon.report['ProblemInstalls'] = problem_items
        munkicommon.report['RemovedItems'] = removed_items
        munkicommon.report['ItemsToInstall'] = installinfo['managed_installs']
        munkicommon.report['ItemsToRemove'] = installinfo['removals']

        # clean up cache dir
        # remove any item in the cache that isn't scheduled
        # to be used for an install or removal
        # this could happen if an item is downloaded on one
        # updatecheck run, but later removed from the manifest
        # before it is installed or removed - so the cached item
        # is no longer needed.
        cache_list = [item['installer_item']
                      for item in installinfo.get('managed_installs',[])]
        cache_list.extend([item['uninstaller_item']
                           for item in installinfo.get('removals',[])
                           if item.get('uninstaller_item')])
        cachedir = os.path.join(ManagedInstallDir, 'Cache')
        for item in os.listdir(cachedir):
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
                    # OK to get rid of any partial downloads hanging around.
                    os.unlink(os.path.join(cachedir, item))
            elif item not in cache_list:
                munkicommon.display_detail('Removing %s from cache' % item)
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
            else:
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
    for item in installinfo.get('managed_installs', []):
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
    for item in installinfo.get('removals', []):
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

