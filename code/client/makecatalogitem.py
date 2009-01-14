#!/usr/bin/env python
# encoding: utf-8
"""
makecatalogitem.py

Created by Greg Neagle on 2008-11-25.
Creates a managed install catalog item plist given an Installer item:
a .pkg, a .mpkg, or a .dmg containing a .pkg or .mpkg
at the root of the mounted disk image.

You may also pass additional items that are installed by the package. These
are added to the 'installs' key of the catalog item plist and are used when 
processing the catalog to check if the package needs to be installed or 
reinstalled.

The generated plist is printed to STDOUT.

Usage: makecatalogitem /path/to/package_or_dmg [-f /path/to/item/it/installs ...]
"""

import sys
import os
import re
import optparse
from distutils import version
import plistlib
import subprocess

import managedinstalls


def mountdmg(dmgpath):
    """
    Attempts to mount the dmg at dmgpath
    and returns a list of mountpoints
    """
    mountpoints = []
    dmgname = os.path.basename(dmgpath)
    p = subprocess.Popen(['/usr/bin/hdiutil', 'attach', dmgpath, '-mountRandom', '/tmp', '-nobrowse', '-plist'],
            bufsize=1, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (plist, err) = p.communicate()
    if err:
        print >>sys.stderr, "Error %s mounting %s." % (err, dmgpath)
    if plist:
        pl = plistlib.readPlistFromString(plist)
        for entity in pl['system-entities']:
            if 'mount-point' in entity:
                mountpoints.append(entity['mount-point'])

    return mountpoints


def unmountdmg(mountpoint):
    """
    Unmounts the dmg at mountpoint
    """
    p = subprocess.Popen(['/usr/bin/hdiutil', 'detach', mountpoint], 
        bufsize=1, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (output, err) = p.communicate()
    if err:
        print >>sys.stderr, err
        p = subprocess.Popen(['/usr/bin/hdiutil', 'detach', mountpoint, '-force'], 
            bufsize=1, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        (output, err) = p.communicate()


def nameAndVersion(s):
    """
    Splits a string into the name and version numbers:
    'TextWrangler2.3b1' becomes ('TextWrangler', '2.3b1')
    'AdobePhotoshopCS3-11.2.1' becomes ('AdobePhotoshopCS3', '11.2.1')
    'MicrosoftOffice2008v12.2.1' becomes ('MicrosoftOffice2008', '12.2.1')
    """
    index = 0
    for char in s:
        if char in "0123456789":
            possibleVersion = s[index:]
            if not (" " in possibleVersion or "_" in possibleVersion or "-" in possibleVersion or "v" in possibleVersion):
                 return (s[0:index].rstrip(" .-_v"), possibleVersion)
        index += 1
    # no version number found, just return original string and empty string
    return (s, '')


def getCatalogInfo(pkgitem):
    info = managedinstalls.getPkgInfo(pkgitem)
    highestpkgversion = "0.0"
    for infoitem in info:
        if version.LooseVersion(infoitem['version']) > version.LooseVersion(highestpkgversion):
            highestpkgversion = infoitem['version']
    
    name = os.path.split(pkgitem)[1]
    shortname = os.path.splitext(name)[0]
    metaversion = nameAndVersion(shortname)[1]
    if not len(metaversion):
        metaversion = highestpkgversion
        
    cataloginfo = {}
    cataloginfo['name'] = nameAndVersion(shortname)[0]
    cataloginfo['version'] = metaversion
    cataloginfo['description'] = ""
    cataloginfo['receipts'] = []
    for infoitem in info: 
        pkginfo = {}
        pkginfo['packageid'] = infoitem['id']
        pkginfo['version'] = infoitem['version']
        cataloginfo['receipts'].append(pkginfo)        
    return cataloginfo
    

def getCatalogInfoFromDmg(dmgpath):
    cataloginfo = None
    mountpoints = mountdmg(dmgpath)
    for mountpoint in mountpoints:
        for fsitem in os.listdir(mountpoint):
            itempath = os.path.join(mountpoint, fsitem)
            if itempath.endswith('.pkg') or itempath.endswith('.mpkg'):
                cataloginfo = getCatalogInfo(itempath)
                # get out of fsitem loop
                break
        if cataloginfo:
            # get out of moutpoint loop
            break
            
    #unmount all the mountpoints from the dmg
    for mountpoint in mountpoints:
        unmountdmg(mountpoint)
    return cataloginfo   


def getBundleInfo(path):
    """
    Returns Info.plist data if available
    for bundle at path
    """
    infopath = os.path.join(path, "Contents", "Info.plist")
    if not os.path.exists(infopath):
        infopath = os.path.join(path, "Resources", "Info.plist")
        
    if os.path.exists(infopath):
        try:
            pl = plistlib.readPlist(infopath)
            return pl
        except:
            pass

    return None


def getiteminfo(itempath):
    infodict = {}
    if itempath.endswith('.app'):
        infodict['type'] = 'application'
        pl = getBundleInfo(itempath)
        if 'CFBundleName' in pl:
            infodict['CFBundleName'] = pl['CFBundleName']
        if 'CFBundleIdentifier' in pl:
            infodict['CFBundleIdentifier'] = pl['CFBundleIdentifier']
        if 'CFBundleShortVersionString' in pl:
            infodict['CFBundleShortVersionString'] = pl['CFBundleShortVersionString']
        if 'LSMinimumSystemVersion' in pl:
            infodict['minosversion'] = pl['LSMinimumSystemVersion']
        elif 'SystemVersionCheck:MinimumSystemVersion' in pl:
            infodict['minosversion'] = pl['SystemVersionCheck:MinimumSystemVersion']
    elif os.path.exists(os.path.join(itempath,'Contents','Info.plist')) or os.path.exists(os.path.join(itempath,'Resources','Info.plist')):
        infodict['type'] = 'bundle'
        infodict['path'] = itempath
        pl = getBundleInfo(itempath)
        if 'CFBundleShortVersionString' in pl:
            infodict['CFBundleShortVersionString'] = pl['CFBundleShortVersionString']
    elif itempath.endswith("Info.plist") or itempath.endswith("version.plist"):
        infodict['type'] = 'plist'
        infodict['path'] = itempath
        try:
            pl = plistlib.readPlist(itempath)
            if 'CFBundleShortVersionString' in pl:
                infodict['CFBundleShortVersionString'] = pl['CFBundleShortVersionString']
        except:
            pass
        
    if not 'CFBundleShortVersionString' in infodict:
        infodict['type'] = 'file'
        infodict['path'] = itempath
    return infodict
        


def main():
    usage = "usage: %prog [options] /path/to/installeritem"
    p = optparse.OptionParser(usage=usage)
    p.add_option('--file', '-f', action="append",
                    help='Path to a filesystem item installed by this package. Can be specified multiple times.')
    options, arguments = p.parse_args()
    if len(arguments) == 0:
        print >>sys.stderr, "Need to specify an installer item (.pkg, .mpkg, .dmg)!"
        exit(-1)
    
    if len(arguments) > 1:
        print >>sys.stderr, "Can process only one installer item at a time. Ignoring additional installer items."
        
    item = arguments[0].rstrip("/")
    if os.path.exists(item):
        if item.endswith('.dmg'):
            catinfo = getCatalogInfoFromDmg(item)
        elif item.endswith('.pkg') or item.endswith('.mpkg'):
            catinfo = getCatalogInfo(item)
        else:
            print >>sys.stderr, "%s is not an installer package!" % item
            exit(-1)
        
        if catinfo:
            minosversion = ""
            if options.file:
                installs = []           
                for fitem in options.file:
                    if os.path.exists(fitem):
                        iteminfodict = getiteminfo(fitem)
                        if 'minosversion' in iteminfodict:
                            thisminosversion = iteminfodict.pop('minosversion')
                            if not minosversion:
                                minosversion = thisminosversion
                            elif version.LooseVersion(thisminosversion) < version.LooseVersion(minosversion):
                                minosversion = thisminosversion
                        installs.append(iteminfodict)
                    else:
                        print >>sys.stderr, "Item %s doesn't exist. Skipping." % fitem
                catinfo['installs'] = installs   
                    
            name = os.path.split(item)[1]
            catinfo['installer_item_location'] = name
            if minosversion:
                catinfo['minimum_os_version'] = minosversion
            else:
                catinfo['minimum_os_version'] = "10.4.0"
            
            # and now, what we've all been waiting for...
            print plistlib.writePlistToString(catinfo)


if __name__ == '__main__':
	main()

