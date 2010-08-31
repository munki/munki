#!/usr/bin/python
# encoding: utf-8
#
# Copyright 2009-2010 Greg Neagle.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
updatecheck

Created by Greg Neagle on 2008-11-13.

"""

#standard libs
import os
import subprocess
from distutils import version
import urlparse
#import hashlib
import time
import calendar
import socket
from OpenSSL.crypto import load_certificate, FILETYPE_PEM
import xattr

import urllib2

#our libs
import munkicommon
import munkistatus
import FoundationPlist

# global to hold our catalog DBs
catalog = {}
def makeCatalogDB(catalogitems):
    '''Takes an array of catalog items and builds some indexes so we can
    get our common data faster. Returns a dict we can use like a database'''
    name_table = {}
    pkgid_table = {}

    itemindex = -1
    for item in catalogitems:
        itemindex = itemindex + 1
        name = item.get('name', "NO NAME")
        vers = item.get('version', "NO VERSION")

        if name == "NO NAME" or vers == "NO VERSION":
            munkicommon.display_warning("Bad pkginfo: %s" % item)

        # build indexes for items by name and version
        if not name in name_table:
            name_table[name] = {}
        if not vers in name_table[name]:
            name_table[name][vers] = []
        name_table[name][vers].append(itemindex)

        # do the same for any aliases
        #if 'aliases' in item:
        #    for alias in item['aliases']:
        #        if not alias in name_table:
        #            name_table[alias] = {}
        #        if not vers in name_table[alias]:
        #            name_table[alias][vers] = []
        #        name_table[alias][vers].append(itemindex)

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
    '''
    Adds packageids from each catalogitem to a dictionary
    '''
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
    '''Gets the next plist from a set of concatenated text-style plists.
    Returns a tuple - the first plist (if any) and the remaining
    string'''
    plistStart = textString.find("<?xml version")
    if plistStart == -1:
        # not found
        return ("", textString)
    plistEnd = textString.find("</plist>", plistStart + 13)
    if plistEnd == -1:
        # not found
        return ("", textString)
    # adjust end value
    plistEnd = plistEnd + 8
    return (textString[plistStart:plistEnd], textString[plistEnd:])


installedpkgs = {}
def getInstalledPackages():
    """
    Builds a dictionary of installed receipts and their version number
    """
    global installedpkgs

    # we use the --regexp option to pkgutil to get it to return receipt
    # info for all installed packages.  Huge speed up.
    proc = subprocess.Popen(["/usr/sbin/pkgutil", "--regexp",
                             "--pkg-info-plist", ".*"], bufsize=8192,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out, err) = proc.communicate()
    while out:
        (pliststr, out) = getFirstPlist(out)
        if pliststr:
            plist = FoundationPlist.readPlistFromString(pliststr)
            if "pkg-version" in plist and "pkgid" in plist:
                installedpkgs[plist["pkgid"]] = \
                                        plist["pkg-version"] or "0.0.0.0.0"
        else:
            break

    # Now check /Library/Receipts
    receiptsdir = "/Library/Receipts"
    if os.path.exists(receiptsdir):
        installitems = os.listdir(receiptsdir)
        for item in installitems:
            if item.endswith(".pkg"):
                pkginfo = munkicommon.getOnePackageInfo(
                                        os.path.join(receiptsdir, item))
                pkgid = pkginfo.get('packageid')
                thisversion = pkginfo.get('version')
                if pkgid:
                    if not pkgid in installedpkgs:
                        installedpkgs[pkgid] = thisversion
                    else:
                        # pkgid is already in our list. There must be
                        # multiple receipts with the same pkgid.
                        # in this case, we want the highest version
                        # number, since that's the one that's
                        # installed, since presumably
                        # the newer package replaced the older one
                        storedversion = installedpkgs[pkgid]
                        if version.LooseVersion(thisversion) > \
                           version.LooseVersion(storedversion):
                            installedpkgs[pkgid] = thisversion

    return installedpkgs

# global pkgdata
pkgdata = {}
def analyzeInstalledPkgs():
    '''Analyzed installed packages in an attempt to determine what is
       installed.'''
    global pkgdata
    managed_pkgids = {}
    for catalogname in catalog.keys():
        catalogitems = catalog[catalogname]['items']
        addPackageids(catalogitems, managed_pkgids)

    if not installedpkgs:
        getInstalledPackages()

    installed = []
    partiallyinstalled = []
    installedpkgsmatchedtoname = {}
    for name in managed_pkgids.keys():
        somepkgsfound = False
        allpkgsfound = True
        for pkg in managed_pkgids[name]:
            if pkg in installedpkgs.keys():
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

    pkgdata = {}
    pkgdata['receipts_for_name'] = installedpkgsmatchedtoname
    pkgdata['installed_names'] = installed
    pkgdata['pkg_references'] = references


# appdict is a global so we don't call system_profiler
# more than once per session
appdict = {}
def getAppData():
    """
    Queries system_profiler and returns a dict
    of app info items
    """
    global appdict
    if appdict == {}:
        munkicommon.display_debug1(
            "Getting info on currently installed applications...")
        cmd = ['/usr/sbin/system_profiler', '-XML', 'SPApplicationsDataType']
        proc = subprocess.Popen(cmd, shell=False, bufsize=1,
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        (pliststr, err) = proc.communicate()
        if proc.returncode == 0:
            plist = FoundationPlist.readPlistFromString(pliststr)
            # top level is an array instead of a dict, so get dict
            spdict = plist[0]
            if '_items' in spdict:
                appdict = spdict['_items']

    return appdict


def getAppBundleID(path):
    """
    Returns CFBundleIdentifier if available
    for application at path
    """
    infopath = os.path.join(path, "Contents", "Info.plist")
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
    """
    Returns -1 if thisvers is older than thatvers
    Returns 1 if thisvers is the same as thatvers
    Returns 2 if thisvers is newer than thatvers
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
    """
    app is a dict with application
    bundle info

    First checks the given path if it's available,
    then uses system profiler data to look for the app

    Returns  0 if the app isn't installed
                or doesn't have valid Info.plist
            -1 if it's older
             1 if the version is the same
             2 if the version is newer
            -2 if there's an error in the input
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
            munkicommon.display_error(
                "No application name or bundleid was specified!")
            return -2

    munkicommon.display_debug1(
        "Looking for application %s with bundleid: %s, version %s..." %
        (name, bundleid, versionstring))
    appinfo = []
    appdata = getAppData()
    if appdata:
        for item in appdata:
            if 'path' in item:
                # in case we get items from other disks
                if not item['path'].startswith('/Volumes/'):
                    if bundleid:
                        if getAppBundleID(item['path']) == bundleid:
                            appinfo.append(item)
                    elif name:
                        if '_name' in item:
                            if item['_name'] == name:
                                appinfo.append(item)

    if not appinfo:
        # app isn't present!
        munkicommon.display_debug1(
            "\tDid not find this application on the startup disk.")
        return 0

    for item in appinfo:
        if '_name' in item:
            munkicommon.display_debug2(
                "\tName: \t %s" % item['_name'].encode("UTF-8"))
        if 'path' in item:
            munkicommon.display_debug2(
                "\tPath: \t %s" % item['path'].encode("UTF-8"))
            munkicommon.display_debug2(
                "\tCFBundleIdentifier: \t %s" % getAppBundleID(item['path']))
        if 'version' in item:
            munkicommon.display_debug2(
                "\tVersion: \t %s" % item['version'].encode("UTF-8"))
            if compareVersions(item['version'], versionstring) == 1:
                # version is the same
                return 1
            if compareVersions(item['version'], versionstring) == 2:
                # version is newer
                return 2

    # if we got this far, must only be older
    munkicommon.display_debug1(
        "An older version of this application is present.")
    return -1


def compareBundleVersion(item):
    """
    Returns  0 if the bundle isn't installed
                or doesn't have valid Info.plist
            -1 if it's older
             1 if the version is the same
             2 if the version is newer
            -2 if there's an error in the input
    """
    if 'path' in item and 'CFBundleShortVersionString' in item:
        vers = item['CFBundleShortVersionString']
    else:
        munkicommon.display_error("Missing bundle path or version!")
        return -2

    munkicommon.display_debug1("Checking bundle %s for version %s..." %
                                (item['path'], vers))
    filepath = os.path.join(item['path'], 'Contents', 'Info.plist')
    if not os.path.exists(filepath):
        munkicommon.display_debug1("\tNo Info.plist found at %s" % filepath)
        filepath = os.path.join(item['path'], 'Resources', 'Info.plist')
        if not os.path.exists(filepath):
            munkicommon.display_debug1(
                                "\tNo Info.plist found at %s" % filepath)
            return 0

    munkicommon.display_debug1("\tFound Info.plist at %s" % filepath)
    try:
        plist = FoundationPlist.readPlist(filepath)
    except FoundationPlist.NSPropertyListSerializationException:
        munkicommon.display_debug1("\t%s may not be a plist!" % filepath)
        return 0

    installedvers = munkicommon.getVersionString(plist)
    if installedvers:
        return compareVersions(installedvers, vers)
    else:
        munkicommon.display_debug1("\tNo version info in %s." % filepath)
        return 0


def comparePlistVersion(item):
    """
    Gets the version string from the plist
    at filepath and compares versions.
    Returns  0 if the plist isn't installed
            -1 if it's older
             1 if the version is the same
             2 if the version is newer
            -2 if there's an error in the input
    """
    if 'path' in item and 'CFBundleShortVersionString' in item:
        filepath = item['path']
        vers = item['CFBundleShortVersionString']
    else:
        munkicommon.display_error("Missing plist path or version!")
        return -2

    munkicommon.display_debug1("Checking %s for version %s..." %
                                (filepath, vers))
    if not os.path.exists(filepath):
        munkicommon.display_debug1("\tNo plist found at %s" % filepath)
        return 0

    try:
        plist = FoundationPlist.readPlist(filepath)
    except FoundationPlist.NSPropertyListSerializationException:
        munkicommon.display_debug1("\t%s may not be a plist!" % filepath)
        return 0

    installedvers = munkicommon.getVersionString(plist)
    if installedvers:
        return compareVersions(installedvers, vers)
    else:
        munkicommon.display_debug1("\tNo version info in %s." % filepath)
        return 0


def filesystemItemExists(item):
    """
    Checks to see if a filesystem item exists
    If item has m5checksum attribute, compares ondisk file's checksum
    """
    if 'path' in item:
        filepath = item['path']
        munkicommon.display_debug1("Checking existence of %s..." % filepath)
        if os.path.exists(filepath):
            munkicommon.display_debug2("\tExists.")
            if 'md5checksum' in item:
                storedchecksum = item['md5checksum']
                ondiskchecksum = munkicommon.getmd5hash(filepath)
                munkicommon.display_debug2("Comparing checksums...")
                if storedchecksum == ondiskchecksum:
                    munkicommon.display_debug2("Checksums match.")
                    return 1
                else:
                    munkicommon.display_debug2(
                        "Checksums differ: expected %s, got %s" %
                         (storedchecksum, ondiskchecksum))
                    return 0
            return 1
        else:
            munkicommon.display_debug2("\tDoes not exist.")
            return 0
    else:
        munkicommon.display_error("No path specified for filesystem item.")
        return -2


def compareReceiptVersion(item):
    """
    Determines if the given package is already installed.
    packageid is a 'com.apple.pkg.ServerAdminTools' style id
    Returns  0 if the receipt isn't present
            -1 if it's older
             1 if the version is the same
             2 if the version is newer
            -2 if there's an error in the input
    """
    if not installedpkgs:
        getInstalledPackages()
    if 'packageid' in item and 'version' in item:
        pkgid = item['packageid']
        vers = item['version']
    else:
        print "Missing packageid or version info!"
        return -2

    munkicommon.display_debug1("Looking for package %s, version %s" %
                                (pkgid, vers))
    installedvers = installedpkgs.get(pkgid)
    if installedvers:
        return compareVersions(installedvers, vers)
    else:
        munkicommon.display_debug1(
            "\tThis package is not currently installed.")
        return 0


def getInstalledVersion(item_plist):
    """
    Attempts to determine the currently installed version of the item
    described by item_plist
    """
    if 'receipts' in item_plist:
        for receipt in item_plist['receipts']:
            installedpkgvers = \
                munkicommon.getInstalledPackageVersion(receipt['packageid'])
            munkicommon.display_debug2("Looking for %s, version %s" %
                                        (receipt['packageid'],
                                         receipt['version']))
            if compareVersions(installedpkgvers, receipt['version']) == 2:
                # version is higher
                installedversion = "newer than %s" % item_plist['version']
                return installedversion
            if compareVersions(installedpkgvers, receipt['version']) == -1:
                # version is lower
                installedversion = "older than %s" % item_plist['version']
                return installedversion
        # if we get here all receipts match
        return item_plist['version']

    if 'installs' in item_plist:
        for install_item in item_plist['installs']:
            if install_item['type'] == 'application':
                name = install_item.get('CFBundleName')
                bundleid = install_item.get('CFBundleIdentifier')
                munkicommon.display_debug2(
                    "Looking for application %s, version %s" %
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
                    appdata = getAppData()
                    if appdata:
                        for ad_item in appdata:
                            if bundleid:
                                if 'path' in ad_item:
                                    if getAppBundleID(ad_item['path']) == \
                                       bundleid:
                                        appinfo.append(ad_item)
                            elif name:
                                if '_name' in ad_item:
                                    if ad_item['_name'] == name:
                                        appinfo.append(ad_item)

                    maxversion = "0.0.0.0.0"
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
                installedversion = "newer than %s" % plist['version']
                return installedversion

            if compareVersions(installedappvers,
                            install_item['CFBundleShortVersionString']) == -1:
                # version is lower
                installedversion = "older than %s" % plist['version']
                return installedversion

        # if we get here all app versions match
        return item_plist['version']

    # if we fall through to here we have no idea what version we have
    return "UNKNOWN"


def download_installeritem(location):
    """
    Downloads a installer item.
    """
    ManagedInstallDir = munkicommon.pref('ManagedInstallDir')
    downloadbaseurl = munkicommon.pref('PackageURL') or \
                      munkicommon.pref('SoftwareRepoURL') + "/pkgs/"
    if not downloadbaseurl.endswith('/'):
        downloadbaseurl = downloadbaseurl + "/"
    munkicommon.display_debug2("Download base URL is: %s" % downloadbaseurl)

    mycachedir = os.path.join(ManagedInstallDir, "Cache")

    # build a URL, quoting the the location to encode reserved characters
    pkgurl = downloadbaseurl + urllib2.quote(location)

    # grab last path component of location to derive package name.
    pkgname = os.path.basename(location)
    destinationpath = os.path.join(mycachedir, pkgname)

    munkicommon.display_detail("Downloading %s from %s" % (pkgname, location))
    # bump up verboseness so we get download percentage done feedback.
    # this is kind of a hack...
    oldverbose = munkicommon.verbose
    munkicommon.verbose = oldverbose + 1
    dl_message = "Downloading %s..." % pkgname
    (path, err) = getHTTPfileIfChangedAtomically(pkgurl, destinationpath,
                                                 resume=True,
                                                 message=dl_message)
    # set verboseness back.
    munkicommon.verbose = oldverbose

    if path:
        return (True, destinationpath)

    else:
        munkicommon.display_error("Could not download %s from server." %
                                  pkgname)
        munkicommon.display_error(err)
        return (False, destinationpath)


def isItemInInstallInfo(manifestitem_pl, thelist, vers=''):
    """
    Returns True if the manifest item has already
    been processed (it's in the list) and, optionally,
    the version is the same or greater.
    """
    names = []
    names.append(manifestitem_pl.get('name'))
    #names.extend(manifestitem_pl.get('aliases',[]))
    for item in thelist:
        if item.get('name') in names:
            if not vers:
                return True
            if item.get('installed'):
                return True
            #if the version already processed is the same or greater,
            #then we're good
            if (compareVersions(item.get('version_to_install'), vers)
                                                                in (1, 2)):
                return True

    return False


def nameAndVersion(aString):
    """
    Splits a string into the name and version number.
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
            if vers[0] in "0123456789":
                return (name, vers)

    return (aString, '')


def getAllItemsWithName(name, cataloglist):
    """
    Searches the catalogs in cataloglist for all items matching
    the given name. Returns a list of pkginfo items.

    The returned list is sorted with newest version first. No precedence is
    given to catalog order.

    """
    def compare_item_versions(a, b):
        return cmp(version.LooseVersion(b['version']),
                   version.LooseVersion(a['version']))

    itemlist = []
    # we'll throw away any included version info
    (name, includedversion) = nameAndVersion(name)

    munkicommon.display_debug1("Looking for all items matching: %s..." % name)
    for catalogname in cataloglist:
        if not catalogname in catalog.keys():
            # in case catalogname refers to a non-existent catalog...
            continue
        # is name in the catalog name table?
        if name in catalog[catalogname]['named']:
            versionsmatchingname = catalog[catalogname]['named'][name]
            for vers in versionsmatchingname.keys():
                if vers != 'latest':
                    indexlist = catalog[catalogname]['named'][name][vers]
                    for index in indexlist:
                        thisitem = catalog[catalogname]['items'][index]
                        if not thisitem in itemlist:
                            munkicommon.display_debug1(
                             "Adding item %s, version %s from catalog %s..." %
                             (name, thisitem['version'], catalogname))
                            itemlist.append(thisitem)

    if itemlist:
        # sort so latest version is first
        itemlist.sort(compare_item_versions)

    return itemlist


def getItemDetail(name, cataloglist, vers=''):
    """
    Searches the catalogs in cataloglist for an item matching
    the given name and version. If no version is supplied, but the version
    is appended to the name ('TextWrangler--2.3.0.0.0') that version is used.
    If no version is given at all, the latest version is assumed.
    Returns a pkginfo item.
    """
    def compare_version_keys(a, b):
        return cmp(version.LooseVersion(b), version.LooseVersion(a))

    global catalog
    (name, includedversion) = nameAndVersion(name)
    if vers == '':
        if includedversion:
            vers = includedversion
    if vers:
        # make sure version is in 1.0.0.0.0 format
        vers = munkicommon.padVersionString(vers, 5)
    else:
        vers = 'latest'

    munkicommon.display_debug1("Looking for detail for: %s, version %s..." %
                                (name, vers))
    for catalogname in cataloglist:
        if not catalogname in catalog.keys():
            # in case the list refers to a non-existent catalog
            continue

        # is name in the catalog?
        if name in catalog[catalogname]['named']:
            itemsmatchingname = catalog[catalogname]['named'][name]
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
                "Considering %s items with name %s from catalog %s" %
                (len(indexlist), name, catalogname))
            for index in indexlist:
                item = catalog[catalogname]['items'][index]
                # we have an item whose name and version matches the request.
                # now check to see if it meets os and cpu requirements
                if 'minimum_os_version' in item:
                    min_os_vers = \
                        munkicommon.padVersionString(
                                                item['minimum_os_version'],3)
                    munkicommon.display_debug1(
                        "Considering item %s, " % item['name'] +
                        "version %s " % item['version'] +
                        "with minimum os version required %s" % min_os_vers)
                    munkicommon.display_debug2("Our OS version is %s" %
                                                machine['os_vers'])
                    if version.LooseVersion(machine['os_vers']) < \
                       version.LooseVersion(min_os_vers):
                        # skip this one, go to the next
                        continue

                if 'maximum_os_version' in item:
                    max_os_vers = \
                        munkicommon.padVersionString(
                                                item['maximum_os_version'],3)
                    munkicommon.display_debug1(
                        "Considering item %s, " % item['name'] +
                        "version %s " % item['version'] +
                        "with maximum os version supported %s" % max_os_vers)
                    munkicommon.display_debug2("Our OS version is %s" %
                                                machine['os_vers'])
                    if version.LooseVersion(machine['os_vers']) > \
                       version.LooseVersion(max_os_vers):
                        # skip this one, go to the next
                        continue

                if 'supported_architectures' in item:
                    supported_arch_found = False
                    munkicommon.display_debug1(
                        "Considering item %s, " % item['name'] +
                        "version %s " % item['version'] +
                        "with supported architectures: %s" %
                                            item['supported_architectures'])
                    for arch in item['supported_architectures']:
                        if arch == machine['arch']:
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
                    "Found %s, version %s in catalog %s" %
                    (item['name'], item['version'], catalogname))
                return item

    # if we got this far, we didn't find it.
    munkicommon.display_debug1("Nothing found")
    return None


def enoughDiskSpace(manifestitem_pl, installlist=None, uninstalling=False):
    """
    Used to determine if there is enough disk space
    to be able to download and install the manifestitem
    """
    # fudgefactor is set to 100MB
    fudgefactor = 102400
    installeritemsize = 0
    installedsize = 0
    alreadydownloadedsize = 0
    if 'installer_item_location' in manifestitem_pl:
        cachedir = os.path.join(munkicommon.pref('ManagedInstallDir'),"Cache")
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
    else:
        if uninstalling:
            munkicommon.display_warning("There is insufficient disk space to "
                                        "download the uninstaller for %s." %
                                        manifestitem_pl.get('name'))
        else:
            munkicommon.display_warning("There is insufficient disk space to "
                                        "download and install %s." %
                                        manifestitem_pl.get('name'))
        munkicommon.display_warning("    %sMB needed; %sMB available" %
                                                  (diskspaceneeded/1024,
                                                   availablediskspace/1024))
        return False


def isInstalled(item_pl):
    """
    Checks to see if the item described by item_pl
    (or a newer version) is currently installed
    All tests must pass to be considered installed.
    Returns True if it looks like this or a newer version
    is installed; False otherwise.
    """
    # does 'installs' exist and is it non-empty?
    if item_pl.get('installs', None):
        installitems = item_pl['installs']
        for item in installitems:
            itemtype = item.get('type')
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
                if filesystemItemExists(item) == 0 :
                    # not there, or wrong checksum
                    return False

    # if there is no 'installs' key, then we'll use receipt info
    # to determine install status.
    elif 'receipts' in item_pl:
        receipts = item_pl['receipts']
        for item in receipts:
            if compareReceiptVersion(item) in (-1, 0):
                # not there or older
                return False

    # if we got this far, we passed all the tests, so the item
    # must be installed (or we don't have enough info...)
    return True


def evidenceThisIsInstalled(item_pl):
    """
    Checks to see if there is evidence that
    the item described by item_pl
    (any version) is currently installed.
    If any tests pass, the item might be installed.
    So this isn't the same as isInstalled()
    """
    global pkgdata

    if item_pl.get('uninstall_method') == "removepackages":
        # we're supposed to use receipt info to remove
        # this, so we should check for relevent receipts
        if item_pl.get('receipts'):
            if pkgdata == {}:
                # build our database of installed packages
                analyzeInstalledPkgs()
            if item_pl['name'] in pkgdata['installed_names']:
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


def verifySoftwarePackageIntegrity(manifestitem, file_path, item_pl, item_key):
    '''
    Verifies the integrity of the given software package.

    The feature can be controlled through the PackageVerificationMode key in
    the ManagedInstalls.plist. Following modes currently exist:
        none: No integrity check is performed.
        hash: Integrity check is performed by calcualting a SHA-256 hash of
            the given file and comparing it against the reference value in
            catalog. Only applies for package plists that contain the item_key;
            for packages without the item_key, verifcation always returns True.
        hash_strict: Same as hash, but returns False for package plists that
            do not contain the item_key.

    Args:
        mainfestitem: The name of the manifest item.
        file_path: The file to check integrity on.
        item_pl: The item plist which contains the reference values.
        item_key: The name of the key in plist which contains the hash.

    Returns:
        True if the package integrity could be validated. Otherwise, False.
    '''
    mode = munkicommon.pref('PackageVerificationMode')
    if not mode:
        munkicommon.display_warning("The PackageVerificationMode key is "
            "missing in the ManagedInstalls.plist. Please add it.")
        munkicommon.display_warning("Package integrity checking is disabled.")
        return True
    elif mode.lower() == 'none':
        munkicommon.display_warning("Package integrity checking is disabled.")
        return True
    elif mode.lower() == 'hash' or mode.lower() == 'hash_strict':
        if item_key in item_pl:
            item_hash = item_pl[item_key]
            if (item_hash is not 'N/A' and
                item_hash == munkicommon.getsha256hash(file_path)):
                return True
            else:
                munkicommon.display_error(
                    "Hash value integrity check for %s failed." % manifestitem)
                return False
        else:
            if mode.lower() == 'hash_strict':
                munkicommon.display_error(
                    "Reference hash value for %s is missing in catalog."
                    % manifestitem)
                return False
            else:
                munkicommon.display_warning(
                    "Package integrity checking is disabled for %s."
                    % manifestitem)
                return True

    else:
        munkicommon.display_error(
            "The PackageVerificationMode in the ManagedInstalls.plist has an "
            "illegal value: %s" % munkicommon.pref('PackageVerificationMode'))

    return False


def getAutoRemovalItems(installinfo, cataloglist):
    '''
    Gets a list of items marked for automatic removal from the catalogs
    in cataloglist. Filters those against items in the managed_installs
    list, which should contain everything that is supposed to be installed.
    '''
    autoremovalnames = []
    for catalogname in cataloglist:
        if catalogname in catalog.keys():
            autoremovalnames += catalog[catalogname]['autoremoveitems']

    #print "Managed Installs: ", installinfo.get('managed_installs',[])
    already_processed_names = [item['name']
                              for item in
                                  installinfo.get('managed_installs',[])]
    #print "Removals: ", installinfo.get('removals',[])
    already_processed_names += [item['manifestitem']
                                for item in installinfo.get('removals',[])]
    autoremovalnames = [item for item in autoremovalnames
                             if item not in already_processed_names]
    #print "Auto removal names: ", autoremovalnames
    return autoremovalnames


def lookForUpdates(manifestitem, cataloglist):
    """
    Looks for updates for a given manifest item that is either
    installed or scheduled to be installed. This handles not only
    specific application updates, but also updates that aren't simply
    later versions of the manifest item.
    For example, AdobeCameraRaw is an update for Adobe Photoshop, but
    doesn't update the version of Adobe Photoshop.
    Returns a list of manifestitem names that are updates for
    manifestitem.
    """
    nameWithVersion = os.path.split(manifestitem)[1]
    (name, includedversion) = nameAndVersion(nameWithVersion)
    # get a list of catalog items that are updates for other items
    update_list = []
    for catalogname in cataloglist:
        if not catalogname in catalog.keys():
            # in case the list refers to a non-existant catalog
            continue

        updaters = catalog[catalogname]['updaters']
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


def processOptionalInstall(manifestitem, cataloglist, installinfo):
    '''
    Process an optional install item to see if it should be added to
    the list of optional installs.
    '''
    manifestitemname = os.path.split(manifestitem)[1]
    item_pl = getItemDetail(manifestitem, cataloglist)

    if not item_pl:
        munkicommon.display_warning(
            "Could not process item %s for optional install: " % manifestitem)
        munkicommon.display_warning(
            "No pkginfo for %s found in catalogs: %s" %
            (manifestitem, ', '.join(cataloglist)))
        return
    # check to see if item (any version) is already in the installlist:
    if isItemInInstallInfo(item_pl, installinfo['managed_installs']):
        munkicommon.display_debug1(
            "%s has already been processed for install." % manifestitemname)
        return
    # check to see if item (any version) is already in the removallist:
    if isItemInInstallInfo(item_pl, installinfo['removals']):
        munkicommon.display_debug1(
            "%s has already been processed for removal." % manifestitemname)
        return
    # check to see if item (any version) is already in the
    # optional_install list:
    for item in installinfo['optional_installs']:
        if item_pl['name'] == item['name']:
            munkicommon.display_debug1(
                "%s has already been processed for optional install." %
                    manifestitemname)
            return
    # if we get to this point we can add this item
    # to the list of optional installs
    iteminfo = {}
    iteminfo["name"] = item_pl.get('name', '')
    iteminfo["manifestitem"] = manifestitemname
    iteminfo["description"] = item_pl.get('description', '')
    iteminfo["version_to_install"] = item_pl.get('version',"UNKNOWN")
    iteminfo['display_name'] = item_pl.get('display_name','')
    iteminfo['installed'] = isInstalled(item_pl)
    iteminfo['uninstallable'] = item_pl.get('uninstallable', False)
    if not iteminfo['installed']:
        iteminfo["installer_item_size"] = item_pl.get('installer_item_size',
                                                                            0)
        iteminfo["installed_size"] = item_pl.get('installer_item_size',
                                        iteminfo["installer_item_size"])
        if not enoughDiskSpace(item_pl,
                                    installinfo.get('managed_installs',[])):
            iteminfo['note'] = \
                "Insufficient disk space to download and install."

    installinfo['optional_installs'].append(iteminfo)


def processInstall(manifestitem, cataloglist, installinfo):
    """
    Processes a manifest item. Determines if it needs to be
    installed, and if so, if any items it is dependent on need to
    be installed first.  Items to be installed are added to
    installinfo['managed_installs']
    Calls itself recursively as it processes dependencies.
    Returns a boolean; when processing dependencies, a false return
    will stop the installation of a dependent item
    """

    if munkicommon.munkistatusoutput:
        # reset progress indicator and detail field
        munkistatus.percent("-1")
        munkistatus.detail('')

    manifestitemname = os.path.split(manifestitem)[1]
    #munkicommon.display_info("Getting detail on %s..." % manifestitemname)
    item_pl = getItemDetail(manifestitem, cataloglist)

    if not item_pl:
        munkicommon.display_warning(
            "Could not process item %s for install: " % manifestitem)
        munkicommon.display_warning(
            "No pkginfo for %s found in catalogs: %s" %
            (manifestitem, ', '.join(cataloglist)))
        return False

    # check to see if item is already in the installlist:
    if isItemInInstallInfo(item_pl,
            installinfo['managed_installs'], item_pl.get('version')):
        munkicommon.display_debug1(
            "%s has already been processed for install." % manifestitemname)
        return True

    # check dependencies
    dependenciesMet = True

    # there are three kinds of dependencies/relationships.
    #
    # 'requires' are prerequistes:
    #  package A requires package B be installed first.
    #  if package A is removed, package B is unaffected.
    #  requires can be a one to many relationship.
    #
    # 'modifies' is a package the current package modifies on install;
    #  generally this means the current package is an updater..
    #  For example, 'Office2008' might resolve to Office2008--12.1.7
    #  which modifies Office2008--12.1.0
    #  which modifies Office2008--12.0.0.
    #  (Office2008--12.1.7 and Office2008--12.1.0 are updater packages,
    #  Office2008--12.0.0 is the original installer.)
    #  If you later remove Office2008, you want to remove everything installed
    #  by all three packages.
    # 'modifies' provides a method to theoretically figure it all out.
    # 'modifies' is a one to one relationship -
    #  this item can modify only one other item.
    #
    # when processing installs, the two dependencies are basically equivalent;
    # the real difference comes when processing removals.
    #
    # 'modifies' has been deprecated and support for it will be removed in
    #  a future release.
    #
    #  The third type of relationship is "update_for".
    #  This signifies that that current package should be considered an update
    #  for the packages listed in the "update_for" array. When processing a
    #  package, we look through the catalogs for other packages that declare
    #  they are updates for the current package and install them if needed.
    #  This can be a one-to-many relationship - one package can be an update
    #  for several other packages; for example, "PhotoshopCS4update-11.0.1"
    #  could be an update for PhotoshopCS4 and for AdobeCS4DesignSuite.
    #
    #  When removing an item, any updates for that item are removed as well.
    #
    #  With 'requires' and 'update_for' you can completely replace the
    #  functionality of 'modifies', plus do more, so 'modifies' is on its way
    #  out.

    if 'requires' in item_pl:
        dependencies = item_pl['requires']
        for item in dependencies:
            munkicommon.display_detail("%s-%s requires %s. "
                                    "Getting info on %s..." %
                                    (item_pl.get('name', manifestitemname),
                                    item_pl.get('version',''), item, item))
            success = processInstall(item, cataloglist, installinfo)
            if not success:
                dependenciesMet = False

    if 'modifies' in item_pl:
        dependencies = item_pl['modifies']
        if type(dependencies) == list:
            # in case this was put in as an array
            # we support only a single modified item.
            item = dependencies[0]
        else:
            item = dependencies

        munkicommon.display_detail("%s-%s modifies %s. "
                                   "Getting info on %s..." %
                                   (item_pl.get('name', manifestitemname),
                                    item_pl.get('version',''), item, item))
        success = processInstall(item, cataloglist, installinfo)
        if not success:
            dependenciesMet = False

    if not dependenciesMet:
        munkicommon.display_warning("Didn't attempt to install %s "
                                    "because could not resolve all "
                                    "dependencies." % manifestitemname)
        return False

    iteminfo = {}
    iteminfo["name"] = item_pl.get('name', '')
    iteminfo["manifestitem"] = manifestitemname
    iteminfo["description"] = item_pl.get('description', '')
    iteminfo["installer_item_size"] = item_pl.get('installer_item_size', 0)
    iteminfo["installed_size"] = item_pl.get('installer_item_size',
                                        iteminfo["installer_item_size"])

    if not isInstalled(item_pl):
        munkicommon.display_detail("Need to install %s" % manifestitemname)
        # check to see if there is enough free space to download and install
        if not enoughDiskSpace(item_pl,
                                    installinfo.get('managed_installs',[])):
            iteminfo['installed'] = False
            iteminfo['note'] = \
                "Insufficient disk space to download and install"
            installinfo['managed_installs'].append(iteminfo)
            return False

        if 'installer_item_location' in item_pl:
            location = item_pl['installer_item_location']
            (download_successful, download_path) = download_installeritem(
                location)
            if download_successful:
                filename = os.path.split(location)[1]
                if verifySoftwarePackageIntegrity(
                    manifestitem, download_path, item_pl,
                    'installer_item_hash'):
                    # required keys
                    iteminfo['installer_item'] = filename
                    iteminfo['installed'] = False
                    iteminfo["version_to_install"] = \
                                                item_pl.get('version',"UNKNOWN")
                    iteminfo['description'] = item_pl.get('description','')
                    iteminfo['display_name'] = (item_pl.get('display_name',''))
                    # optional keys
                    optional_keys = ['suppress_bundle_relocation',
                                     'installer_choices_xml',
                                     'adobe_install_info',
                                     'RestartAction',
                                     'installer_type',
                                     'adobe_package_name',
                                     'package_path',
                                     'items_to_copy', # used w/ copy_from_dmg
                                     'copy_local'] # used w/ Adobe CS5 Updaters
                    for key in optional_keys:
                        if key in item_pl:
                            iteminfo[key] = item_pl[key]

                    installinfo['managed_installs'].append(iteminfo)
                    if nameAndVersion(manifestitemname)[1] == '':
                        # didn't specify a specific version, so
                        # now look for updates for this item
                        update_list = lookForUpdates(iteminfo["name"],
                                                     cataloglist)
                        for update_item in update_list:
                            # call processInstall recursively so we get the
                            # latest version and dependencies
                            is_or_will_be_installed = processInstall(
                                update_item, cataloglist, installinfo)
                    return True
                else:
                    munkicommon.display_warning(
                        "Can't install %s because the integrity check failed."
                        % manifestitem)
                    iteminfo['installed'] = False
                    iteminfo['note'] = "Integrity check failed"
                    installinfo['managed_installs'].append(iteminfo)
                    return False
            else:
                munkicommon.display_warning(
                    "Download of %s failed." % manifestitem)
                iteminfo['installed'] = False
                iteminfo['note'] = "Download failed"
                installinfo['managed_installs'].append(iteminfo)
                return False
        else:
            munkicommon.display_warning("Can't install %s because there's no "
                                        "download info for the installer "
                                        "item" % manifestitemname)
            iteminfo['installed'] = False
            iteminfo['note'] = "Download info missing"
            installinfo['managed_installs'].append(iteminfo)
            return False
    else:
        iteminfo['installed'] = True
        #iteminfo["installed_version"] = getInstalledVersion(pl)
        installinfo['managed_installs'].append(iteminfo)
        # remove included version number if any
        (name, includedversion) = nameAndVersion(manifestitemname)
        munkicommon.display_detail("%s version %s (or newer) is already "
                                    "installed." % (name, item_pl['version']))
        if not includedversion:
            # no specific version is specified;
            # the item is already installed;
            # now look for updates for this item
            update_list = lookForUpdates(iteminfo["name"], cataloglist)
            for update_item in update_list:
                # call processInstall recursively so we get the latest version
                # and any dependencies
                is_or_will_be_installed = processInstall(update_item,
                                                         cataloglist,
                                                         installinfo)
        return True


def processManifestForOptionalInstalls(manifestpath, installinfo,
                                                        parentcatalogs=None):
    """
    Processes manifests to build a list of optional installs that
    can be displayed by Managed Software Update.
    Will be recursive is manifests include other manifests.
    """
    cataloglist = getManifestValueForKey(manifestpath, 'catalogs')
    if cataloglist:
        getCatalogs(cataloglist)
    elif parentcatalogs:
        cataloglist = parentcatalogs

    if cataloglist:
        nestedmanifests = getManifestValueForKey(manifestpath,
                                                 "included_manifests")
        if nestedmanifests:
            for item in nestedmanifests:
                try:
                    nestedmanifestpath = getmanifest(item)
                except ManifestException:
                    nestedmanifestpath = None
                if munkicommon.stopRequested():
                    return {}
                if nestedmanifestpath:
                    processManifestForOptionalInstalls(nestedmanifestpath,
                                                       installinfo,
                                                       cataloglist)

        optionalinstallitems = getManifestValueForKey(manifestpath,
                                              "optional_installs")
        if optionalinstallitems:
            for item in optionalinstallitems:
                if munkicommon.stopRequested():
                    return {}
                processOptionalInstall(item, cataloglist, installinfo)


def processManifestForInstalls(manifestpath, installinfo,
                                                        parentcatalogs=None):
    """
    Processes manifests to build a list of items to install.
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
                                                 "included_manifests")
        if nestedmanifests:
            for item in nestedmanifests:
                try:
                    nestedmanifestpath = getmanifest(item)
                except ManifestException:
                    nestedmanifestpath = None
                if munkicommon.stopRequested():
                    return {}
                if nestedmanifestpath:
                    processManifestForInstalls(nestedmanifestpath,
                                                installinfo, cataloglist)

        installitems = getManifestValueForKey(manifestpath,
                                              "managed_installs")
        if installitems:
            for item in installitems:
                if munkicommon.stopRequested():
                    return {}
                is_or_will_be_installed = processInstall(item, cataloglist,
                                                         installinfo)

    else:
        munkicommon.display_warning("Manifest %s has no 'catalogs'" %
                                    manifestpath)

    return installinfo


def getReceiptsToRemove(item):
    '''Returns a list of receipts to remove for item'''
    name = item['name']
    if name in pkgdata['receipts_for_name']:
        return pkgdata['receipts_for_name'][name]
    return []


def processRemoval(manifestitem, cataloglist, installinfo):
    """
    Processes a manifest item; attempts to determine if it
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

    munkicommon.display_detail("Processing manifest item %s..." %
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
        munkicommon.display_warning("Could not get information for %s" %
                                     manifestitemname_withversion)
        return False

    for item in infoitems:
        # check to see if item is already in the installlist,
        # if so, that's bad - it means it's scheduled to be installed
        # _and_ removed.  We'll warn, and do nothing with this item.
        if isItemInInstallInfo(item, installinfo['managed_installs']):
            munkicommon.display_warning("Will not attempt to remove %s "
                                        "because some version of it is in "
                                        "the list of managed installs, or "
                                        "it is required by another managed "
                                        "install." %
                                         manifestitemname_withversion)
            return False

    for item in infoitems:
        # check to see if item is already in the removallist:
        if isItemInInstallInfo(item, installinfo['removals']):
            munkicommon.display_debug1(
                "%s has already been processed for removal." %
                manifestitemname_withversion)
            return True

    installEvidence = False
    for item in infoitems:
        if evidenceThisIsInstalled(item):
            installEvidence = True
            break

    if not installEvidence:
        munkicommon.display_detail("%s doesn't appear to be installed." %
                                    manifestitemname_withversion)
        iteminfo = {}
        iteminfo["manifestitem"] = manifestitemname_withversion
        iteminfo["installed"] = False
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
        munkicommon.display_warning("Could not find uninstall info for %s." %
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

    # make a list of the name and aliases of the current uninstall_item
    uninstall_item_names = []
    uninstall_item_names.append(uninstall_item.get('name'))
    #uninstall_item_names.extend(uninstall_item.get('aliases',[]))

    processednamesandaliases = []
    for catalogname in cataloglist:
        localcatalog = os.path.join(catalogsdir, catalogname)
        catalog_pl = FoundationPlist.readPlist(localcatalog)
        for item_pl in catalog_pl:
            namesandaliases = []
            namesandaliases.append(item_pl.get('name'))
            #namesandaliases.extend(item_pl.get('aliases',[]))
            if not set(namesandaliases).intersection(
                                            processednamesandaliases):
                if 'requires' in item_pl:
                    if set(item_pl['requires']).intersection(
                                                    uninstall_item_names):
                        munkicommon.display_debug1("%s requires %s, checking "
                                                   "to see if it's "
                                                   "installed..." %
                                                   (item_pl.get('name'),
                                                    manifestitemname))
                        if evidenceThisIsInstalled(item_pl):
                            munkicommon.display_detail("%s requires %s. "
                                                     "%s must be removed "
                                                     "as well." %
                                                     (item_pl.get('name'),
                                                      manifestitemname,
                                                      item_pl.get('name')))
                            success = processRemoval(item_pl.get('name'),
                                                     cataloglist, installinfo)
                            if not success:
                                dependentitemsremoved = False
                                break
            # record these names so we don't process them again
            processednamesandaliases.extend(namesandaliases)

    # if this package modifies another one, and we're using removepackages,
    # we must remove it as well
    # if we're using another removal method, we just have to hope that
    # the method is smart enough to get everything...
    if 'modifies' in uninstall_item and uninstallmethod == 'removepackages':
        modifies_value = uninstall_item['modifies']
        if type(modifies_value) == list:
            modifieditem = modifies_value[0]
        else:
            modifieditem = modifies_value
            (modifieditemname,
             modifieditemversion) = nameAndVersion(modifieditem)
            if not modifieditemname in uninstall_item_names:
                success = processRemoval(modifieditem, cataloglist,
                                         installinfo)
                if not success:
                    dependentitemsremoved = False

    if not dependentitemsremoved:
        munkicommon.display_warning("Will not attempt to remove %s because "
                                    "could not remove all items dependent "
                                    "on it." % manifestitemname_withversion)
        return False

    # Finally! We can record the removal information!
    iteminfo = {}
    iteminfo["name"] = uninstall_item.get('name', '')
    iteminfo["display_name"] = uninstall_item.get('display_name', '')
    iteminfo["manifestitem"] = manifestitemname_withversion
    iteminfo["description"] = "Will be removed."
    if packagesToRemove:
        # remove references for each package
        packagesToReallyRemove = []
        for pkg in packagesToRemove:
            munkicommon.display_debug1("Considering %s for removal..." % pkg)
            # find pkg in pkgdata['pkg_references'] and remove the reference
            # so we only remove packages if we're the last reference to it
            if pkg in pkgdata['pkg_references']:
                munkicommon.display_debug1("%s references are: %s" %
                                            (pkg,
                                             pkgdata['pkg_references'][pkg]))
                pkgdata['pkg_references'][pkg].remove(iteminfo["name"])
                if len(pkgdata['pkg_references'][pkg]) == 0:
                    munkicommon.display_debug1("Adding %s to removal list." %
                                                pkg)
                    packagesToReallyRemove.append(pkg)
            else:
                # This shouldn't happen
                munkicommon.display_warning("pkg id %s missing from pkgdata" %
                                             pkg)
        if packagesToReallyRemove:
            iteminfo['packages'] = packagesToReallyRemove
        else:
            # no packages that belong to this item only.
            munkicommon.display_warning("could not find unique packages to "
                                        "remove for %s" % iteminfo["name"])
            return False

    iteminfo["uninstall_method"] = uninstallmethod
    if uninstallmethod.startswith("Adobe"):
        if 'adobe_install_info' in item:
            iteminfo['adobe_install_info'] = item['adobe_install_info']
        else:
            if 'uninstaller_item_location' in item:
                location = uninstall_item['uninstaller_item_location']
            else:
                location = uninstall_item['installer_item_location']
            if not enoughDiskSpace(uninstall_item, uninstalling=True):
                return False

            (download_successful, download_path) = (
                download_installeritem(location))
            if download_successful:
                if verifySoftwarePackageIntegrity(
                    iteminfo['name'], download_path, item_pl,
                    'uninstaller_item_hash'):
                    filename = os.path.split(location)[1]
                    iteminfo['uninstaller_item'] = filename
                    iteminfo['adobe_package_name'] = \
                        uninstall_item.get('adobe_package_name','')
                else:
                    munkicommon.display_warning(
                        "Can't uinstall %s because the integrity check failed."
                        % iteminfo['name'])
                    return False
            else:
                munkicommon.display_warning("Failed to download the "
                                            "uninstaller for %s"
                                            % iteminfo["name"])
                return False
    elif uninstallmethod == "remove_copied_items":
        iteminfo['items_to_remove'] = item.get('items_to_copy', [])
    elif uninstallmethod == "remove_app":
        if uninstall_item.get('installs', None):
            iteminfo['remove_app_info'] = uninstall_item['installs'][0]

    # before we add this removal to the list,
    # check for installed updates and add them to the
    # removal list as well:
    update_list = lookForUpdates(iteminfo["name"], cataloglist)
    for update_item in update_list:
        # call us recursively...
        is_or_will_be_removed = processRemoval(update_item,
                                               cataloglist, installinfo)

    # finish recording info for this removal
    iteminfo["installed"] = True
    iteminfo["installed_version"] = uninstall_item.get('version')
    if 'RestartAction' in uninstall_item:
        iteminfo['RestartAction'] = uninstall_item['RestartAction']
    installinfo['removals'].append(iteminfo)
    munkicommon.display_detail(
        "Removal of %s added to ManagedInstaller tasks." %
         manifestitemname_withversion)
    return True


def processManifestForRemovals(manifestpath, installinfo,
                                                        parentcatalogs=None):
    """
    Processes manifests for removals. Can be recursive if manifests include
    other manifests.
    Probably doesn't handle circular manifest references well...
    """
    cataloglist = getManifestValueForKey(manifestpath, 'catalogs')
    if cataloglist:
        getCatalogs(cataloglist)
    elif parentcatalogs:
        cataloglist = parentcatalogs

    if cataloglist:
        nestedmanifests = getManifestValueForKey(manifestpath,
                                                 "included_manifests")
        if nestedmanifests:
            for item in nestedmanifests:
                if munkicommon.stopRequested():
                    return {}
                try:
                    nestedmanifestpath = getmanifest(item)
                except ManifestException:
                    nestedmanifestpath = None
                if nestedmanifestpath:
                    processManifestForRemovals(nestedmanifestpath,
                                               installinfo, cataloglist)

        autoremovalitems = getAutoRemovalItems(installinfo, cataloglist)
        explicitremovalitems = getManifestValueForKey(manifestpath,
                                                "managed_uninstalls") or []
        removalitems = autoremovalitems
        removalitems.extend(explicitremovalitems)
        for item in removalitems:
            if munkicommon.stopRequested():
                return {}
            is_or_will_be_removed = processRemoval(item, cataloglist,
                                                   installinfo)

    else:
        munkicommon.display_warning("Manifest %s has no 'catalogs'" %
                                    manifestpath)


def getManifestValueForKey(manifestpath, keyname):
    '''Returns a value for keyname in manifestpath'''
    try:
        plist = FoundationPlist.readPlist(manifestpath)
    except FoundationPlist.NSPropertyListSerializationException:
        munkicommon.display_error("Could not read plist %s" % manifestpath)
        return None
    if keyname in plist:
        return plist[keyname]
    else:
        return None


def getCatalogs(cataloglist):
    """
    Retreives the catalogs from the server and populates our catalogs
    dictionary
    """
    global catalog
    catalogbaseurl = munkicommon.pref('CatalogURL') or \
                     munkicommon.pref('SoftwareRepoURL') + "/catalogs/"
    if not catalogbaseurl.endswith('?') and not catalogbaseurl.endswith('/'):
        catalogbaseurl = catalogbaseurl + "/"
    munkicommon.display_debug2("Catalog base URL is: %s" % catalogbaseurl)
    catalog_dir = os.path.join(munkicommon.pref('ManagedInstallDir'),
                               "catalogs")

    for catalogname in cataloglist:
        if not catalogname in catalog:
            catalogurl = catalogbaseurl + urllib2.quote(catalogname)
            catalogpath = os.path.join(catalog_dir, catalogname)
            munkicommon.display_detail("Getting catalog %s..." % catalogname)
            message = "Retreiving catalog '%s'..." % catalogname
            (newcatalog, err) = getHTTPfileIfChangedAtomically(catalogurl,
                                                             catalogpath,
                                                             message=message)
            if newcatalog:
                if munkicommon.validPlist(newcatalog):
                    catalog[catalogname] = \
                        makeCatalogDB(FoundationPlist.readPlist(newcatalog))
                else:
                    munkicommon.display_error(
                        "Retreived catalog %s is invalid." % catalogname)
                    try:
                        os.unlink(newcatalog)
                    except (OSError, IOError):
                        pass
            else:
                munkicommon.display_error(
                    "Could not retrieve catalog %s from server." %
                     catalogname)
                munkicommon.display_error(err)

class ManifestException(Exception):
    # lets us raise an exception when we get an invalid
    # manifest.
    pass

manifests = {}
def getmanifest(partialurl, suppress_errors=False):
    """
    Gets a manifest from the server.
    Returns a local path to the downloaded manifest.
    """
    global manifests
    manifestbaseurl = munkicommon.pref('ManifestURL') or \
                      munkicommon.pref('SoftwareRepoURL') + "/manifests/"
    if not manifestbaseurl.endswith('?') and \
       not manifestbaseurl.endswith('/'):
        manifestbaseurl = manifestbaseurl + "/"
    manifest_dir = os.path.join(munkicommon.pref('ManagedInstallDir'),
                                "manifests")

    if partialurl.startswith("http://") or partialurl.startswith("https://"):
        # then it's really a request for the client's primary manifest
        manifesturl = partialurl
        partialurl = "client_manifest"
        manifestname = "client_manifest.plist"
    else:
        # request for nested manifest
        manifestname = os.path.split(partialurl)[1]
        manifesturl = manifestbaseurl + urllib2.quote(partialurl)

    if manifestname in manifests:
        return manifests[manifestname]

    munkicommon.display_debug2("Manifest base URL is: %s" % manifestbaseurl)
    munkicommon.display_detail("Getting manifest %s..." % partialurl)
    manifestpath = os.path.join(manifest_dir, manifestname)
    message = "Retreiving list of software for this machine..."
    (newmanifest, err) = getHTTPfileIfChangedAtomically(manifesturl,
                                                      manifestpath,
                                                      message=message)
    if err or not newmanifest:
        if not suppress_errors:
            munkicommon.display_error(
                "Could not retrieve manifest %s from the server." %
                 partialurl)
            munkicommon.display_error(err)
        return None

    if munkicommon.validPlist(newmanifest):
        # record it for future access
        manifests[manifestname] = newmanifest
        return newmanifest
    else:
        errormsg = "manifest returned for %s is invalid." % partialurl
        munkicommon.display_error(errormsg)
        try:
            os.unlink(newmanifest)
        except (OSError, IOError):
            pass
        raise ManifestException(errormsg)


def getPrimaryManifest(alternate_id):
    """
    Gets the client manifest from the server
    """
    manifest = ""
    manifesturl = munkicommon.pref('ManifestURL') or \
                  munkicommon.pref('SoftwareRepoURL') + "/manifests/"
    if not manifesturl.endswith('?') and not manifesturl.endswith('/'):
        manifesturl = manifesturl + "/"
    munkicommon.display_debug2("Manifest base URL is: %s" % manifesturl)

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
                                                    "certs", name)
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
            munkicommon.display_detail("No client id specified. "
                                       "Requesting %s..." % clientidentifier)
            manifest = getmanifest(manifesturl + clientidentifier,
                                   suppress_errors=True)
            if not manifest:
                # try the short hostname
                clientidentifier = hostname.split('.')[0]
                munkicommon.display_detail("Request failed. Trying %s..." %
                                            clientidentifier)
                manifest = getmanifest(manifesturl + clientidentifier,
                                        suppress_errors=True)
                if not manifest:
                    # last resort - try for the site_default manifest
                    clientidentifier = "site_default"
                    munkicommon.display_detail("Request failed. " +
                                               "Trying %s..." %
                                                clientidentifier)

        if not manifest:
            manifest = getmanifest(manifesturl +
                                   urllib2.quote(clientidentifier))
        if manifest:
            # record this info for later
            munkicommon.report['ManifestName'] = clientidentifier
            munkicommon.display_detail("Using manifest: %s" %
                                        clientidentifier)
    except ManifestException:
        # bad manifests throw an exception
        pass
    return manifest


def checkServer(url):
    '''A function we can call to check to see if the server is
    available before we kick off a full run. This can be fooled by
    ISPs that return results for non-existent web servers...'''
    # deconstruct URL so we can check availability
    (scheme, netloc, path, query, fragment) = urlparse.urlsplit(url)
    if scheme == "http":
        port = 80
    elif scheme == "https":
        port = 443
    else:
        return False

    # get rid of any embedded username/password
    netlocparts = netloc.split("@")
    netloc = netlocparts[-1]
    # split into host and port if present
    netlocparts = netloc.split(":")
    host = netlocparts[0]
    if host == "":
        return (-1, "Bad URL")
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
    header['http_result_code'] = "000"
    header['http_result_description'] = ""

    curldirectivepath = os.path.join(munkicommon.tmpdir,"curl_temp")
    tempdownloadpath = destinationpath + ".download"

    # we're writing all the curl options to a file and passing that to
    # curl so we avoid the problem of URLs showing up in a process listing
    try:
        fileobj = open(curldirectivepath, mode='w')
        print >> fileobj, "silent"         # no progress meter
        print >> fileobj, "show-error"     # print error msg to stderr
        print >> fileobj, "no-buffer"      # don't buffer output
        print >> fileobj, "fail"           # throw error if download fails
        print >> fileobj, "dump-header -"  # dump headers to stdout
        print >> fileobj, "speed-time = 30" # give up if too slow d/l
        print >> fileobj, 'output = "%s"' % tempdownloadpath
        print >> fileobj, 'url = "%s"' % url

        if cacert:
            if not os.path.isfile(cacert):
                raise CurlError(-1, "No CA cert at %s" % cacert)
            print >> fileobj, 'cacert = "%s"' % cacert
        if capath:
            if not os.path.isdir(capath):
                raise CurlError(-2, "No CA directory at %s" % capath)
            print >> fileobj, 'capath = "%s"' % capath
        if cert:
            if not os.path.isfile(cert):
                raise CurlError(-3, "No client cert at %s" % cert)
            print >> fileobj, 'cert = "%s"' % cert
        if key:
            if not os.path.isfile(cert):
                raise CurlError(-4, "No client key at %s" % key)
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

        fileobj.close()
    except:
        raise CurlError(-5, "Error writing curl directive")

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
            info =  proc.stdout.readline().strip("\r\n")
            if info:
                if info.startswith("HTTP/"):
                    header['http_result_code'] = info.split(None, 2)[1]
                    header['http_result_description'] = info.split(None, 2)[2]
                elif ": " in info:
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
                if header.get('http_result_code') == "206":
                    # partial content because we're resuming
                    munkicommon.display_detail(
                        "Resuming partial download for %s" %
                                        os.path.basename(destinationpath))
                    contentrange = header.get('content-range')
                    if contentrange.startswith("bytes"):
                        try:
                            targetsize = int(contentrange.split("/")[1])
                        except (ValueError, TypeError):
                            targetsize = 0

                if message and header['http_result_code'] != "304":
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
        http_result = header['http_result_code']
        if downloadedpercent != 100 and \
            http_result.startswith('2'):
            downloadedsize = os.path.getsize(tempdownloadpath)
            if downloadedsize >= targetsize:
                munkicommon.display_percent_done(100, 100)
                os.rename(tempdownloadpath, destinationpath)
                return header
            else:
                # not enough bytes retreived
                if not resume and os.path.exists(tempdownloadpath):
                    os.unlink(tempdownloadpath)
                raise CurlError(-5, "Expected %s bytes, got: %s" %
                                        (targetsize, downloadedsize))
        elif http_result.startswith('2'):
            os.rename(tempdownloadpath, destinationpath)
            return header
        elif http_result == "304":
            return header
        else:
            raise HTTPError(http_result,
                                header['http_result_description'])


def getHTTPfileIfChangedAtomically(url, destinationpath,
                                 message=None, resume=False):
    '''Gets file from HTTP URL, checking first to see if it has changed on the
       server.'''
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
        ca_cert_path = os.path.join(ManagedInstallDir, "certs", "ca.pem")
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
                client_cert_path = os.path.join(ManagedInstallDir, "certs",
                                                                    name)
                if os.path.exists(client_cert_path):
                    break

    etag = None
    getonlyifnewer = False
    if os.path.exists(destinationpath):
        getonlyifnewer = True
        # see if we have an etag attribute
        if "com.googlecode.munki.etag" in xattr.listxattr(destinationpath):
            getonlyifnewer = False
            etag = xattr.getxattr(destinationpath,
                                  "com.googlecode.munki.etag")

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
        err = "Error %s: %s" % tuple(err)
        if not os.path.exists(destinationpath):
            destinationpath = None
    except HTTPError, err:
        err = "HTTP result %s: %s" % tuple(err)
        if not os.path.exists(destinationpath):
            destinationpath = None
    else:
        err = None
        if header['http_result_code'] == "304":
            # not modified, return existing file
            munkicommon.display_debug1("%s already exists and is up-to-date."
                                            % destinationpath)
        else:
            if header.get("last-modified"):
                # set the modtime of the downloaded file to the modtime of the
                # file on the server
                modtimestr = header['last-modified']
                modtimetuple = time.strptime(modtimestr,
                                             "%a, %d %b %Y %H:%M:%S %Z")
                modtimeint = calendar.timegm(modtimetuple)
                os.utime(destinationpath, (time.time(), modtimeint))
            if header.get("etag"):
                # store etag in extended attribute for future use
                xattr.setxattr(destinationpath,
                               "com.googlecode.munki.etag", header['etag'])

    return destinationpath, err


def getMachineFacts():
    global machine

    machine['hostname'] = os.uname()[1]
    machine['arch'] = os.uname()[4]
    cmd = ['/usr/bin/sw_vers', '-productVersion']
    proc = subprocess.Popen(cmd, shell=False, bufsize=1,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (output, err) = proc.communicate()
    # format version string like "10.5.8", so that "10.6" becomes "10.6.0"
    machine['os_vers'] = munkicommon.padVersionString(
                                                str(output).rstrip("\n"),3)


# some globals
machine = {}
def check(client_id=''):
    '''Checks for available new or updated managed software, downloading
    installer items if needed. Returns 1 if there are available updates,
    0 if there are no available updates, and -1 if there were errors.'''
    getMachineFacts()
    munkicommon.report['MachineInfo'] = machine

    ManagedInstallDir = munkicommon.pref('ManagedInstallDir')

    if munkicommon.munkistatusoutput:
        munkistatus.activate()
        munkistatus.message("Checking for available updates...")
        munkistatus.detail("")
        munkistatus.percent("-1")

    munkicommon.log("### Beginning managed software check ###")

    mainmanifestpath = getPrimaryManifest(client_id)
    if munkicommon.stopRequested():
        return 0

    installinfo = {}

    if mainmanifestpath:
        # initialize our installinfo record
        installinfo['managed_installs'] = []
        installinfo['removals'] = []
        installinfo['optional_installs'] = []
        munkicommon.display_detail("**Checking for installs**")
        installinfo = processManifestForInstalls(mainmanifestpath,
                                                 installinfo)
        if munkicommon.stopRequested():
            return 0

        if munkicommon.munkistatusoutput:
            # reset progress indicator and detail field
            munkistatus.message("Checking for additional changes...")
            munkistatus.percent("-1")
            munkistatus.detail('')

        # now generate a list of items to be uninstalled
        munkicommon.display_detail("**Checking for removals**")
        processManifestForRemovals(mainmanifestpath, installinfo)
        if munkicommon.stopRequested():
            return 0

        # build list of optional installs
        processManifestForOptionalInstalls(mainmanifestpath, installinfo)
        if munkicommon.stopRequested():
            return 0

        # now process any self-serve choices
        usermanifest = "/Users/Shared/.SelfServeManifest"
        selfservemanifest = os.path.join(ManagedInstallDir, "manifests",
                                                "SelfServeManifest")
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
                    except OSErr:
                        pass
            except FoundationPlist.FoundationPlistException:
                pass

        if os.path.exists(selfservemanifest):
            # use catalogs from main manifest for self-serve manifest
            cataloglist = getManifestValueForKey(mainmanifestpath, 'catalogs')
            munkicommon.display_detail("**Processing self-serve choices**")
            processManifestForInstalls(selfservemanifest,
                                                     installinfo, cataloglist)
            processManifestForRemovals(selfservemanifest,
                                                     installinfo, cataloglist)

            # update optional installs with info from self-serve manifest
            for item in installinfo['optional_installs']:
                if isItemInInstallInfo(item,
                                        installinfo['managed_installs']):
                    item['will_be_installed'] = True
                elif isItemInInstallInfo(item, installinfo['removals']):
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
        cache_list = [item["installer_item"]
                      for item in installinfo.get('managed_installs',[])]
        cache_list.extend([item["uninstaller_item"]
                           for item in installinfo.get('removals',[])
                           if item.get('uninstaller_item')])
        cachedir = os.path.join(ManagedInstallDir, "Cache")
        for item in os.listdir(cachedir):
            if item.endswith(".download"):
                # we have a partial download here
                # remove the ".download" from the end of the filename
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
                munkicommon.display_detail("Removing %s from cache" % item)
                os.unlink(os.path.join(cachedir, item))

        # write out install list so our installer
        # can use it to install things in the right order
        installinfochanged = True
        installinfopath = os.path.join(ManagedInstallDir, "InstallInfo.plist")
        if os.path.exists(installinfopath):
            oldinstallinfo = FoundationPlist.readPlist(installinfopath)
            if oldinstallinfo == installinfo:
                installinfochanged = False
                munkicommon.display_detail("No change in InstallInfo.")
        if installinfochanged:
            FoundationPlist.writePlist(installinfo,
                                       os.path.join(ManagedInstallDir,
                                                    "InstallInfo.plist"))
    else:
        # couldn't get a primary manifest. Check to see if we have a valid
        # install/remove list from an earlier run.
        munkicommon.display_error(
            "Could not retrieve managed install primary manifest.")
        installinfopath = os.path.join(ManagedInstallDir, "InstallInfo.plist")
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


    installcount = len(installinfo.get("managed_installs", []))
    removalcount = len(installinfo.get("removals", []))

    munkicommon.log("")
    if installcount:
        munkicommon.display_info(
            "The following items will be installed or upgraded:")
    for item in installinfo.get('managed_installs', []):
        if item.get('installer_item'):
            munkicommon.display_info("    + %s-%s" %
                                     (item.get('name',''),
                                      item.get('version_to_install','')))
            if item.get('description'):
                munkicommon.display_info("        %s" % item['description'])
            if item.get('RestartAction') == 'RequireRestart' or \
               item.get('RestartAction') == 'RecommendRestart':
                munkicommon.display_info("       *Restart required")
                munkicommon.report['RestartRequired'] = True
            if item.get('RestartAction') == 'RequireLogout':
                munkicommon.display_info("       *Logout required")
                munkicommon.report['LogoutRequired'] = True

    if removalcount:
        munkicommon.display_info("The following items will be removed:")
    for item in installinfo.get('removals', []):
        if item.get('installed'):
            munkicommon.display_info("    - %s" % item.get('name'))
            if item.get('RestartAction') == 'RequireRestart' or \
               item.get('RestartAction') == 'RecommendRestart':
                munkicommon.display_info("       *Restart required")
                munkicommon.report['RestartRequired'] = True
            if item.get('RestartAction') == 'RequireLogout':
                munkicommon.display_info("       *Logout required")
                munkicommon.report['LogoutRequired'] = True

    if installcount == 0 and removalcount == 0:
        munkicommon.display_info(
            "No changes to managed software are available.")

    munkicommon.savereport()
    munkicommon.log("###    End managed software check    ###")

    if installcount or removalcount:
        return 1
    else:
        return 0


def main():
    '''Placeholder'''
    pass


if __name__ == '__main__':
    main()

