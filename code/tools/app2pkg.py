#!/usr/bin/env python
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
app2pkg.py

Created by Greg Neagle on 2009-09-28.
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


def makeDMG(pkgpath):
    print "Making disk image..."
    cmd = ["/usr/bin/hdiutil", "create", "-srcfolder", pkgpath, 
                                                       pkgpath + ".dmg"]
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


def main():
	# command-line options
    p = optparse.OptionParser()
    p.add_option('--makedmg', '-d', action='store_true',
                    help='Makes a disk image containing the package.')
    p.add_option('--name', '-n',
                    help='Specify a name for the package.')
    p.add_option('--version', '-v',
                    help='Specify a version number for the package.')
    p.add_option('--displayname',
                    help='Specify a display name for the package.')
    p.add_option('--description',
                    help='Specify a description for the package.')
    p.add_option('--id',
                    help='Specify a package id for the package.')
    # Get our options and our package names
    options, app_paths = p.parse_args()

    if not os.path.exists(packagemaker):
        print >>sys.stderr, "packagemaker tool not found at %s." % \
                                                            packagemaker
        exit(-1)
    
    if len(app_paths) == 0:
        print >>sys.stderr, "You must specify a path to an application!"
        exit(-1)
        
    if len(app_paths) > 1:
        print >>sys.stderr, "You may package only one app at a time."
        exit(-1)
        
    app_path = app_paths[0]
    
    if not os.path.exists(app_path):
        print "Nothing exists at %s" % app_path
        exit(-1)
                
    mytmpdir = tempfile.mkdtemp()
    if options.name:
        pkgname = options.name
    else:
        pkgname = os.path.splitext(os.path.basename(app_path))[0]
        
    enclosingpath = os.path.dirname(app_path).lstrip("/") or "Applications"
    
    # make packageroot directory
    packageroot = os.path.join(mytmpdir, pkgname)
    os.mkdir(packageroot)
    application_dir = os.path.join(packageroot, enclosingpath)
    os.makedirs(application_dir)
    copytodir = os.path.join(application_dir, os.path.basename(app_path))
    cmd = ['/usr/bin/ditto', '--noqtn', app_path, copytodir ]
    p = subprocess.Popen(cmd, shell=False, bufsize=1, stdin=subprocess.PIPE, 
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (output, err) = p.communicate()
    if p.returncode != 0:
        print >>sys.stderr, err
        exit(-1)
    if err:
        print >>sys.stderr, err
        exit(-1)
        
    # fix uid/gid/perms on directories
    for dirpath, dirnames, filenames in os.walk(packageroot):
        srcdir = dirpath[len(packageroot):]
        if srcdir == "": srcdir = "/"
        os.chown(dirpath, os.stat(srcdir).st_uid, os.stat(srcdir).st_gid)
        os.chmod(dirpath, stat.S_IMODE(os.stat(srcdir).st_mode))
    
    pkgid = pkgvers = ""    
    if options.id:
        pkgid = options.id
    if options.version:
        pkgvers = options.version    
        
    appinfo = os.path.join(app_path, "Contents/Info.plist")
    if os.path.exists(appinfo):
        pl = plistlib.readPlist(appinfo)
        if "CFBundleIdentifier" in pl and pkgid == "":
            pkgid = pl["CFBundleIdentifier"] + ".pkg"
        if "CFBundleShortVersionString" in pl and pkgvers == "":
            pkgvers = pl["CFBundleShortVersionString"]
                
    if pkgid == "":
        pkgid = pkgidprefix + pkgname.lower().replace(" ","_")
    if pkgvers == "":
        pkgvers = "1.0.0"
        
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
    cmd = [packagemaker, '--root', packageroot, '--id', pkgid, 
            '--version', pkgvers, 
            '--no-recommend', '--out', outputname, '--verbose',
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
            plistlib.writePlist(pl, infoplist)
            
        if options.displayname or options.description:
            descriptionplist = os.path.join(outputname, 
                              "Contents/Resources/en.lproj/Description.plist")
            pl = {}
            pl['IFPkgDescriptionTitle'] = options.displayname or pkgname
            pl['IFPkgDescriptionDescription'] = options.description or ""
            plistlib.writePlist(pl, descriptionplist)
        
        print "Completed package is at %s" % outputname
        if options.makedmg:
            makeDMG(outputname)
    
    #cleanup temp dir
    retcode = subprocess.call(["/bin/rm", "-rf", mytmpdir])
    
    
if __name__ == '__main__':
	main()
