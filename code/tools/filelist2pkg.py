#!/usr/bin/env python
# encoding: utf-8
#
# Copyright 2009-2011 Greg Neagle.
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
filelist2pkg.py

Created by Greg Neagle on 2009-11-24.
"""

import sys
import os
import stat
import plistlib
import subprocess
import optparse
import tempfile

# change these to suit yourself
packagemaker = "/Developer/usr/bin/packagemaker"
pkgidprefix = "com.myorg.pkg."
pkgoutputdir = "/Users/Shared/pkgs"


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
            if not (" " in possibleVersion or "_" in possibleVersion 
                    or "-" in possibleVersion or "v" in possibleVersion):
                 return (s[0:index].rstrip(" .-_v"), possibleVersion)
        index += 1
    # no version number found, just return original string and empty string
    return (s, '')
    
    
def makeDMG(pkgpath):
    print "Making disk image..."
    cmd = ["/usr/bin/hdiutil", "create", "-srcfolder", 
            pkgpath, pkgpath + ".dmg"]
    p = subprocess.Popen(cmd, shell=False, bufsize=1, stdin=subprocess.PIPE, 
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    while True: 
        output =  p.stdout.readline()
        if not output and (p.poll() != None):
            break
        print output.rstrip("\n")
        sys.stdout.flush()
        
    retcode = p.poll()
    if retcode:
        print >>sys.stderr, "Disk image creation failed."
        return(-1)


def copyItem(sourceitem, packageroot):
    if not os.path.lexists(sourceitem):
        print >>sys.stderr, "%s does not exist!" % sourceitem
        return
    
    paths = []
    pathitem = sourceitem
    while pathitem != "/":
        pathitem = os.path.dirname(pathitem)
        paths.append(pathitem)

    paths.reverse()
    for sourcepath in paths:
        targetpath = os.path.join(packageroot, sourcepath.lstrip('/'))
        if not os.path.exists(targetpath):
            os.mkdir(targetpath)
            os.chown(targetpath, os.stat(sourcepath).st_uid, 
                     os.stat(sourcepath).st_gid)
            os.chmod(targetpath, stat.S_IMODE(os.stat(sourcepath).st_mode))

    targetitem = os.path.join(packageroot, sourceitem.lstrip('/'))
    if os.path.isdir(sourceitem) and not os.path.islink(sourceitem):
        os.mkdir(targetitem)
        os.chown(targetitem, os.stat(sourceitem).st_uid, 
                 os.stat(sourceitem).st_gid)
        os.chmod(targetitem, stat.S_IMODE(os.stat(sourceitem).st_mode))
    elif os.path.islink(sourceitem):
        # make sure we don't follow the symlink
        err = subprocess.call(['/bin/cp', "-a", sourceitem, targetitem])
    else:
        err = subprocess.call(['/bin/cp', "-p", sourceitem, targetitem])


def copyItemsFromList(filelist, packageroot):
    f = open(filelist, 'rb')
    while 1:
        item = f.readline()
        if not item:
            break
        if not (item.startswith('.') or item.startswith("/")):
            continue
        item = item.lstrip('./').rstrip('\n')
        sourceitem = os.path.join("/", item)
        copyItem(sourceitem, packageroot)
    f.close()


def main():
	# command-line options
    p = optparse.OptionParser()
    p.add_option('--nomakedmg', action='store_true',
                    help='Don\'t make a disk image containing the package.')
    p.add_option('--name', '-n',
                       help='Specify a name for the package.')
    p.add_option('--version', '-v',
                       help='Specify a version number for the package.')
    p.add_option('--id',
                       help='Specify a package id for the package.')
    p.add_option('--displayname',
                        help='Specify a display name for the package.')
    p.add_option('--description',
                        help='Specify a description for the package.')
    p.add_option('--restart', action='store_true',
                    help='Restart is required on install.')
    p.add_option('--logout', action='store_true',
                    help='Logout is required to install.')

    # Get our options and our package names
    options, filelists = p.parse_args()

    if not os.path.exists(packagemaker):
        print >>sys.stderr, \
                "packagemaker tool not found at %s." % packagemaker
        exit(-1)
    
    if len(filelists) == 0:
        print >>sys.stderr, "You must specify a file list!"
        exit(-1)
        
    if len(filelists) > 1:
        print >>sys.stderr, "You may convert only one file list at a time."
        exit(-1)
        
    filelist = filelists[0]
    if not os.path.exists(filelist):
        print "No file list at %s" % filelist
        exit(-1)
                
    mytmpdir = tempfile.mkdtemp()
    if options.name:
        pkgname = options.name
    else:
        pkgname = os.path.splitext(os.path.basename(filelist))[0]
    
    packageroot = os.path.join(mytmpdir, pkgname)
    os.mkdir(packageroot)
    copyItemsFromList(filelist, packageroot)
    
    # some default values
    (name, versionInName) = nameAndVersion(pkgname)
    if options.id:
        pkgid = options.id
    else:
        pkgid = pkgidprefix + name.lower()
    if options.version:
        pkgvers = options.version
    elif versionInName:
        pkgvers = versionInName
    else:
        pkgvers = "1.0.0"
        
    infopath = ""
    
    # look through packageroot dir for Receipts
    pkgrootreceipts = os.path.join(packageroot, "Library/Receipts")
    if os.path.exists(pkgrootreceipts):
        receiptlist = os.listdir(pkgrootreceipts)
        if len(receiptlist) == 1:
            receipt = os.path.join(pkgrootreceipts, receiptlist[0])
            infopath = os.path.join(receipt,"Contents/Info.plist")
            if os.path.exists(infopath):
                print "Using package info from %s" % infopath
            else:
                infopath = ""
        else:
            print >>sys.stderr, \
                  ("Found multiple receipts, "
                   "so cannot determine pkgid and version.")
                
    if not infopath:
        # look for a single application bundle and get info from that
        appinfo = ""
        for dirpath, dirnames, filenames in os.walk(packageroot):
            if dirpath.endswith('.app'):
                if not appinfo:
                    appinfo = os.path.join(dirpath, "Contents/Info.plist")
                    if not os.path.exists(appinfo):
                        appinfo = ""
                else:
                    # crap, found more than one.
                    appinfo = ""
                    print >>sys.stderr, \
                          ("Found multiple application bundles, "
                           "so cannot determine pkgid and version.")
                    break
                    
        if appinfo:
            pl = plistlib.readPlist(appinfo)
            if "CFBundleIdentifier" in pl and not options.id:
                pkgid = pl["CFBundleIdentifier"] + ".pkg"
            if "CFBundleShortVersionString" in pl and not options.version:
                pkgvers = pl["CFBundleShortVersionString"]
            print "Using pkgid: %s, version: %s from %s" % (pkgid, pkgvers,
                                                            appinfo)
        else:
            # let's look for any Contents/Info.plist
            infoplist = ""
            for dirpath, dirnames, filenames in os.walk(packageroot):
                if dirpath.endswith("/Contents") and \
                   "Info.plist" in filenames:
                    if not infoplist:
                        infoplist = os.path.join(dirpath, "Info.plist")
                        if not os.path.exists(infoplist):
                            infoplist = ""
                    else:
                        # found more than one Info.plist
                        infoplist = ""
                        break
            
            if infoplist:
                pl = plistlib.readPlist(infoplist)
                if "CFBundleIdentifier" in pl and not options.id:
                    pkgid = pl["CFBundleIdentifier"] + ".pkg"
                if "CFBundleShortVersionString" in pl and not options.version:
                    pkgvers = pl["CFBundleShortVersionString"]
                print "Using pkgid: %s, version: %s from %s" % (pkgid,
                                                                pkgvers,
                                                                infoplist)
                
        print "Package name: %s" % pkgname
        newdisplayname = raw_input("Display name [%s]: " 
                                        % options.displayname)
        options.displayname = newdisplayname or options.displayname
        newdescription = raw_input("Description [%s]: " % options.description)
        options.description =  newdescription or options.description
        newid = raw_input("PackageID [%s]: " % pkgid)
        pkgid = newid or pkgid
        newversion = raw_input("Version [%s]: " % pkgvers)
        pkgvers = newversion or pkgvers
    
    print
    print
    print "Package name: %s" % pkgname
    print "Display name: %s" % options.displayname
    print "Description:  %s" % options.description
    print "PackageID:    %s" % pkgid
    print "Version:      %s" % pkgvers
    print
    answer = raw_input("Build the package? [y/n] ")
    if not answer.lower().startswith("y"):
        exit(0)
    
    # build package   
    outputname = os.path.join(pkgoutputdir, pkgname + ".pkg")
    if os.path.exists(outputname):
        retcode = subprocess.call(["/bin/rm", "-rf", outputname])
        
    if infopath:
        cmd = [packagemaker, '--root', packageroot, '--info', infopath, 
                        '--no-recommend', '--out', outputname, '--verbose',
                        '--filter', 'Library/Receipts', 
                        '--filter', '.DS_Store$']
    else:
        cmd = [packagemaker, '--root', packageroot, '--id', pkgid,
                '--version', pkgvers, '--out', outputname,
                 '--verbose', '--no-recommend',
                 '--filter', 'Library/Receipts', 
                 '--filter', '.DS_Store$']
    print cmd
    p = subprocess.Popen(cmd, shell=False, bufsize=1, stdin=subprocess.PIPE, 
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    while True: 
        output =  p.stdout.readline()
        if not output and (p.poll() != None):
            break
        print output.rstrip("\n")
        sys.stdout.flush()
        
    retcode = p.poll()
    if retcode:
        print >>sys.stderr, "Package creation failed."
        exit(-1)
    else:
        # remove relocatable stuff
        tokendefinitions = os.path.join(outputname, 
                            "Contents/Resources/TokenDefinitions.plist")
        if os.path.exists(tokendefinitions):
            os.remove(tokendefinitions)
        infoplist = os.path.join(outputname, "Contents/Info.plist")
        pl = plistlib.readPlist(infoplist)
        if 'IFPkgPathMappings' in pl:
            del pl['IFPkgPathMappings']
        
        if options.restart:
            # add restart info to plist
            pl['IFPkgFlagRestartAction'] = "RequiredRestart"
        elif options.logout:
            # add logout info to plist
            pl['IFPkgFlagRestartAction'] = "RequiredLogout"
            
        plistlib.writePlist(pl, infoplist)
        
        if options.displayname or options.description:
            languages = ['en.lproj', 'English.lproj']
            for item in languages:
                lprojpath = os.path.join(outputname, 
                                        'Contents/Resources', item)
                if os.path.exists(lprojpath):
                    descriptionplist = os.path.join(lprojpath,
                                                    "Description.plist")
                    pl = {}
                    pl['IFPkgDescriptionTitle'] = (options.displayname or 
                                                    pkgname)
                    pl['IFPkgDescriptionDescription'] = (options.description        
                                                            or "")
                    plistlib.writePlist(pl, descriptionplist)
                    break
        
        print "Completed package is at %s" % outputname
        if not options.nomakedmg:
            makeDMG(outputname)
    
    #cleanup temp dir
    retcode = subprocess.call(["/bin/rm", "-rf", mytmpdir])
    
        
if __name__ == '__main__':
	main()
