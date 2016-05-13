#!/usr/bin/python
# encoding: utf-8
#
# Copyright 2009-2016 Greg Neagle.
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
installer.py
munki module to automatically install pkgs, mpkgs, and dmgs
(containing pkgs and mpkgs) from a defined folder.
"""

import datetime
import os
import pwd
import subprocess
import time
import stat

import adobeutils
import launchd
import munkicommon
import munkistatus
import powermgr
import profiles
import updatecheck
import FoundationPlist
from removepackages import removepackages

# PyLint cannot properly find names inside Cocoa libraries, so issues bogus
# No name 'Foo' in module 'Bar' warnings. Disable them.
# pylint: disable=E0611
from Foundation import NSDate
# pylint: enable=E0611

# lots of camelCase names
# pylint: disable=C0103

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
    munkicommon.display_debug1("Looking for bundle relocation info...")
    if os.path.isdir(pkgpath):
        # remove relocatable stuff
        tokendefinitions = os.path.join(
            pkgpath, "Contents/Resources/TokenDefinitions.plist")
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
                munkicommon.display_debug1("Removed IFPkgPathMappings")
            except FoundationPlist.NSPropertyListWriteException:
                pass


def install(pkgpath, choicesXMLpath=None, suppressBundleRelocation=False,
            environment=None):
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
        restartaction = pkginfo.get('RestartAction', 'None')
    if not packagename:
        packagename = os.path.basename(pkgpath)
    #munkicommon.display_status_major("Installing %s..." % packagename)
    munkicommon.log("Installing %s from %s" % (packagename,
                                               os.path.basename(pkgpath)))
    cmd = ['/usr/sbin/installer', '-query', 'RestartAction', '-pkg', pkgpath]
    if choicesXMLpath:
        cmd.extend(['-applyChoiceChangesXML', choicesXMLpath])
    proc = subprocess.Popen(cmd, shell=False, bufsize=1,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (output, dummy_err) = proc.communicate()
    restartaction = str(output).decode('UTF-8').rstrip("\n")
    if restartaction == "RequireRestart" or \
       restartaction == "RecommendRestart":
        munkicommon.display_status_minor(
            '%s requires a restart after installation.' % packagename)
        restartneeded = True

    # get the OS version; we need it later when processing installer's output,
    # which varies depending on OS version.
    os_version = munkicommon.getOsVersion()
    cmd = ['/usr/sbin/installer', '-verboseR', '-pkg', pkgpath, '-target', '/']
    if choicesXMLpath:
        cmd.extend(['-applyChoiceChangesXML', choicesXMLpath])

    # set up environment for installer
    env_vars = os.environ.copy()
    # get info for root
    userinfo = pwd.getpwuid(0)
    env_vars['USER'] = userinfo.pw_name
    env_vars['HOME'] = userinfo.pw_dir
    if environment:
        # Munki admin has specified custom installer environment
        for key in environment.keys():
            if key == 'USER' and environment[key] == 'CURRENT_CONSOLE_USER':
                # current console user (if there is one) 'owns' /dev/console
                userinfo = pwd.getpwuid(os.stat('/dev/console').st_uid)
                env_vars['USER'] = userinfo.pw_name
                env_vars['HOME'] = userinfo.pw_dir
            else:
                env_vars[key] = environment[key]
        munkicommon.display_debug1(
            'Using custom installer environment variables: %s', env_vars)

    # run installer as a launchd job
    try:
        job = launchd.Job(cmd, environment_vars=env_vars)
        job.start()
    except launchd.LaunchdJobException, err:
        munkicommon.display_error(
            'Error with launchd job (%s): %s', cmd, str(err))
        munkicommon.display_error('Can\'t run installer.')
        return (-3, False)

    timeout = 2 * 60 * 60
    inactive = 0
    last_output = None
    while True:
        installinfo = job.stdout.readline()
        if not installinfo:
            if job.returncode() is not None:
                break
            else:
                # no data, but we're still running
                inactive += 1
                if inactive >= timeout:
                    # no output for too long, kill this installer session
                    munkicommon.display_error(
                        "/usr/sbin/installer timeout after %d seconds"
                        % timeout)
                    job.stop()
                    break
                # sleep a bit before checking for more output
                time.sleep(1)
                continue

        # we got non-empty output, reset inactive timer
        inactive = 0

        # Don't bother parsing the stdout output if it hasn't changed since
        # the last loop iteration.
        if last_output == installinfo:
            continue
        last_output = installinfo

        installinfo = installinfo.decode('UTF-8')
        if installinfo.startswith("installer:"):
            # save all installer output in case there is
            # an error so we can dump it to the log
            installeroutput.append(installinfo)
            msg = installinfo[10:].rstrip("\n")
            if msg.startswith("PHASE:"):
                phase = msg[6:]
                if phase:
                    munkicommon.display_status_minor(phase)
            elif msg.startswith("STATUS:"):
                status = msg[7:]
                if status:
                    munkicommon.display_status_minor(status)
            elif msg.startswith("%"):
                percent = float(msg[1:])
                if os_version == '10.5':
                    # Leopard uses a float from 0 to 1
                    percent = int(percent * 100)
                if munkicommon.munkistatusoutput:
                    munkistatus.percent(percent)
                else:
                    munkicommon.display_status_minor(
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

    # installer exited
    retcode = job.returncode()
    if retcode != 0:
        # append stdout to our installer output
        installeroutput.extend(job.stderr.read().splitlines())
        munkicommon.display_status_minor(
            "Install of %s failed with return code %s" % (packagename, retcode))
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


def installall(dirpath, choicesXMLpath=None, suppressBundleRelocation=False,
               environment=None):
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
        if munkicommon.hasValidDiskImageExt(item):
            munkicommon.display_info("Mounting disk image %s" % item)
            mountpoints = munkicommon.mountdmg(itempath, use_shadow=True)
            if mountpoints == []:
                munkicommon.display_error("No filesystems mounted from %s",
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
                                                     suppressBundleRelocation,
                                                     environment)
                if needsrestart:
                    restartflag = True
                if retcode:
                    # ran into error; should unmount and stop.
                    munkicommon.unmountdmg(mountpoints[0])
                    return (retcode, restartflag)

            munkicommon.unmountdmg(mountpoints[0])

        if munkicommon.hasValidInstallerItemExt(item):
            (retcode, needsrestart) = install(
                itempath, choicesXMLpath, suppressBundleRelocation, environment)
            if needsrestart:
                restartflag = True
            if retcode:
                # ran into error; should stop.
                return (retcode, restartflag)

    return (retcode, restartflag)


def copyAppFromDMG(dmgpath):
    '''copies application from DMG to /Applications
    This type of installer_type is deprecated and should be
    replaced with the more generic copyFromDMG'''
    munkicommon.display_status_minor(
        'Mounting disk image %s' % os.path.basename(dmgpath))
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
            # make an itemlist we can pass to copyItemsFromMountpoint
            itemlist = []
            item = {}
            item['source_item'] = appname
            item['destination_path'] = "/Applications"
            itemlist.append(item)
            retcode = copyItemsFromMountpoint(mountpoint, itemlist)
            if retcode == 0:
                # let the user know we completed successfully
                munkicommon.display_status_minor(
                    "The software was successfully installed.")
        else:
            munkicommon.display_error(
                "No application found on %s" % os.path.basename(dmgpath))
            retcode = -2
        munkicommon.unmountdmg(mountpoint)
        return retcode
    else:
        munkicommon.display_error("No mountable filesystems on %s",
                                  os.path.basename(dmgpath))
        return -1


def copyItemsFromMountpoint(mountpoint, itemlist):
    '''copies items from the mountpoint to the startup disk
    Returns 0 if no issues; some error code otherwise.

    If the 'destination_item' key is provided, items will be copied
    as its value.'''
    for item in itemlist:

        # get itemname
        source_itemname = item.get("source_item")
        dest_itemname = item.get("destination_item")
        if not source_itemname:
            munkicommon.display_error("Missing name of item to copy!")
            return -1

        # check source path
        source_itempath = os.path.join(mountpoint, source_itemname)
        if not os.path.exists(source_itempath):
            munkicommon.display_error(
                "Source item %s does not exist!" % source_itemname)
            return -1

        # check destination path
        destpath = item.get('destination_path')
        if not destpath:
            destpath = item.get('destination_item')
            if destpath:
                # split it into path and name
                dest_itemname = os.path.basename(destpath)
                destpath = os.path.dirname(destpath)

        if not destpath:
            munkicommon.display_error("Missing destination path for item!")
            return -1

        if not os.path.exists(destpath):
            munkicommon.display_detail(
                "Destination path %s does not exist, will determine "
                "owner/permissions from parent" % destpath)
            parent_path = destpath
            new_paths = []

            # work our way back up to an existing path and build a list
            while not os.path.exists(parent_path):
                new_paths.insert(0, parent_path)
                parent_path = os.path.split(parent_path)[0]

            # stat the parent, get uid/gid/mode
            parent_stat = os.stat(parent_path)
            parent_uid, parent_gid = parent_stat.st_uid, parent_stat.st_gid
            parent_mode = stat.S_IMODE(parent_stat.st_mode)

            # make the new tree with the parent's mode
            try:
                os.makedirs(destpath, mode=parent_mode)
            except IOError:
                munkicommon.display_error(
                    "There was an IO error in creating the path %s!" % destpath)
                return -1
            except BaseException:
                munkicommon.display_error(
                    "There was an unknown error in creating the path %s!"
                    % destpath)
                return -1

            # chown each new dir
            for new_path in new_paths:
                os.chown(new_path, parent_uid, parent_gid)


        # setup full destination path using 'destination_item', if supplied
        if dest_itemname:
            full_destpath = os.path.join(
                destpath, os.path.basename(dest_itemname))
        else:
            full_destpath = os.path.join(
                destpath, os.path.basename(source_itemname))

        # remove item if it already exists
        if os.path.exists(full_destpath):
            retcode = subprocess.call(["/bin/rm", "-rf", full_destpath])
            if retcode:
                munkicommon.display_error(
                    "Error removing existing %s" % full_destpath)
                return retcode

        # all tests passed, OK to copy
        munkicommon.display_status_minor(
            "Copying %s to %s" % (source_itemname, full_destpath))
        retcode = subprocess.call(["/usr/bin/ditto", "--noqtn",
                                   source_itempath, full_destpath])
        if retcode:
            munkicommon.display_error(
                "Error copying %s to %s" % (source_itempath, full_destpath))
            return retcode

        # set owner
        user = item.get('user', 'root')
        munkicommon.display_detail(
            "Setting owner for '%s' to '%s'" % (full_destpath, user))
        retcode = subprocess.call(
            ['/usr/sbin/chown', '-R', user, full_destpath])
        if retcode:
            munkicommon.display_error(
                "Error setting owner for %s" % (full_destpath))
            return retcode

        # set group
        group = item.get('group', 'admin')
        munkicommon.display_detail(
            "Setting group for '%s' to '%s'" % (full_destpath, group))
        retcode = subprocess.call(
            ['/usr/bin/chgrp', '-R', group, full_destpath])
        if retcode:
            munkicommon.display_error(
                "Error setting group for %s" % (full_destpath))
            return retcode

        # set mode
        mode = item.get('mode', 'o-w')
        munkicommon.display_detail(
            "Setting mode for '%s' to '%s'" % (full_destpath, mode))
        retcode = subprocess.call(['/bin/chmod', '-R', mode, full_destpath])
        if retcode:
            munkicommon.display_error(
                "Error setting mode for %s" % (full_destpath))
            return retcode

    # all items copied successfully!
    return 0


def copyFromDMG(dmgpath, itemlist):
    '''copies items from DMG to local disk'''
    if not itemlist:
        munkicommon.display_error("No items to copy!")
        return -1

    munkicommon.display_status_minor(
        'Mounting disk image %s' % os.path.basename(dmgpath))
    mountpoints = munkicommon.mountdmg(dmgpath)
    if mountpoints:
        mountpoint = mountpoints[0]
        retcode = copyItemsFromMountpoint(mountpoint, itemlist)
        if retcode == 0:
            # let the user know we completed successfully
            munkicommon.display_status_minor(
                "The software was successfully installed.")
        munkicommon.unmountdmg(mountpoint)
        return retcode
    else:
        munkicommon.display_error(
            "No mountable filesystems on %s" % os.path.basename(dmgpath))
        return -1


def removeCopiedItems(itemlist):
    '''Removes filesystem items based on info in itemlist.
    These items were typically installed via DMG'''
    retcode = 0
    if not itemlist:
        munkicommon.display_error("Nothing to remove!")
        return -1

    for item in itemlist:
        if 'destination_item' in item:
            itemname = item.get("destination_item")
        else:
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
        path_to_remove = os.path.join(destpath, os.path.basename(itemname))
        if os.path.exists(path_to_remove):
            munkicommon.display_status_minor('Removing %s' % path_to_remove)
            retcode = subprocess.call(['/bin/rm', '-rf', path_to_remove])
            if retcode:
                munkicommon.display_error(
                    'Removal error for %s', path_to_remove)
                break
        else:
            # path_to_remove doesn't exist
            # note it, but not an error
            munkicommon.display_detail("Path %s doesn't exist.", path_to_remove)

    return retcode


def itemPrereqsInSkippedItems(item, skipped_items):
    '''Looks for item prerequisites (requires and update_for) in the list
    of skipped items. Returns a list of matches.'''

    # shortcut -- if we have no skipped items, just return an empty list
    # also reduces log noise in the common case
    if not skipped_items:
        return []

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
        munkicommon.display_debug1(
            'Adding skipped item: %s-%s',
            skipped_item['name'], normalized_version)
        skipped_item_dict[skipped_item['name']].append(normalized_version)

    # now check prereqs against the skipped items
    matched_prereqs = []
    for prereq in prerequisites:
        (name, version) = updatecheck.nameAndVersion(prereq)
        munkicommon.display_debug1(
            'Comparing %s-%s against skipped items', name, version)
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

        skipped_prereqs = itemPrereqsInSkippedItems(item, skipped_installs)
        if skipped_prereqs:
            # one or more prerequisite for this item was skipped or failed;
            # need to skip this item too
            skipped_installs.append(item)
            if only_unattended:
                format_str = ('Skipping unattended install of %s because these '
                              'prerequisites were skipped: %s')
            else:
                format_str = ('Skipping install of %s because these '
                              'prerequisites were not installed: %s')
            munkicommon.display_detail(
                format_str % (item['name'], ", ".join(skipped_prereqs)))
            continue

        if munkicommon.stopRequested():
            return restartflag, skipped_installs

        display_name = item.get('display_name') or item.get('name')
        version_to_install = item.get('version_to_install', '')

        retcode = 0
        if 'preinstall_script' in item:
            retcode = munkicommon.runEmbeddedScript('preinstall_script', item)

        if retcode == 0 and 'installer_item' in item:
            munkicommon.display_status_major(
                "Installing %s (%s of %s)"
                % (display_name, itemindex, len(installlist)))

            installer_type = item.get("installer_type", "")

            itempath = os.path.join(dirpath, item["installer_item"])
            if installer_type != "nopkg" and not os.path.exists(itempath):
                # can't install, so we should stop. Since later items might
                # depend on this one, we shouldn't continue
                munkicommon.display_error(
                    "Installer item %s was not found.", item["installer_item"])
                return restartflag, skipped_installs

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
                munkicommon.display_warning(
                    "install_type 'appdmg' is deprecated. Use 'copy_from_dmg'.")
                retcode = copyAppFromDMG(itempath)
            elif installer_type == 'profile':
                # profiles.install_profile returns True/False
                retcode = 0
                identifier = item.get('PayloadIdentifier')
                if not profiles.install_profile(itempath, identifier):
                    retcode = -1
            elif installer_type == "nopkg": # Packageless install
                if (item.get("RestartAction") == "RequireRestart" or
                        item.get("RestartAction") == "RecommendRestart"):
                    restartflag = True
            elif installer_type != "":
                # we've encountered an installer type
                # we don't know how to handle
                munkicommon.display_error(
                    "Unsupported install type: %s" % installer_type)
                retcode = -99
            else:
                # better be Apple installer package
                suppressBundleRelocation = item.get(
                    "suppress_bundle_relocation", False)
                munkicommon.display_debug1(
                    "suppress_bundle_relocation: %s", suppressBundleRelocation)
                if 'installer_choices_xml' in item:
                    choicesXMLfile = os.path.join(munkicommon.tmpdir(),
                                                  "choices.xml")
                    FoundationPlist.writePlist(item['installer_choices_xml'],
                                               choicesXMLfile)
                else:
                    choicesXMLfile = ''
                installer_environment = item.get('installer_environment')
                if munkicommon.hasValidDiskImageExt(itempath):
                    munkicommon.display_status_minor(
                        "Mounting disk image %s" % item["installer_item"])
                    mountWithShadow = suppressBundleRelocation
                    # we need to mount the diskimage as read/write to
                    # be able to modify the package to suppress bundle
                    # relocation
                    mountpoints = munkicommon.mountdmg(
                        itempath, use_shadow=mountWithShadow)
                    if mountpoints == []:
                        munkicommon.display_error("No filesystems mounted "
                                                  "from %s",
                                                  item["installer_item"])
                        return restartflag, skipped_installs
                    if munkicommon.stopRequested():
                        munkicommon.unmountdmg(mountpoints[0])
                        return restartflag, skipped_installs

                    retcode = -99 # in case we find nothing to install
                    needtorestart = False
                    if munkicommon.hasValidInstallerItemExt(
                            item.get('package_path', '')):
                        # admin has specified the relative path of the pkg
                        # on the DMG
                        # this is useful if there is more than one pkg on
                        # the DMG, or the actual pkg is not at the root
                        # of the DMG
                        fullpkgpath = os.path.join(
                            mountpoints[0], item['package_path'])
                        if os.path.exists(fullpkgpath):
                            (retcode, needtorestart) = install(
                                fullpkgpath, choicesXMLfile,
                                suppressBundleRelocation,
                                installer_environment)
                    else:
                        # no relative path to pkg on dmg, so just install all
                        # pkgs found at the root of the first mountpoint
                        # (hopefully there's only one)
                        (retcode, needtorestart) = installall(
                            mountpoints[0], choicesXMLfile,
                            suppressBundleRelocation, installer_environment)
                    if (needtorestart or
                            item.get("RestartAction") == "RequireRestart" or
                            item.get("RestartAction") == "RecommendRestart"):
                        restartflag = True
                    munkicommon.unmountdmg(mountpoints[0])
                elif (munkicommon.hasValidPackageExt(itempath) or
                      itempath.endswith(".dist")):
                    (retcode, needtorestart) = install(
                        itempath, choicesXMLfile, suppressBundleRelocation,
                        installer_environment)
                    if (needtorestart or
                            item.get("RestartAction") == "RequireRestart" or
                            item.get("RestartAction") == "RecommendRestart"):
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
            retcode = munkicommon.runEmbeddedScript(
                'postinstall_script', item)
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

        # if install was successful and this is a SelfService OnDemand install
        # remove the item from the SelfServeManifest's managed_installs
        if retcode == 0 and item.get('OnDemand'):
            removeItemFromSelfServeInstallList(item['name'])

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
            # add this failed install to the skipped_installs list
            # so that any item later in the list that requires this
            # item is skipped as well.
            skipped_installs.append(item)

        log_msg = message % (display_name, version_to_install, status)
        munkicommon.log(log_msg, "Install.log")

        # Calculate install duration; note, if a machine is put to sleep
        # during the install this time may be inaccurate.
        utc_now_complete = datetime.datetime.utcnow()
        duration_seconds = (utc_now_complete - utc_now).seconds

        download_speed = item.get('download_kbytes_per_sec', 0)
        install_result = {
            'display_name': display_name,
            'name': item['name'],
            'version': version_to_install,
            'applesus': applesus,
            'status': retcode,
            'time': NSDate.new(),
            'duration_seconds': duration_seconds,
            'download_kbytes_per_sec': download_speed,
            'unattended': only_unattended,
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

        # ensure package is not deleted from cache if installation
        # fails by checking retcode
        if not foundagain and retcode == 0:
            # now remove the item from the install cache
            # (if it's still there)
            itempath = os.path.join(dirpath, current_installer_item)
            if os.path.exists(itempath):
                if os.path.isdir(itempath):
                    retcode = subprocess.call(
                        ["/bin/rm", "-rf", itempath])
                else:
                    # flat pkg or dmg
                    retcode = subprocess.call(["/bin/rm", itempath])
                    if munkicommon.hasValidDiskImageExt(itempath):
                        shadowfile = os.path.join(itempath, ".shadow")
                        if os.path.exists(shadowfile):
                            retcode = subprocess.call(
                                ["/bin/rm", shadowfile])

    return (restartflag, skipped_installs)


def skippedItemsThatRequireThisItem(item, skipped_items):
    '''Looks for items in the skipped_items that require or are update_for
    the current item. Returns a list of matches.'''

    # shortcut -- if we have no skipped items, just return an empty list
    # also reduces log noise in the common case
    if not skipped_items:
        return []

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
            (prereq_name, dummy_version) = updatecheck.nameAndVersion(prereq)
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
                'Skipping removal of %s because these '
                'skipped items required it: %s'
                % (item['name'], ", ".join(dependent_skipped_items)))
            continue

        if munkicommon.stopRequested():
            return restartFlag, skipped_removals
        if not item.get('installed'):
            # not installed, so skip it (this shouldn't happen...)
            continue

        index += 1
        display_name = item.get('display_name') or item.get('name')
        munkicommon.display_status_major(
            "Removing %s (%s of %s)...", display_name, index, len(removallist))

        retcode = 0
        # run preuninstall_script if it exists
        if 'preuninstall_script' in item:
            retcode = munkicommon.runEmbeddedScript('preuninstall_script', item)

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
                                       "cancelled." % display_name)
                        else:
                            message = "Uninstall of %s failed." % display_name
                        munkicommon.display_error(message)
                    else:
                        munkicommon.log(
                            "Uninstall of %s was successful." % display_name)

            elif uninstallmethod.startswith("Adobe"):
                retcode = adobeutils.doAdobeRemoval(item)

            elif uninstallmethod == "remove_copied_items":
                retcode = removeCopiedItems(item.get('items_to_remove'))

            elif uninstallmethod == "remove_app":
                remove_app_info = item.get('remove_app_info', None)
                if remove_app_info:
                    path_to_remove = remove_app_info['path']
                    munkicommon.display_status_minor(
                        'Removing %s' % path_to_remove)
                    retcode = subprocess.call(
                        ["/bin/rm", "-rf", path_to_remove])
                    if retcode:
                        munkicommon.display_error(
                            "Removal error for %s", path_to_remove)
                else:
                    munkicommon.display_error(
                        "Application removal info missing from %s",
                        display_name)

            elif uninstallmethod == 'remove_profile':
                identifier = item.get('PayloadIdentifier')
                if identifier:
                    retcode = 0
                    if not profiles.remove_profile(identifier):
                        retcode = -1
                        munkicommon.display_error(
                            "Profile removal error for %s", identifier)
                else:
                    munkicommon.display_error(
                        "Profile removal info missing from %s", display_name)
            elif uninstallmethod == 'uninstall_script':
                retcode = munkicommon.runEmbeddedScript(
                    'uninstall_script', item)
                if (retcode == 0 and
                        item.get('RestartAction') == "RequireRestart"):
                    restartFlag = True

            elif os.path.exists(uninstallmethod) and \
                 os.access(uninstallmethod, os.X_OK):
                # it's a script or program to uninstall
                retcode = munkicommon.runScript(
                    display_name, uninstallmethod, 'uninstall script')
                if (retcode == 0 and
                        item.get('RestartAction') == "RequireRestart"):
                    restartFlag = True

            else:
                munkicommon.log("Uninstall of %s failed because "
                                "there was no valid uninstall "
                                "method." % display_name)
                retcode = -99

            if retcode == 0 and item.get('postuninstall_script'):
                retcode = munkicommon.runEmbeddedScript(
                    'postuninstall_script', item)
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
            success_msg = "Removal of %s: SUCCESSFUL" % display_name
            munkicommon.log(success_msg, "Install.log")
            removeItemFromSelfServeUninstallList(item['name'])
        else:
            failure_msg = "Removal of %s: " % display_name + \
                          " FAILED with return code: %s" % retcode
            munkicommon.log(failure_msg, "Install.log")
            # append failed removal to skipped_removals so dependencies
            # aren't removed yet.
            skipped_removals.append(item)
        removal_result = {
            'display_name': display_name,
            'name': item['name'],
            'status': retcode,
            'time': NSDate.new(),
            'unattended': only_unattended,
        }
        munkicommon.report['RemovalResults'].append(removal_result)

    return (restartFlag, skipped_removals)


def removeItemFromSelfServeInstallList(itemname):
    """Remove the given itemname from the self-serve manifest's
    managed_installs list"""
    removeItemFromSelfServeSection(itemname, 'managed_installs')


def removeItemFromSelfServeUninstallList(itemname):
    """Remove the given itemname from the self-serve manifest's
    managed_uninstalls list"""
    removeItemFromSelfServeSection(itemname, 'managed_uninstalls')


def removeItemFromSelfServeSection(itemname, section):
    """Remove the given itemname from the self-serve manifest's
    managed_uninstalls list"""
    munkicommon.display_debug1(
        "Removing %s from SelfSeveManifest's %s...", itemname, section)
    ManagedInstallDir = munkicommon.pref('ManagedInstallDir')
    selfservemanifest = os.path.join(
        ManagedInstallDir, "manifests", "SelfServeManifest")
    if not os.path.exists(selfservemanifest):
        # SelfServeManifest doesn't exist, bail
        munkicommon.display_debug1("%s doesn't exist.", selfservemanifest)
        return
    try:
        plist = FoundationPlist.readPlist(selfservemanifest)
    except FoundationPlist.FoundationPlistException, err:
        # SelfServeManifest is broken, bail
        munkicommon.display_debug1(
            "Error reading %s: %s", selfservemanifest, err)
        return
    # make sure the section is in the plist
    if section in plist:
        # filter out our item
        plist[section] = [
            item for item in plist[section] if item != itemname
        ]
        try:
            FoundationPlist.writePlist(plist, selfservemanifest)
        except FoundationPlist.FoundationPlistException, err:
            munkicommon.display_debug1(
                "Error writing %s: %s", selfservemanifest, err)


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
    # hold onto the assertionID so we can release it later
    no_idle_sleep_assertion_id = powermgr.assertNoIdleSleep()

    managedinstallbase = munkicommon.pref('ManagedInstallDir')
    installdir = os.path.join(managedinstallbase, 'Cache')

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
                            munkistatus.message(
                                "Installing %i items..." % len(installlist))
                        munkistatus.detail("")
                        # set indeterminate progress bar
                        munkistatus.percent(-1)
                    munkicommon.log("Processing installs")
                    (installs_need_restart, skipped_installs) = installWithInfo(
                        installdir, installlist,
                        only_unattended=only_unattended)
                    # if any installs were skipped record them for later
                    installinfo['managed_installs'] = skipped_installs

        # update optional_installs with new installation/removal status
        for removal in munkicommon.report.get('RemovalResults', []):
            matching_optional_installs = [
                item for item in installinfo.get('optional_installs', [])
                if item['name'] == removal['name']]
            if len(matching_optional_installs) == 1:
                if removal['status'] != 0:
                    matching_optional_installs[0]['removal_error'] = True
                    matching_optional_installs[0]['will_be_removed'] = False
                else:
                    matching_optional_installs[0]['installed'] = False
                    matching_optional_installs[0]['will_be_removed'] = False

        for install_item in munkicommon.report.get('InstallResults', []):
            matching_optional_installs = [
                item for item in installinfo.get('optional_installs', [])
                if item['name'] == install_item['name']
                and item['version_to_install'] == install_item['version']]
            if len(matching_optional_installs) == 1:
                if install_item['status'] != 0:
                    matching_optional_installs[0]['install_error'] = True
                    matching_optional_installs[0]['will_be_installed'] = False
                elif matching_optional_installs[0].get('OnDemand'):
                    matching_optional_installs[0]['installed'] = False
                    matching_optional_installs[0]['needs_update'] = False
                    matching_optional_installs[0]['will_be_installed'] = False
                else:
                    matching_optional_installs[0]['installed'] = True
                    matching_optional_installs[0]['needs_update'] = False
                    matching_optional_installs[0]['will_be_installed'] = False

        # write updated installinfo back to disk to reflect current state
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

    powermgr.removeNoIdleSleepAssertion(no_idle_sleep_assertion_id)

    return removals_need_restart or installs_need_restart
