#!/usr/bin/python
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
installer.py
munki module to automatically install pkgs, mpkgs, and dmgs
(containing pkgs and mpkgs) from a defined folder.
"""

import os
import subprocess
import sys

import adobeutils
import munkicommon
import munkistatus
import FoundationPlist
from removepackages import removepackages


# initialize our report fields
# we do this here because appleupdates.installAppleUpdates()
# calls installWithInfo()
munkicommon.report['InstallResults'] = []
munkicommon.report['RemovalResults'] = []

def removeBundleRelocationInfo(pkgpath):
    '''Attempts to remove any info in the package
    that would cause bundle relocation behavior.
    This makes bundles install or update in their
    default location.'''
    munkicommon.display_debug1(
            "Looking for bundle relocation info...")
    if os.path.isdir(pkgpath):
        # remove relocatable stuff
        tokendefinitions = os.path.join(pkgpath,
            "Contents/Resources/TokenDefinitions.plist")
        if os.path.exists(tokendefinitions):
            try:
                os.remove(tokendefinitions)
                munkicommon.display_debug1(
                        "Removed Contents/Resources/TokenDefinitions.plist")
            except OSError:
                pass

        plist = {}
        infoplist = os.path.join(pkgpath, "Contents/Info.plist")
        if os.path.exists(infoplist):
            try:
                plist = FoundationPlist.readPlist(infoplist)
            except FoundationPlist.NSPropertyListSerializationException:
                pass

        if 'IFPkgPathMappings' in plist:
            del plist['IFPkgPathMappings']
            try:
                FoundationPlist.writePlist(plist, infoplist)
                munkicommon.display_debug1(
                        "Removed IFPkgPathMappings")
            except FoundationPlist.NSPropertyListWriteException:
                pass


def install(pkgpath, choicesXMLpath=None, suppressBundleRelocation=False):
    """
    Uses the apple installer to install the package or metapackage
    at pkgpath. Prints status messages to STDOUT.
    Returns a tuple:
    the installer return code and restart needed as a boolean.
    """

    restartneeded = False
    installeroutput = []

    if os.path.islink(pkgpath):
        # resolve links before passing them to /usr/bin/installer
        pkgpath = os.path.realpath(pkgpath)

    if suppressBundleRelocation:
        removeBundleRelocationInfo(pkgpath)

    packagename = ''
    restartaction = 'None'
    pkginfo = munkicommon.getInstallerPkgInfo(pkgpath)
    if pkginfo:
        packagename = pkginfo.get('display_name')
        restartaction = pkginfo.get('RestartAction','None')
    if not packagename:
        packagename = os.path.basename(pkgpath)

    if munkicommon.munkistatusoutput:
        munkistatus.message("Installing %s..." % packagename)
        munkistatus.detail("")
        # clear indeterminate progress bar
        munkistatus.percent(0)

    munkicommon.log("Installing %s from %s" % (packagename,
                                               os.path.basename(pkgpath)))
    cmd = ['/usr/sbin/installer', '-query', 'RestartAction', '-pkg', pkgpath]
    if choicesXMLpath:
        cmd.extend(['-applyChoiceChangesXML', choicesXMLpath])
    proc = subprocess.Popen(cmd, shell=False, bufsize=1,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (output, unused_err) = proc.communicate()
    restartaction = str(output).decode('UTF-8').rstrip("\n")
    if restartaction == "RequireRestart" or \
       restartaction == "RecommendRestart":
        munkicommon.display_status("%s requires a restart after installation."
                                    % packagename)
        restartneeded = True

    # get the OS version; we need it later when processing installer's output,
    # which varies depending on OS version.
    osvers = int(os.uname()[2].split('.')[0])
    cmd = ['/usr/sbin/installer', '-verboseR', '-pkg', pkgpath,
                                  '-target', '/']
    if choicesXMLpath:
        cmd.extend(['-applyChoiceChangesXML', choicesXMLpath])
    proc = subprocess.Popen(cmd, shell=False, bufsize=1,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    while True:
        installinfo =  proc.stdout.readline().decode('UTF-8')
        if not installinfo and (proc.poll() != None):
            break
        if installinfo.startswith("installer:"):
            # save all installer output in case there is
            # an error so we can dump it to the log
            installeroutput.append(installinfo)
            msg = installinfo[10:].rstrip("\n")
            if msg.startswith("PHASE:"):
                phase = msg[6:]
                if phase:
                    if munkicommon.munkistatusoutput:
                        munkistatus.detail(phase)
                    else:
                        print phase.encode('UTF-8')
                        sys.stdout.flush()
            elif msg.startswith("STATUS:"):
                status = msg[7:]
                if status:
                    if munkicommon.munkistatusoutput:
                        munkistatus.detail(status)
                    else:
                        print status.encode('UTF-8')
                        sys.stdout.flush()
            elif msg.startswith("%"):
                percent = float(msg[1:])
                if osvers < 10:
                    # Leopard uses a float from 0 to 1
                    percent = int(percent * 100)
                if munkicommon.munkistatusoutput:
                    munkistatus.percent(percent)
                else:
                    print "%s percent complete" % percent
                    sys.stdout.flush()
            elif msg.startswith(" Error"):
                if munkicommon.munkistatusoutput:
                    munkistatus.detail(msg)
                    munkicommon.log(msg)
                else:
                    munkicommon.display_error(msg)
            elif msg.startswith(" Cannot install"):
                if munkicommon.munkistatusoutput:
                    munkistatus.detail(msg)
                    munkicommon.log(msg)
                else:
                    munkicommon.display_error(msg)
            else:
                munkicommon.log(msg)

    retcode = proc.poll()
    if retcode:
        munkicommon.display_status("Install of %s failed." % packagename)
        munkicommon.display_error("-"*78)
        for line in installeroutput:
            munkicommon.display_error(line.rstrip("\n"))
        munkicommon.display_error("-"*78)
        restartneeded = False
    else:
        munkicommon.log("Install of %s was successful." % packagename)
        if munkicommon.munkistatusoutput:
            munkistatus.percent(100)

    return (retcode, restartneeded)


def installall(dirpath, choicesXMLpath=None, suppressBundleRelocation=False):
    """
    Attempts to install all pkgs and mpkgs in a given directory.
    Will mount dmg files and install pkgs and mpkgs found at the
    root of any mountpoints.
    """
    retcode = 0
    restartflag = False
    installitems = os.listdir(dirpath)
    for item in installitems:
        if munkicommon.stopRequested():
            return (retcode, restartflag)
        itempath = os.path.join(dirpath, item)
        if item.endswith(".dmg"):
            munkicommon.display_info("Mounting disk image %s" % item)
            mountpoints = munkicommon.mountdmg(itempath, use_shadow=True)
            if mountpoints == []:
                munkicommon.display_error("No filesystems mounted from %s" %
                                           item)
                return (retcode, restartflag)
            if munkicommon.stopRequested():
                munkicommon.unmountdmg(mountpoints[0])
                return (retcode, restartflag)
            for mountpoint in mountpoints:
                # install all the pkgs and mpkgs at the root
                # of the mountpoint -- call us recursively!
                (retcode, needsrestart) = installall(mountpoint,
                                                     choicesXMLpath,
                                                     suppressBundleRelocation)
                if needsrestart:
                    restartflag = True
                if retcode:
                    # ran into error; should unmount and stop.
                    munkicommon.unmountdmg(mountpoints[0])
                    return (retcode, restartflag)

            munkicommon.unmountdmg(mountpoints[0])

        if (item.endswith(".pkg") or item.endswith(".mpkg")):
            (retcode, needsrestart) = install(itempath, choicesXMLpath,
                                                suppressBundleRelocation)
            if needsrestart:
                restartflag = True
            if retcode:
                # ran into error; should stop.
                return (retcode, restartflag)

    return (retcode, restartflag)


def copyAppFromDMG(dmgpath):
    '''copies application from DMG to /Applications'''
    munkicommon.display_status("Mounting disk image %s" %
                                os.path.basename(dmgpath))
    mountpoints = munkicommon.mountdmg(dmgpath)
    if mountpoints:
        retcode = 0
        appname = None
        mountpoint = mountpoints[0]
        # find an app at the root level, copy it to /Applications
        for item in os.listdir(mountpoint):
            itempath = os.path.join(mountpoint, item)
            if munkicommon.isApplication(itempath):
                appname = item
                break

        if appname:
            destpath = os.path.join("/Applications", appname)
            if os.path.exists(destpath):
                retcode = subprocess.call(["/bin/rm", "-r", destpath])
                if retcode:
                    munkicommon.display_error("Error removing existing "
                                              "%s" % destpath)
            if retcode == 0:
                munkicommon.display_status(
                            "Copying %s to Applications folder" % appname)
                retcode = subprocess.call(["/bin/cp", "-R",
                                            itempath, destpath])
                if retcode:
                    munkicommon.display_error("Error copying %s to %s" %
                                                (itempath, destpath))
            if retcode == 0:
                # remove com.apple.quarantine attribute from copied app
                cmd = ["/usr/bin/xattr", destpath]
                proc = subprocess.Popen(cmd, shell=False, bufsize=1,
                                        stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE)
                (out, unused_err) = proc.communicate()
                if out:
                    xattrs = str(out).splitlines()
                    if "com.apple.quarantine" in xattrs:
                        unused_result = subprocess.call(
                                            ["/usr/bin/xattr", "-d",
                                             "com.apple.quarantine",
                                              destpath])
                # let the user know we completed successfully
                munkicommon.display_status(
                                "The software was successfully installed.")
        munkicommon.unmountdmg(mountpoint)
        if not appname:
            munkicommon.display_error("No application found on %s" %
                                        os.path.basename(dmgpath))
            retcode = -2

        return retcode
    else:
        munkicommon.display_error("No mountable filesystems on %s" %
                                    os.path.basename(dmgpath))
        return -1


def copyFromDMG(dmgpath, itemlist):
    '''copies items from DMG to local disk'''
    if not itemlist:
        munkicommon.display_error("No items to copy!")
        return -1

    munkicommon.display_status("Mounting disk image %s" %
                                os.path.basename(dmgpath))
    mountpoints = munkicommon.mountdmg(dmgpath)
    if mountpoints:
        mountpoint = mountpoints[0]
        retcode = 0
        for item in itemlist:
            itemname = item.get("source_item")
            if not itemname:
                munkicommon.display_error("Missing name of item to copy!")
                retcode = -1

            if retcode == 0:
                itempath = os.path.join(mountpoint, itemname)
                if os.path.exists(itempath):
                    destpath = item.get("destination_path")
                    if os.path.exists(destpath):
                        # remove item if it already exists
                        olditem = os.path.join(destpath, itemname)
                        if os.path.exists(olditem):
                            retcode = subprocess.call(
                                                ["/bin/rm", "-rf", olditem])
                            if retcode:
                                munkicommon.display_error(
                                    "Error removing existing %s" % olditem)
                    else:
                        munkicommon.display_error(
                            "Destination path %s does not exist!" % destpath)
                        retcode = -1
                else:
                    munkicommon.display_error(
                        "Source item %s does not exist!" % itemname)
                    retcode = -1

            if retcode == 0:
                munkicommon.display_status(
                    "Copying %s to %s" % (itemname, destpath))
                retcode = subprocess.call(["/bin/cp", "-R",
                                            itempath, destpath])
                if retcode:
                    munkicommon.display_error(
                        "Error copying %s to %s" %
                                            (itempath, destpath))

            destitem = os.path.join(destpath, itemname)
            if (retcode == 0) and ('user' in item):
                munkicommon.display_detail(
                                        "Setting owner for '%s' to '%s'" %
                                                    (destitem, item['user']))
                cmd = ['/usr/sbin/chown', '-R', item['user'], destitem]
                retcode = subprocess.call(cmd)
                if retcode:
                    munkicommon.display_error("Error setting owner for %s" %
                                                (destitem))

            if (retcode == 0) and ('group' in item):
                munkicommon.display_detail(
                                        "Setting group for '%s' to '%s'" %
                                                    (destitem, item['group']))
                cmd = ['/usr/bin/chgrp', '-R', item['group'], destitem]
                retcode = subprocess.call(cmd)
                if retcode:
                    munkicommon.display_error("Error setting group for %s" %
                                                (destitem))

            if (retcode == 0) and ('mode' in item):
                munkicommon.display_detail(
                                        "Setting mode for '%s' to '%s'" %
                                                    (destitem, item['mode']))
                cmd = ['/bin/chmod', '-R', item['mode'], destitem]
                retcode = subprocess.call(cmd)
                if retcode:
                    munkicommon.display_error("Error setting mode for %s" %
                                                (destitem))

            if retcode == 0:
                # remove com.apple.quarantine attribute from copied item
                cmd = ["/usr/bin/xattr", destitem]
                proc = subprocess.Popen(cmd, shell=False, bufsize=1,
                                     stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE)
                (out, unused_err) = proc.communicate()
                if out:
                    xattrs = str(out).splitlines()
                    if "com.apple.quarantine" in xattrs:
                        unused_result = subprocess.call(
                                                ["/usr/bin/xattr", "-d",
                                                 "com.apple.quarantine",
                                                 destitem])

            if retcode:
                # we encountered an error on this iteration;
                # should not continue.
                break

        if retcode == 0:
            # let the user know we completed successfully
            munkicommon.display_status(
                                "The software was successfully installed.")
        munkicommon.unmountdmg(mountpoint)
        return retcode
    else:
        munkicommon.display_error("No mountable filesystems on %s" %
                                    os.path.basename(dmgpath))
        return -1


def removeCopiedItems(itemlist):
    '''Removes filesystem items based on info in itemlist.
    These items were typically installed via DMG'''
    retcode = 0
    if not itemlist:
        munkicommon.display_error("Nothing to remove!")
        return -1

    for item in itemlist:
        itemname = item.get("source_item")
        if not itemname:
            munkicommon.display_error("Missing item name to remove.")
            retcode = -1
            break
        destpath = item.get("destination_path")
        if not destpath:
            munkicommon.display_error("Missing path for item to remove.")
            retcode = -1
            break
        path_to_remove = os.path.join(destpath, itemname)
        if os.path.exists(path_to_remove):
            munkicommon.display_status("Removing %s" % path_to_remove)
            retcode = subprocess.call(["/bin/rm", "-rf", path_to_remove])
            if retcode:
                munkicommon.display_error("Removal error for %s" %
                                                            path_to_remove)
                break
        else:
            # path_to_remove doesn't exist
            # note it, but not an error
            munkicommon.display_detail("Path %s doesn't exist." %
                                                            path_to_remove)

    return retcode

def installWithInfo(dirpath, installlist):
    """
    Uses the installlist to install items in the
    correct order.
    """
    restartflag = False
    itemindex = 0
    for item in installlist:
        if munkicommon.stopRequested():
            return restartflag
        if "installer_item" in item:
            itemindex = itemindex + 1
            display_name = item.get('display_name') or item.get('name') or \
                           item.get('manifestitem')
            version_to_install = item.get('version_to_install','')
            if munkicommon.munkistatusoutput:
                munkistatus.message("Installing %s (%s of %s)..." %
                                    (display_name, itemindex,
                                     len(installlist)))
                munkistatus.detail("")
                munkistatus.percent(-1)
            else:
                munkicommon.display_status("Installing %s (%s of %s)" %
                                            (display_name, itemindex,
                                            len(installlist)))
            itempath = os.path.join(dirpath, item["installer_item"])
            if not os.path.exists(itempath):
                # can't install, so we should stop. Since later items might
                # depend on this one, we shouldn't continue
                munkicommon.display_error("Installer item %s was not found." %
                                           item["installer_item"])
                return restartflag
            installer_type = item.get("installer_type","")
            if installer_type.startswith("Adobe"):
                retcode = adobeutils.doAdobeInstall(item)
                if retcode == 0:
                    if (item.get("RestartAction") == "RequireRestart" or
                        item.get("RestartAction") == "RecommendRestart"):
                        restartflag = True
                if retcode == 8:
                    # Adobe Setup says restart needed.
                    restartflag = True
                    retcode = 0
            elif installer_type == "copy_from_dmg":
                retcode = copyFromDMG(itempath, item.get('items_to_copy'))
                if retcode == 0:
                    if (item.get("RestartAction") == "RequireRestart" or
                        item.get("RestartAction") == "RecommendRestart"):
                        restartflag = True
            elif installer_type == "appdmg":
                retcode = copyAppFromDMG(itempath)
            elif installer_type != "":
                # we've encountered an installer type
                # we don't know how to handle
                munkicommon.log("Unsupported install type: %s" %
                                                            installer_type)
                retcode = -99
            else:
                # must be Apple installer package
                suppressBundleRelocation = item.get(
                                    "suppress_bundle_relocation", False)
                munkicommon.display_debug1("suppress_bundle_relocation: %s" %
                                                    suppressBundleRelocation )
                if 'installer_choices_xml' in item:
                    choicesXMLfile = os.path.join(munkicommon.tmpdir,
                                                  "choices.xml")
                    FoundationPlist.writePlist(item['installer_choices_xml'],
                                               choicesXMLfile)
                else:
                    choicesXMLfile = ''
                if itempath.endswith(".dmg"):
                    munkicommon.display_status("Mounting disk image %s" %
                                                item["installer_item"])
                    mountWithShadow = suppressBundleRelocation
                    # we need to mount the diskimage as read/write to
                    # be able to modify the package to suppress bundle
                    # relocation
                    mountpoints = munkicommon.mountdmg(itempath,
                                                use_shadow=mountWithShadow)
                    if mountpoints == []:
                        munkicommon.display_error("No filesystems mounted "
                                                  "from %s" %
                                                  item["installer_item"])
                        return restartflag
                    if munkicommon.stopRequested():
                        munkicommon.unmountdmg(mountpoints[0])
                        return restartflag
                    needtorestart = False
                    if item.get('package_path','').endswith('.pkg') or \
                       item.get('package_path','').endswith('.mpkg'):
                        # admin has specified the relative path of the pkg
                        # on the DMG
                        # this is useful if there is more than one pkg on
                        # the DMG, or the actual pkg is not at the root
                        # of the DMG
                        fullpkgpath = os.path.join(mountpoints[0],
                                                    item['package_path'])
                        if os.path.exists(fullpkgpath):
                            (retcode, needtorestart) = install(fullpkgpath,
                                                     choicesXMLfile,
                                                     suppressBundleRelocation)
                    else:
                        # no relative path to pkg on dmg, so just install all
                        # pkgs found at the root of the first mountpoint
                        # (hopefully there's only one)
                        (retcode, needtorestart) = installall(mountpoints[0],
                                                              choicesXMLfile,
                                                    suppressBundleRelocation)
                    if needtorestart:
                        restartflag = True
                    munkicommon.unmountdmg(mountpoints[0])
                else:
                    itempath = munkicommon.findInstallerItem(itempath)
                    if (itempath.endswith(".pkg") or \
                            itempath.endswith(".mpkg")):
                        (retcode, needtorestart) = install(itempath,
                                                           choicesXMLfile,
                                                    suppressBundleRelocation)
                        if needtorestart:
                            restartflag = True
                    elif os.path.isdir(itempath):
                        # directory of packages,
                        # like what we get from Software Update
                        (retcode, needtorestart) = installall(itempath,
                                                              choicesXMLfile,
                                                    suppressBundleRelocation)
                        if needtorestart:
                            restartflag = True

            # record install success/failure
            if retcode == 0:
                success_msg = ("Install of %s-%s: SUCCESSFUL" %
                               (display_name, version_to_install))
                munkicommon.log(success_msg, "Install.log")
                munkicommon.report['InstallResults'].append(success_msg)
            else:
                failure_msg = ("Install of %s-%s: "
                               "FAILED with return code: %s" %
                               (display_name, version_to_install, retcode))
                munkicommon.log(failure_msg, "Install.log")
                munkicommon.report['InstallResults'].append(failure_msg)

            # check to see if this installer item is needed by any additional
            # items in installinfo
            # this might happen if there are multiple things being installed
            # with choicesXML files applied to a metapackage or
            # multiple packages being installed from a single DMG
            foundagain = False
            current_installer_item = item['installer_item']
            # are we at the end of the installlist?
            # (we already incremented itemindex for display
            # so with zero-based arrays itemindex now points to the item
            # after the current item)
            if itemindex < len(installlist):
                # nope, let's check the remaining items
                for lateritem in installlist[itemindex:]:
                    if 'installer_item' in lateritem:
                        if lateritem['installer_item'] == \
                                    current_installer_item:
                            foundagain = True
                            break

            if not foundagain:
                # now remove the item from the install cache
                # (if it's still there)
                itempath = os.path.join(dirpath, current_installer_item)
                if os.path.exists(itempath):
                    if os.path.isdir(itempath):
                        retcode = subprocess.call(
                                                ["/bin/rm", "-rf", itempath])
                    else:
                        retcode = subprocess.call(["/bin/rm", itempath])
                shadowfile = os.path.join(itempath,".shadow")
                if os.path.exists(shadowfile):
                    retcode = subprocess.call(["/bin/rm", shadowfile])

    return restartflag


def processRemovals(removallist):
    '''processes removals from the removal list'''
    restartFlag = False
    index = 0
    for item in removallist:
        if munkicommon.stopRequested():
            return restartFlag
        if not item.get('installed'):
            # not installed, so skip it
            continue

        index += 1
        name = item.get('display_name') or item.get('name') or \
               item.get('manifestitem')
        if munkicommon.munkistatusoutput:
            munkistatus.message("Removing %s (%s of %s)..." %
                                (name, index, len(removallist)))
            munkistatus.detail("")
            munkistatus.percent(-1)
        else:
            munkicommon.display_status("Removing %s (%s of %s)..." %
                                      (name, index, len(removallist)))

        if 'uninstall_method' in item:
            uninstallmethod = item['uninstall_method'].split(' ')
            if uninstallmethod[0] == "removepackages":
                if 'packages' in item:
                    if item.get('RestartAction') == "RequireRestart":
                        restartFlag = True
                    retcode = removepackages(item['packages'],
                                             forcedeletebundles=True)
                    if retcode:
                        if retcode == -128:
                            message = ("Uninstall of %s was "
                                       "cancelled." % name)
                        else:
                            message = "Uninstall of %s failed." % name
                        munkicommon.display_error(message)
                    else:
                        munkicommon.log("Uninstall of %s was "
                                        "successful." % name)

            elif uninstallmethod[0].startswith("Adobe"):
                retcode = adobeutils.doAdobeRemoval(item)

            elif uninstallmethod[0] == "remove_copied_items":
                retcode = removeCopiedItems(item.get('items_to_remove'))

            elif uninstallmethod[0] == "remove_app":
                remove_app_info = item.get('remove_app_info', None)
                if remove_app_info:
                    path_to_remove = remove_app_info['path']
                    munkicommon.display_status("Removing %s" %
                                                path_to_remove)
                    retcode = subprocess.call(["/bin/rm", "-rf",
                                                path_to_remove])
                    if retcode:
                        munkicommon.display_error("Removal error "
                                                  "for %s" %
                                                   path_to_remove)
                else:
                    munkicommon.display_error("Application removal "
                                              "info missing from %s" %
                                              name)

            elif os.path.exists(uninstallmethod[0]) and \
                 os.access(uninstallmethod[0], os.X_OK):
                # it's a script or program to uninstall
                if munkicommon.munkistatusoutput:
                    munkistatus.message("Running uninstall script "
                                        "for %s..." % name)
                    munkistatus.detail("")
                    # set indeterminate progress bar
                    munkistatus.percent(-1)

                if item.get('RestartAction') == "RequireRestart":
                    restartFlag = True

                cmd = uninstallmethod
                uninstalleroutput = []
                proc = subprocess.Popen(cmd, shell=False, bufsize=1,
                                     stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT)

                while (proc.poll() == None):
                    msg =  proc.stdout.readline().decode('UTF-8')
                    # save all uninstaller output in case there is
                    # an error so we can dump it to the log
                    uninstalleroutput.append(msg)
                    msg = msg.rstrip("\n")
                    if munkicommon.munkistatusoutput:
                        # do nothing with the output
                        pass
                    else:
                        print msg

                retcode = proc.poll()
                if retcode:
                    message = "Uninstall of %s failed." % name
                    print >> sys.stderr, message
                    munkicommon.log(message)
                    message = \
                   "-------------------------------------------------"
                    print >> sys.stderr, message
                    munkicommon.log(message)
                    for line in uninstalleroutput:
                        print >> sys.stderr, "     ", line.rstrip("\n")
                        munkicommon.log(line.rstrip("\n"))
                    message = \
                   "-------------------------------------------------"
                    print >> sys.stderr, message
                    munkicommon.log(message)
                else:
                    munkicommon.log("Uninstall of %s was "
                                    "successful." % name)

                if munkicommon.munkistatusoutput:
                    # clear indeterminate progress bar
                    munkistatus.percent(0)

            else:
                munkicommon.log("Uninstall of %s failed because "
                                "there was no valid uninstall "
                                "method." % name)
                retcode = -99

            # record removal success/failure
            if retcode == 0:
                success_msg = "Removal of %s: SUCCESSFUL" % name
                munkicommon.log(success_msg, "Install.log")
                munkicommon.report[
                                 'RemovalResults'].append(success_msg)
                removeItemFromSelfServeUninstallList(item.get('name'))
            else:
                failure_msg = "Removal of %s: " % name + \
                              " FAILED with return code: %s" % retcode
                munkicommon.log(failure_msg, "Install.log")
                munkicommon.report[
                                 'RemovalResults'].append(failure_msg)

    return restartFlag


def removeItemFromSelfServeUninstallList(itemname):
    """Remove the given itemname from the self-serve manifest's
    managed_uninstalls list"""
    ManagedInstallDir = munkicommon.pref('ManagedInstallDir')
    selfservemanifest = os.path.join(ManagedInstallDir, "manifests",
                                            "SelfServeManifest")
    if os.path.exists(selfservemanifest):
        # if item_name is in the managed_uninstalls in the self-serve
        # manifest, we should remove it from the list
        try:
            plist = FoundationPlist.readPlist(selfservemanifest)
        except FoundationPlist.FoundationPlistException:
            pass
        else:
            plist['managed_uninstalls'] = \
              [item for item in plist.get('managed_uninstalls',[])
                 if item != itemname]
            try:
                FoundationPlist.writePlist(plist, selfservemanifest)
            except FoundationPlist.FoundationPlistException:
                pass


def run(only_unattended=False):
    """Runs the install/removal session.

    Args:
      only_unattended: Boolean. If True, only do unattended installs/removals.
    """
    managedinstallbase = munkicommon.pref('ManagedInstallDir')
    installdir = os.path.join(managedinstallbase , 'Cache')

    removals_need_restart = installs_need_restart = False

    if only_unattended:
        munkicommon.log("### Beginning unattended installer session ###")
    else:
        munkicommon.log("### Beginning managed installer session ###")

    installinfo = os.path.join(managedinstallbase, 'InstallInfo.plist')
    if os.path.exists(installinfo):
        try:
            plist = FoundationPlist.readPlist(installinfo)
        except FoundationPlist.NSPropertyListSerializationException:
            print >> sys.stderr, "Invalid %s" % installinfo
            return -1

        # TODO(ogle): if unattended, remove installed items from
        # InstallInfo.plist but preserve the rest. Only rm if not unattended.

        # remove the install info file
        # it's no longer valid once we start running
        try:
            os.unlink(installinfo)
        except (OSError, IOError):
            munkicommon.display_warning(
                "Could not remove %s" % installinfo)

        if (munkicommon.munkistatusoutput and
            munkicommon.pref('SuppressStopButtonOnInstall')):
            munkistatus.hideStopButton()

        if "removals" in plist:
            # filter list to items that need to be removed
            if only_unattended:
                removallist = [item for item in plist['removals']
                               if item.get('installed') and \
                                  item.get('unattended', False) == True]
            else:
                removallist = [item for item in plist['removals']
                               if item.get('installed')]
            munkicommon.report['ItemsToRemove'] = removallist
            if removallist:
                if munkicommon.munkistatusoutput:
                    if len(removallist) == 1:
                        munkistatus.message("Removing 1 item...")
                    else:
                        munkistatus.message("Removing %i items..." %
                                            len(removallist))
                    munkistatus.detail("")
                    # set indeterminate progress bar
                    munkistatus.percent(-1)
                munkicommon.log("Processing removals")
                removals_need_restart = processRemovals(removallist)
        if "managed_installs" in plist:
            if not munkicommon.stopRequested():
                # filter list to items that need to be installed
                if only_unattended:
                    installlist = [item for item in plist['managed_installs']
                                   if item.get('installed') == False and \
                                      item.get('unattended', False) == True]
                else:
                    installlist = [item for item in plist['managed_installs']
                                   if item.get('installed') == False]
                munkicommon.report['ItemsToInstall'] = installlist
                if installlist:
                    if munkicommon.munkistatusoutput:
                        if len(installlist) == 1:
                            munkistatus.message("Installing 1 item...")
                        else:
                            munkistatus.message("Installing %i items..." %
                                                len(installlist))
                        munkistatus.detail("")
                        # set indeterminate progress bar
                        munkistatus.percent(-1)
                    munkicommon.log("Processing installs")
                    installs_need_restart = installWithInfo(installdir,
                                                            installlist)

    else:
        if not only_unattended:  # not need to log that no unattended found.
            munkicommon.log("No %s found." % installinfo)

    if only_unattended:
        munkicommon.log("###    End unattended installer session    ###")
    else:
        munkicommon.log("###    End managed installer session    ###")

    munkicommon.savereport()

    return (removals_need_restart or installs_need_restart)

