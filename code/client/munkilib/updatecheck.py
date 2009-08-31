#!/usr/bin/python
# encoding: utf-8
#
# Copyright 2009 Greg Neagle.
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
import sys
import os
import subprocess
from distutils import version
import urllib2
import urlparse
import httplib
import hashlib
import datetime
import time
import calendar
import socket

#our lib
import munkicommon
import munkistatus
import FoundationPlist

def reporterrors():
    # just a placeholder right now;
    # this needs to be expanded to support error reporting
    # via email and HTTP CGI.
    # (and maybe moved to a library module so the installer
    # can use it, too.)
    
    managedinstallprefs = munkicommon.prefs()
    clientidentifier = managedinstallprefs.get('ClientIdentifier','')
    #alternate_id = option_id
    hostname = os.uname()[1]
    
    print "installcheck errors %s:" % datetime.datetime.now().ctime()
    print "Hostname:           %s" % hostname
    print "Client identifier:  %s" % clientidentifier
    #print "Alternate ID:       %s" % alternate_id
    print "-----------------------------------------"
    print munkicommon.errors


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
        name = item['name']
        vers = item['version']
        
        # build indexes for items by name and version
        if not name in name_table:
            name_table[name] = {}
        if not vers in name_table[name]:
            name_table[name][vers] = []
        name_table[name][vers].append(itemindex)
        
        # do the same for any aliases
        if 'aliases' in item:
            for alias in item['aliases']:
                if not alias in name_table:
                    name_table[alias] = {}
                if not vers in name_table[alias]:
                    name_table[alias][vers] = []
                name_table[alias][vers].append(itemindex)
        
        # build table of receipts              
        if 'receipts' in item:
            for receipt in item['receipts']:
                if 'packageid' in receipt:
                    if not receipt['packageid'] in pkgid_table:
                        pkgid_table[receipt['packageid']] = {}
                    if not receipt['version'] in pkgid_table[receipt['packageid']]:
                        pkgid_table[receipt['packageid']][receipt['version']] = []
                    pkgid_table[receipt['packageid']][receipt['version']].append(itemindex)
                    
        pkgdb = {}
        pkgdb['named'] = name_table
        pkgdb['receipts'] = pkgid_table
        #pkgdb['installeritem_table'] = installeritem_table
        pkgdb['items'] = catalogitems

    return pkgdb


def addPackageids(catalogitems, pkgid_table):
    '''
    Adds packageids from each catalogitem to a dictionary
    '''
    for item in catalogitems:
        name = item['name']
        if not name in pkgid_table:
            pkgid_table[name] = []
        if 'receipts' in item:
            for receipt in item['receipts']:
                if 'packageid' in receipt:
                    if not receipt['packageid'] in pkgid_table[name]:
                        pkgid_table[name].append(receipt['packageid'])
                        
    
def getInstalledPackages():
    """
    Builds a dictionary of installed receipts and their version number
    """
    installedpkgs = {}
    # Check /Library/Receipts
    receiptsdir = "/Library/Receipts"
    if os.path.exists(receiptsdir):
        installitems = os.listdir(receiptsdir)
        for item in installitems:
            if item.endswith(".pkg"):
                infoplist = os.path.join(receiptsdir, item, "Contents/Info.plist")
                if os.path.exists(infoplist):
                    try:
                        pl = FoundationPlist.readPlist(infoplist)
                        pkgid = pl.get('CFBundleIdentifier')
                        if not pkgid:
                            # special case JAMF Composer packages
                            pkgid = pl.get('Bundle identifier')
                        if pkgid:
                            thisversion = munkicommon.getExtendedVersion(os.path.join(receiptsdir, item))
                            if not pkgid in installedpkgs:
                                installedpkgs[pkgid] = thisversion
                            else:
                                # pkgid is already in our list. There must be multiple receipts with the same pkgid.
                                # in this case, we want the highest version number, since that's the one that's installed,
                                # since presumably the newer package replaced the older
                                storedversion = installedpkgs[pkgid]
                                if version.LooseVersion(thisversion) > version.LooseVersion(storedversion):
                                    installedpkgs[pkgid] = thisversion
                    except:
                        pass
                                
    # Now check new (Leopard and later) package database
    p = subprocess.Popen(["/usr/sbin/pkgutil", "--pkgs"], bufsize=1, 
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out, err) = p.communicate()

    if out:
        pkgs = out.split("\n")
        for pkg in pkgs:
            p = subprocess.Popen(["/usr/sbin/pkgutil", "--pkg-info-plist", pkg], bufsize=1, 
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            (out, err) = p.communicate()

            if out:
                pl = FoundationPlist.readPlistFromString(out)
                if "pkg-version" in pl:
                    installedpkgs[pkg] = pl["pkg-version"]
        
    return installedpkgs

# global pkgdata
pkgdata = {}
def analyzeInstalledPkgs():
    global pkgdata
    managed_pkgids = {}
    for catalogname in catalog.keys():
        catalogitems = catalog[catalogname]['items']
        addPackageids(catalogitems, managed_pkgids)
        
    installedpkgs = getInstalledPackages()
    
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


# appdict is a global so we don't call system_profiler more than once per session
appdict = {}
def getAppData():
    """
    Queries system_profiler and returns a dict
    of app info items
    """
    global appdict
    if appdict == {}:
        munkicommon.display_debug1("Getting info on currently installed applications...")
        cmd = ['/usr/sbin/system_profiler', '-XML', 'SPApplicationsDataType']
        p = subprocess.Popen(cmd, shell=False, bufsize=1, stdin=subprocess.PIPE, 
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        (plist, err) = p.communicate()
        if p.returncode == 0:
            pl = FoundationPlist.readPlistFromString(plist)
            # top level is an array instead of a dict, so get dict
            spdict = pl[0]
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
            pl = FoundationPlist.readPlist(infopath)
            if 'CFBundleIdentifier' in pl:
                return pl['CFBundleIdentifier']
        except:
            pass
            
    return None


def compareVersions(thisvers, thatvers):
    """
    Returns -1 if thisvers is older than thatvers
    Returns 1 if thisvers is the same as thatvers
    Returns 2 if thisvers is newer than thatvers
    """
    thisvers = munkicommon.padVersionString(thisvers,5)
    thatvers = munkicommon.padVersionString(thatvers,5)
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
            munkicommon.display_error("No application name or bundleid was specified!")
            return -2
    
    munkicommon.display_debug1("Looking for application %s with bundleid: %s, version %s..." % (name, bundleid, versionstring))
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
        munkicommon.display_debug1("\tDid not find this application on the startup disk.")
        return 0
    
    for item in appinfo:
        if '_name' in item:
            munkicommon.display_debug2("\tName: \t %s" % item['_name'].encode("UTF-8"))
        if 'path' in item:
            munkicommon.display_debug2("\tPath: \t %s" % item['path'].encode("UTF-8"))
            munkicommon.display_debug2("\tCFBundleIdentifier: \t %s" % getAppBundleID(item['path']))
        if 'version' in item:
            munkicommon.display_debug2("\tVersion: \t %s" % item['version'].encode("UTF-8"))
            if compareVersions(item['version'], versionstring) == 1:
                # version is the same
                return 1
            if compareVersions(item['version'], versionstring) == 2:
                # version is newer
                return 2
                
    # if we got this far, must only be older
    munkicommon.display_debug1("An older version of this application is present.")
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
        filepath = os.path.join(item['path'], 'Contents', 'Info.plist')
        vers = item['CFBundleShortVersionString']
    else:
        munkicommon.display_error("Missing bundle path or version!")
        return -2

    munkicommon.display_debug1("Checking %s for version %s..." % (filepath, vers))
    if not os.path.exists(filepath):
        munkicommon.display_debug1("\tNo Info.plist found at %s" % filepath)
        return 0

    try:
        pl = FoundationPlist.readPlist(filepath) 
    except:
        munkicommon.display_debug1("\t%s may not be a plist!" % filepath)
        return 0

    if 'CFBundleShortVersionString' in pl:
        installedvers = pl['CFBundleShortVersionString']
        return compareVersions(installedvers, vers)
    else:
        munkicommon.display_debug1("\tNo version info in %s." % filepath)
        return 0


def comparePlistVersion(item):
    """
    Gets the CFBundleShortVersionString from the plist
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
    
    munkicommon.display_debug1("Checking %s for version %s..." % (filepath, vers))
    if not os.path.exists(filepath):
        munkicommon.display_debug1("\tNo plist found at %s" % filepath)
        return 0
        
    try:
        pl = FoundationPlist.readPlist(filepath) 
    except:
        munkicommon.display_debug1("\t%s may not be a plist!" % filepath)
        return 0
    
    if 'CFBundleShortVersionString' in pl:
        installedvers = pl['CFBundleShortVersionString']
        return compareVersions(installedvers, vers)
    else:
        munkicommon.display_debug1("\tNo version info in %s." % filepath)
        return 0


def getmd5hash(filename):
    if not os.path.isfile(filename):
        return "NOT A FILE"
        
    f = open(filename, 'rb')
    m = hashlib.md5()
    while 1:
        chunk = f.read(2**16)
        if not chunk:
            break
        m.update(chunk)
    f.close()
    return m.hexdigest()


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
                ondiskchecksum = getmd5hash(filepath)
                munkicommon.display_debug2("Comparing checksums...")
                if storedchecksum == ondiskchecksum:
                    munkicommon.display_debug2("Checksums match.")
                    return 1
                else:
                    munkicommon.display_debug2("Checksums differ: expected %s, got %s" % (storedchecksum, ondiskchecksum))
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
    if 'packageid' in item and 'version' in item:
        pkgid = item['packageid']
        vers = item['version']
    else:
        print "Missing packageid or version info!"
        return -2
        
    munkicommon.display_debug1("Looking for package %s, version %s" % (pkgid, vers))
    installedvers = munkicommon.getInstalledPackageVersion(pkgid)
    if installedvers:
        # compare the same number of version components.
        # if munkicommon.getInstalledPackageVersion(pkgid) returns "7.1.0"
        # and our candidate version is "7.1.0.123.456"
        # consider this a match.
        # we do this because the Leopard (and later) package database
        # sometimes seems to store less detail on versions than is available
        # in the original package
        component_count = len(str(installedvers).split("."))
        normalized_vers = munkicommon.padVersionString(vers,component_count)
        return compareVersions(installedvers, normalized_vers)
    else:
        munkicommon.display_debug1("\tThis package is not currently installed.")
        return 0
        
        
def getInstalledVersion(pl):
    """
    Attempts to determine the currently installed version of the item
    described by pl
    """
    if 'receipts' in pl:
        for receipt in pl['receipts']:
            installedpkgvers = munkicommon.getInstalledPackageVersion(receipt['packageid'])
            munkicommon.display_debug2("Looking for %s, version %s" % (receipt['packageid'], receipt['version']))
            if compareVersions(installedpkgvers, receipt['version']) == 2:
                # version is higher
                installedversion = "newer than %s" % pl['version']
                return installedversion
            if compareVersions(installedpkgvers, receipt['version']) == -1:
                # version is lower
                installedversion = "older than %s" % pl['version']
                return installedversion
        # if we get here all reciepts match
        return pl['version']
               
    if 'installs' in pl:
        for install_item in pl['installs']:
            if install_item['type'] == 'application':
                name = install_item.get('CFBundleName')
                bundleid = install_item.get('CFBundleIdentifier')
                munkicommon.display_debug2("Looking for application %s, version %s" % (name, install_item.get('CFBundleIdentifier')))
                try:
                    # check default location for app
                    filepath = os.path.join(install_item['path'], 'Contents', 'Info.plist')
                    pl = FoundationPlist.readPlist(filepath)
                    installedappvers = pl.get('CFBundleShortVersionString')
                except:
                    # that didn't work, fall through to the slow way
                    # using System Profiler
                    appinfo = []
                    appdata = getAppData()
                    if appdata:
                        for ad_item in appdata:
                            if bundleid:
                                if 'path' in ad_item:
                                    if getAppBundleID(ad_item['path']) == bundleid:
                                        appinfo.append(ad_item)
                            elif name:
                                if '_name' in ad_item:
                                    if ad_item['_name'] == name:
                                        appinfo.append(ad_item)
                
                    for ai_item in appinfo:
                        if 'version' in ai_item:
                            if compareVersions(ai_item['version'], maxversion) == 2:
                                # version is higher
                                maxversion = ai_item['version']
                    installedappvers = maxversion
            
            if compareVersions(installedappvers, install_item['CFBundleShortVersionString']) == 2:
                # version is higher
                installedversion = "newer than %s" % pl['version']
                return installedversion
                    
            if compareVersions(installedappvers, install_item['CFBundleShortVersionString']) == -1:
                # version is lower
                installedversion = "older than %s" % pl['version']
                return installedversion
        
        # if we get here all app versions match
        return pl['version']

    # if we fall through to here we have no idea what version we have
    return "UNKNOWN"            


def download_installeritem(location):
    """
    Downloads a installer item.
    """
    ManagedInstallDir = munkicommon.ManagedInstallDir()
    sw_repo_baseurl = munkicommon.SoftwareRepoURL()
    downloadbaseurl = sw_repo_baseurl + "/pkgs/"
    mycachedir = os.path.join(ManagedInstallDir, "Cache")
    
    # build a URL, quoting the the location to encode reserved characters
    pkgurl = downloadbaseurl + urllib2.quote(location)
    
    # grab last path component of location to derive package name.
    pkgname = os.path.basename(location)
    destinationpath = os.path.join(mycachedir, pkgname)
    
    # bump up verboseness so we get download percentage done feedback.
    # this is kind of a hack...
    oldverbose = munkicommon.verbose
    munkicommon.verbose = oldverbose + 1
    
    dl_message = "Downloading %s from %s" % (pkgname, pkgurl)
    munkicommon.log(dl_message)
    dl_message = "Downloading %s..." % pkgname
    (path, err) = getHTTPfileIfNewerAtomically(pkgurl, destinationpath, message=dl_message)
    
    # set verboseness back.
    munkicommon.verbose = oldverbose
    
    if path:
        return True
    else:
        munkicommon.display_error("Could not download %s from server." % pkgname)
        munkicommon.display_error(err)
        return False
        


def isItemInInstallInfo(manifestitem_pl, thelist, vers=''):
    """
    Returns True if the manifest item has already
    been processed (it's in the list) and, optionally,
    the version is the same or greater.
    """
    names = []
    names.append(manifestitem_pl.get('name'))
    names.extend(manifestitem_pl.get('aliases',[]))
    for item in thelist:
        if item.get('name') in names:
            if not vers:
                return True
            if item.get('installed'):
                return True
            #if the version already processed is the same or greater, then we're good
            if compareVersions(item.get('version_to_install'), vers) in (1,2):
                return True
    
    return False
    
    
def nameAndVersion(s):
    """
    Splits a string into the name and version number.
    Name and version must be seperated with a hyphen ('-') or double hyphen ('--').
    'TextWrangler-2.3b1' becomes ('TextWrangler', '2.3b1')
    'AdobePhotoshopCS3--11.2.1' becomes ('AdobePhotoshopCS3', '11.2.1')
    'MicrosoftOffice2008-12.2.1' becomes ('MicrosoftOffice2008', '12.2.1')
    """
    for delim in ('--', '-'):
        if s.count(delim) > 0:
            chunks = s.split(delim)
            vers = chunks.pop()
            name = delim.join(chunks)
            if vers[0] in "0123456789":
                return (name, vers)
            
    return (s, '')


def getAllItemsWithName(name,cataloglist):
    """
    Searches the catalogs in cataloglist for all items matching
    the given name. Returns a list of pkginfo items.
    
    The returned list is sorted with newest version first. No precedence is
    given to catalog order.
    
    """
    def compare_item_versions(a, b):
        return cmp(version.LooseVersion(b['version']), version.LooseVersion(a['version']))
        
    itemlist = []
    # we'll throw away any included version info
    (name, includedversion) = nameAndVersion(name)
    
    munkicommon.display_debug1("Looking for all items matching: %s..." % name)
    for catalogname in cataloglist:
        # is name in the catalog name table?
        if name in catalog[catalogname]['named']:
            versionsmatchingname = catalog[catalogname]['named'][name]
            for vers in versionsmatchingname.keys():
                if vers != 'latest':
                    indexlist = catalog[catalogname]['named'][name][vers]
                    for index in indexlist:
                        thisitem = catalog[catalogname]['items'][index]
                        if not thisitem in itemlist:
                            munkicommon.display_debug1("Adding item %s, version %s from catalog %s..." % (name, thisitem['version'], catalogname))
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
        vers = munkicommon.padVersionString(vers,5)
    else:
        vers = 'latest'
        
    munkicommon.display_debug1("Looking for detail for: %s, version %s..." % (name, vers))
    for catalogname in cataloglist:
        # is name or alias in the catalog?
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
            
            munkicommon.display_debug1("Considering %s items with name %s from catalog %s" % (len(indexlist), name, catalogname))
            for index in indexlist:
                item = catalog[catalogname]['items'][index]
                # we have an item whose name and version matches the request.
                # now check to see if it meets os and cpu requirements
                if 'minimum_os_version' in item:
                    munkicommon.display_debug1("Considering item %s, version %s with minimum os version required %s" % (item['name'], item['version'], item['minimum_os_version']))
                    if version.LooseVersion(machine['os_vers']) < version.LooseVersion(item['minimum_os_version']):
                        # skip this one, go to the next
                        continue
                        
                if 'supported_architectures' in item:
                    supported_arch_found = False
                    munkicommon.display_debug1("Considering item %s, version %s with supported architectures: %s" % (item['name'], item['version'], item['supported_architectures']))
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
                
                # item name, version, minimum_os_version, and supported_architecture are all OK
                munkicommon.display_debug1("Found %s, version %s in catalog %s" % (item['name'], item['version'], catalogname))
                return item
               
    # if we got this far, we didn't find it.
    munkicommon.display_debug1("Nothing found")
    return None
    
    
def enoughDiskSpace(manifestitem_pl):
    """
    Used to determine if there is enough disk space
    to be able to download and install the manifestitem
    """
    # fudgefactor is set to 100MB
    fudgefactor = 100000
    installeritemsize = 0
    installedsize = 0
    if 'installer_item_size' in manifestitem_pl:
        installeritemsize = manifestitem_pl['installer_item_size']
    if 'installed_size' in manifestitem_pl:
        installedsize = manifestitem_pl['installed_size']
    diskspaceneeded = (installeritemsize + installedsize + fudgefactor)/1024
    availablediskspace = munkicommon.getAvailableDiskSpace()/1024
    if availablediskspace > diskspaceneeded:
        return True
    else:
        munkicommon.display_info("There is insufficient disk space to download and install %s." % manifestitem_pl.get('name'))
        munkicommon.display_info("    %sMB needed; %sMB available" % (diskspaceneeded, availablediskspace))
        return False


def isInstalled(pl):
    """
    Checks to see if the item described by pl
    (or a newer version) is currently installed
    All tests must pass to be considered installed.
    Returns True if it looks like this or a newer version
    is installed; False otherwise.
    """
    if 'installs' in pl:
       installitems = pl['installs']
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
    elif 'receipts' in pl:
       receipts = pl['receipts']
       for item in receipts:
           if compareReceiptVersion(item) in (-1, 0):
               # not there or older
               return False

    # if we got this far, we passed all the tests, so the item
    # must be installed (or we don't have enough info...)
    return True


def evidenceThisIsInstalled(pl):
    """
    Checks to see if there is evidence that 
    the item described by pl
    (any version) is currently installed.
    If any tests pass, the item might be installed.
    So this isn't the same as isInstalled()
    """
    global pkgdata
    # first check our pkgdata
    if pl['name'] in pkgdata['installed_names']:
        return True
    if 'aliases' in pl:
        for alias in pl['aliases']:
            if alias in pkgdata['installed_names']:
                return True
                
    if 'installs' in pl:
        installitems = pl['installs']
        for item in installitems:
            if 'path' in item:
                # we can only check by path; if the item has been moved
                # we're not clever enough to find it, and our removal
                # methods are even less clever
                if os.path.exists(item['path']):
                    # some version is installed
                    return True
                    
    # this has been superceded by our pkgdata check
    #if 'receipts' in pl:
    #    receipts = pl['receipts']
    #    for item in receipts:
    #        if 'packageid' in item:
    #            if munkicommon.getInstalledPackageVersion(item['packageid']):
    #                # some version of this package is installed
    #                return True

    # if we got this far, we failed all the tests, so the item
    # must not be installed (or we have bad metadata...)
    return False
    

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
    
    managedinstallprefs = munkicommon.prefs()
    ManagedInstallDir = managedinstallprefs['ManagedInstallDir']
    
    manifestitemname = os.path.split(manifestitem)[1]
    #munkicommon.display_info("Getting detail on %s..." % manifestitemname)
    pl = getItemDetail(manifestitem, cataloglist)
    
    if not pl:
        munkicommon.display_info("Could not process item %s for install because could not get detail." % manifestitem)
        return False
                 
    # check to see if item is already in the installlist:
    if isItemInInstallInfo(pl, installinfo['managed_installs'], pl.get('version')):
        munkicommon.display_debug1("%s has already been processed for install." % manifestitemname)
        return True
        
    # check dependencies
    dependenciesMet = True
    
    # there are two kinds of dependencies.
    #
    # 'requires' are prerequistes: package A requires package B be installed first.
    #  if package A is removed, package B is unaffected. requires is one to many.
    #
    # 'modifies' is a package the current package modifies on install; generally this means the
    # current package is an updater..  For example, 'Office2008' might resolve to Office2008--12.1.7 which modifies 
    # Office2008--12.1.0 which modifies Office2008--12.0.0. (Office2008--12.1.7 and 
    # Office2008--12.1.0 are updater packages, Office2008--12.0.0 is the original installer.)
    # If you later remove Office2008, you want to remove everything installed by all three packages.
    # 'modifies' provides a method to theoretically figure it all out.  
    # 'modifies' is one to one relationship - this item can modify only one other item.
    #
    # when processing installs, the two dependencies are basically equivilent;
    # the real difference comes when processing removals.
    
    if 'requires' in pl:
        dependencies = pl['requires']
        for item in dependencies:
            munkicommon.display_detail("%s requires %s. Getting info on %s..." % (manifestitemname, item, item))
            success = processInstall(item, cataloglist, installinfo)
            if not success:
                dependenciesMet = False
              
    if 'modifies' in pl:
        dependencies = pl['modifies']
        if type(dependencies) == list:
            # in case this was put in as an array
            # we support only a single modified item.
            item = dependencies[0]
        else:
            item = dependencies
            
        munkicommon.display_detail("%s modifies %s. Getting info on %s..." % (manifestitemname, item, item))
        success = processInstall(item, cataloglist, installinfo)
        if not success:
            dependenciesMet = False
    
    if not dependenciesMet:
        munkicommon.display_info("Didn't attempt to install %s because could not resolve all dependencies." % manifestitemname)
        return False
    
    iteminfo = {}
    iteminfo["name"] = pl.get('name', '')
    iteminfo["manifestitem"] = manifestitemname
    iteminfo["description"] = pl.get('description', '')
               
    if not isInstalled(pl):
        munkicommon.display_detail("Need to install %s" % manifestitemname)
        # check to see if there is enough free space to download and install
        if not enoughDiskSpace(pl):
            iteminfo['installed'] = False
            iteminfo['note'] = "Insufficient disk space to download and install"
            installinfo['managed_installs'].append(iteminfo)
            return False
        
        if 'installer_item_location' in pl:
            location = pl['installer_item_location']
            if download_installeritem(location):
                filename = os.path.split(location)[1]
                iteminfo['installer_item'] = filename
                iteminfo['installed'] = False
                iteminfo["version_to_install"] = pl.get('version',"UNKNOWN")
                iteminfo['description'] = pl.get('description','')
                iteminfo['display_name'] = pl.get('display_name','')
                if 'installer_choices_xml' in pl:
                    iteminfo['installer_choices_xml'] = pl['installer_choices_xml']
                if 'RestartAction' in pl:
                    iteminfo['RestartAction'] = pl['RestartAction']
                installinfo['managed_installs'].append(iteminfo)
                return True
            else:
                iteminfo['installed'] = False
                iteminfo['note'] = "Download failed"
                installinfo['managed_installs'].append(iteminfo)
                return False
        else:
            munkicommon.display_info("Can't install %s because there's no download info for the installer item" % manifestitemname)
            iteminfo['installed'] = False
            iteminfo['note'] = "Download info missing"
            installinfo['managed_installs'].append(iteminfo)
            return False
    else:
        iteminfo["installed"] = True
        #iteminfo["installed_version"] = getInstalledVersion(pl)
        installinfo['managed_installs'].append(iteminfo)
        # remove included version number if any
        (name, includedversion) = nameAndVersion(manifestitemname)
        munkicommon.display_detail("%s version %s (or newer) is already installed." % (name, pl['version']))
        return True
    
    
def processManifestForInstalls(manifestpath, installinfo):
    """
    Processes manifests to build a list of items to install.
    Can be recursive if manifests inlcude other manifests.
    Probably doesn't handle circular manifest references well...
    """
    cataloglist = getManifestValueForKey(manifestpath, 'catalogs')
    
    if cataloglist:
        getCatalogs(cataloglist)
    
    nestedmanifests = getManifestValueForKey(manifestpath, "included_manifests")
    if nestedmanifests:
        for item in nestedmanifests:
            nestedmanifestpath = getmanifest(item)
            if munkicommon.stopRequested():
                return {}
            if nestedmanifestpath:
                listofinstalls = processManifestForInstalls(nestedmanifestpath, installinfo)
                    
    installitems = getManifestValueForKey(manifestpath, "managed_installs")
    if installitems:
        for item in installitems:
            if munkicommon.stopRequested():
                return {}
            result = processInstall(item, cataloglist, installinfo)
        
    return installinfo
        
    
def getReceiptsToRemove(item):
    name = item['name']
    if name in pkgdata['receipts_for_name']:
        return pkgdata['receipts_for_name'][name]
    # now check aliases
    if 'aliases' in item:
         for alias in item['aliases']:
             if alias in pkgdata['receipts_for_name']:
                 return pkgdata['receipts_for_name'][alias]
    # found nothing
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
    global pkgdata
    manifestitemname_withversion = os.path.split(manifestitem)[1]
    
    munkicommon.display_detail("Processing manifest item %s..." % manifestitemname_withversion)
    (manifestitemname, includedversion) = nameAndVersion(manifestitemname_withversion)
    infoitems = []
    if includedversion:
        # a specific version was specified
        pl = getItemDetail(manifestitemname, cataloglist, includedversion)
        if pl:
            infoitems.append(pl)
    else:
        # get all items matching the name provided
        infoitems = getAllItemsWithName(manifestitemname,cataloglist)
        
    if not infoitems:
        munkicommon.display_info("Could not get information for %s" % manifestitemname_withversion)
        return False
    
    for item in infoitems:
        # check to see if item is already in the installlist,
        # if so, that's bad - it means it's scheduled to be installed
        # _and_ removed.  We'll warn, and do nothing with this item.
        if isItemInInstallInfo(item, installinfo['managed_installs']):
            munkicommon.display_info("Will not attempt to remove %s because some version of it is in the list of managed installs, or it is required by another managed install." % manifestitemname_withversion)
            return False
    
    for item in infoitems:
        # check to see if item is already in the removallist:
        if isItemInInstallInfo(item, installinfo['removals']):
            munkicommon.display_debug1("%s has already been processed for removal." % manifestitemname_withversion)
            return True
    
    installEvidence = False       
    for item in infoitems:
        if evidenceThisIsInstalled(item):
            installEvidence = True
            break
            
    if not installEvidence:
        munkicommon.display_detail("%s doesn't appear to be installed." % manifestitemname_withversion)
        iteminfo = {}
        iteminfo["manifestitem"] = manifestitemname_withversion
        iteminfo["installed"] = False
        installinfo['removals'].append(iteminfo)
        return True
        
    uninstall_item = None
    for item in infoitems:
        # check for uninstall info
        # walk through the list of items (sorted newest first)
        # and grab the first uninstall method we find.
        if 'uninstallable' in item and 'uninstall_method' in item:
            uninstallmethod = item['uninstall_method']
            if uninstallmethod == 'removepackages':
                packagesToRemove = getReceiptsToRemove(item)
                if packagesToRemove:
                    uninstall_item = item
                    break
                else:
                    # no matching packages found. Check next item
                    continue
            else:
                # uninstall_method is a local script.
                # Check to see if it exists and is executable
                if os.path.exists(uninstallmethod) and os.access(uninstallmethod, os.X_OK):
                    uninstall_item = item
                    break
                    
    if not uninstall_item:
        # we didn't find an item that seems to match anything on disk.
        munkicommon.display_info("Could not find uninstall info for %s." % manifestitemname_withversion)
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
    ManagedInstallDir = munkicommon.ManagedInstallDir()
    catalogsdir = os.path.join(ManagedInstallDir, 'catalogs')
    
    # make a list of the name and aliases of the current uninstall_item
    uninstall_item_names = []
    uninstall_item_names.append(uninstall_item.get('name'))
    uninstall_item_names.extend(uninstall_item.get('aliases',[]))
    
    processednamesandaliases = []
    for catalogname in cataloglist:
        localcatalog = os.path.join(catalogsdir,catalogname)
        catalog = FoundationPlist.readPlist(localcatalog)
        for item_pl in catalog:
            namesandaliases = []
            namesandaliases.append(item_pl.get('name'))
            namesandaliases.extend(item_pl.get('aliases',[])) 
            if not set(namesandaliases).intersection(processednamesandaliases):
                if 'requires' in item_pl:
                    if set(item_pl['requires']).intersection(uninstall_item_names):
                        munkicommon.display_debug1("%s requires %s, checking to see if it's installed..." % (item_pl.get('name'), manifestitemname))
                        if evidenceThisIsInstalled(item_pl):
                            munkicommon.display_info("%s requires %s and must be removed as well." % (item_pl.get('name'), manifestitemname))
                            success = processRemoval(item_pl.get('name'), cataloglist, installinfo)
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
            (modifieditemname, modifieditemversion) = nameAndVersion(modifieditem)
            if not modifieditemname in uninstall_item_names:
                success = processRemoval(modifieditem, cataloglist, installinfo)
                if not success:
                    dependentitemsremoved = False
    
    if not dependentitemsremoved:
        munkicommon.display_info("Will not attempt to remove %s because could not remove all items dependent on it." % manifestitemname_withversion)
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
            # find pkg in pkgdata['pkg_references'] and remove the reference so
            # we only remove packages if we're the last reference to it
            if pkg in pkgdata['pkg_references']:
                munkicommon.display_debug1("%s references are: %s" % (pkg, pkgdata['pkg_refcount'][pkg]))
                pkgdata['pkg_references'][pkg].remove(iteminfo["name"])
                if len(pkgdata['pkg_refcount'][pkg]) == 0:
                    munkicommon.display_debug1("Adding %s to removal list." % pkg)
                    packagesToReallyRemove.append(pkg)
            else:
                # This shouldn't happen
                munkicommon.display_error("WARNING: pkg id %s missing from pkgdata" % pkg)
        iteminfo['packages'] = packagesToReallyRemove
    iteminfo["uninstall_method"] = uninstallmethod
    iteminfo["installed"] = True
    iteminfo["installed_version"] = uninstall_item.get('version')
    if 'RestartAction' in uninstall_item:
        iteminfo['RestartAction'] = uninstall_item['RestartAction']
    installinfo['removals'].append(iteminfo)
    munkicommon.display_detail("Removal of %s added to ManagedInstaller tasks." % manifestitemname_withversion)
    return True
    
    
def processManifestForRemovals(manifestpath, installinfo):
    """
    Processes manifests for removals. Can be recursive if manifests include other manifests.
    Probably doesn't handle circular manifest references well...
    """
    global pkgdata
    if pkgdata == {}:
        # build our database of installed packages
        analyzeInstalledPkgs()
        
    cataloglist = getManifestValueForKey(manifestpath, 'catalogs')

    nestedmanifests = getManifestValueForKey(manifestpath, "included_manifests")
    if nestedmanifests:
        for item in nestedmanifests:
            if munkicommon.stopRequested():
                return {}
            nestedmanifestpath = getmanifest(item)
            if nestedmanifestpath:
                listofremovals = processManifestForRemovals(nestedmanifestpath, installinfo)

    removalitems = getManifestValueForKey(manifestpath, "managed_uninstalls")
    if removalitems:
        for item in removalitems:
            if munkicommon.stopRequested():
                return {}
            result = processRemoval(item, cataloglist, installinfo)

    return installinfo


def getManifestValueForKey(manifestpath, keyname):    
    try:
        pl = FoundationPlist.readPlist(manifestpath)
    except:
        munkicommon.display_error("Could not read plist %s" % manifestpath)
        return None    
    if keyname in pl:
        return pl[keyname]
    else:
        return None
        
    
def getCatalogs(cataloglist):
    """
    Retreives the catalogs from the server and populates our catalogs dictionary
    """
    global catalog
    managedinstallprefs = munkicommon.prefs()
    sw_repo_baseurl = managedinstallprefs['SoftwareRepoURL']
    catalog_dir = os.path.join(managedinstallprefs['ManagedInstallDir'], "catalogs")
    
    for catalogname in cataloglist:
        if not catalogname in catalog:
            catalogurl = sw_repo_baseurl + "/catalogs/" + urllib2.quote(catalogname)
            catalogpath = os.path.join(catalog_dir, catalogname)
            message = "Getting catalog %s from %s..." % (catalogname, catalogurl)
            munkicommon.log(message)
            message = "Retreiving catalog '%s'..." % catalogname
            (newcatalog, err) = getHTTPfileIfNewerAtomically(catalogurl, catalogpath, message=message)
            if newcatalog:
                catalog[catalogname] = makeCatalogDB(FoundationPlist.readPlist(newcatalog))
            else:
                munkicommon.display_error("Could not retreive catalog %s from server." % catalog)
                munkicommon.display_error(err)
            

def getmanifest(partialurl, suppress_errors=False):
    """
    Gets a manifest from the server
    """
    managedinstallprefs = munkicommon.prefs()
    sw_repo_baseurl = managedinstallprefs['SoftwareRepoURL']
    manifest_dir = os.path.join(managedinstallprefs['ManagedInstallDir'], "manifests")
        
    if partialurl.startswith("http"):
        # then it's really a request for the client's primary manifest
        manifesturl = partialurl
        manifestname = "client_manifest.plist"
    else:
        # request for nested manifest
        manifestname = os.path.split(partialurl)[1]
        manifesturl = sw_repo_baseurl + "/manifests/" + urllib2.quote(partialurl)
        
    manifestpath = os.path.join(manifest_dir, manifestname)
    message = "Getting manifest %s from %s..." % (manifestname, manifesturl)
    munkicommon.log(message)
    message = "Retreiving list of software for this machine..."
    (newmanifest, err) = getHTTPfileIfNewerAtomically(manifesturl, manifestpath, message=message)
    if not newmanifest and not suppress_errors:
        munkicommon.display_error("Could not retreive manifest %s from the server." % partialurl)
        munkicommon.display_error(err)
        
    return newmanifest


def getPrimaryManifest(alternate_id):
    """
    Gets the client manifest from the server
    """
    global errors
    manifest = ""
    managedinstallprefs = munkicommon.prefs()
    manifesturl = managedinstallprefs['ManifestURL']
    clientidentifier = managedinstallprefs.get('ClientIdentifier','')

    if not manifesturl.endswith('?') and not manifesturl.endswith('/'):
        manifesturl = manifesturl + "/"
    if alternate_id:
        # use id passed in at command-line
        manifesturl = manifesturl + urllib2.quote(alternate_id)
    elif clientidentifier:
        # use client_identfier from /Library/Preferences/ManagedInstalls.plist
        manifesturl = manifesturl + urllib2.quote(clientidentifier)
    else:
        # no client identifier specified, so use the hostname
        hostname = os.uname()[1]
        munkicommon.display_detail("No client id specified. Requesting %s..." % (manifesturl + hostname))
        manifest = getmanifest(manifesturl + hostname,suppress_errors=True)
        if not manifest:
            # try the short hostname
            munkicommon.display_detail("Request failed. Trying %s..." % (manifesturl + hostname.split('.')[0]))
            manifest = getmanifest(manifesturl + hostname.split('.')[0], suppress_errors=True)
            if not manifest:
                # last resort - try for the site_default manifest
                munkicommon.display_detail("Request failed. Trying %s..." % (manifesturl + "site_default"))
                manifesturl = manifesturl + "site_default"
                
    if not manifest:
        manifest = getmanifest(manifesturl)
    if manifest:
        # clear out any errors we got while trying to find
        # the primary manifest
        errors = ""
        
    return manifest
    
    
def getInstallCount(installinfo):
    count = 0
    for item in installinfo.get('managed_installs',[]):
        if 'installer_item' in item:
            count +=1
    return count


def getRemovalCount(installinfo):
    count = 0
    for item in installinfo.get('removals',[]):
        if 'installed' in item:
            if item['installed']:
                count +=1
    return count


def checkServer():
    '''in progress'''
    managedinstallprefs = munkicommon.prefs()
    manifesturl = managedinstallprefs['ManifestURL']
    # deconstruct URL so we can check availability
    port = 80
    (scheme, netloc, path, query, fragment) = urlparse.urlsplit(manifesturl)
    # get rid of any embedded username/password
    netlocparts = netloc.split("@")
    netloc = netlocparts[-1]
    # split into host and port if present
    netlocparts = netloc.split(":")
    host = netlocparts[0]
    if len(netlocparts) == 2:
        port = netlocparts[1]
        
    s = socket.socket()
    #try:
    s.connect((host, port))
    s.close()
    return True
    #except:
        #return False
        

# HTTP download functions
#
#    Handles http downloads
#
#    Supports Last-modified and If-modified-since headers so
#    we download from the server only if we don't have it in the
#    local cache, or the locally cached item is older than the
#    one on the server.
#
#    Possible failure mode: if client's main catalog gets pointed 
#    to a different, older, catalog, we'll fail to retreive it.
#    Need to check content length as well, and if it changes, retreive
#    it anyway.
#
#    Should probably cleanup/unify 
#       httpDownload/getfilefromhttpurl/getHTTPfileIfNewerAtomically
#

# urllib2 has no handler for client certificates, so make one...
# Subclass HTTPSClientAuthHandler adapted from the following sources:
# http://www.osmonov.com/2009/04/client-certificates-with-urllib2.html
# http://www.threepillarsoftware.com/soap_client_auth
# http://bugs.python.org/issue3466
# bcw
class HTTPSClientAuthHandler(urllib2.HTTPSHandler):  
   def __init__(self, key, cert):  
       urllib2.HTTPSHandler.__init__(self)  
       self.key = key  
       self.cert = cert  
   def https_open(self, req):  
       # Rather than pass in a reference to a connection class, we pass in  
       # a reference to a function which, for all intents and purposes,  
       # will behave as a constructor  
       return self.do_open(self.getConnection, req)  
   def getConnection(self, host, timeout=300):  
       return httplib.HTTPSConnection(host, key_file=self.key, cert_file=self.cert)

# An empty subclass for identifying missing certs, bcw
# Maybe there is a better place for this?
class UseClientCertificateError(IOError):
    pass

def httpDownload(url, filename, headers={}, postData=None, reporthook=None, message=None):

    # The required name for combination certifcate and private key
    # File must be PEM formatted and include the client's private key
    # bcw
    pemfile = 'munki.pem'
    
    # Grab the prefs for UseClientCertificate and construct a loc for the cert, bcw
    ManagedInstallDir = munkicommon.ManagedInstallDir()
    UseClientCertificate = munkicommon.UseClientCertificate()
    cert = os.path.join(ManagedInstallDir, 'certs', pemfile)
    
    reqObj = urllib2.Request(url, postData, headers)
    
    if UseClientCertificate == True:
        # Check for the existence of the PEM file, bcw
    	if os.path.isfile(cert):
            # Construct a secure urllib2 opener, bcw
            secureopener = urllib2.build_opener(HTTPSClientAuthHandler(cert, cert))
            fp = secureopener.open(reqObj)
    	else:
	    # No x509 cert so fail -0x509 (decimal -1289). So amusing. bcw
    	    raise UseClientCertificateError(-1289, "PEM file missing, %s" % cert)
  
    else:	    
        fp = urllib2.urlopen(reqObj)
    
    headers = fp.info()
    
    if message:
        # log always, display if verbose is 2 or more
        munkicommon.display_detail(message)
        if munkicommon.munkistatusoutput:
            # send to detail field on MunkiStatus
            munkistatus.detail(message)
        
    #read & write fileObj to filename
    tfp = open(filename, 'wb')
    result = filename, headers
    bs = 1024*8
    size = -1
    read = 0
    blocknum = 0

    if reporthook:
        if "content-length" in headers:
            size = int(headers["Content-Length"])
        reporthook(blocknum, bs, size)

    while 1:
        block = fp.read(bs)
        if block == "":
            break
        read += len(block)
        tfp.write(block)
        blocknum += 1
        if reporthook:
            reporthook(blocknum, bs, size)

    fp.close()
    tfp.close()

    # raise exception if actual size does not match content-length header
    if size >= 0 and read < size:
        raise ContentTooShortError("retrieval incomplete: got only %i out "
                                    "of %i bytes" % (read, size), result)

    return result


def getfilefromhttpurl(url,filepath, ifmodifiedsince=None, message=None):
    """
    gets a file from a url.
    If 'ifmodifiedsince' is specified, this header is set
    and the file is not retreived if it hasn't changed on the server.
    Returns 0 if successful, or HTTP error code
    """
    def reporthook(block_count, block_size, file_size):
         if (file_size > 0):
            max_blocks = file_size/block_size
            munkicommon.display_percent_done(block_count, max_blocks)
                   
    try:
        request_headers = {}
        if ifmodifiedsince:
            modtimestr = time.strftime("%a, %d %b %Y %H:%M:%S GMT",time.gmtime(ifmodifiedsince))
            request_headers["If-Modified-Since"] = modtimestr
        (f,headers) = httpDownload(url, filename=filepath, headers=request_headers, reporthook=reporthook, message=message)
        if 'last-modified' in headers:
            # set the modtime of the downloaded file to the modtime of the
            # file on the server
            modtimestr = headers['last-modified']
            modtimetuple = time.strptime(modtimestr, "%a, %d %b %Y %H:%M:%S %Z")
            modtimeint = calendar.timegm(modtimetuple)
            os.utime(filepath, (time.time(), modtimeint))
            
    except urllib2.HTTPError, err:
        return err.code
    # Uncommented the exception handler below and added str(err)
    # This will catch missing or invalid certs/keys in getHTTPfileIfNewerAtomically 
    # bcw
    except urllib2.URLError, err:
        return str(err)
    # This will catch missing certs in getHTTPfileIfNewerAtomically, bcw
    except UseClientCertificateError, err:
        return err 
    except IOError, err:
        return err
    except Exception, err:
        return (-1, err)
    
    return 0


def getHTTPfileIfNewerAtomically(url,destinationpath, message=None):
    """
    Gets file from HTTP URL, only if newer on web server.
    Replaces pre-existing file only on success. (thus 'Atomically')
    """
    err = None
    mytemppath = os.path.join(munkicommon.tmpdir,"TempDownload")
    if os.path.exists(destinationpath):
        modtime = os.stat(destinationpath).st_mtime
    else:
        modtime = None
    result = getfilefromhttpurl(url, mytemppath, ifmodifiedsince=modtime, message=message)
    if result == 0:
        try:
            os.rename(mytemppath, destinationpath)
            return destinationpath, err
        except:
            err = "Could not write to %s" % destinationpath
            destinationpath = None
    elif result == 304:
        # not modified, return existing file
        munkicommon.display_debug1("%s already exists and is up-to-date." % destinationpath)
        return destinationpath, err
    # Added to catch private key errors when the opener is constructed, bcw
    elif result == '<urlopen error SSL_CTX_use_PrivateKey_file error>':
        err = "SSL_CTX_use_PrivateKey_file error: PrivateKey Invalid or Missing"
        destinationpath = None
    # Added to catch certificate errors when the opener is constructed, bcw
    elif result == '<urlopen error SSL_CTX_use_certificate_chain_file error>':
        err = "SSL_CTX_use_certificate_chain_file error: Certificate Invalid or Missing"
        destinationpath = None
    else:
        err = "Error code: %s retreiving %s" % (result, url)
        destinationpath = None
        
    if os.path.exists(mytemppath):
        os.remove(mytemppath)
        
    return destinationpath, err
    
    
def getMachineFacts():
    global machine
    
    machine['arch'] = os.uname()[4]
    cmd = ['/usr/bin/sw_vers', '-productVersion']
    p = subprocess.Popen(cmd, shell=False, bufsize=1, stdin=subprocess.PIPE, 
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (output, err) = p.communicate()
    machine['os_vers'] = output.rstrip("\n")
    

# some globals
machine = {}

def check(id=''):
    '''Checks for available new or updated managed software, downloading installer items
    if needed. Returns 1 if there are available updates,  0 if there are no available updates, 
    and -1 if there were errors.'''
    
    getMachineFacts()
    
    ManagedInstallDir = munkicommon.ManagedInstallDir()
            
    if munkicommon.munkistatusoutput:
        munkistatus.activate()
        munkistatus.message("Checking for available updates...")
        munkistatus.percent("-1")
        
    munkicommon.log("### Beginning managed software check ###")
    
    mainmanifestpath = getPrimaryManifest(id)
    if munkicommon.stopRequested():
        return 0
        
    installinfo = {}
    
    if mainmanifestpath:   
        # initialize our installinfo record
        installinfo['managed_installs'] = []
        installinfo['removals'] = []
        munkicommon.display_detail("**Checking for installs**")
        installinfo = processManifestForInstalls(mainmanifestpath, installinfo)
        if munkicommon.stopRequested():
            return 0
        
        # clean up cache dir
        # remove any item in the install cache that isn't scheduled
        # to be installed --
        # this allows us to 'pull back' an item before it is installed
        # by removing it from the manifest
        installer_item_list = []
        for item in installinfo['managed_installs']:
            if "installer_item" in item:
                installer_item_list.append(item["installer_item"])
        
        cachedir = os.path.join(ManagedInstallDir, "Cache")
        for item in os.listdir(cachedir):
            if item not in installer_item_list:
                munkicommon.display_detail("Removing %s from cache" % item)
                os.unlink(os.path.join(cachedir, item))
        
        if munkicommon.munkistatusoutput:
            # reset progress indicator and detail field
            munkistatus.percent("-1")
            munkistatus.detail('')
        
        # now generate a list of items to be uninstalled
        munkicommon.display_detail("**Checking for removals**")
        if munkicommon.stopRequested():
            return 0
        installinfo = processManifestForRemovals(mainmanifestpath, installinfo)
        if munkicommon.munkistatusoutput:
            munkistatus.disableStopButton()
        
        # need to write out install list so the autoinstaller
        # can use it to install things in the right order
        installinfochanged = True
        installinfopath = os.path.join(ManagedInstallDir, "InstallInfo.plist")
        if os.path.exists(installinfopath):
            oldinstallinfo = FoundationPlist.readPlist(installinfopath)
            if oldinstallinfo == installinfo:
                installinfochanged = False
                munkicommon.display_detail("No change in InstallInfo.")
        if installinfochanged:
            FoundationPlist.writePlist(installinfo, os.path.join(ManagedInstallDir, "InstallInfo.plist"))
            
    else:
        # couldn't get a primary manifest. Check to see if we have a valid InstallList from
        # an earlier run.
        munkicommon.display_error("Could not retreive managed install primary manifest.")
        installinfopath = os.path.join(ManagedInstallDir, "InstallInfo.plist")
        if os.path.exists(installinfopath):
            try:
                installinfo = FoundationPlist.readPlist(installinfopath)
            except:
                installinfo = {}
                
        
    installcount = getInstallCount(installinfo)
    removalcount = getRemovalCount(installinfo)
    
    if installcount:
        munkicommon.display_info("The following items will be installed or upgraded:")
        for item in installinfo['managed_installs']:
            if item.get('installer_item'):
                munkicommon.display_info("    + %s-%s" % (item.get('name',''), item.get('version_to_install','')))
                if item.get('description'):
                   munkicommon.display_info("        %s" % item['description'])
                if item.get('RestartAction') == 'RequireRestart':
                    munkicommon.display_info("       *Restart required")
    if removalcount:
        munkicommon.display_info("The following items will be removed:")
        for item in installinfo['removals']:
            if item.get('installed'):
                munkicommon.display_info("    - %s" % item.get('name'))
                if item.get('RestartAction') == 'RequireRestart':
                    munkicommon.display_info("       *Restart required")
    
    if installcount == 0 and removalcount == 0:
        munkicommon.display_info("No changes to managed software are available.")
        
    munkicommon.log("###    End managed software check    ###")
    
    if munkicommon.errors:
        reporterrors()
    
    if installcount or removalcount:
        return 1
    else:
        return 0
        
        
def main():
    pass


if __name__ == '__main__':
    main()

