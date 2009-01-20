#!/usr/bin/env python
# encoding: utf-8
"""
catalogcheck.py

Created by Greg Neagle on 2008-11-13.
"""

#standard libs
import sys
import os
import plistlib
import tempfile
import subprocess
from distutils import version
import urlparse
import optparse
import hashlib

#our lib
import managedinstalls

# appdict is a global so we don't call system_profiler more than once per session
appdict = {}
def getAppData():
    """
    Queries system_profiler and returns a dict
    of app info items
    """
    global appdict
    if appdict == {}:
        print "Getting info on currently installed applications..."
        cmd = ['/usr/sbin/system_profiler', '-XML', 'SPApplicationsDataType']
        p = subprocess.Popen(cmd, shell=False, bufsize=1, stdin=subprocess.PIPE, 
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        (plist, err) = p.communicate()
        if p.returncode == 0:
            pl = plistlib.readPlistFromString(plist)
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
            pl = plistlib.readPlist(infopath)
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
    if version.LooseVersion(thisvers) < version.LooseVersion(thatvers):
        print "\tInstalled version is older (%s)." % thisvers
        return -1
    elif version.LooseVersion(thisvers) == version.LooseVersion(thatvers):
        print "\tThis version is currently installed."
        return 1
    else:
        print "\tA newer version is currently installed (%s)." % thisvers
        return 2


def isSameOrNewerApplicationInstalled(app):
    """
    app is a dict with application
    bundle info
    uses system profiler data to look for
    an app that is the same or newer version
    """
    
    name = bundleid = ''
    versionstring = '0.0.0'
    if 'CFBundleName' in app:
        name = app['CFBundleName']
    if 'CFBundleIdentifier' in app:
        bundleid = app['CFBundleIdentifier']
    if 'CFBundleShortVersionString' in app:
        versionstring = app['CFBundleShortVersionString']
        
    if name == '' and bundleid == '':
        print "No application name or bundleid was specified!"
        # return True so we don't install
        return True
    
    print "Looking for application %s with bundleid: %s, version %s..." % (name, bundleid, versionstring)
    appinfo = []
    appdata = getAppData()
    if appdata:
        for item in appdata:
            if bundleid:
                if 'path' in item:
                    if getAppBundleID(item['path']) == bundleid:
                        appinfo.append(item)
            elif name:
                if '_name' in item:
                    if item['_name'] == name:
                        appinfo.append(item)
    
    for item in appinfo:
        if '_name' in item:
            print "\tName: \t %s" % item['_name'].encode("UTF-8")
        if 'path' in item:
            print "\tPath: \t %s" % item['path'].encode("UTF-8")
            print "\tCFBundleIdentifier: \t %s" % getAppBundleID(item['path'])
        if 'version' in item:
            print "\tVersion: \t %s" % item['version'].encode("UTF-8")
            if compareVersions(item['version'], versionstring) > 0:
                return True
                
    # if we got this far, we didn't find the same or newer
    print "Did not find the same or newer application on the startup disk."
    return False


def compareBundleVersion(item):
    """
    Gets the CFBundleShortVersionString from the Info.plist
    in bundlepath/Contents and compares versions.
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
        print "Missing bundle path or version!"
        return -2

    print "Checking %s for version %s..." % (filepath, vers)
    if not os.path.exists(filepath):
        print "\tNo Info.plist found at %s" % filepath
        return 0

    try:
        pl = plistlib.readPlist(filepath) 
    except:
        print "\t%s may not be a plist!" % filepath
        return 0

    if 'CFBundleShortVersionString' in pl:
        installedvers = pl['CFBundleShortVersionString']
        return compareVersions(installedvers, vers)
    else:
        print "\tNo version info in %s." % filepath
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
        print "Missing plist path or version!"
        return -2
    
    print "Checking %s for version %s..." % (filepath, vers)
    if not os.path.exists(filepath):
        print "\tNo plist found at %s" % filepath
        return 0
        
    try:
        pl = plistlib.readPlist(filepath) 
    except:
        print "\t%s may not be a plist!" % filepath
        return 0
    
    if 'CFBundleShortVersionString' in pl:
        installedvers = pl['CFBundleShortVersionString']
        return compareVersions(installedvers, vers)
    else:
        print "\tNo version info in %s." % filepath
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
    To do: add checksum support
    """
    if 'path' in item:
        filepath = item['path']
        print "Checking existence of %s..." % filepath
        if os.path.exists(filepath):
            print "\tExists."
            if 'md5checksum' in item:
                storedchecksum = item['md5checksum']
                ondiskchecksum = getmd5hash(filepath)
                print "Comparing checksums..."
                if storedchecksum == ondiskchecksum:
                    print "Checksums match."
                    return 1
                else:
                    print "Checksums differ: expected %s, got %s" % (storedchecksum, ondiskchecksum)
                    return 0
            return 1
        else:
            print "\tDoes not exist."
            return 0
    else:
        print "No path specified!"
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
        
    print "Looking for package %s, version %s" % (pkgid, vers)
    installedvers = managedinstalls.getInstalledPackageVersion(pkgid)
    if installedvers:
        return compareVersions(installedvers, vers)
    else:
        print "\tThis package is not currently installed." 
        return 0


def download_installeritem(pkgurl):
    global mytmpdir
    
    managed_install_dir = managedinstalls.managed_install_dir()
    mycachedir = os.path.join(managed_install_dir, "Cache")    
    pkgname = os.path.basename(urlparse.urlsplit(pkgurl)[2])
    destinationpath = os.path.join(mycachedir, pkgname)
    if os.path.exists(destinationpath):
        itemmodtime = os.stat(destinationpath).st_mtime
    else:
        itemmodtime = None
        
    print "Downloading %s from %s" % (pkgname, pkgurl)
    tempfilepath = os.path.join(mytmpdir, pkgname)
    result = managedinstalls.getfilefromhttpurl(pkgurl, tempfilepath, showprogress=True, ifmodifiedsince=itemmodtime)
    if result == 0:
        os.rename(tempfilepath, destinationpath)
        return True
    elif result == 304:
        # not modified
        print "Installer item %s is already in the install cache." % pkgname
        return True
    else:
        print >>sys.stderr, "Error code: %s" % result
        if os.path.exists(tempfilepath):
            os.remove(tempfilepath)
        print "Couldn't get %s: %s" % (pkgname, result)
        return False


def isItemInInstallList(catalogitem_pl, thelist):
    """
    Returns True if the filename from the download location 
    for catalogitem is already in the install list, 
    and therefore already scheduled to be installed.
    """
    if 'installer_item_location' in catalogitem_pl:
        location = catalogitem_pl['installer_item_location']
        filename = os.path.split(location)[1]
        for item in thelist:
            if "installer_item" in item:
                if filename == item['installer_item']:
                    return True
            
    return False


def getCatalogItemDetail(item, defaultbranch=''):
    
    managedinstallprefs = managedinstalls.prefs()
    sw_repo_baseurl = managedinstallprefs['sw_repo_url']
    managed_install_dir = managedinstallprefs['managed_install_dir']
    
    catalogitempath = os.path.join(managed_install_dir, "catalogitems")
    catalogbaseurl = sw_repo_baseurl + "/catalogitems"
    
    if defaultbranch == '':
        defaultbranch = "production"
    
    itemname = os.path.split(item)[1]
    itempath = os.path.join(catalogitempath, itemname)
    if os.path.exists(itempath):
        itemmodtime = os.stat(itempath).st_mtime
    else:
        itemmodtime = None
        
    if item.startswith("/"):
        # branch in item name
        itemurl = catalogbaseurl + item
    else:
        # use default branch
        itemurl = catalogbaseurl + "/" + defaultbranch + "/" + item
    
    tempfilepath = os.path.join(mytmpdir, itemname)
    print "Getting detail for %s from %s..." % (item, itemurl)
    result = managedinstalls.getfilefromhttpurl(itemurl, tempfilepath, showprogress=True, ifmodifiedsince=itemmodtime)
    if result == 0:
        os.rename(tempfilepath, itempath)
    elif result == 304:
        # not modified, just return existing item
        print "Item %s in local cache is up-to-date." % item
        return itempath
    else:
        print >>sys.stderr, "Error code: %s" % result
        if os.path.exists(tempfilepath):
            os.remove(tempfilepath)
               
    if os.path.exists(itempath):
        return itempath
    else:
        print "Couldn't get detail for item %s: %s" % (item, result)
        return ""


def enoughDiskSpace(catalogitem_pl):
    # fudgefactor is set to 100MB
    fudgefactor = 100000
    installeritemsize = 0
    installedsize = 0
    if 'installer_item_size' in catalogitem_pl:
        installeritemsize = catalogitem_pl['installer_item_size']
    if 'installed_size' in catalogitem_pl:
        installedsize = catalogitem_pl['installed_size']
    diskspaceneeded = installeritemsize + installedsize + fudgefactor
    availablediskspace = managedinstalls.getAvailableDiskSpace()
    if availablediskspace > diskspaceneeded:
        return True
    else:
        print "There is insufficient disk space to download and install. %sMB needed; %sMB available" % (int(diskspaceneeded/1024), int(availablediskspace/1024))
        return False


def processInstalls(catalogitem, defaultbranch, installlist):
    """
    Processes a catalog item. Determines if it needs to be
    installed, and if so, if any items it is dependent on need to 
    be installed first.  Items to be installed are added to the
    installlist (a list of filenames)
    Calls itself recursively as it processes dependencies.
    Returns a boolean; when processing dependencies, a false return
    will stop the installation of a dependent item
    """
    
    managedinstallprefs = managedinstalls.prefs()
    sw_repo_baseurl = managedinstallprefs['sw_repo_url']
    managed_install_dir = managedinstallprefs['managed_install_dir']
    
    catalogitempath = os.path.join(managed_install_dir, "catalogitems")
    downloadbaseurl = sw_repo_baseurl + "/pkgs/"
    
    catalogitemname = os.path.split(catalogitem)[1]
    print "\nProcessing catalog item %s..." % catalogitemname
    catalogitemdetail = getCatalogItemDetail(catalogitem, defaultbranch)
    
    if not catalogitemdetail:
        return False
    
    try:
        pl = plistlib.readPlist(catalogitemdetail)
    except:
        print >>sys.stderr, "%s is not a valid plist!" % catalogitem
        return False
        
    # check to see if item is already in the installlist:
    if isItemInInstallList(pl, installlist):
        print "%s is already scheduled to be installed." % catalogitemname
        return True
    
    # check dependencies
    dependenciesMet = True
    if 'dependencies' in pl:
        dependencies = pl['dependencies']
        for item in dependencies:
            print "%s is dependent on %s. Getting info on %s..." % (catalogitemname, item, item)
            success = processInstalls(item, defaultbranch, installlist)
            if not success:
                dependenciesMet = False
                
    if not dependenciesMet:
        print "Didn't attempt to install %s because could not resolve all dependencies." % catalogitemname
        return False
        
    needToInstall = False 
    if 'installs' in pl:
        installitems = pl['installs']
        for item in installitems:
            if 'type' in item:
                if item['type'] == 'application':
                    if not isSameOrNewerApplicationInstalled(item):
                        print "Need to install %s" % catalogitemname
                        needToInstall = True
                        # once we know we need to install this one,
                        # no need to keep checking
                        break
                if item['type'] == 'bundle':
                    comparisonResult = compareBundleVersion(item)
                    if comparisonResult == -1 or comparisonResult == 0 :
                        # not there or older
                        print "Need to install %s" % catalogitemname
                        needToInstall = True
                        # once we know we need to install this one,
                        # no need to keep checking
                        break
                if item['type'] == 'plist':
                    comparisonResult = comparePlistVersion(item)
                    if comparisonResult == -1 or comparisonResult == 0 :
                        # not there or older
                        print "Need to install %s" % catalogitemname
                        needToInstall = True
                        # once we know we need to install this one,
                        # no need to keep checking
                        break
                if item['type'] == 'file':
                    if filesystemItemExists(item) == 0 :
                        # not there
                        print "Need to install %s" % catalogitemname
                        needToInstall = True
                        # once we know we need to install this one,
                        # no need to keep checking
                        break
    elif 'receipts' in pl:
        receipts = pl['receipts']
        for item in receipts:
            comparisonResult = compareReceiptVersion(item)
            if comparisonResult == -1 or comparisonResult == 0 :
                # not there or older
                print "Need to install %s" % catalogitemname
                needToInstall = True
                # once we know we need to install this one,
                # no need to keep checking
                break
            
    name = description = ""
    try:
        name = pl['name']
        description = pl['description']
    except:
        pass
    iteminfo = {}
    iteminfo["name"] = name
    iteminfo["catalogitem"] = catalogitemname
    iteminfo["description"] = description
               
    if needToInstall:
        # check to see if there is enough free space to download and install
        if not enoughDiskSpace(pl):
            return False
        
        if 'installer_item_location' in pl:
            location = pl['installer_item_location']
            url = downloadbaseurl + location
            if download_installeritem(url):
                filename = os.path.split(location)[1]
                iteminfo["installer_item"] = filename
                iteminfo["installed"] = False
                installlist.append(iteminfo)
                return True
            else:
                iteminfo["installed"] = False
                installlist.append(iteminfo)
                return False
        else:
            print "Can't install %s because there's no download info for the installer item" % catalogitemname
            iteminfo["installed"] = False
            installlist.append(iteminfo)
            return False
    else:
        print "No need to install %s" % catalogitemname
        iteminfo["installed"] = True
        installlist.append(iteminfo)
        return True
    
    
def processCatalogForInstalls(catalogpath, listofinstalls=[]):
    """
    Processes catalogs. Can be recursive if catalogs inlcude other catalogs.
    Probably doesn't handle circular catalog references well...
    """
    defaultbranch = getCatalogValueForKey(catalogpath, 'default_branch')
    
    nestedcatalogs = getCatalogValueForKey(catalogpath, "included_catalogs")
    if nestedcatalogs:
        for item in nestedcatalogs:
            nestedcatalogpath = getcatalog(item)
            if nestedcatalogpath:
                listofinstalls = processCatalogForInstalls(nestedcatalogpath, listofinstalls)
    
    installitems = getCatalogValueForKey(catalogpath, "managed_installs")
    if installitems:
        for item in installitems:
            result = processInstalls(item, defaultbranch, listofinstalls)
        
    return listofinstalls


def processRemovals(catalogitem, defaultbranch, removallist):
    """
    Processes a catalog item. Determines if it needs to be
    removed, {{and if so, if any items dependent on it need to 
    be removed first.}}  Items to be removed are added to the
    removallist
    {{Calls itself recursively as it processes dependencies.
    Returns a boolean; when processing dependencies, a false return
    will stop the installation of a dependent item}}
    """

    managedinstallprefs = managedinstalls.prefs()
    sw_repo_baseurl = managedinstallprefs['sw_repo_url']
    managed_install_dir = managedinstallprefs['managed_install_dir']

    catalogitempath = os.path.join(managed_install_dir, "catalogitems")
    downloadbaseurl = sw_repo_baseurl + "/pkgs/"

    catalogitemname = os.path.split(catalogitem)[1]
    print "\nProcessing catalog item %s..." % catalogitemname
    catalogitemdetail = getCatalogItemDetail(catalogitem, defaultbranch)

    if not catalogitemdetail:
        return False

    try:
        pl = plistlib.readPlist(catalogitemdetail)
    except:
        print >>sys.stderr, "%s is not a valid plist!" % catalogitem
        return False
        
    # check for uninstall info
    if not 'uninstallable' in pl or not pl['uninstallable']:
        print "%s is not uninstallable." % catalogitemname
        return False
        
    if not 'uninstall_method' in pl:
        print "No uninstall info for %s." % catalogitemname
        return False
            
    # check for dependent items
    # look at all the items in the local catalogitem cache
    # and see if any depend on the current item; if so
    # we should remove them as well
    dependentitemsremoved = True
    for item in os.listdir(catalogitempath):
        if item != catalogitemname:
            try:
                itempath = os.path.join(catalogitempath, item)
                itempl = plistlib.readPlist(itempath)
                if 'dependencies' in itempl:
                    if catalogitemname in itempl['dependencies']:
                        print "%s is dependent on %s and must be removed as well" % (item, catalogitemname)
                        success = processRemovals(item, defaultbranch, removallist)
                        if not success:
                            dependentitemsremoved = False
            except:
                pass
    
    if not dependentitemsremoved:
        print "Didn't attempt to remove %s because could not remove all items dependent on it." % catalogitemname
        return False
    
    # check to see if item is already in the removallist:
    if isItemInInstallList(pl, removallist):
        print "%s is already scheduled to be removed." % catalogitemname
        return True

    needToRemove = False 
    if 'installs' in pl:
        installitems = pl['installs']
        for item in installitems:
            if 'type' in item:
                if item['type'] == 'application':
                    if isSameOrNewerApplicationInstalled(item):
                        print "Need to remove %s" % catalogitemname
                        needToRemove = True
                        # once we know we need to remove this one,
                        # no need to keep checking
                        break
                if item['type'] == 'bundle':
                    comparisonResult = compareBundleVersion(item)
                    if comparisonResult == 1:
                        # same version is installed
                        print "Need to remove %s" % catalogitemname
                        needToRemove = True
                        # once we know we need to remove this one,
                        # no need to keep checking
                        break
                if item['type'] == 'plist':
                    comparisonResult = comparePlistVersion(item)
                    if comparisonResult == 1:
                        # same version is installed
                        print "Need to remove %s" % catalogitemname
                        needToRemove = True
                        # once we know we need to remove this one,
                        # no need to keep checking
                        break
                if item['type'] == 'file':
                    if filesystemItemExists(item) == 1:
                        print "Need to remove %s" % catalogitemname
                        needToRemove = True
                        # once we know we need to remove this one,
                        # no need to keep checking
                        break
    elif 'receipts' in pl:
        receipts = pl['receipts']
        for item in receipts:
            comparisonResult = compareReceiptVersion(item) 
            if comparisonResult == 1:
                # same version is installed
                print "Need to remove %s" % catalogitemname
                needToRemove = True
                # once we know we need to remove this one,
                # no need to keep checking
                break

    name = description = ""
    try:
        name = pl['name']
        description = pl['description']
    except:
        pass
    iteminfo = {}
    iteminfo["name"] = name
    iteminfo["catalogitem"] = catalogitemname
    iteminfo["description"] = description

    if needToRemove:
        uninstallmethod = pl['uninstall_method']
        
        if uninstallmethod == 'removepackages':
            # build list of packages based on receipts
            print "Building list of packages to remove"
            packages = []
            if 'receipts' in pl:
                for item in pl['receipts']:
                    if compareReceiptVersion(item) == 1:
                        packages.append(item['packageid'])
            iteminfo['packages'] = packages
                        
        iteminfo["uninstall_method"] = uninstallmethod
        iteminfo["installed"] = True
        removallist.append(iteminfo)
        return True
            
    else:
        print "No need to remove %s" % catalogitemname
        iteminfo["installed"] = False
        removallist.append(iteminfo)
        return True


def processCatalogForRemovals(catalogpath, listofremovals=[]):
    """
    Processes catalogs for removals. Can be recursive if catalogs inlcude other catalogs.
    Probably doesn't handle circular catalog references well...
    """
    defaultbranch = getCatalogValueForKey(catalogpath, 'default_branch')

    nestedcatalogs = getCatalogValueForKey(catalogpath, "included_catalogs")
    if nestedcatalogs:
        for item in nestedcatalogs:
            nestedcatalogpath = getcatalog(item)
            if nestedcatalogpath:
                listofremovals = processCatalogForRemovals(nestedcatalogpath, listofremovals)

    removalitems = getCatalogValueForKey(catalogpath, "managed_uninstalls")
    if removalitems:
        for item in removalitems:
            result = processRemovals(item, defaultbranch, listofremovals)

    return listofremovals


def getCatalogValueForKey(catalogpath, keyname):
    
    try:
        pl = plistlib.readPlist(catalogpath)
    except:
        print >>sys.stderr, "Could not read plist %s" % catalogpath
        return None
    
    if keyname in pl:
        return pl[keyname]
    else:
        return None
        

def createDirsIfNeeded(dirlist):
    for dir in dirlist:
        if not os.path.exists(dir):
            try:
                os.mkdir(dir)
            except:
                print >>sys.stderr, "Could not create %s" % dir
                return False
                
    return True


def getcatalog(partialurl):
    """
    Gets a catalog from the server
    """
    managedinstallprefs = managedinstalls.prefs()
    sw_repo_baseurl = managedinstallprefs['sw_repo_url']
    catalog_dir = os.path.join(managedinstallprefs['managed_install_dir'], "catalogs")
    if not createDirsIfNeeded([catalog_dir]):
        exit(-1)
        
    if partialurl.startswith("http"):
        # then it's really a request for the main catalog
        catalogurl = partialurl
        catalogname = "MainCatalog.plist"
    else:
        # request for nested catalog
        catalogname = os.path.split(partialurl)[1]
        catalogurl = sw_repo_baseurl + "/catalogs/" + partialurl
        
    catalogpath = os.path.join(catalog_dir, catalogname)
    if os.path.exists(catalogpath):
        catalogmodtime = os.stat(catalogpath).st_mtime
    else:
        catalogmodtime = None
    tempfilepath = os.path.join(mytmpdir, catalogname)
    print "Getting catalog %s from %s..." % (catalogname, catalogurl)
    result = managedinstalls.getfilefromhttpurl(catalogurl, tempfilepath, showprogress=True, ifmodifiedsince=catalogmodtime)
    if result == 0:
        try:
            os.rename(tempfilepath, catalogpath)
            return catalogpath
        except:
            print >>sys.stderr, "Could not write to %s" % catalogpath
            return ""
    elif result == 304:
        # not modified, do nothing
        print "Catalog %s in local cache is up-to-date." % catalogname
        return catalogpath
    else:
        print >>sys.stderr, "Error code: %s retreiving catalog %s" % (result, catalogname)
        if os.path.exists(tempfilepath):
            os.remove(tempfilepath)
        return ""


def getMainCatalog(alternate_id):
    """
    Gets the main client catalog (aka manifest) from the server
    """
    managedinstallprefs = managedinstalls.prefs()
    manifesturl = managedinstallprefs['manifest_url']
    clientidentifier = managedinstallprefs['client_identifier']

    if not manifesturl.endswith('?') and not manifesturl.endswith('/'):
        manifesturl = manifesturl + "/"
    if alternate_id:
        # use id passed in at command-line
        manifesturl = manifesturl + alternate_id
    elif clientidentifier:
        # use client_identfier from /Library/Preferences/ManagedInstalls.plist
        manifesturl = manifesturl + clientidentifier
    else:
        # no client identifier specified, so use the hostname
         manifesturl = manifesturl + os.uname()[1]
         
    return getcatalog(manifesturl)


mytmpdir = ""      
def main():
    global mytmpdir
    mytmpdir = tempfile.mkdtemp()
    
    p = optparse.OptionParser()
    p.add_option('--id', '-i', default='',
                    help='Alternate identifier for catalog retreival')
    options, arguments = p.parse_args()
    
    managedinstallprefs = managedinstalls.prefs()
    managed_install_dir = managedinstallprefs['managed_install_dir']
    catalogitemsdir = os.path.join(managed_install_dir, "catalogitems")
    cachedir = os.path.join(managed_install_dir, "Cache")
    
    if not createDirsIfNeeded([managed_install_dir, catalogitemsdir, cachedir]):
        print >>sys.stderr, "No write access to managed install directory: %s" % managed_install_dir
        exit(-1)
    
    maincatalogpath = getMainCatalog(options.id)
    if not maincatalogpath:
        print >>sys.stderr, "Could not retreive managed install catalog."
        exit(-1)
        
    installlist = processCatalogForInstalls(maincatalogpath)
    
    # clean up cache dir
    # remove any item in the install cache that isn't scheduled
    # to be installed --
    # this allows us to 'pull back' an item before it is installed
    # by removing it from the manifest
    installer_item_list = []
    for item in installlist:
        if "installer_item" in item:
            installer_item_list.append(item["installer_item"])
        
    for item in os.listdir(cachedir):
        if item not in installer_item_list:
            print "Removing %s from cache" % item
            os.unlink(os.path.join(cachedir, item))
            
    # now generate a list of items to be uninstalled
    removallist = processCatalogForRemovals(maincatalogpath)
            
            
    # need to write out install list so the autoinstaller
    # can use it to install things in the right order
    pldict = {}
    pldict['managed_installs'] = installlist
    pldict['removals'] = removallist
    plistlib.writePlist(pldict, os.path.join(managed_install_dir, "InstallInfo.plist"))
    
    # now clean up catalogitem dir, removing items no longer needed
    currentcatalogitems = []
    for item in installlist:
        currentcatalogitems.append(item['catalogitem'])
    for item in removallist:
        currentcatalogitems.append(item['catalogitem'])
    
    for item in os.listdir(catalogitemsdir):
        if item not in currentcatalogitems:
            os.unlink(os.path.join(catalogitemsdir,item))
    
    try:
        # clean up our tmp dir
        os.rmdir(mytmpdir)
    except:
        # not fatal if it fails
        pass

if __name__ == '__main__':
    main()

