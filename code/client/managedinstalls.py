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
managedinstallslib.py

Created by Greg Neagle on 2008-11-18.

Common functions used by the managedinstalls tools.
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
from xml.dom import minidom


#####################################################
# managed installs preferences/metadata
#####################################################


def getManagedInstallsPrefs():
    # define default values
    prefs = {}
    prefs['managed_install_dir'] = "/Library/Managed Installs"
    prefs['manifest_url'] = "http:/managedinstalls/cgi-bin/getmanifest"
    prefs['sw_repo_url'] = "http://managedinstalls/swrepo"
    prefs['client_identifier'] = ""
    prefsfile = "/Library/Preferences/ManagedInstalls.plist"
    
    if os.path.exists(prefsfile):
        try:
            pl = plistlib.readPlist(prefsfile)
        except:
            pass
        if pl:
            if 'managed_install_dir' in pl:
                prefs['managed_install_dir'] = pl['managed_install_dir']
            if 'manifest_url' in pl:
                prefs['manifest_url'] = pl['manifest_url']
            if 'sw_repo_url' in pl:
                prefs['sw_repo_url'] = pl['sw_repo_url']
            if 'client_identifier' in pl:
                prefs['client_identifier'] = pl['client_identifier']
                
    return prefs


def managed_install_dir():
    prefs = getManagedInstallsPrefs()
    return prefs['managed_install_dir']


def manifest_url():
    prefs = getManagedInstallsPrefs()
    return prefs['manifest_url']


def sw_repo_url():
    prefs = getManagedInstallsPrefs()
    return prefs['sw_repo_url']


def pref(prefname):
    prefs = getManagedInstallsPrefs()
    if prefname in prefs:
        return prefs[prefname]
    else:
        return ''


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


def httpDownload(url, filename, headers={}, postData=None, reporthook=None):
    reqObj = urllib2.Request(url, postData, headers)
    fp = urllib2.urlopen(reqObj)
    headers = fp.info()
    
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



def getfilefromhttpurl(url,filepath,showprogress=False,ifmodifiedsince=None):
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
        (f,headers) = httpDownload(url, filename=filepath, headers=request_headers, reporthook=reporthook)
        if 'last-modified' in headers:
            # set the modtime of the downloaded file to the modtime of the
            # file on the server
            modtimestr = headers['last-modified']
            modtimetuple = time.strptime(modtimestr, "%a, %d %b %Y %H:%M:%S %Z")
            modtimeint = calendar.timegm(modtimetuple)
            os.utime(filepath, (time.time(), modtimeint))
            
    except urllib2.HTTPError, err:
        return err.code
    except IOError, err:
        return err
    except:
        return (-1, "Unexpected error")
    
    return 0
    
        
debug = False
def main():
    pass


if __name__ == '__main__':
    main()

