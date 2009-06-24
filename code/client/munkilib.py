#!/usr/bin/env python
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
munkilib

Created by Greg Neagle on 2008-11-18.

Common functions used by the munki tools.
"""

import sys
import os
import plistlib
import urllib2
import urlparse
import time
import calendar
import subprocess
import tempfile
import shutil
from distutils import version
from xml.dom import minidom

#from SystemConfiguration import SCDynamicStoreCopyConsoleUser
from Foundation import NSDictionary, NSDate


# misc functions

def readPlist(plistfile):
  """Read a plist, return a dict.
  This method can deal with binary plists,
  whereas plistlib cannot.

  Args:
    plistfile: Path to plist file to read

  Returns:
    dict of plist contents.
  """
  return NSDictionary.dictionaryWithContentsOfFile_(plistfile)


def getconsoleuser():
    osvers = int(os.uname()[2].split('.')[0])
    if osvers > 9:
        cmd = ['/usr/bin/who | /usr/bin/grep console']
        p = subprocess.Popen(cmd, shell=True, bufsize=1, stdin=subprocess.PIPE, 
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        (output, err) = p.communicate()
        return output
    else:
        from SystemConfiguration import SCDynamicStoreCopyConsoleUser
        cfuser = SCDynamicStoreCopyConsoleUser( None, None, None )
        return cfuser[0]
    
    
def pythonScriptRunning(scriptname):
    cmd = ['/bin/ps', '-eo', 'command=']
    p = subprocess.Popen(cmd, shell=False, bufsize=1, stdin=subprocess.PIPE, 
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out, err) = p.communicate()
    lines = out.splitlines()
    for line in lines:
        # first look for Python processes
        if line.find("MacOS/Python ") != -1:
            if line.find(scriptname) != -1:
                return True

    return False


# dmg helpers

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


#####################################################
# managed installs preferences/metadata
#####################################################


def NSDateNowString():
    '''
    Generates a NSDate-compatible 
    '''
    now = NSDate.new()
    return str(now)


def getManagedInstallsPrefs():
    # define default values
    prefs = {}
    prefs['ManagedInstallDir'] = "/Library/Managed Installs"
    prefs['ManifestURL'] = "http://munki/repo/manifests/"
    prefs['SoftwareRepoURL'] = "http://munki/repo"
    prefs['ClientIdentifier'] = ""
    prefs['LoggingLevel'] = 1
    prefs['InstallAppleSoftwareUpdates'] = False
    prefs['SoftwareUpdateServerURL'] = None
    prefs['DaysBetweenNotifications'] = 1
    prefs['LastNotifiedDate'] = '1970-01-01 00:00:00 -0000'
    
    prefsfile = "/Library/Preferences/ManagedInstalls.plist"
    pl = {}
    if os.path.exists(prefsfile):
        try:
            pl = readPlist(prefsfile)
            for key in pl.keys():
                if type(pl[key]).__name__ == "__NSCFDate":
                    # convert NSDate/CFDates to strings
                    prefs[key] = str(pl[key])
                else:
                    prefs[key] = pl[key]               
        except:
            pass
                
    return prefs


def ManagedInstallDir():
    prefs = getManagedInstallsPrefs()
    return prefs['ManagedInstallDir']


def ManifestURL():
    prefs = getManagedInstallsPrefs()
    return prefs['ManifestURL']


def SoftwareRepoURL():
    prefs = getManagedInstallsPrefs()
    return prefs['SoftwareRepoURL']


def pref(prefname):
    return getManagedInstallsPrefs().get(prefname)


def prefs():
    return getManagedInstallsPrefs()
    
    
#####################################################    
# Apple package utilities
#####################################################

def getInstallerPkgInfo(filename):
    installerinfo = {}
    p = subprocess.Popen(["/usr/sbin/installer", "-pkginfo", "-verbose", "-plist", "-pkg", filename], bufsize=1, 
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out, err) = p.communicate()

    if out:
        pl = plistlib.readPlistFromString(out)
        if 'Size' in pl:
            installerinfo['installed_size'] = int(pl['Size'])
        if 'Description' in pl:
            installerinfo['description'] = pl['Description']
        if 'Will Restart' in pl:
            if pl['Will Restart'] == "YES":
                installerinfo['RestartAction'] = "RequireRestart"
        if "Title" in pl:
            installerinfo['display_name'] = pl['Title']
                
    return installerinfo
    

def padVersionString(versString,tupleCount):
    if versString == None:
        versString = "0"
    components = versString.split(".")
    if len(components) > tupleCount :
        components = components[0:tupleCount]
    else:
        while len(components) < tupleCount :
            components.append("0")
    return ".".join(components)
    

def getExtendedVersion(bundlepath):
    """
    Returns five-part version number like Apple uses in package DB
    """
    versionPlist = os.path.join(bundlepath,"Contents","version.plist")
    infoPlist = os.path.join(bundlepath,"Contents","Info.plist")
    pl = {}
    if os.path.exists(versionPlist):
        pl = plistlib.readPlist(versionPlist)
    elif os.path.exists(infoPlist):
        pl = plistlib.readPlist(infoPlist)
    if pl:
        shortVers = "0.0.0"
        sourceVers = "0"
        buildVers = "0"
        if "CFBundleShortVersionString" in pl:
            shortVers = padVersionString(pl["CFBundleShortVersionString"],3)
        if "SourceVersion" in pl:
            sourceVers = padVersionString(pl["SourceVersion"],1)
        if "BuildVersion" in pl:
            buildVers = padVersionString(pl["BuildVersion"],1)
        return shortVers + "." + sourceVers + "." + buildVers
    else:
        return "0.0.0.0.0"


def parsePkgRefs(filename):
    info = []
    dom = minidom.parse(filename)
    pkgrefs = dom.getElementsByTagName("pkg-ref")
    if pkgrefs:
        for ref in pkgrefs:
            keys = ref.attributes.keys()
            if 'id' in keys and 'version' in keys:
                if debug:
                    for key in keys:
                        print key, "=>", ref.attributes[key].value.encode('UTF-8')

                pkginfo = {}
                pkginfo['id'] = ref.attributes['id'].value.encode('UTF-8')
                pkginfo['version'] = padVersionString(ref.attributes['version'].value.encode('UTF-8'),5)
                if 'installKBytes' in keys:
                    pkginfo['installed_size'] = int(ref.attributes['installKBytes'].value.encode('UTF-8'))
                if not pkginfo['id'].startswith('manual'):
                    if not pkginfo in info:
                        info.append(pkginfo)
    else:
        pkgrefs = dom.getElementsByTagName("pkg-info")
        if pkgrefs:
            for ref in pkgrefs:
                keys = ref.attributes.keys()
                if 'identifier' in keys and 'version' in keys:
                    if debug:
                        for key in keys:
                            print key, "=>", ref.attributes[key].value.encode('UTF-8')

                    pkginfo = {}
                    pkginfo['id'] = ref.attributes['identifier'].value.encode('UTF-8')
                    pkginfo['version'] = padVersionString(ref.attributes['version'].value.encode('UTF-8'),5)
                    if not pkginfo in info:
                        info.append(pkginfo)
    return info


def getFlatPackageInfo(pkgpath):
    """
    returns array of dictionaries with info on packages
    contained in the flat package
    """

    infoarray = []
    mytmpdir = tempfile.mkdtemp()
    os.chdir(mytmpdir)
    p = subprocess.Popen(["/usr/bin/xar", "-xf", pkgpath, "--exclude", "Payload"])
    returncode = p.wait()
    if returncode == 0:
        currentdir = mytmpdir
        packageinfofile = os.path.join(currentdir, "PackageInfo")
        if os.path.exists(packageinfofile):
            infoarray = parsePkgRefs(packageinfofile)

        else:
            distributionfile = os.path.join(currentdir, "Distribution")
            if os.path.exists(distributionfile):
                infoarray = parsePkgRefs(distributionfile)

    shutil.rmtree(mytmpdir)
    return infoarray


def getBundlePackageInfo(pkgpath):
    infoarray = []
    pkginfo = {}

    if pkgpath.endswith(".pkg"):
        plistpath = os.path.join(pkgpath, "Contents", "Info.plist")
        if os.path.exists(plistpath):
            pl = plistlib.readPlist(plistpath)
            if debug:
                for key in pl:
                    print key, "=>", pl[key]
                    
            if "CFBundleIdentifier" in pl:
                pkginfo['id'] = pl["CFBundleIdentifier"]
                
                if "IFPkgFlagInstalledSize" in pl:
                    pkginfo['installed_size'] = pl["IFPkgFlagInstalledSize"]
                
                pkginfo['version'] = getExtendedVersion(pkgpath)
                infoarray.append(pkginfo)
                return infoarray

    bundlecontents = os.path.join(pkgpath, "Contents")
    if os.path.exists(bundlecontents):
        for item in os.listdir(bundlecontents):
            if item.endswith(".dist"):
                filename = os.path.join(bundlecontents, item)
                infoarray = parsePkgRefs(filename)
                return infoarray

    return infoarray


def getPkgInfo(p):
    info = []
    if p.endswith(".pkg") or p.endswith(".mpkg"):
        if debug:
            print "Examining %s" % p
        if os.path.isfile(p):             # new flat package
            info = getFlatPackageInfo(p)

        if os.path.isdir(p):              # bundle-style package?
            info = getBundlePackageInfo(p)
    elif p.endswith('.dist'):
            info = parsePkgRefs(p)
            
    return info


def examinePackage(p):
    info = []
    if p.endswith(".pkg") or p.endswith(".mpkg"):
        if debug:
            print "Examining %s" % p
        if os.path.isfile(p):             # new flat package
            info = getFlatPackageInfo(p)

        if os.path.isdir(p):              # bundle-style package?
            info = getBundlePackageInfo(p)

        if len(info) == 0:
            print >>sys.stderr, "Can't determine bundle ID of %s." % p
            return

        # print info
        for pkg in info:
            #print pkg
            pkg_id = pkg['id']
            vers = pkg['version']
            print "packageid: %s \t version: %s" % (pkg_id, vers) 

    else:
        print >>sys.stderr, "%s doesn't appear to be an Installer package." % p


def getInstalledPackageVersion(pkgid):
    """
    Checks a package id against the receipts to
    determine if a package is already installed.
    Returns the version string of the installed pkg
    if it exists, or an empty string if it does not
    """

    # Check /Library/Receipts
    receiptsdir = "/Library/Receipts"
    if os.path.exists(receiptsdir):
        installitems = os.listdir(receiptsdir)
        for item in installitems:
            if item.endswith(".pkg"):
                info = getBundlePackageInfo(os.path.join(receiptsdir, item))
                if len(info):
                    infoitem = info[0]
                    foundbundleid = infoitem['id']
                    foundvers = infoitem['version']
                    if pkgid == foundbundleid:
                        return foundvers

    # If we got to this point, we haven't found the pkgid yet.                        
    # Now check new (Leopard) package database
    p = subprocess.Popen(["/usr/sbin/pkgutil", "--pkg-info-plist", pkgid], bufsize=1, 
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out, err) = p.communicate()

    if out:
        pl = plistlib.readPlistFromString(out)

        if "pkgid" in pl:
            foundbundleid = pl["pkgid"]
        if "pkg-version" in pl:
            foundvers = pl["pkg-version"]
        if pkgid == foundbundleid:
            return padVersionString(foundvers,5)

    # This package does not appear to be currently installed
    return ""
    
    
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


def findInstallerItem(path):
    if path.endswith('.pkg') or path.endswith('.mpkg') or path.endswith('.dmg'):
        return path
    else:
        # Apple Software Updates sometimes download as
        # directories with .dist files within. Grrr.
        if os.path.isdir(path):
            for item in os.listdir(path):
                if item.endswith('.dist'):
                    itempath = os.path.join(path,item)
                    # usually the .dist file is a symlink to another one
                    # in a subfolder (like Packages)
                    if os.path.islink(itempath):
                        itempath = os.path.realpath(itempath)
                    return itempath
    return ''


def getPackageMetaData(pkgitem):
    """
    Queries an installer item (.pkg, .mpkg, .dist)
    and gets metadata. There are a lot of valid Apple package formats
    and this function may not deal with them all equally well.
    Standard bundle packages are probably the best understood and documented,
    so this code deals with those pretty well.

    metadata items include:
    installer_item_size:  size of the installer item (.dmg, .pkg, etc)
    installed_size: size of items that will be installed
    RestartAction: will a restart be needed after installation?
    name
    version
    description
    receipts: an array of packageids that may be installed (some may be optional)
    """
    
    installedsize = 0
    pkgitem = findInstallerItem(pkgitem)
    if pkgitem == None:
        return {}
        
    installerinfo = getInstallerPkgInfo(pkgitem)
    info = getPkgInfo(pkgitem)

    highestpkgversion = "0.0"
    for infoitem in info:
        if version.LooseVersion(infoitem['version']) > version.LooseVersion(highestpkgversion):
            highestpkgversion = infoitem['version']
        if "installed_size" in infoitem:
            # note this is in KBytes
            installedsize += infoitem['installed_size']

    name = os.path.split(pkgitem)[1]
    shortname = os.path.splitext(name)[0]
    metaversion = nameAndVersion(shortname)[1]
    if not len(metaversion):
        # there is no version number in the filename
        metaversion = highestpkgversion
    elif len(info) == 1:
        # there is only one package in this item
        metaversion = highestpkgversion
    elif highestpkgversion.startswith(metaversion):
        # for example, highestpkgversion is 2.0.3124.0, version in filename is 2.0
        metaversion = highestpkgversion
    
    if 'installed_size' in installerinfo:
        if installerinfo['installed_size'] > 0:
            installedsize = installerinfo['installed_size']

    cataloginfo = {}
    cataloginfo['name'] = nameAndVersion(shortname)[0]
    cataloginfo['version'] = metaversion
    for key in ('display_name', 'RestartAction', 'description'):
        if key in installerinfo:
            cataloginfo[key] = installerinfo[key]

    if installedsize > 0:
        cataloginfo['installed_size'] = installedsize

    cataloginfo['receipts'] = []        
    for infoitem in info: 
        pkginfo = {}
        pkginfo['packageid'] = infoitem['id']
        pkginfo['version'] = infoitem['version']
        cataloginfo['receipts'].append(pkginfo)        
    return cataloginfo
    
    
# some utility functions

def getAvailableDiskSpace(volumepath="/"):
    # returns available diskspace in KBytes.
    p = subprocess.Popen(["/usr/sbin/diskutil", "info", "-plist", volumepath], bufsize=1,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out, err) = p.communicate()
    if out:
        pl = plistlib.readPlistFromString(out)

        if "FreeSpace" in pl:
            freespace = pl["FreeSpace"]
        return int(freespace/1024)

    # Yikes
    return 0
    
    
#
#    Handles http downloads for the managed installer tools.
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


def getsteps(num_of_steps, limit):
    """
    Helper function for display_percent_done
    """
    steps = []
    current = 0.0
    for i in range(0,num_of_steps):
        if i == num_of_steps-1:
            steps.append(int(round(limit)))
        else:
            steps.append(int(round(current)))
        current += float(limit)/float(num_of_steps-1)
    return steps


def display_percent_done(current,maximum):
    """
    Mimics the command-line progress meter seen in some
    of Apple's tools (like softwareupdate)
    """
    step = getsteps(16, maximum)
    output = ''
    indicator = ['\t0','.','.','20','.','.','40','.','.',
                '60','.','.','80','.','.','100\n']
    for i in range(0,16):
        if current == step[i]:
            output += indicator[i]
    if output:
        sys.stdout.write(output)
        sys.stdout.flush()


def httpDownload(url, filename, headers={}, postData=None, reporthook=None, message=None):
    reqObj = urllib2.Request(url, postData, headers)
    fp = urllib2.urlopen(reqObj)
    headers = fp.info()
    
    if message: print message
        
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



def getfilefromhttpurl(url,filepath,showprogress=False,ifmodifiedsince=None, message=None):
    """
    gets a file from a url.
    If 'ifmodifiedsince' is specified, this header is set
    and the file is not retreived if it hasn't changed on the server.
    Returns 0 if successful, or HTTP error code
    """
    def reporthook(block_count, block_size, file_size):
         if showprogress and (file_size > 0):
            max_blocks = file_size/block_size
            display_percent_done(block_count, max_blocks)
                   
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
    #except urllib2.URLError, err:
    #    return err   
    except IOError, err:
        return err
    except:
        return (-1, "Unexpected error")
    
    return 0


def getHTTPfileIfNewerAtomically(url,destinationpath,showprogress=False, message=None):
    """
    Gets file from HTTP URL, only if newer on web server.
    Replaces pre-existing file only on success. (thus 'Atomically')
    """
    mytmpdir = tempfile.mkdtemp()
    mytemppath = os.path.join(mytmpdir,"TempDownload")
    if os.path.exists(destinationpath):
        modtime = os.stat(destinationpath).st_mtime
    else:
        modtime = None
    result = getfilefromhttpurl(url, mytemppath, showprogress=True, ifmodifiedsince=modtime, message=message)
    if result == 0:
        try:
            os.rename(mytemppath, destinationpath)
            return destinationpath
        except:
            print >>sys.stderr, "Could not write to %s" % destinationpath
            destinationpath = None
    elif result == 304:
        # not modified, return existing file
        return destinationpath
    else:
        print >>sys.stderr, "Error code: %s retreiving %s" % (result, url)
        destinationpath = None
        
    if os.path.exists(mytemppath):
        os.remove(mytemppath)
    os.rmdir(mytmpdir)
    return destinationpath
    
    
debug = False
def main():
    print "This is a library of support tools for the Munki Suite."


if __name__ == '__main__':
    main()

