#!/usr/bin/env python
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
import plistlib
import sqlite3
import time
import munkistatus
import munkilib


##################################################################
# Schema of /Library/Receipts/db/a.receiptsdb:
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
# our package db schema -- a subset of Apple's
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

def stopRequested():
    if munkistatusoutput:
        if munkistatus.getStopButtonState() == 1:
            return True
            
    return False
    

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
    of Apple's tools (like softwareupdate), or tells
    MunkiStatus to display percent done via progress bar.
    """
    if munkistatusoutput:
        step = getsteps(21, maximum)
        if current in step:
            if current == maximum:
                percentdone = 100
            else:
                percentdone = int(float(current)/float(maximum)*100)
            munkistatus.percent(str(percentdone))
    elif not verbose:
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


def display_status(msg):
    """
    Displays major status messages, formatting as needed
    for verbose/non-verbose and munkistatus-style output.
    """
    log(msg)
    if munkistatusoutput:
        munkistatus.detail(msg)
    elif verbose:
        print "%s..." % msg
    else:
        print "%s: " % msg
    sys.stdout.flush()


def display_info(msg):
    """
    Displays minor info messages, formatting as needed
    for verbose/non-verbose and munkistatus-style output.
    """
    if munkistatusoutput:
        #munkistatus.detail(msg)
        pass
    elif verbose:
        print msg


def display_error(msg):
    """
    Prints msg to stderr and the log
    """
    print >>sys.stderr, msg
    log(msg)
    


def log(msg):
    try:
        f = open(logfile, mode='a', buffering=1)
        print >>f, time.ctime(), msg
        f.close()
    except:
        pass


def shouldRebuildDB(pkgdbpath):
    """
    Checks to see if our internal package DB should be rebuilt.
    If anything in /Library/Receipts, /Library/Receipts/boms, or
    /Library/Receipts/db/a.receiptdb has a newer modtime than our
    database, we should rebuild.
    """
    receiptsdir = "/Library/Receipts"
    bomsdir = "/Library/Receipts/boms"
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

    if os.path.exists(applepkgdb):
        applepkgdb_modtime = os.stat(applepkgdb).st_mtime
        if packagedb_modtime < applepkgdb_modtime:
            return True



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


def ImportPackage(packagepath, c):
    """
    Imports package data from the receipt at packagepath into
    our internal package database.
    """

    bompath = os.path.join(packagepath, 'Contents/Archive.bom')
    infopath = os.path.join(packagepath, 'Contents/Info.plist')
    pkgname = os.path.basename(packagepath)

    if not os.path.exists(packagepath):
        display_error("%s not found." % packagepath)
        return

    if not os.path.isdir(packagepath):
        display_error("%s is not a valid receipt. Skipping." % packagepath)
        return

    if not os.path.exists(bompath):
        # look in receipt's Resources directory
        bomname = os.path.splitext(pkgname)[0] + '.bom'
        bompath = os.path.join(packagepath, "Contents/Resources", 
                                bomname)
        if not os.path.exists(bompath):
            display_error("%s has no BOM file. Skipping." % packagepath)
            return

    if not os.path.exists(infopath):
        display_error("%s has no Info.plist. Skipping." % packagepath)
        return

    timestamp = os.stat(packagepath).st_mtime
    owner = 0
    pl = plistlib.readPlist(infopath)
    if "CFBundleIdentifier" in pl:
        pkgid =  pl["CFBundleIdentifier"]
    else:
        pkgid = pkgname
    if "CFBundleShortVersionString" in pl:
        vers = pl["CFBundleShortVersionString"]
    else:
        vers = "1.0"
    if "IFPkgRelocatedPath" in pl:
        ppath = pl["IFPkgRelocatedPath"]
    else:
        ppath = "./"

    t = (timestamp, owner, pkgid, vers, ppath, pkgname)
    c.execute('INSERT INTO pkgs (timestamp, owner, pkgid, vers, ppath, pkgname) values (?, ?, ?, ?, ?, ?)', t)
    pkgkey = c.lastrowid

    #pkgdict = {}
    #pkgdict['timestamp'] = timestamp
    #pkgdict['owner'] = owner
    #pkgdict['pkgid'] = pkgid
    #pkgdict['vers'] = vers
    #pkgdict['ppath'] = ppath
    #pkgdict['pkgname'] = pkgname
    #pkgdbarray.append(pkgdict)

    cmd = ["/usr/bin/lsbom", bompath]
    p = subprocess.Popen(cmd, shell=False, bufsize=1, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    for line in p.stdout:
        item = line.rstrip("\n").split("\t")
        path = item[0]
        perms = item[1]
        uidgid = item[2].split("/")
        uid = uidgid[0]
        gid = uidgid[1]
        if path != ".":
            # special case for MS Office 2008 installers
            if ppath == "./tmp/com.microsoft.updater/office_location/":
                ppath = "./Applications/"

            # prepend the ppath so the paths match the actual install locations
            path = path.lstrip("./")
            path = ppath + path
            path = path.lstrip("./")

            t = (path, )
            row = c.execute('SELECT path_key from paths where path = ?', t).fetchone()
            if not row:
                c.execute('INSERT INTO paths (path) values (?)', t)
                pathkey = c.lastrowid
            else:
                pathkey = row[0]

            t = (pkgkey, pathkey, uid, gid, perms)
            c.execute('INSERT INTO pkgs_paths (pkg_key, path_key, uid, gid, perms) values (?, ?, ?, ?, ?)', t)


def ImportBom(bompath, c):
    """
    Imports package data into our internal package database
    using a combination of the bom file and data in Apple's
    package database into our internal package database.
    If we completely trusted the accuracy of Apple's database, we wouldn't
    need the bom files, but in my enviroment at least, the bom files are
    a better indicator of what flat packages have actually been installed
    on the current machine. We still need to consult Apple's package database
    because the bom files are missing metadata about the package.
    """
    applepkgdb = "/Library/Receipts/db/a.receiptdb"
    pkgname = os.path.basename(bompath)

    timestamp = os.stat(bompath).st_mtime
    owner = 0
    pkgid =  os.path.splitext(pkgname)[0]
    vers = "1.0"
    ppath = "./"

    #try to get metadata from applepkgdb
    p = subprocess.Popen(["/usr/sbin/pkgutil", "--pkg-info-plist", pkgid],
        bufsize=1, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (plist, err) = p.communicate()
    if plist:
        pl = plistlib.readPlistFromString(plist)
        if "install-location" in pl:
            ppath = pl["install-location"]
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

    for line in p.stdout:
        item = line.rstrip("\n").split("\t")
        path = item[0]
        perms = item[1]
        uidgid = item[2].split("/")
        uid = uidgid[0]
        gid = uidgid[1]
        if path != ".":

            #prepend the ppath so the paths match the actual install locations
            path = path.lstrip("./")
            path = ppath + path
            path = path.lstrip("./")

            t = (path, )
            row = c.execute('SELECT path_key from paths where path = ?', t).fetchone()
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

    display_status('Gathering information on installed packages')

    if os.path.exists(packagedb):
        try:
            os.remove(packagedb)
        except Exception, e:
            display_error("Could not remove out-of-date receipt database.")
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

    conn = sqlite3.connect(packagedb)
    c = conn.cursor()
    CreateTables(c)

    currentpkgindex = 0
    display_percent_done(0, pkgcount)

    if os.path.exists(receiptsdir):
        receiptlist = os.listdir(receiptsdir)
        for item in receiptlist:
            if stopRequested():
                c.close()
                conn.close()
                #our package db isn't valid, so we should delete it
                os.remove(packagedb)
                
                return False
                
            if item.endswith(".pkg"):
                receiptpath = os.path.join(receiptsdir, item)
                display_info("Importing %s..." % receiptpath)
                ImportPackage(receiptpath, c)
                currentpkgindex += 1
                display_percent_done(currentpkgindex, pkgcount)

    if os.path.exists(bomsdir):
        bomslist = os.listdir(bomsdir)
        for item in bomslist:
            if stopRequested():
                c.close()
                conn.close()
                #our package db isn't valid, so we should delete it
                os.remove(packagedb)
                
                return False
            
            if item.endswith(".bom"):
                bompath = os.path.join(bomsdir, item)
                display_info("Importing %s..." % bompath)
                ImportBom(bompath, c)
                currentpkgindex += 1
                display_percent_done(currentpkgindex, pkgcount)

    # in case we didn't quite get to 100% for some reason
    if currentpkgindex < pkgcount:
        display_percent_done(pkgcount, pkgcount)

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
    
    # check package names to make sure they're all in the database, build our list of pkg_keys
    pkgerror = False
    pkgkeyslist = []
    for pkg in pkgnames:
        t = (pkg, )
        pkg_key = c.execute('select pkg_key from pkgs where pkgname = ?', t).fetchone()
        if pkg_key is None:
            # try pkgid
            pkg_key = c.execute('select pkg_key from pkgs where pkgid = ?', t).fetchone()
        if pkg_key is None:
            display_error("%s not found in database." % pkg)
            pkgerror = True
        else:
            pkgkeyslist.append(pkg_key[0])
    if pkgerror:
        pkgkeyslist = []
    c.close
    conn.close
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
    in_selected_packages = "select distinct path_key from pkgs_paths where pkg_key in %s" % str(pkgkeys)
    
    # all the paths that are referred to by every package except the selected packages:
    not_in_other_packages = "select distinct path_key from pkgs_paths where pkg_key not in %s" % str(pkgkeys)
    
    # every path that is used by the selected packages and no other packages:
    combined_query = "select path from paths where (path_key in (%s) and path_key not in (%s))" % (in_selected_packages, not_in_other_packages)
    
    display_status('Determining which filesystem items to remove')
    if munkistatusoutput:
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
    display_status('Removing receipt info')
    display_percent_done(0,4)
    
    conn = sqlite3.connect(packagedb)
    c = conn.cursor()
    
    applepkgdb = '/Library/Receipts/db/a.receiptdb'
    if not noupdateapplepkgdb:
        aconn = sqlite3.connect(applepkgdb)
        ac = aconn.cursor()
    
    if not verbose:
        display_percent_done(1,4)
    
    for pkgkey in pkgkeylist:
        pkgid = ''
        t = (pkgkey, )
        row = c.execute('SELECT pkgname, pkgid from pkgs where pkg_key = ?', t).fetchone()
        if row:
            pkgname = row[0]
            pkgid = row[1]
            if pkgname.endswith('.pkg'):
                receiptpath = os.path.join('/Library/Receipts', pkgname)
            if pkgname.endswith('.bom'):
                receiptpath = os.path.join('/Library/Receipts/boms', pkgname)
            if os.path.exists(receiptpath):
                display_info("Removing %s..." % receiptpath)
                log("Removing %s..." % receiptpath)
                retcode = subprocess.call(["/bin/rm", "-rf", receiptpath])
        
        # remove pkg info from our database
        if verbose:
            print "Removing package data from internal database..."
        c.execute('DELETE FROM pkgs_paths where pkg_key = ?', t)
        c.execute('DELETE FROM pkgs where pkg_key = ?', t)
        
        # then remove pkg info from Apple's database unless option is passed
        if not noupdateapplepkgdb:
            if pkgid:
                t = (pkgid, )
                row = ac.execute('SELECT pkg_key FROM pkgs where pkgid = ?', t).fetchone()
                if row:
                    if verbose:
                        print "Removing package data from Apple package database..."
                    apple_pkg_key = row[0]
                    t = (apple_pkg_key, )
                    ac.execute('DELETE FROM pkgs where pkg_key = ?', t)
                    ac.execute('DELETE FROM pkgs_paths where pkg_key = ?', t)
                    ac.execute('DELETE FROM pkgs_groups where pkg_key = ?', t)
                    ac.execute('DELETE FROM acls where pkg_key = ?', t)
                    ac.execute('DELETE FROM taints where pkg_key = ?', t)
                    ac.execute('DELETE FROM sha1s where pkg_key = ?', t)
                    ac.execute('DELETE FROM oldpkgs where pkg_key = ?', t)
    
    display_percent_done(2,4)
    
    # now remove orphaned paths from paths table
    # first, Apple's database if option is passed
    if not noupdateapplepkgdb:
        display_info("Removing unused paths from Apple package database...")
        ac.execute('DELETE FROM paths where path_key not in (select distinct path_key from pkgs_paths)')
        aconn.commit()
        ac.close()
        aconn.close()
    
    display_percent_done(3,4)
    
    # we do our database last so its modtime is later than the modtime for the Apple DB...
    display_info("Removing unused paths from internal package database...")
    c.execute('DELETE FROM paths where path_key not in (select distinct path_key from pkgs_paths)')
    conn.commit()
    c.close()
    conn.close()
    
    display_percent_done(4,4)


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

def removeFilesystemItems(removalpaths, forcedeletebundles):
    """
    Attempts to remove all the paths in the array removalpaths
    """
    # we sort in reverse because we can delete from the bottom up,
    # clearing a directory before we try to remove the directory itself
    removalpaths.sort(reverse=True)
    
    display_status("Removing filesystem items")
    
    itemcount = len(removalpaths)
    itemindex = 0
    display_percent_done(itemindex, itemcount)
    
    for item in removalpaths:
        itemindex += 1
        pathtoremove = "/" + item
        # use os.path.lexists so broken links return true so we can remove them
        if os.path.lexists(pathtoremove):
            display_info("Removing: " + pathtoremove.encode("UTF-8"))
            log("Removing: " + pathtoremove.encode("UTF-8"))
            if (os.path.isdir(pathtoremove) and not os.path.islink(pathtoremove)):
                diritems = os.listdir(pathtoremove)
                if diritems == ['.DS_Store']:
                    # If there's only a .DS_Store file
                    # we'll consider it empty
                    ds_storepath = pathtoremove + "/.DS_Store"
                    retcode = subprocess.call(['/bin/rm', ds_storepath])
                    diritems = os.listdir(pathtoremove)
                if diritems == []:
                    # directory is empty
                    retcode = subprocess.call(['/bin/rmdir', pathtoremove])
                    if retcode:
                        display_error("ERROR: couldn't remove directory %s" % pathtoremove)
                else:
                    # the directory is marked for deletion but isn't empty.
                    # if so directed, if it's a bundle (like .app), we should
                    # remove it anyway - no use having a broken bundle hanging
                    # around
                    if (forcedeletebundles and isBundle(pathtoremove)):
                        retcode = subprocess.call(['/bin/rm', '-rf', pathtoremove])
                        if retcode:
                            display_error("ERROR: couldn't remove bundle %s" % pathtoremove)
                    else:
                        display_error("WARNING: Did not remove %s because it is not empty." % pathtoremove)
                        
            else:
                # not a directory, just unlink it
                # we're using rm instead of Python because I don't trust
                # handling of resource forks with Python
                retcode = subprocess.call(['/bin/rm', pathtoremove])
                if retcode:
                    display_error("ERROR: couldn't remove item %s" % pathtoremove)
                    
        display_percent_done(itemindex, itemcount)        


def removepackages(pkgnames, forcedeletebundles=False, listfiles=False,
                    rebuildpkgdb=False, noremovereceipts=False,
                    noupdateapplepkgdb=False, **kwargs):
    
    # we get the following arguments from the kwargs dictionary
    # so we can assign them to the globals without a name conflict
    global munkistatusoutput, verbose, verbose
    munkistatusoutput = kwargs.get('munkistatusoutput', False)
    verbose = kwargs.get('verbose', False)
    verbose = kwargs.get('verbose', '')
    
    if pkgnames == []:
        display_error("You must specify at least one package to remove!")
        return -2

    if not initDatabase(packagedb,rebuildpkgdb):
        display_error("Could not initialize receipt database.")
        return -3

    pkgkeyslist = getpkgkeys(pkgnames)
    if len(pkgkeyslist) == 0:
        return -4
    
    if stopRequested():
        return -128
    removalpaths = getpathstoremove(pkgkeyslist)
    if stopRequested():
        return -128

    if removalpaths:
        if listfiles:
            removalpaths.sort()
            for item in removalpaths:
                print "/" + item.encode("UTF-8")
        else:
            removeFilesystemItems(removalpaths, forcedeletebundles)
            if not noremovereceipts:
                removeReceipts(pkgkeyslist, noupdateapplepkgdb)
        if munkistatusoutput:
            display_status('Package removal complete.')
            time.sleep(2)

    else:
        display_status('Nothing to remove.')
        if munkistatusoutput:
            time.sleep(2)
           
    return 0


# some globals
packagedb = os.path.join(munkilib.ManagedInstallDir(), "b.receiptdb")
munkistatusoutput = False
verbose = False
logfile = ''


def main():
    # command-line options
    p = optparse.OptionParser()
    p.add_option('--forcedeletebundles', '-f', action='store_true',
                    help='Delete bundles even if they aren\'t empty.')
    p.add_option('--listfiles', '-l', action='store_true',
                    help='List the filesystem objects to be removed, but do not actually remove them.')
    p.add_option('--rebuildpkgdb', action='store_true',
                    help='Force a rebuild of the internal package database.')
    p.add_option('--noremovereceipts', action='store_true',
                    help='Do not remove receipts and boms from /Library/Receipts and update internal package database.')
    p.add_option('--noupdateapplepkgdb', action='store_true',
                    help='Do not update Apple\'s package database. If --noremovereceipts is also given, this is implied')
    p.add_option('--munkistatusoutput', '-m', action='store_true',
                    help='Output is formatted for use with MunkiStatus.')
    p.add_option('--verbose', '-v', action='store_true',
                    help='More verbose output.')
    p.add_option('--logfile', default='',
                    help="Path to a log file.")
    # Get our options and our package names
    options, pkgnames = p.parse_args()
    
    # check to see if we're root
    if os.geteuid() != 0:
        display_error("You must run this as root!")       
        exit(-1)
        
    retcode = removepackages(pkgnames, forcedeletebundles=options.forcedeletebundles, listfiles=options.listfiles, 
                    rebuildpkgdb=options.rebuildpkgdb, noremovereceipts=options.noremovereceipts,
                    noupdateapplepkgdb=options.noupdateapplepkgdb, munkistatusoutput=options.munkistatusoutput,
                    verbose=options.verbose, logfile=options.logfile)
    if munkistatusoutput:
        munkistatus.quit()
    exit(retcode)
    
    
if __name__ == '__main__':
	main()

  