#!/usr/bin/python
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
installer.py
munki module to automatically install pkgs, mpkgs, and dmgs
(containing pkgs and mpkgs) from a defined folder.
"""

import datetime
import os
import signal
import subprocess
import time

import adobeutils
import munkicommon
import munkistatus
import updatecheck
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

    # run installer, setting the program id of the process (all child
    # processes will also use the same program id), making it easier to kill
    # not only hung installer but also any child processes it started.
    proc = munkicommon.Popen(cmd, shell=False, bufsize=-1,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            preexec_fn=lambda: os.setpgid(
                                os.getpid(), os.getpid()))
    timeout = 2 * 60 * 60

    while True:
        try:
            installinfo = proc.timed_readline(proc.stdout, timeout=timeout)
        except munkicommon.TimeoutError:
            munkicommon.display_error(
                "/usr/sbin/installer timeout after %d seconds" % timeout)
            signal.signal(signal.SIGCHLD, signal.SIG_IGN)  # reap immed.
            os.kill(-1 * proc.pid, signal.SIGTERM)
            signal.signal(signal.SIGCHLD, signal.SIG_DFL)
            break

        installinfo = installinfo.decode('UTF-8')
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
                    munkicommon.display_status(phase)
            elif msg.startswith("STATUS:"):
                status = msg[7:]
                if status:
                    munkicommon.display_status(status)
            elif msg.startswith("%"):
                percent = float(msg[1:])
                if osvers < 10:
                    # Leopard uses a float from 0 to 1
                    percent = int(percent * 100)
                if munkicommon.munkistatusoutput:
                    munkistatus.percent(percent)
                else:
                    munkicommon.display_status(
                        "%s percent complete" % percent)
            elif msg.startswith(" Error"):
                munkicommon.display_error(msg)
                if munkicommon.munkistatusoutput:
                    munkistatus.detail(msg)
            elif msg.startswith(" Cannot install"):
                munkicommon.display_error(msg)
                if munkicommon.munkistatusoutput:
                    munkistatus.detail(msg)
            else:
                munkicommon.log(msg)

    # try for a little bit to catch return code from exiting process...
    retcode = proc.poll()
    t = 0
    while retcode is None and t < 5:
        time.sleep(1)
        t += 1
        retcode = proc.poll()

    if retcode != 0:  # this could be <0, >0, or even None (never returned)
        munkicommon.display_status(
                "Install of %s failed with return code %s" % (
                    packagename, retcode))
        munkicommon.display_error("-"*78)
        for line in installeroutput:
            munkicommon.display_error(line.rstrip("\n"))
        munkicommon.display_error("-"*78)
        restartneeded = False
    elif retcode == 0:
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
    installitems = munkicommon.listdir(dirpath)
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
        for item in munkicommon.listdir(mountpoint):
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
                retcode = subprocess.call(["/bin/cp", "-pR",
                                            itempath, destpath])
                if retcode:
                    munkicommon.display_error(
                        "Error copying %s to %s" %
                                            (itempath, destpath))

            destitem = os.path.join(destpath, os.path.basename(itemname))

            if retcode == 0:
                # set owner
                user = item.get('user', 'root')
                munkicommon.display_detail(
                                        "Setting owner for '%s' to '%s'" %
                                                    (destitem, user))
                cmd = ['/usr/sbin/chown', '-R', user, destitem]
                retcode = subprocess.call(cmd)
                if retcode:
                    munkicommon.display_error("Error setting owner for %s" %
                                                (destitem))

            if retcode == 0:
                # set group
                group = item.get('group', 'admin')
                munkicommon.display_detail(
                                        "Setting group for '%s' to '%s'" %
                                                    (destitem, group))
                cmd = ['/usr/bin/chgrp', '-R', group, destitem]
                retcode = subprocess.call(cmd)
                if retcode:
                    munkicommon.display_error("Error setting group for %s" %
                                                (destitem))

            if retcode == 0:
                # set mode
                mode  = item.get('mode', 'o-w')
                munkicommon.display_detail(
                                        "Setting mode for '%s' to '%s'" %
                                                    (destitem, mode))
                cmd = ['/bin/chmod', '-R', mode, destitem]
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
            munkicommon.display_status('Removing %s' % path_to_remove)
            retcode = subprocess.call(['/bin/rm', '-rf', path_to_remove])
            if retcode:
                munkicommon.display_error('Removal error for %s' %
                                                            path_to_remove)
                break
        else:
            # path_to_remove doesn't exist
            # note it, but not an error
            munkicommon.display_detail("Path %s doesn't exist." %
                                                            path_to_remove)

    return retcode


def itemPrereqsInSkippedItems(item, skipped_items):
    '''Looks for item prerequisites (requires and update_for) in the list
    of skipped items. Returns a list of matches.'''
    munkicommon.display_debug1(
        'Checking for skipped prerequisites for %s-%s'
        % (item['name'], item.get('version_to_install')))

    # get list of prerequisites for this item
    prerequisites = item.get('requires', [])
    prerequisites.extend(item.get('update_for', []))
    if not prerequisites:
        munkicommon.display_debug1(
            '%s-%s has no prerequisites.'
            % (item['name'], item.get('version_to_install')))
        return []
    munkicommon.display_debug1('Prerequisites: %s' % ", ".join(prerequisites))

    # build a dictionary of names and versions of skipped items
    skipped_item_dict = {}
    for skipped_item in skipped_items:
        if skipped_item['name'] not in skipped_item_dict:
            skipped_item_dict[skipped_item['name']] = []
        normalized_version = updatecheck.trimVersionString(
                                skipped_item.get('version_to_install', '0.0'))
        munkicommon.display_debug1('Adding skipped item: %s-%s'
                                % (skipped_item['name'], normalized_version))
        skipped_item_dict[skipped_item['name']].append(normalized_version)

    # now check prereqs against the skipped items
    matched_prereqs = []
    for prereq in prerequisites:
        (name, version) = updatecheck.nameAndVersion(prereq)
        munkicommon.display_debug1(
            'Comparing %s-%s against skipped items' % (name, version))
        if name in skipped_item_dict:
            if version:
                version = updatecheck.trimVersionString(version)
                if version in skipped_item_dict[name]:
                    matched_prereqs.append(prereq)
            else:
                matched_prereqs.append(prereq)
    return matched_prereqs


def installWithInfo(
    dirpath, installlist, only_unattended=False, applesus=False):
    """
    Uses the installlist to install items in the
    correct order.
    """
    restartflag = False
    itemindex = 0
    skipped_installs = []
    for item in installlist:
        # Keep track of when this particular install started.
        utc_now = datetime.datetime.utcnow()
        itemindex = itemindex + 1
        if only_unattended:
            if not item.get('unattended_install'):
                skipped_installs.append(item)
                munkicommon.display_detail(
                    ('Skipping install of %s because it\'s not unattended.'
                     % item['name']))
                continue
            elif blockingApplicationsRunning(item):
                skipped_installs.append(item)
                munkicommon.display_detail(
                    'Skipping unattended install of %s because '
                    'blocking application(s) running.'
                    % item['name'])
                continue
            skipped_prereqs = itemPrereqsInSkippedItems(
                                                    item, skipped_installs)
            if skipped_prereqs:
                # need to skip this too
                skipped_installs.append(item)
                munkicommon.display_detail(
                    'Skipping unattended install of %s because these '
                    'prerequisites were skipped: %s'
                    % (item['name'], ", ".join(skipped_prereqs)))
                continue

        if munkicommon.stopRequested():
            return restartflag, skipped_installs

        retcode = 0
        if 'preinstall_script' in item:
            retcode = runEmbeddedScript('preinstall_script', item)

        if retcode == 0 and 'installer_item' in item:
            display_name = item.get('display_name') or item.get('name')
            version_to_install = item.get('version_to_install','')
            if munkicommon.munkistatusoutput:
                munkistatus.message("Installing %s (%s of %s)..." %
                                    (display_name, itemindex,
                                     len(installlist)))
                munkistatus.detail('')
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
                return restartflag, skipped_installs

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
                # better be Apple installer package
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
                        return restartflag, skipped_installs
                    if munkicommon.stopRequested():
                        munkicommon.unmountdmg(mountpoints[0])
                        return restartflag, skipped_installs

                    retcode = -99 # in case we find nothing to install
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
                elif (itempath.endswith(".pkg") or itempath.endswith(".mpkg") 
                      or itempath.endswith(".dist")):
                    (retcode, needtorestart) = install(itempath,    
                                                       choicesXMLfile, 
                                                     suppressBundleRelocation)
                    if needtorestart:
                        restartflag = True
                else:
                    # we didn't find anything we know how to install
                    munkicommon.log(
                        "Found nothing we know how to install in %s" 
                        % itempath)
                    retcode = -99

            if retcode == 0  and 'postinstall_script' in item:
                # only run embedded postinstall script if the install did not
                # return a failure code
                retcode = runEmbeddedScript('postinstall_script', item)
                if retcode:
                    # we won't consider postinstall script failures as fatal
                    # since the item has been installed via package/disk image
                    # but admin should be notified
                    munkicommon.display_warning(
                        'Postinstall script for %s returned %s'
                        % (item['name'], retcode))
                    # reset retcode to 0 so we will mark this install
                    # as successful
                    retcode = 0

            # record install success/failure
            if not 'InstallResults' in munkicommon.report:
                munkicommon.report['InstallResults'] = []

            if applesus:
                message = "Apple SUS install of %s-%s: %s"
            else:
                message = "Install of %s-%s: %s"

            if retcode == 0:
                status = "SUCCESSFUL"
            else:
                status = "FAILED with return code: %s" % retcode

            log_msg = message % (display_name, version_to_install, status)
            munkicommon.log(log_msg, "Install.log")

            # Calculate install duration; note, if a machine is put to sleep
            # during the install this time may be inaccurate.
            utc_now_complete = datetime.datetime.utcnow()
            duration_seconds = (utc_now_complete - utc_now).seconds

            install_result = {
                'name': display_name,
                'version': version_to_install,
                'applesus': applesus,
                'status': retcode,
                'duration_seconds': duration_seconds,
            }
            munkicommon.report['InstallResults'].append(install_result)

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
                    if (lateritem.get('installer_item') ==
                        current_installer_item):
                        foundagain = True
                        break

            # need to check skipped_installs as well
            if not foundagain:
                for skipped_item in skipped_installs:
                    if (skipped_item.get('installer_item') ==
                        current_installer_item):
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
                    elif itempath.endswith('MunkiGenerated.dist'):
                        # softwareupdate item handled by munki
                        # remove enclosing directory
                        retcode = subprocess.call(
                            ["/bin/rm", "-rf", os.path.dirname(itempath)])
                    else:
                        # flat pkg or dmg
                        retcode = subprocess.call(["/bin/rm", itempath])
                        if itempath.endswith('.dmg'):
                            shadowfile = os.path.join(itempath,".shadow")
                            if os.path.exists(shadowfile):
                                retcode = subprocess.call(
                                    ["/bin/rm", shadowfile])

    return (restartflag, skipped_installs)


def writefile(stringdata, path):
    '''Writes string data to path.
    Returns the path on success, empty string on failure.'''
    try:
        fileobject = open(path, mode='w', buffering=1)
        print >> fileobject, stringdata.encode('UTF-8')
        fileobject.close()
        return path
    except (OSError, IOError):
        munkicommon.display_error("Couldn't write %s" % stringdata)
        return ""


def runEmbeddedScript(scriptname, pkginfo_item):
    '''Runs a script embedded in the pkginfo.
    Returns the result code.'''

    # get the script text from the pkginfo
    script_text = pkginfo_item.get(scriptname)
    itemname =  pkginfo_item.get('name')
    if not script_text:
        munkicommon.display_error(
            'Missing script %s for %s' % (scriptname, itemname))
        return -1

    # write the script to a temp file
    scriptpath = os.path.join(munkicommon.tmpdir, scriptname)
    if writefile(script_text, scriptpath):
        cmd = ['/bin/chmod', '-R', 'o+x', scriptpath]
        retcode = subprocess.call(cmd)
        if retcode:
            munkicommon.display_error(
                'Error setting script mode in %s for %s'
                % (scriptname, itemname))
            return -1
    else:
        munkicommon.display_error(
            'Cannot write script %s for %s' % (scriptname, itemname))
        return -1

    # now run the script
    return runScript(itemname, scriptpath, scriptname)


def runScript(itemname, path, scriptname):
    '''Runs a script, Returns return code.'''
    if munkicommon.munkistatusoutput:
        munkistatus.message('Running %s for %s '
                            % (scriptname, itemname))
        munkistatus.detail("")
        # set indeterminate progress bar
        munkistatus.percent(-1)
    else:
        munkicommon.display_status('Running %s for %s '
                                   % (scriptname, itemname))

    scriptoutput = []
    proc = subprocess.Popen(path, shell=False, bufsize=1,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)

    while True:
        msg = proc.stdout.readline().decode('UTF-8')
        if not msg and (proc.poll() != None):
            break
        # save all script output in case there is
        # an error so we can dump it to the log
        scriptoutput.append(msg)
        msg = msg.rstrip("\n")
        munkicommon.display_info(msg)

    retcode = proc.poll()
    if retcode:
        munkicommon.display_error(
            'Running %s for %s failed.' % (scriptname, itemname))
        munkicommon.display_error("-"*78)
        for line in scriptoutput:
            munkicommon.display_error("\t%s" % line.rstrip("\n"))
        munkicommon.display_error("-"*78)
    else:
        munkicommon.log(
            'Running %s for %s was successful.' % (scriptname, itemname))

    if munkicommon.munkistatusoutput:
        # clear indeterminate progress bar
        munkistatus.percent(0)

    return retcode


def skippedItemsThatRequireThisItem(item, skipped_items):
    '''Looks for items in the skipped_items that require or are update_for
    the current item. Returns a list of matches.'''
    munkicommon.display_debug1(
        'Checking for skipped items that require %s' % item['name'])

    matched_skipped_items = []
    for skipped_item in skipped_items:
        # get list of prerequisites for this skipped_item
        prerequisites = skipped_item.get('requires', [])
        prerequisites.extend(skipped_item.get('update_for', []))
        munkicommon.display_debug1(
            '%s has these prerequisites: %s'
            % (skipped_item['name'], ', '.join(prerequisites)))
        for prereq in prerequisites:
            (prereq_name, unused_version) = updatecheck.nameAndVersion(prereq)
            if prereq_name == item['name']:
                matched_skipped_items.append(skipped_item['name'])
    return matched_skipped_items


def processRemovals(removallist, only_unattended=False):
    '''processes removals from the removal list'''
    restartFlag = False
    index = 0
    skipped_removals = []
    for item in removallist:
        if only_unattended:
            if not item.get('unattended_uninstall'):
                skipped_removals.append(item)
                munkicommon.display_detail(
                    ('Skipping removal of %s because it\'s not unattended.'
                     % item['name']))
                continue
            elif blockingApplicationsRunning(item):
                skipped_removals.append(item)
                munkicommon.display_detail(
                    'Skipping unattended removal of %s because '
                    'blocking application(s) running.' % item['name'])
                continue
            dependent_skipped_items = skippedItemsThatRequireThisItem(
                                                    item, skipped_removals)
            if dependent_skipped_items:
                # need to skip this too
                skipped_removals.append(item)
                munkicommon.display_detail(
                    'Skipping unattended removal of %s because these '
                    'skipped items required it: %s'
                    % (item['name'], ", ".join(dependent_skipped_items)))
                continue

        if munkicommon.stopRequested():
            return restartFlag
        if not item.get('installed'):
            # not installed, so skip it (this shouldn't happen...)
            continue

        index += 1
        name = item.get('display_name') or item.get('name')
        if munkicommon.munkistatusoutput:
            munkistatus.message("Removing %s (%s of %s)..." %
                                (name, index, len(removallist)))
            munkistatus.detail("")
            munkistatus.percent(-1)
        else:
            munkicommon.display_status("Removing %s (%s of %s)..." %
                                      (name, index, len(removallist)))
                                      
        retcode = 0
        # run preuninstall_script if it exists
        if 'preuninstall_script' in item:
            retcode = runEmbeddedScript('preuninstall_script', item)

        if retcode == 0 and 'uninstall_method' in item:
            uninstallmethod = item['uninstall_method']
            if uninstallmethod == "removepackages":
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

            elif uninstallmethod.startswith("Adobe"):
                retcode = adobeutils.doAdobeRemoval(item)

            elif uninstallmethod == "remove_copied_items":
                retcode = removeCopiedItems(item.get('items_to_remove'))

            elif uninstallmethod == "remove_app":
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

            elif uninstallmethod == 'uninstall_script':
                retcode = runEmbeddedScript('uninstall_script', item)
                if (retcode == 0 and
                    item.get('RestartAction') == "RequireRestart"):
                    restartFlag = True

            elif os.path.exists(uninstallmethod) and \
                 os.access(uninstallmethod, os.X_OK):
                # it's a script or program to uninstall
                retcode = runScript(
                    name, uninstallmethod, 'uninstall script')
                if (retcode == 0 and
                    item.get('RestartAction') == "RequireRestart"):
                    restartFlag = True

            else:
                munkicommon.log("Uninstall of %s failed because "
                                "there was no valid uninstall "
                                "method." % name)
                retcode = -99
                
            if retcode == 0 and item.get('postuninstall_script'):
                retcode = runEmbeddedScript('postuninstall_script', item)
                if retcode:
                    # we won't consider postuninstall script failures as fatal
                    # since the item has been uninstalled
                    # but admin should be notified
                    munkicommon.display_warning(
                        'Postuninstall script for %s returned %s'
                        % (item['name'], retcode))
                    # reset retcode to 0 so we will mark this uninstall
                    # as successful
                    retcode = 0

        # record removal success/failure
        if not 'RemovalResults' in munkicommon.report:
            munkicommon.report['RemovalResults'] = []
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
            munkicommon.report['RemovalResults'].append(failure_msg)

    return (restartFlag, skipped_removals)


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


def blockingApplicationsRunning(pkginfoitem):
    """Returns true if any application in the blocking_applications list
    is running or, if there is no blocking_applications list, if any
    application in the installs list is running."""

    if 'blocking_applications' in pkginfoitem:
        appnames = pkginfoitem['blocking_applications']
    else:
        # if no blocking_applications specified, get appnames
        # from 'installs' list if it exists
        appnames = [os.path.basename(item.get('path'))
                    for item in pkginfoitem.get('installs', [])
                    if item['type'] == 'application']

    munkicommon.display_debug1("Checking for %s" % appnames)
    running_apps = [appname for appname in appnames
                    if munkicommon.isAppRunning(appname)]
    if running_apps:
        munkicommon.display_detail(
            "Blocking apps for %s are running:" % pkginfoitem['name'])
        munkicommon.display_detail(
            "    %s" % running_apps)
        return True
    return False


def run(only_unattended=False):
    """Runs the install/removal session.

    Args:
      only_unattended: Boolean. If True, only do unattended_(un)install pkgs.
    """
    managedinstallbase = munkicommon.pref('ManagedInstallDir')
    installdir = os.path.join(managedinstallbase , 'Cache')

    removals_need_restart = installs_need_restart = False

    if only_unattended:
        munkicommon.log("### Beginning unattended installer session ###")
    else:
        munkicommon.log("### Beginning managed installer session ###")

    installinfopath = os.path.join(managedinstallbase, 'InstallInfo.plist')
    if os.path.exists(installinfopath):
        try:
            installinfo = FoundationPlist.readPlist(installinfopath)
        except FoundationPlist.NSPropertyListSerializationException:
            munkicommon.display_error("Invalid %s" % installinfopath)
            return -1

        # remove the install info file
        # it's no longer valid once we start running
        try:
            os.unlink(installinfopath)
        except (OSError, IOError):
            munkicommon.display_warning(
                "Could not remove %s" % installinfopath)

        if (munkicommon.munkistatusoutput and
            munkicommon.pref('SuppressStopButtonOnInstall')):
            munkistatus.hideStopButton()

        if "removals" in installinfo:
            # filter list to items that need to be removed
            removallist = [item for item in installinfo['removals']
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
                (removals_need_restart,
                 skipped_removals) = processRemovals(
                     removallist, only_unattended=only_unattended)
                # if any removals were skipped, record them for later
                installinfo['removals'] = skipped_removals

        if "managed_installs" in installinfo:
            if not munkicommon.stopRequested():
                # filter list to items that need to be installed
                installlist = [item for item in
                               installinfo['managed_installs']
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
                    (installs_need_restart,
                    skipped_installs) = installWithInfo(
                        installdir,
                        installlist,
                        only_unattended=only_unattended)
                    # if any installs were skipped record them for later
                    installinfo['managed_installs'] = skipped_installs

        if (only_unattended and
            installinfo['managed_installs'] or installinfo['removals']):
            # need to write the installinfo back out minus the stuff we
            # actually installed
            try:
                FoundationPlist.writePlist(installinfo, installinfopath)
            except FoundationPlist.NSPropertyListWriteException:
                # not fatal
                munkicommon.display_warning(
                    "Could not write to %s" % installinfopath)

    else:
        if not only_unattended:  # no need to log that no unattended pkgs found.
            munkicommon.log("No %s found." % installinfo)

    if only_unattended:
        munkicommon.log("###    End unattended installer session    ###")
    else:
        munkicommon.log("###    End managed installer session    ###")

    munkicommon.savereport()

    return (removals_need_restart or installs_need_restart)

