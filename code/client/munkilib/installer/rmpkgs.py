# encoding: utf-8
#
# Copyright 2009-2023 Greg Neagle.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
installer.rmpkgs

Code to analyze installed packages and remove
files unique to the packages given. No attempt
is made to revert to older versions of a file when uninstalling;
only file removals are done.

"""
from __future__ import absolute_import, print_function

import os
import subprocess
import sqlite3

from .. import display
from .. import munkistatus
from .. import osutils
from .. import pkgutils
from .. import prefs
from .. import processes
from .. import FoundationPlist


#################################################################
# our package db schema -- a subset of Apple's schema in Leopard
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


def should_rebuild_db(pkgdbpath):
    """
    Checks to see if our internal package DB should be rebuilt.
    If anything in /Library/Receipts, /Library/Receipts/boms, or
    /Library/Receipts/db/a.receiptdb has a newer modtime than our
    database, we should rebuild.
    """
    def items_newer_than_pkgdb(directory, file_extensions):
        '''Return true if the directory or files inside the directory
        with the given file extensions are newer than the pkgdb'''
        if os.path.exists(directory):
            dir_modtime = os.stat(directory).st_mtime
            # was directory modified after packagedb?
            if dir_modtime > packagedb_modtime:
                return True
            for item in osutils.listdir(directory):
                if item.endswith(file_extensions):
                    filepath = os.path.join(directory, item)
                    file_modtime = os.stat(filepath).st_mtime
                    # was file modified after packagedb?
                    if file_modtime > packagedb_modtime:
                        return True
        return False

    if not os.path.exists(pkgdbpath):
        return True

    packagedb_modtime = os.stat(pkgdbpath).st_mtime

    if items_newer_than_pkgdb('/Library/Receipts', '.pkg'):
        return True
    if items_newer_than_pkgdb('/Library/Receipts/boms', '.bom'):
        return True
    if items_newer_than_pkgdb('/private/var/db/receipts', ('.bom', '.plist')):
        return True

    installhistory = '/Library/Receipts/InstallHistory.plist'
    if os.path.exists(installhistory):
        installhistory_modtime = os.stat(installhistory).st_mtime
        if packagedb_modtime < installhistory_modtime:
            return True

    # if we got this far, we don't need to update the db
    return False


def create_tables(curs):
    """
    Creates the tables needed for our internal package database.
    """
    curs.execute('''CREATE TABLE paths
                         (path_key INTEGER PRIMARY KEY AUTOINCREMENT,
                          path VARCHAR NOT NULL UNIQUE )''')
    curs.execute('''CREATE TABLE pkgs
                         (pkg_key INTEGER PRIMARY KEY AUTOINCREMENT,
                          timestamp INTEGER NOT NULL,
                          owner INTEGER NOT NULL,
                          pkgid VARCHAR NOT NULL,
                          vers VARCHAR NOT NULL,
                          ppath VARCHAR NOT NULL,
                          pkgname VARCHAR NOT NULL,
                          replaces INTEGER )''')
    curs.execute('''CREATE TABLE pkgs_paths
                         (pkg_key INTEGER NOT NULL,
                          path_key INTEGER NOT NULL,
                          uid INTEGER,
                          gid INTEGER,
                          perms INTEGER )''')


def find_bundle_receipt(pkgid):
    '''Finds a bundle receipt in /Library/Receipts based on packageid.
    Some packages write bundle receipts under /Library/Receipts even on
    Snow Leopard; we need to be able to find them so we can remove them.
    Returns a path.'''
    if not pkgid:
        return ''
    receiptsdir = "/Library/Receipts"
    if os.path.isdir(receiptsdir):
        for item in osutils.listdir(receiptsdir):
            itempath = os.path.join(receiptsdir, item)
            if item.endswith('.pkg') and os.path.isdir(itempath):
                info = pkgutils.getOnePackageInfo(itempath)
                if info.get('packageid') == pkgid:
                    return itempath

    #if we get here, not found
    return ''


def insert_bomvalues_into_pkgdb(bom_line, pkgkey, ppath, curs):
    '''Parses line from lsbom or pkgutil --files and inserts the paths into
    our pkgdb'''
    try:
        item = bom_line.rstrip("\n").split("\t")
        path = item[0]
        perms = item[1]
        uidgid = item[2].split("/")
        uid = uidgid[0]
        gid = uidgid[1]
    except IndexError:
        # we really only care about the path
        perms = "0000"
        uid = "0"
        gid = "0"

    try:
        if path != ".":
            # special case for MS Office 2008 installers
            if ppath == "tmp/com.microsoft.updater/office_location":
                ppath = "Applications"

            # prepend the ppath so the paths match the actual install locations
            path = path.lstrip("./")
            if ppath:
                path = ppath + "/" + path

            values_t = (path, )
            row = curs.execute(
                'SELECT path_key from paths where path = ?',
                values_t).fetchone()
            if not row:
                curs.execute(
                    'INSERT INTO paths (path) values (?)', values_t)
                pathkey = curs.lastrowid
            else:
                pathkey = row[0]

            values_t = (pkgkey, pathkey, uid, gid, perms)
            curs.execute(
                'INSERT INTO pkgs_paths (pkg_key, path_key, uid, gid, '
                'perms) values (?, ?, ?, ?, ?)', values_t)
    except sqlite3.DatabaseError:
        pass


def import_package(packagepath, curs):
    """
    Imports package data from the receipt at packagepath into
    our internal package database.
    """

    bompath = os.path.join(packagepath, 'Contents/Archive.bom')
    infopath = os.path.join(packagepath, 'Contents/Info.plist')
    pkgname = os.path.basename(packagepath)

    if not os.path.exists(packagepath):
        display.display_error("%s not found.", packagepath)
        return

    if not os.path.isdir(packagepath):
        # Every machine I've seen has a bogus BSD.pkg,
        # so we won't print a warning for that specific one.
        if pkgname != "BSD.pkg":
            display.display_warning(
                "%s is not a valid receipt. Skipping.", packagepath)
        return

    if not os.path.exists(bompath):
        # look in receipt's Resources directory
        bomname = os.path.splitext(pkgname)[0] + '.bom'
        bompath = os.path.join(
            packagepath, "Contents/Resources", bomname)
        if not os.path.exists(bompath):
            display.display_warning(
                "%s has no BOM file. Skipping.", packagepath)
            return

    if not os.path.exists(infopath):
        display.display_warning(
            "%s has no Info.plist. Skipping.", packagepath)
        return

    timestamp = os.stat(packagepath).st_mtime
    owner = 0
    plist = FoundationPlist.readPlist(infopath)
    # 'Bundle identifier' is a weird Casper Composer thing
    pkgid = plist.get('CFBundleIdentifier',
                      plist.get('Bundle identifier', pkgname))
    # 'Bundle versions string, short' is a weird Casper Composer thing
    vers = plist.get('CFBundleShortVersionString',
                     plist.get('Bundle versions string, short', '1.0'))
    ppath = plist.get('IFPkgRelocatedPath', '').lstrip('./').rstrip('/')

    values_t = (timestamp, owner, pkgid, vers, ppath, pkgname)
    curs.execute(
        '''INSERT INTO pkgs (timestamp, owner, pkgid, vers, ppath, pkgname)
           values (?, ?, ?, ?, ?, ?)''', values_t)
    pkgkey = curs.lastrowid

    proc = subprocess.Popen(
        ['/usr/bin/lsbom', bompath], shell=False, bufsize=-1,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    while True:
        line = proc.stdout.readline().decode('UTF-8')
        if not line and (proc.poll() != None):
            break
        insert_bomvalues_into_pkgdb(line, pkgkey, ppath, curs)


def import_bom(bompath, curs):
    """
    Imports package data into our internal package database
    using a combination of the bom file and data in Apple's
    package database into our internal package database.
    """
    # If we completely trusted the accuracy of Apple's database, we wouldn't
    # need the bom files, but in my environment at least, the bom files are
    # a better indicator of what flat packages have actually been installed
    # on the current machine.
    # We still need to consult Apple's package database
    # because the bom files are missing metadata about the package.

    pkgname = os.path.basename(bompath)

    timestamp = os.stat(bompath).st_mtime
    owner = 0
    pkgid = os.path.splitext(pkgname)[0]
    vers = "1.0"
    ppath = ""

    # try to get metadata from pkginfo db
    proc = subprocess.Popen(["/usr/sbin/pkgutil", "--pkg-info-plist", pkgid],
                            bufsize=-1, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    pliststr = proc.communicate()[0]
    if pliststr:
        plist = FoundationPlist.readPlistFromString(pliststr)
        if "install-location" in plist:
            ppath = plist["install-location"]
            ppath = ppath.lstrip('./').rstrip('/')
        if "pkg-version" in plist:
            vers = plist["pkg-version"]
        if "install-time" in plist:
            timestamp = plist["install-time"]

    values_t = (timestamp, owner, pkgid, vers, ppath, pkgname)
    curs.execute(
        '''INSERT INTO pkgs (timestamp, owner, pkgid, vers, ppath, pkgname)
           values (?, ?, ?, ?, ?, ?)''', values_t)
    pkgkey = curs.lastrowid

    cmd = ["/usr/bin/lsbom", bompath]
    proc = subprocess.Popen(cmd, shell=False, bufsize=-1,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    while True:
        line = proc.stdout.readline().decode('UTF-8')
        if not line and (proc.poll() != None):
            break
        insert_bomvalues_into_pkgdb(line, pkgkey, ppath, curs)

def import_from_pkgutil(pkgname, curs):
    """
    Imports package data from pkgutil into our internal package database.
    """

    timestamp = 0
    owner = 0
    pkgid = pkgname
    vers = "1.0"
    ppath = ""

    #get metadata from pkginfo db
    proc = subprocess.Popen(["/usr/sbin/pkgutil", "--pkg-info-plist", pkgid],
                            bufsize=-1, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    pliststr = proc.communicate()[0]
    if pliststr:
        plist = FoundationPlist.readPlistFromString(pliststr)
        if "pkg-version" in plist:
            vers = plist["pkg-version"]
        if "install-time" in plist:
            timestamp = plist["install-time"]
        if "install-location" in plist:
            ppath = plist["install-location"]
            ppath = ppath.lstrip('./').rstrip('/')
        else:
            # there _should_ be an install-location. If there's not, let's
            # check the old /Library/Receipts.
            # (Workaround for QuarkXPress 8.1 packages)
            receiptpath = find_bundle_receipt(pkgid)
            if receiptpath:
                infopath = os.path.join(receiptpath, 'Contents/Info.plist')
                if os.path.exists(infopath):
                    infopl = FoundationPlist.readPlist(infopath)
                    if "IFPkgRelocatedPath" in infopl:
                        ppath = infopl["IFPkgRelocatedPath"]
                        ppath = ppath.lstrip('./').rstrip('/')

    values_t = (timestamp, owner, pkgid, vers, ppath, pkgname)
    curs.execute(
        '''INSERT INTO pkgs (timestamp, owner, pkgid, vers, ppath, pkgname)
           values (?, ?, ?, ?, ?, ?)''', values_t)
    pkgkey = curs.lastrowid

    cmd = ["/usr/sbin/pkgutil", "--files", pkgid]
    proc = subprocess.Popen(cmd, shell=False, bufsize=-1,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    while True:
        line = proc.stdout.readline().decode('UTF-8')
        if not line and (proc.poll() != None):
            break
        insert_bomvalues_into_pkgdb(line, pkgkey, ppath, curs)


def init_database(forcerebuild=False):
    """
    Builds or rebuilds our internal package database.
    """
    def abort_init_database():
        '''What to do if user requests we stop'''
        curs.close()
        conn.close()
        #our package db isn't valid, so we should delete it
        os.remove(PACKAGEDB)
        return False

    if not should_rebuild_db(PACKAGEDB) and not forcerebuild:
        return True

    display.display_status_minor(
        'Gathering information on installed packages')

    if os.path.exists(PACKAGEDB):
        try:
            os.remove(PACKAGEDB)
        except (OSError, IOError):
            display.display_error(
                "Could not remove out-of-date receipt database.")
            return False

    receiptsdir = u'/Library/Receipts'
    receiptlist = []
    if os.path.exists(receiptsdir):
        receiptlist = [item for item in osutils.listdir(receiptsdir)
                       if item.endswith(u'.pkg')]

    bomsdir = u'/Library/Receipts/boms'
    bomslist = []
    if os.path.exists(bomsdir):
        bomslist = [item for item in osutils.listdir(bomsdir)
                    if item.endswith('.bom')]

    pkglist = []
    cmd = ['/usr/sbin/pkgutil', '--pkgs']
    proc = subprocess.Popen(cmd, shell=False, bufsize=-1,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    while True:
        line = proc.stdout.readline().decode('UTF-8')
        if not line and (proc.poll() != None):
            break

        pkglist.append(line.rstrip(u'\n'))

    pkgcount = len(receiptlist) + len(bomslist) + len(pkglist)
    conn = sqlite3.connect(PACKAGEDB)
    conn.text_factory = str
    curs = conn.cursor()
    create_tables(curs)

    currentpkgindex = 0
    display.display_percent_done(0, pkgcount)

    for item in receiptlist:
        if processes.stop_requested():
            return abort_init_database()

        receiptpath = os.path.join(receiptsdir, item)
        display.display_detail("Importing %s...", receiptpath)
        import_package(receiptpath, curs)
        currentpkgindex += 1
        display.display_percent_done(currentpkgindex, pkgcount)

    for item in bomslist:
        if processes.stop_requested():
            return abort_init_database()

        bompath = os.path.join(bomsdir, item)
        display.display_detail("Importing %s...", bompath)
        import_bom(bompath, curs)
        currentpkgindex += 1
        display.display_percent_done(currentpkgindex, pkgcount)

    for pkg in pkglist:
        if processes.stop_requested():
            return abort_init_database()

        display.display_detail("Importing %s...", pkg)
        import_from_pkgutil(pkg, curs)
        currentpkgindex += 1
        display.display_percent_done(currentpkgindex, pkgcount)

    # in case we didn't quite get to 100% for some reason
    display.display_percent_done(pkgcount, pkgcount)

    # commit and close the db when we're done.
    conn.commit()
    curs.close()
    conn.close()
    return True


def getpkgkeys(pkgnames):
    """
    Given a list of receipt names, bom file names, or package ids,
    gets a list of pkg_keys from the pkgs table in our database.
    """
    # open connection and cursor to our database
    conn = sqlite3.connect(PACKAGEDB)
    curs = conn.cursor()

    # check package names to make sure they're all in the database,
    # build our list of pkg_keys
    pkgerror = False
    pkgkeyslist = []
    for pkg in pkgnames:
        values_t = (pkg, )
        display.display_debug1(
            "select pkg_key from pkgs where pkgid = %s", pkg)
        pkg_keys = curs.execute(
            'select pkg_key from pkgs where pkgid = ?', values_t).fetchall()
        if not pkg_keys:
            # try pkgname
            display.display_debug1(
                "select pkg_key from pkgs where pkgname = %s", pkg)
            pkg_keys = curs.execute(
                'select pkg_key from pkgs where pkgname = ?',
                values_t).fetchall()
        if not pkg_keys:
            display.display_error("%s not found in database.", pkg)
            pkgerror = True
        else:
            for row in pkg_keys:
                # only want first column
                pkgkeyslist.append(row[0])
    if pkgerror:
        pkgkeyslist = []

    curs.close()
    conn.close()
    display.display_debug1("pkgkeys: %s", pkgkeyslist)
    return pkgkeyslist


def getpathstoremove(pkgkeylist):
    """
    Queries our database for paths to remove.
    """
    pkgkeys = tuple(pkgkeylist)

    # open connection and cursor to our database
    conn = sqlite3.connect(PACKAGEDB)
    curs = conn.cursor()

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

    display.display_status_minor(
        'Determining which filesystem items to remove')
    munkistatus.percent(-1)

    curs.execute(combined_query)
    results = curs.fetchall()
    curs.close()
    conn.close()

    removalpaths = []
    for item in results:
        removalpaths.append(item[0])

    return removalpaths


def remove_receipts(pkgkeylist, noupdateapplepkgdb):
    """
    Removes receipt data from /Library/Receipts,
    /Library/Receipts/boms, our internal package database,
    and optionally Apple's package database.
    """
    display.display_status_minor('Removing receipt info')
    display.display_percent_done(0, 4)

    os_version = osutils.getOsVersion(as_tuple=True)
    conn = sqlite3.connect(PACKAGEDB)
    curs = conn.cursor()

    display.display_percent_done(1, 4)

    for pkgkey in pkgkeylist:
        pkgid = ''
        pkgkey_t = (pkgkey, )
        row = curs.execute(
            'SELECT pkgname, pkgid from pkgs where pkg_key = ?',
            pkgkey_t).fetchone()
        if row:
            pkgname = row[0]
            pkgid = row[1]
            receiptpath = None
            if os_version <= (10, 5):
                if pkgname.endswith('.pkg'):
                    receiptpath = os.path.join('/Library/Receipts', pkgname)
                if pkgname.endswith('.bom'):
                    receiptpath = os.path.join(
                        '/Library/Receipts/boms', pkgname)
            else:
                # clean up /Library/Receipts in case there's stuff left there
                receiptpath = find_bundle_receipt(pkgid)

            if receiptpath and os.path.exists(receiptpath):
                display.display_detail("Removing %s...", receiptpath)
                dummy_retcode = subprocess.call(
                    ["/bin/rm", "-rf", receiptpath])

        # remove pkg info from our database
        display.display_detail(
            "Removing package data from internal database...")
        curs.execute('DELETE FROM pkgs_paths where pkg_key = ?', pkgkey_t)
        curs.execute('DELETE FROM pkgs where pkg_key = ?', pkgkey_t)

        # then remove pkg info from Apple's database unless option is passed
        if not noupdateapplepkgdb and pkgid:
            cmd = ['/usr/sbin/pkgutil', '--forget', pkgid]
            proc = subprocess.Popen(cmd, bufsize=-1,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)
            output = proc.communicate()[0].decode('UTF-8')
            if output:
                display.display_detail(output.rstrip('\n'))

    display.display_percent_done(2, 4)

    # now remove orphaned paths from paths table
    display.display_percent_done(3, 4)

    # we do our database last so its modtime is later than the modtime for the
    # Apple DB...
    display.display_detail(
        "Removing unused paths from internal package database...")
    curs.execute(
        '''DELETE FROM paths where path_key not in
           (select distinct path_key from pkgs_paths)''')
    conn.commit()
    curs.close()
    conn.close()

    display.display_percent_done(4, 4)


def is_bundle(pathname):
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
                         ".wdgt"]
    if os.path.isdir(pathname):
        basename = os.path.basename(pathname)
        extension = os.path.splitext(basename)[1]
        if extension in bundle_extensions:
            return True
    return False


def inside_bundle(pathname):
    '''Check the path to see if it's inside a bundle.'''
    while len(pathname) > 1:
        if is_bundle(pathname):
            return True
        else:
            # chop off last item in path
            pathname = os.path.dirname(pathname)
    #if we get here, we didn't find a bundle path
    return False


def remove_filesystem_items(removalpaths, forcedeletebundles):
    """
    Attempts to remove all the paths in the array removalpaths
    """
    # we sort in reverse because we can delete from the bottom up,
    # clearing a directory before we try to remove the directory itself
    removalpaths.sort(reverse=True)
    removalerrors = ""
    removalcount = len(removalpaths)
    display.display_status_minor(
        'Removing %s filesystem items' % removalcount)

    itemcount = len(removalpaths)
    itemindex = 0
    display.display_percent_done(itemindex, itemcount)

    for item in removalpaths:
        itemindex += 1
        pathtoremove = "/" + item
        # use os.path.lexists so broken links return true
        # so we can remove them
        if os.path.lexists(pathtoremove):
            display.display_detail("Removing: " + pathtoremove)
            if (os.path.isdir(pathtoremove) and
                    not os.path.islink(pathtoremove)):
                diritems = osutils.listdir(pathtoremove)
                if diritems == ['.DS_Store']:
                    # If there's only a .DS_Store file
                    # we'll consider it empty
                    ds_storepath = pathtoremove + "/.DS_Store"
                    try:
                        os.remove(ds_storepath)
                    except (OSError, IOError):
                        pass
                    diritems = osutils.listdir(pathtoremove)
                if diritems == []:
                    # directory is empty
                    try:
                        os.rmdir(pathtoremove)
                    except (OSError, IOError) as err:
                        msg = "Couldn't remove directory %s - %s" % (
                            pathtoremove, err)
                        display.display_error(msg)
                        removalerrors = removalerrors + "\n" + msg
                else:
                    # the directory is marked for deletion but isn't empty.
                    # if so directed, if it's a bundle (like .app), we should
                    # remove it anyway - no use having a broken bundle hanging
                    # around
                    if forcedeletebundles and is_bundle(pathtoremove):
                        display.display_warning(
                            "Removing non-empty bundle: %s", pathtoremove)
                        retcode = subprocess.call(['/bin/rm', '-r',
                                                   pathtoremove])
                        if retcode:
                            msg = "Couldn't remove bundle %s" % pathtoremove
                            display.display_error(msg)
                            removalerrors = removalerrors + "\n" + msg
                    else:
                        # if this path is inside a bundle, and we've been
                        # directed to force remove bundles,
                        # we don't need to warn because it's going to be
                        # removed with the bundle.
                        # Otherwise, we should warn about non-empty
                        # directories.
                        if not inside_bundle(pathtoremove) or \
                           not forcedeletebundles:
                            msg = \
                              "Did not remove %s because it is not empty." % \
                               pathtoremove
                            display.display_error(msg)
                            removalerrors = removalerrors + "\n" + msg

            else:
                # not a directory, just unlink it
                try:
                    os.remove(pathtoremove)
                except (OSError, IOError) as err:
                    msg = "Couldn't remove item %s: %s" % (pathtoremove, err)
                    display.display_error(msg)
                    removalerrors = removalerrors + "\n" + msg

        display.display_percent_done(itemindex, itemcount)

    if removalerrors:
        display.display_info(
            "---------------------------------------------------")
        display.display_info(
            "There were problems removing some filesystem items.")
        display.display_info(
            "---------------------------------------------------")
        display.display_info(removalerrors)


def removepackages(pkgnames, forcedeletebundles=False, listfiles=False,
                   rebuildpkgdb=False, noremovereceipts=False,
                   noupdateapplepkgdb=False):
    """
    Our main function, called by installer.py to remove items based on
    receipt info.
    """
    if pkgnames == []:
        display.display_error(
            "You must specify at least one package to remove!")
        return -2

    if not init_database(forcerebuild=rebuildpkgdb):
        display.display_error("Could not initialize receipt database.")
        return -3

    pkgkeyslist = getpkgkeys(pkgnames)
    if not pkgkeyslist:
        return -4

    if processes.stop_requested():
        return -128
    removalpaths = getpathstoremove(pkgkeyslist)
    if processes.stop_requested():
        return -128

    if removalpaths:
        if listfiles:
            removalpaths.sort()
            for item in removalpaths:
                print("/%s" % item)
        else:
            munkistatus.disableStopButton()
            remove_filesystem_items(removalpaths, forcedeletebundles)
    else:
        display.display_status_minor('Nothing to remove.')

    if not listfiles:
        if not noremovereceipts:
            remove_receipts(pkgkeyslist, noupdateapplepkgdb)
        munkistatus.enableStopButton()
        display.display_status_minor('Package removal complete.')

    return 0


# some globals
PACKAGEDB = os.path.join(prefs.pref('ManagedInstallDir'), "b.receiptdb")


if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
