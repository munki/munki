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
removepackages.py 

a tool to analyze installed packages and remove
files unique to the packages given at the command line. No attempt
is made to revert to older versions of a file when uninstalling;
only file removals are done.

Callable directly from the command-line and as a python module.
"""


import optparse
import os
import subprocess
import sys
import sqlite3
import time
import munkistatus
import munkicommon
import FoundationPlist


##################################################################
# Schema of Leopard's /Library/Receipts/db/a.receiptsdb:
#
# CREATE TABLE acls (path_key INTEGER NOT NULL,
#                    pkg_key INTEGER NOT NULL,
#                    acl VARCHAR NOT NULL );
# CREATE TABLE groups (group_key INTEGER PRIMARY KEY AUTOINCREMENT,
#                      owner INTEGER NOT NULL, groupid VARCHAR NOT NULL);
# CREATE TABLE oldpkgs (pkg_key INTEGER PRIMARY KEY,
#                       tmestamp INTEGER NOT NULL,
#                       owner INTEGER NOT NULL,
#                       pkgid VARCHAR NOT NULL,
#                       vers VARCHAR NOT NULL,
#                       ppath VARCHAR NOT NULL,
#                       replaces INTEGER,
#                       replacedby INTEGER );
# CREATE TABLE paths (path_key INTEGER PRIMARY KEY AUTOINCREMENT,
#                     path VARCHAR NOT NULL UNIQUE );
# CREATE TABLE pkgs (pkg_key INTEGER PRIMARY KEY AUTOINCREMENT,
#                    timestamp INTEGER NOT NULL,
#                    owner INTEGER NOT NULL,
#                    pkgid VARCHAR NOT NULL,
#                    vers VARCHAR NOT NULL,
#                    ppath VARCHAR NOT NULL,
#                    replaces INTEGER );
# CREATE TABLE pkgs_groups (pkg_key INTEGER NOT NULL,
#                           group_key INTEGER NOT NULL );
# CREATE TABLE pkgs_paths (pkg_key INTEGER NOT NULL,
#                          path_key INTEGER NOT NULL,
#                          uid INTEGER,
#                          gid INTEGER,
#                          perms INTEGER );
# CREATE TABLE sha1s (path_key INTEGER NOT NULL,
#                     pkg_key INTEGER NOT NULL,
#                     sha1 BLOB NOT NULL );
# CREATE TABLE taints (pkg_key INTEGER NOT NULL,
#                      taint VARCHAR NOT NULL);
#################################################################
#################################################################
# our package db schema -- a subset of Apple's, but sufficient
#                          for our needs:
#
# CREATE TABLE paths (path_key INTEGER PRIMARY KEY AUTOINCREMENT,
#                     path VARCHAR NOT NULL UNIQUE )
# CREATE TABLE pkgs (pkg_key INTEGER PRIMARY KEY AUTOINCREMENT,
#                    timestamp INTEGER NOT NULL,
#                    owner INTEGER NOT NULL,
#                    pkgid VARCHAR NOT NULL,
#                    vers VARCHAR NOT NULL,
#                    ppath VARCHAR NOT NULL,
#                    pkgname VARCHAR NOT NULL,
#                    replaces INTEGER )
# CREATE TABLE pkgs_paths (pkg_key INTEGER NOT NULL,
#                          path_key INTEGER NOT NULL,
#                          uid INTEGER,
#                          gid INTEGER,
#                          perms INTEGER )
#################################################################

def local_display_percent_done(current,maximum):
    # bump up verboseness so we get download percentage done feedback.
    oldverbose = munkicommon.verbose
    munkicommon.verbose = oldverbose + 1
    
    munkicommon.display_percent_done(current,maximum)
    
    # set verboseness back.
    munkicommon.verbose = oldverbose


def shouldRebuildDB(pkgdbpath):
    """
    Checks to see if our internal package DB should be rebuilt.
    If anything in /Library/Receipts, /Library/Receipts/boms, or
    /Library/Receipts/db/a.receiptdb has a newer modtime than our
    database, we should rebuild.
    """
    receiptsdir = "/Library/Receipts"
    bomsdir = "/Library/Receipts/boms"
    sl_receiptsdir = "/private/var/db/receipts"
    installhistory = "/Library/Receipts/InstallHistory.plist"
    applepkgdb = "/Library/Receipts/db/a.receiptdb"

    if not os.path.exists(pkgdbpath):
        return True

    packagedb_modtime = os.stat(pkgdbpath).st_mtime

    if os.path.exists(receiptsdir):
        receiptsdir_modtime = os.stat(receiptsdir).st_mtime
        if packagedb_modtime < receiptsdir_modtime:
            return True
        receiptlist = os.listdir(receiptsdir)
        for item in receiptlist:
            if item.endswith(".pkg"):
                pkgpath = os.path.join(receiptsdir, item)
                pkg_modtime = os.stat(pkgpath).st_mtime
                if (packagedb_modtime < pkg_modtime):
                    return True

    if os.path.exists(bomsdir):
        bomsdir_modtime = os.stat(bomsdir).st_mtime
        if packagedb_modtime < bomsdir_modtime:
            return True
        bomlist = os.listdir(bomsdir)
        for item in bomlist:
            if item.endswith(".bom"):
                bompath = os.path.join(bomsdir, item)
                bom_modtime = os.stat(bompath).st_mtime
                if (packagedb_modtime < bom_modtime):
                    return True

    if os.path.exists(sl_receiptsdir):
        receiptsdir_modtime = os.stat(sl_receiptsdir).st_mtime
        if packagedb_modtime < receiptsdir_modtime:
            return True
        receiptlist = os.listdir(sl_receiptsdir)
        for item in receiptlist:
            if item.endswith(".bom") or item.endswith(".plist"):
                pkgpath = os.path.join(sl_receiptsdir, item)
                pkg_modtime = os.stat(pkgpath).st_mtime
                if (packagedb_modtime < pkg_modtime):
                    return True                    
                    
    if os.path.exists(installhistory):
        installhistory_modtime = os.stat(installhistory).st_mtime
        if packagedb_modtime < installhistory_modtime:
            return True

    if os.path.exists(applepkgdb):
        applepkgdb_modtime = os.stat(applepkgdb).st_mtime
        if packagedb_modtime < applepkgdb_modtime:
            return True
            
    # if we got this far, we don't need to update the db
    return False


def CreateTables(c):
    """
    Creates the tables needed for our internal package database.
    """
    c.execute('''CREATE TABLE paths (path_key INTEGER PRIMARY KEY AUTOINCREMENT,
                                     path VARCHAR NOT NULL UNIQUE )''')
    c.execute('''CREATE TABLE pkgs (pkg_key INTEGER PRIMARY KEY AUTOINCREMENT,
                                    timestamp INTEGER NOT NULL,
                                    owner INTEGER NOT NULL,
                                    pkgid VARCHAR NOT NULL,
                                    vers VARCHAR NOT NULL,
                                    ppath VARCHAR NOT NULL,
                                    pkgname VARCHAR NOT NULL,
                                    replaces INTEGER )''')
    c.execute('''CREATE TABLE pkgs_paths (pkg_key INTEGER NOT NULL,
                                          path_key INTEGER NOT NULL,
                                          uid INTEGER,
                                          gid INTEGER,
                                          perms INTEGER )''')
                                          
                                          
def findBundleReceiptFromID(pkgid):
    '''Finds a bundle receipt in /Library/Receipts based on packageid.
    Some packages write bundle receipts under /Library/Receipts even on
    Snow Leopard; we need to be able to find them so we can remove them.
    Returns a path.'''
    if not pkgid:
        return ''
    receiptsdir = "/Library/Receipts"
    for item in os.listdir(receiptsdir):
        itempath = os.path.join(receiptsdir, item)
        if item.endswith('.pkg') and os.path.isdir(itempath):
            info = munkicommon.getOnePackageInfo(itempath)
            if info.get('packageid') == pkgid:
                return itempath
                
    #if we get here, not found
    return ''


def ImportPackage(packagepath, c):
    """
    Imports package data from the receipt at packagepath into
    our internal package database.
    """

    bompath = os.path.join(packagepath, 'Contents/Archive.bom')
    infopath = os.path.join(packagepath, 'Contents/Info.plist')
    pkgname = os.path.basename(packagepath)

    if not os.path.exists(packagepath):
        munkicommon.display_error("%s not found." % packagepath)
        return

    if not os.path.isdir(packagepath):
        # Every machine I've seen has a bogus BSD.pkg, 
        # so we won't print a warning for that specific one. 
        if pkgname != "BSD.pkg":
            munkicommon.display_warning(
                "%s is not a valid receipt. Skipping." % packagepath)
        return

    if not os.path.exists(bompath):
        # look in receipt's Resources directory
        bomname = os.path.splitext(pkgname)[0] + '.bom'
        bompath = os.path.join(packagepath, "Contents/Resources", 
                                bomname)
        if not os.path.exists(bompath):
            munkicommon.display_warning("%s has no BOM file. Skipping." % 
                                        packagepath)
            return

    if not os.path.exists(infopath):
        munkicommon.display_warning("%s has no Info.plist. Skipping." %
                                    packagepath)
        return

    timestamp = os.stat(packagepath).st_mtime
    owner = 0
    pl = FoundationPlist.readPlist(infopath)
    if "CFBundleIdentifier" in pl:
        pkgid = pl["CFBundleIdentifier"]
    elif "Bundle identifier" in pl:
        # special case for JAMF Composer generated packages. WTF?
        pkgid = pl["Bundle identifier"]
    else:
        pkgid = pkgname
    if "CFBundleShortVersionString" in pl:
        vers = pl["CFBundleShortVersionString"]
    elif "Bundle versions string, short" in pl:
        # another special case for JAMF Composer-generated packages. Wow.
        vers = pl["Bundle versions string, short"]
    else:
        vers = "1.0"
    if "IFPkgRelocatedPath" in pl:
        ppath = pl["IFPkgRelocatedPath"]
        ppath = ppath.lstrip('./').rstrip('/')
    else:
        ppath = ""
        
    t = (timestamp, owner, pkgid, vers, ppath, pkgname)
    c.execute('INSERT INTO pkgs (timestamp, owner, pkgid, vers, ppath, pkgname) values (?, ?, ?, ?, ?, ?)', t)
    pkgkey = c.lastrowid
    
    cmd = ["/usr/bin/lsbom", bompath]
    p = subprocess.Popen(cmd, shell=False, bufsize=1, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                            
    while True: 
        line =  p.stdout.readline().decode('UTF-8')
        if not line and (p.poll() != None):
            break
        
        try:
            item = line.rstrip("\n").split("\t")
            path = item[0]
            perms = item[1]
            uidgid = item[2].split("/")
            uid = uidgid[0]
            gid = uidgid[1]
            if path != ".":
                # special case for MS Office 2008 installers
                if ppath == "tmp/com.microsoft.updater/office_location":
                    ppath = "Applications"
                    
                # prepend the ppath so the paths match the actual install 
                # locations
                path = path.lstrip("./")
                if ppath:
                    path = ppath + "/" + path
                    
                t = (path, )
                row = c.execute('SELECT path_key from paths where path = ?',
                                t).fetchone()
                if not row:
                    c.execute('INSERT INTO paths (path) values (?)', t)
                    pathkey = c.lastrowid
                else:
                    pathkey = row[0]

                t = (pkgkey, pathkey, uid, gid, perms)
                c.execute('INSERT INTO pkgs_paths (pkg_key, path_key, uid, gid, perms) values (?, ?, ?, ?, ?)', t)
        except sqlite3.DatabaseError:
            pass


def ImportBom(bompath, c):
    """
    Imports package data into our internal package database
    using a combination of the bom file and data in Apple's
    package database into our internal package database.
    """
    # If we completely trusted the accuracy of Apple's database, we wouldn't
    # need the bom files, but in my enviroment at least, the bom files are
    # a better indicator of what flat packages have actually been installed
    # on the current machine. 
    # We still need to consult Apple's package database
    # because the bom files are missing metadata about the package.
    
    applepkgdb = "/Library/Receipts/db/a.receiptdb"
    pkgname = os.path.basename(bompath)

    timestamp = os.stat(bompath).st_mtime
    owner = 0
    pkgid =  os.path.splitext(pkgname)[0]
    vers = "1.0"
    ppath = ""

    #try to get metadata from applepkgdb
    p = subprocess.Popen(["/usr/sbin/pkgutil", "--pkg-info-plist", pkgid],
        bufsize=1, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (plist, err) = p.communicate()
    if plist:
        pl = FoundationPlist.readPlistFromString(plist)
        if "install-location" in pl:
            ppath = pl["install-location"]
            ppath = ppath.lstrip('./').rstrip('/')
        if "pkg-version" in pl:
            vers = pl["pkg-version"]
        if "install-time" in pl:
            timestamp = pl["install-time"]

    t = (timestamp, owner, pkgid, vers, ppath, pkgname)
    c.execute('INSERT INTO pkgs (timestamp, owner, pkgid, vers, ppath, pkgname) values (?, ?, ?, ?, ?, ?)', t)
    pkgkey = c.lastrowid

    cmd = ["/usr/bin/lsbom", bompath]
    p = subprocess.Popen(cmd, shell=False, bufsize=1, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                            
    while True: 
        line =  p.stdout.readline().decode('UTF-8')
        if not line and (p.poll() != None):
            break
        item = line.rstrip("\n").split("\t")
        path = item[0]
        perms = item[1]
        uidgid = item[2].split("/")
        uid = uidgid[0]
        gid = uidgid[1]
        if path != ".":
            # special case for MS Office 2008 installers
            if ppath == "tmp/com.microsoft.updater/office_location":
                ppath = "Applications"

            #prepend the ppath so the paths match the actual install locations
            path = path.lstrip("./")
            if ppath:
                path = ppath + "/" + path

            t = (path, )
            row = c.execute('SELECT path_key from paths where path = ?',
                            t).fetchone()
            if not row:
                c.execute('INSERT INTO paths (path) values (?)', t)
                pathkey = c.lastrowid
            else:
                pathkey = row[0]

            t = (pkgkey, pathkey, uid, gid, perms)
            c.execute('INSERT INTO pkgs_paths (pkg_key, path_key, uid, gid, perms) values (?, ?, ?, ?, ?)', t)


def ImportFromPkgutil(pkgname, c):
    """
    Imports package data from pkgutil into our internal package database.
    """
    
    timestamp = 0
    owner = 0
    pkgid =  pkgname
    vers = "1.0"
    ppath = ""

    #get metadata from applepkgdb
    p = subprocess.Popen(["/usr/sbin/pkgutil", "--pkg-info-plist", pkgid],
        bufsize=1, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (plist, err) = p.communicate()
    if plist:
        pl = FoundationPlist.readPlistFromString(plist)
        if "install-location" in pl:
            ppath = pl["install-location"]
            ppath = ppath.lstrip('./').rstrip('/')
        else:
            # there _should_ be an install-location. If there's not, let's
            # check the old /Library/Receipts. 
            # (Workaround for QuarkXPress 8.1 packages)
            receiptpath = findBundleReceiptFromID(pkgid)
            if receiptpath:
                infopath = os.path.join(receiptpath, 'Contents/Info.plist')
                if os.path.exists(infopath):
                    infopl = FoundationPlist.readPlist(infopath)
                    if "IFPkgRelocatedPath" in infopl:
                        ppath = infopl["IFPkgRelocatedPath"]
                        ppath = ppath.lstrip('./').rstrip('/')
        if "pkg-version" in pl:
            vers = pl["pkg-version"]
        if "install-time" in pl:
            timestamp = pl["install-time"]

    t = (timestamp, owner, pkgid, vers, ppath, pkgname)
    c.execute('INSERT INTO pkgs (timestamp, owner, pkgid, vers, ppath, pkgname) values (?, ?, ?, ?, ?, ?)', t)
    pkgkey = c.lastrowid

    cmd = ["/usr/sbin/pkgutil", "--files", pkgid]
    p = subprocess.Popen(cmd, shell=False, bufsize=1, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    while True: 
        line =  p.stdout.readline().decode('UTF-8')
        if not line and (p.poll() != None):
            break
        path = line.rstrip("\n")
        
        # pkgutil --files pkgid only gives us path info.  We don't
        # really need perms, uid and gid, so we'll just fake them.
        # if we needed them, we'd have to call 
        # pkgutil --export-plist pkgid and iterate through the
        # plist.  That would be slower, so we'll do things this way...
        perms = "0000"
        uid = "0"
        gid = "0"
        if path != ".":
            # special case for MS Office 2008 installers
            # /tmp/com.microsoft.updater/office_location
            if ppath == "tmp/com.microsoft.updater/office_location":
                ppath = "Applications"

            #prepend the ppath so the paths match the actual install locations
            path = path.lstrip("./")
            if ppath:
                path = ppath + "/" + path

            t = (path, )
            row = c.execute('SELECT path_key from paths where path = ?',
                            t).fetchone()
            if not row:
                c.execute('INSERT INTO paths (path) values (?)', t)
                pathkey = c.lastrowid
            else:
                pathkey = row[0]

            t = (pkgkey, pathkey, uid, gid, perms)
            c.execute('INSERT INTO pkgs_paths (pkg_key, path_key, uid, gid, perms) values (?, ?, ?, ?, ?)', t)


def initDatabase(packagedb,forcerebuild=False):
    """
    Builds or rebuilds our internal package database.
    """
    if not shouldRebuildDB(packagedb) and not forcerebuild:
        return True
        
    munkicommon.display_status('Gathering information on installed packages')
    
    if os.path.exists(packagedb):
        try:
            os.remove(packagedb)
        except (OSError, IOError), e:
            munkicommon.display_error(
                "Could not remove out-of-date receipt database.")
            return False
            
    pkgcount = 0
    receiptsdir = "/Library/Receipts"
    bomsdir = "/Library/Receipts/boms"
    if os.path.exists(receiptsdir):
        receiptlist = os.listdir(receiptsdir)
        for item in receiptlist:
            if item.endswith(".pkg"):
                pkgcount += 1
    if os.path.exists(bomsdir):
        bomslist = os.listdir(bomsdir)
        for item in bomslist:
            if item.endswith(".bom"):
                pkgcount += 1
    else:
        #no boms dir in some versions of OS X
        pkglist = []
        cmd = ['/usr/sbin/pkgutil', '--pkgs']
        p = subprocess.Popen(cmd, shell=False, bufsize=1, 
                             stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, 
                             stderr=subprocess.PIPE)
        while True: 
            line =  p.stdout.readline()
            if not line and (p.poll() != None):
                break
            
            pkglist.append(line.rstrip('\n'))
            pkgcount += 1
            
    conn = sqlite3.connect(packagedb)
    conn.text_factory = str
    c = conn.cursor()
    CreateTables(c)
    
    currentpkgindex = 0
    local_display_percent_done(0, pkgcount)
    
    if os.path.exists(receiptsdir):
        receiptlist = os.listdir(receiptsdir)
        for item in receiptlist:
            if munkicommon.stopRequested():
                c.close()
                conn.close()
                #our package db isn't valid, so we should delete it
                os.remove(packagedb)
                return False
                
            if item.endswith(".pkg"):
                receiptpath = os.path.join(receiptsdir, item)
                munkicommon.display_detail("Importing %s..." % receiptpath)
                ImportPackage(receiptpath, c)
                currentpkgindex += 1
                local_display_percent_done(currentpkgindex, pkgcount)
                
    if os.path.exists(bomsdir):
        bomslist = os.listdir(bomsdir)
        for item in bomslist:
            if munkicommon.stopRequested():
                c.close()
                conn.close()
                #our package db isn't valid, so we should delete it
                os.remove(packagedb)
                return False
                
            if item.endswith(".bom"):
                bompath = os.path.join(bomsdir, item)
                munkicommon.display_detail("Importing %s..." % bompath)
                ImportBom(bompath, c)
                currentpkgindex += 1
                local_display_percent_done(currentpkgindex, pkgcount)
    else:
        #no boms dir in some versions of OS X
        for pkg in pkglist:
            if munkicommon.stopRequested():
                c.close()
                conn.close()
                #our package db isn't valid, so we should delete it
                os.remove(packagedb)
            munkicommon.display_detail("Importing %s..." % pkg)
            ImportFromPkgutil(pkg, c)
            currentpkgindex += 1
            local_display_percent_done(currentpkgindex, pkgcount)
            
    # in case we didn't quite get to 100% for some reason
    if currentpkgindex < pkgcount:
        local_display_percent_done(pkgcount, pkgcount)
        
    # commit and close the db when we're done.
    conn.commit()
    c.close()
    conn.close()
    return True


def getpkgkeys(pkgnames):
    """
    Given a list of receipt names, bom file names, or package ids,
    gets a list of pkg_keys from the pkgs table in our database.
    """
    # open connection and cursor to our database
    conn = sqlite3.connect(packagedb)
    c = conn.cursor()
    
    # check package names to make sure they're all in the database, 
    # build our list of pkg_keys
    pkgerror = False
    pkgkeyslist = []
    for pkg in pkgnames:
        t = (pkg, )
        munkicommon.display_debug1(
                    "select pkg_key from pkgs where pkgid = %s" % pkg)
        pkg_keys = c.execute('select pkg_key from pkgs where pkgid = ?',
                             t).fetchall()
        if not pkg_keys:
            # try pkgname
            munkicommon.display_debug1(
                        "select pkg_key from pkgs where pkgname = %s" % pkg)
            pkg_keys = c.execute('select pkg_key from pkgs where pkgname = ?',
                                 t).fetchall()
        if not pkg_keys:
            munkicommon.display_error("%s not found in database." % pkg)
            pkgerror = True
        else:
            for row in pkg_keys:
                # only want first column
                pkgkeyslist.append(row[0])
    if pkgerror:
        pkgkeyslist = []
    c.close
    conn.close
    munkicommon.display_debug1("pkgkeys: %s" % pkgkeyslist)
    return pkgkeyslist


def getpathstoremove(pkgkeylist):
    """
    Queries our database for paths to remove.
    """
    pkgkeys = tuple(pkgkeylist)
    
    # open connection and cursor to our database
    conn = sqlite3.connect(packagedb)
    c = conn.cursor()
    
    # set up some subqueries:
    # all the paths that are referred to by the selected packages:
    if len(pkgkeys) > 1:
        in_selected_packages = \
          "select distinct path_key from pkgs_paths where pkg_key in %s" % \
           str(pkgkeys)
    else:
        in_selected_packages = \
          "select distinct path_key from pkgs_paths where pkg_key = %s" % \
           str(pkgkeys[0])
        
    # all the paths that are referred to by every package 
    # except the selected packages:
    if len(pkgkeys) > 1:
        not_in_other_packages = \
        "select distinct path_key from pkgs_paths where pkg_key not in %s" % \
         str(pkgkeys)
    else:
        not_in_other_packages = \
        "select distinct path_key from pkgs_paths where pkg_key != %s" % \
         str(pkgkeys[0])
        
    # every path that is used by the selected packages and no other packages:
    combined_query = \
        "select path from paths where " + \
        "(path_key in (%s) and path_key not in (%s))" % \
                                (in_selected_packages, not_in_other_packages)
    
    munkicommon.display_status('Determining which filesystem items to remove')
    if munkicommon.munkistatusoutput:
        munkistatus.percent(-1)
    
    c.execute(combined_query)
    results = c.fetchall()
    c.close()
    conn.close()
    
    removalpaths = []
    for item in results:
        removalpaths.append(item[0])
        
    return removalpaths


def removeReceipts(pkgkeylist, noupdateapplepkgdb):
    """
    Removes receipt data from /Library/Receipts,
    /Library/Receipts/boms, our internal package database,
    and optionally Apple's package database.
    """
    munkicommon.display_status('Removing receipt info')
    local_display_percent_done(0,4)
    
    conn = sqlite3.connect(packagedb)
    c = conn.cursor()
    
    osvers = int(os.uname()[2].split('.')[0])
    
    applepkgdb = '/Library/Receipts/db/a.receiptdb'
    if not noupdateapplepkgdb and osvers < 10:
        aconn = sqlite3.connect(applepkgdb)
        ac = aconn.cursor()
    
    local_display_percent_done(1,4)
    
    for pkgkey in pkgkeylist:
        pkgid = ''
        t = (pkgkey, )
        row = c.execute('SELECT pkgname, pkgid from pkgs where pkg_key = ?',
                        t).fetchone()
        if row:
            pkgname = row[0]
            pkgid = row[1]
            receiptpath = None
            if osvers < 10:
                if pkgname.endswith('.pkg'):
                    receiptpath = os.path.join('/Library/Receipts', pkgname)
                if pkgname.endswith('.bom'):
                    receiptpath = os.path.join('/Library/Receipts/boms',
                                                pkgname)
            else:
                # clean up /Library/Receipts in case there's stuff left there
                receiptpath = findBundleReceiptFromID(pkgid)
                
            if receiptpath and os.path.exists(receiptpath):
                munkicommon.display_detail("Removing %s..." % receiptpath)
                retcode = subprocess.call(["/bin/rm", "-rf", receiptpath])
            
        # remove pkg info from our database
        if munkicommon.verbose > 1:
            print "Removing package data from internal database..."
        c.execute('DELETE FROM pkgs_paths where pkg_key = ?', t)
        c.execute('DELETE FROM pkgs where pkg_key = ?', t)
        
        # then remove pkg info from Apple's database unless option is passed
        if not noupdateapplepkgdb and pkgid:
            if osvers < 10:
                # Leopard
                t = (pkgid, )
                row = ac.execute(
                    'SELECT pkg_key FROM pkgs where pkgid = ?',
                     t).fetchone()
                if row:
                    munkicommon.display_detail(
                        "Removing package data from Apple package "+
                        "database...")
                    apple_pkg_key = row[0]
                    t = (apple_pkg_key, )
                    ac.execute('DELETE FROM pkgs where pkg_key = ?', t)
                    ac.execute('DELETE FROM pkgs_paths where pkg_key = ?', t)
                    ac.execute('DELETE FROM pkgs_groups where pkg_key = ?', t)
                    ac.execute('DELETE FROM acls where pkg_key = ?', t)
                    ac.execute('DELETE FROM taints where pkg_key = ?', t)
                    ac.execute('DELETE FROM sha1s where pkg_key = ?', t)
                    ac.execute('DELETE FROM oldpkgs where pkg_key = ?', t)
            else:
                # Snow Leopard or higher, must use pkgutil
                cmd = ['/usr/sbin/pkgutil', '--forget', pkgid]
                p = subprocess.Popen(cmd, bufsize=1, 
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE)
                (output, err) = p.communicate()
                if munkicommon.verbose > 1:
                    if output: print output.decode('UTF-8').rstrip('\n')
                    
    local_display_percent_done(2,4)
    
    # now remove orphaned paths from paths table
    # first, Apple's database if option is passed
    if not noupdateapplepkgdb:
        if osvers < 10:
            munkicommon.display_detail(
                "Removing unused paths from Apple package database...")
            ac.execute('DELETE FROM paths where path_key not in (select distinct path_key from pkgs_paths)')
            aconn.commit()
            ac.close()
            aconn.close()
    
    local_display_percent_done(3,4)
    
    # we do our database last so its modtime is later than the modtime for the 
    # Apple DB...
    munkicommon.display_detail("Removing unused paths from internal package "
                               "database...")
    c.execute('DELETE FROM paths where path_key not in (select distinct path_key from pkgs_paths)')
    conn.commit()
    c.close()
    conn.close()
    
    local_display_percent_done(4,4)


def isBundle(pathname):
    """
    Returns true if pathname is a bundle-style directory.
    """
    bundle_extensions = [".action",
                       ".app",
                       ".bundle",
                       ".clr",
                       ".colorPicker",
                       ".component",
                       ".dictionary",
                       ".docset",
                       ".framework",
                       ".fs",
                       ".kext",
                       ".loginPlugin",
                       ".mdiimporter",
                       ".monitorPanel",
                       ".osax",
                       ".pkg",
                       ".plugin",
                       ".prefPane",
                       ".qlgenerator",
                       ".saver",
                       ".service",
                       ".slideSaver",
                       ".SpeechRecognizer",
                       ".SpeechSynthesizer",
                       ".SpeechVoice",
                       ".spreporter",
                       ".wdgt" ]
    if os.path.isdir(pathname):
        basename = os.path.basename(pathname)
        (filename, extension) = os.path.splitext(basename)
        if extension in bundle_extensions:
            return True
        else:
            return False
    else:
        return False
        
        
def insideBundle(pathname):
    # check the path to see if it's inside a bundle
    while len(pathname) > 1:
        if isBundle(pathname):
            return True
        else:
            # chop off last item in path
            pathname = os.path.dirname(pathname)
    #if we get here, we didn't find a bundle path
    return False


def removeFilesystemItems(removalpaths, forcedeletebundles):
    """
    Attempts to remove all the paths in the array removalpaths
    """
    # we sort in reverse because we can delete from the bottom up,
    # clearing a directory before we try to remove the directory itself
    removalpaths.sort(reverse=True)
    removalerrors = ""
    removalcount = len(removalpaths)
    munkicommon.display_status("Removing %s filesystem items" % removalcount)
    
    itemcount = len(removalpaths)
    itemindex = 0
    local_display_percent_done(itemindex, itemcount)
    
    for item in removalpaths:
        itemindex += 1
        pathtoremove = "/" + item
        # use os.path.lexists so broken links return true 
        # so we can remove them
        if os.path.lexists(pathtoremove):
            munkicommon.display_detail("Removing: " + pathtoremove)
            if (os.path.isdir(pathtoremove) and \
               not os.path.islink(pathtoremove)):
                diritems = os.listdir(pathtoremove)
                if diritems == ['.DS_Store']:
                    # If there's only a .DS_Store file
                    # we'll consider it empty
                    ds_storepath = pathtoremove + "/.DS_Store"
                    try:
                        os.remove(ds_storepath)
                    except (OSError, IOError):
                        pass
                    diritems = os.listdir(pathtoremove)
                if diritems == []:
                    # directory is empty
                    try:
                        os.rmdir(pathtoremove)
                    except (OSError, IOError), err:
                        msg = "Couldn't remove directory %s - %s" % \
                               (pathtoremove, err)
                        munkicommon.display_error(msg)
                        removalerrors = removalerrors + "\n" + msg
                else:
                    # the directory is marked for deletion but isn't empty.
                    # if so directed, if it's a bundle (like .app), we should
                    # remove it anyway - no use having a broken bundle hanging
                    # around
                    if (forcedeletebundles and isBundle(pathtoremove)):
                        munkicommon.display_warning(
                            "Removing non-empty bundle: %s" % pathtoremove)
                        retcode = subprocess.call(['/bin/rm', '-r',
                                                   pathtoremove])
                        if retcode:
                            msg = "Couldn't remove bundle %s" % pathtoremove
                            munkicommon.display_error(msg)
                            removalerrors = removalerrors + "\n" + msg
                    else:
                        # if this path is inside a bundle, and we've been
                        # directed to force remove bundles,
                        # we don't need to warn because it's going to be 
                        # removed with the bundle. 
                        # Otherwise, we should warn about non-empty 
                        # directories.
                        if not insideBundle(pathtoremove) or \
                           not forcedeletebundles:
                            msg = \
                              "Did not remove %s because it is not empty." % \
                               pathtoremove
                            munkicommon.display_error(msg)
                            removalerrors = removalerrors + "\n" + msg
                            
            else:
                # not a directory, just unlink it
                # I was using rm instead of Python because I don't trust
                # handling of resource forks with Python
                #retcode = subprocess.call(['/bin/rm', pathtoremove])
                # but man that's slow. 
                # I think there's a lot of overhead with the
                # subprocess call. I'm going to use os.remove. 
                # I hope I don't regret it.
                retcode = ''
                try:
                    os.remove(pathtoremove)
                except (OSError, IOError), err:
                    msg = "Couldn't remove item %s: %s" % (pathtoremove, err)
                    munkicommon.display_error(msg)
                    removalerrors = removalerrors + "\n" + msg
                    
        local_display_percent_done(itemindex, itemcount)
        
    if removalerrors:
        munkicommon.display_info(
                        "---------------------------------------------------")
        munkicommon.display_info(
                        "There were problems removing some filesystem items.")
        munkicommon.display_info(
                        "---------------------------------------------------")
        munkicommon.display_info(removalerrors)
        
        
def removepackages(pkgnames, forcedeletebundles=False, listfiles=False,
                    rebuildpkgdb=False, noremovereceipts=False,
                    noupdateapplepkgdb=False):
    
    if pkgnames == []:
        munkicommon.display_error(
            "You must specify at least one package to remove!")
        return -2
        
    if not initDatabase(packagedb,forcerebuild=rebuildpkgdb):
        munkicommon.display_error("Could not initialize receipt database.")
        return -3
        
    pkgkeyslist = getpkgkeys(pkgnames)
    if len(pkgkeyslist) == 0:
        return -4
        
    if munkicommon.stopRequested():
        return -128
    removalpaths = getpathstoremove(pkgkeyslist)
    if munkicommon.stopRequested():
        return -128
        
    if removalpaths:
        if listfiles:
            removalpaths.sort()
            for item in removalpaths:
                print "/" + item.encode('UTF-8')
        else:
            if munkicommon.munkistatusoutput:
                munkistatus.disableStopButton()
            removeFilesystemItems(removalpaths, forcedeletebundles)
    else:
        munkicommon.display_status('Nothing to remove.')
        if munkicommon.munkistatusoutput:
            time.sleep(2)
            
    if not listfiles:
        if not noremovereceipts:
            removeReceipts(pkgkeyslist, noupdateapplepkgdb)
        if munkicommon.munkistatusoutput:
            munkistatus.enableStopButton()
            munkicommon.display_status('Package removal complete.')
            time.sleep(2)
           
    return 0


# some globals
packagedb = os.path.join(munkicommon.pref('ManagedInstallDir'), "b.receiptdb")

def main():
    # command-line options
    p = optparse.OptionParser()
    p.add_option('--forcedeletebundles', '-f', action='store_true',
                    help='Delete bundles even if they aren\'t empty.')
    p.add_option('--listfiles', '-l', action='store_true',
                    help='''List the filesystem objects to be removed, 
                    but do not actually remove them.''')
    p.add_option('--rebuildpkgdb', action='store_true',
                    help='Force a rebuild of the internal package database.')
    p.add_option('--noremovereceipts', action='store_true',
                    help='''Do not remove receipts and boms from 
                    /Library/Receipts and update internal package 
                    database.''')
    p.add_option('--noupdateapplepkgdb', action='store_true',
                    help='''Do not update Apple\'s package database. 
                    If --noremovereceipts is also given, this is implied''')
    p.add_option('--munkistatusoutput', '-m', action='store_true',
                    help='Output is formatted for use with MunkiStatus.')
    p.add_option('--verbose', '-v', action='count', default=1,
                    help='''More verbose output. May be specified multiple 
                    times.''')
    
    # Get our options and our package names
    options, pkgnames = p.parse_args()
    
    # check to see if we're root
    if os.geteuid() != 0:
        munkicommon.display_error("You must run this as root!")       
        exit(-1)
        
    # set the munkicommon globals
    munkicommon.munkistatusoutput = options.munkistatusoutput
    munkicommon.verbose = options.verbose
    
    if options.munkistatusoutput:
        pkgcount = len(pkgnames)
        munkistatus.message("Removing %s packages..." % pkgcount)
        munkistatus.detail("")
        
    retcode = removepackages(pkgnames,
                             forcedeletebundles=options.forcedeletebundles,
                             listfiles=options.listfiles,
                             rebuildpkgdb=options.rebuildpkgdb,
                             noremovereceipts=options.noremovereceipts,
                             noupdateapplepkgdb=options.noupdateapplepkgdb)                    
    if options.munkistatusoutput:
        munkistatus.quit()
    exit(retcode)
    
    
if __name__ == '__main__':
	main()

  