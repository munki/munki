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
installer.core

munki module to automatically install pkgs, mpkgs, and dmgs
(containing pkgs and mpkgs) from a defined folder.
"""
# This code is largely still compatible with Python 2, so for now, turn off
# Python 3 style warnings
# pylint: disable=consider-using-f-string
# pylint: disable=redundant-u-string-prefix
# pylint: disable=useless-object-inheritance

from __future__ import absolute_import, print_function

import datetime
import os
import subprocess

# PyLint cannot properly find names inside Cocoa libraries, so issues bogus
# No name 'Foo' in module 'Bar' warnings. Disable them.
# pylint: disable=E0611,E0401
from Foundation import NSDate
# pylint: enable=E0611,E0401

from . import dmg
from . import pkg
from . import rmpkgs

from .. import adobeutils
from .. import constants
from .. import display
from .. import dmgutils
from .. import munkistatus
from .. import munkilog
from .. import osinstaller
from .. import pkgutils
from .. import powermgr
from .. import prefs
from .. import processes
from .. import profiles
from .. import reports
from .. import scriptutils
from .. import FoundationPlist

from ..updatecheck import catalogs
from ..updatecheck import manifestutils

# initialize our report fields
# we do this here because appleupdates.installAppleUpdates()
# calls install_with_info()
reports.report['InstallResults'] = []
reports.report['RemovalResults'] = []


def remove_copied_items(itemlist):
    '''Removes filesystem items based on info in itemlist.
    These items were typically installed via DMG'''
    retcode = 0
    if not itemlist:
        display.display_error("Nothing to remove!")
        return -1

    for item in itemlist:
        if 'destination_item' in item:
            itemname = item.get("destination_item")
        else:
            itemname = item.get("source_item")
        if not itemname:
            display.display_error("Missing item name to remove.")
            retcode = -1
            break
        destpath = item.get("destination_path")
        if not destpath:
            display.display_error("Missing path for item to remove.")
            retcode = -1
            break
        path_to_remove = os.path.join(destpath, os.path.basename(itemname))
        if os.path.exists(path_to_remove):
            display.display_status_minor('Removing %s' % path_to_remove)
            retcode = subprocess.call(['/bin/rm', '-rf', path_to_remove])
            if retcode:
                display.display_error(
                    'Removal error for %s', path_to_remove)
                break
        else:
            # path_to_remove doesn't exist
            # note it, but not an error
            display.display_detail("Path %s doesn't exist.", path_to_remove)

    return retcode


def item_prereqs_in_skipped_items(item, skipped_items):
    '''Looks for item prerequisites (requires and update_for) in the list
    of skipped items. Returns a list of matches.'''

    # shortcut -- if we have no skipped items, just return an empty list
    # also reduces log noise in the common case
    if not skipped_items:
        return []

    display.display_debug1(
        'Checking for skipped prerequisites for %s-%s'
        % (item['name'], item.get('version_to_install')))

    # get list of prerequisites for this item
    prerequisites = item.get('requires', [])
    prerequisites.extend(item.get('update_for', []))
    if not prerequisites:
        display.display_debug1(
            '%s-%s has no prerequisites.'
            % (item['name'], item.get('version_to_install')))
        return []
    display.display_debug1('Prerequisites: %s' % ", ".join(prerequisites))

    # build a dictionary of names and versions of skipped items
    skipped_item_dict = {}
    for skipped_item in skipped_items:
        if skipped_item['name'] not in skipped_item_dict:
            skipped_item_dict[skipped_item['name']] = []
        normalized_version = pkgutils.trim_version_string(
            skipped_item.get('version_to_install', '0.0'))
        display.display_debug1(
            'Adding skipped item: %s-%s',
            skipped_item['name'], normalized_version)
        skipped_item_dict[skipped_item['name']].append(normalized_version)

    # now check prereqs against the skipped items
    matched_prereqs = []
    for prereq in prerequisites:
        (name, version) = catalogs.split_name_and_version(prereq)
        display.display_debug1(
            'Comparing %s-%s against skipped items', name, version)
        if name in skipped_item_dict:
            if version:
                version = pkgutils.trim_version_string(version)
                if version in skipped_item_dict[name]:
                    matched_prereqs.append(prereq)
            else:
                matched_prereqs.append(prereq)
    return matched_prereqs


def requires_restart(item):
    '''Returns boolean to indicate if the item needs a restart'''
    return (item.get("RestartAction") == "RequireRestart" or
            item.get("RestartAction") == "RecommendRestart")


def handle_apple_package_install(item, itempath):
    '''Process an Apple package for install. Returns retcode, needs_restart'''
    needs_restart = False
    suppress_bundle_relocation = item.get("suppress_bundle_relocation", False)
    display.display_debug1(
        "suppress_bundle_relocation: %s", suppress_bundle_relocation)
    if pkgutils.hasValidDiskImageExt(itempath):
        display.display_status_minor(
            "Mounting disk image %s" % os.path.basename(itempath))
        mount_with_shadow = suppress_bundle_relocation
        # we need to mount the diskimage as read/write to be able to
        # modify the package to suppress bundle relocation
        mountpoints = dmgutils.mountdmg(
            itempath, use_shadow=mount_with_shadow, skip_verification=True)
        if not mountpoints:
            display.display_error(
                "No filesystems mounted from %s", item["installer_item"])
            return (-99, False)
        if processes.stop_requested():
            dmgutils.unmountdmg(mountpoints[0])
            return (-99, False)

        retcode = -99 # in case we find nothing to install
        needtorestart = False
        if pkgutils.hasValidInstallerItemExt(item.get('package_path', '')):
            # admin has specified the relative path of the pkg on the DMG
            # this is useful if there is more than one pkg on the DMG,
            # or the actual pkg is not at the root of the DMG
            fullpkgpath = os.path.join(mountpoints[0], item['package_path'])
            if os.path.exists(fullpkgpath):
                (retcode, needtorestart) = pkg.install(fullpkgpath, item)
        else:
            # no relative path to pkg on dmg, so just install all
            # pkgs found at the root of the first mountpoint
            # (hopefully there's only one)
            (retcode, needtorestart) = pkg.installall(mountpoints[0], item)
        needs_restart = needtorestart or requires_restart(item)
        dmgutils.unmountdmg(mountpoints[0])
    elif pkgutils.hasValidPackageExt(itempath):
        (retcode, needtorestart) = pkg.install(itempath, item)
        needs_restart = needtorestart or requires_restart(item)
    else:
        # we didn't find anything we know how to install
        munkilog.log(
            "Found nothing we know how to install in %s" % itempath)
        retcode = -99

    return (retcode, needs_restart)


def install_with_info(
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

        if item.get('installer_type') == 'startosinstall':
            skipped_installs.append(item)
            display.display_debug1(
                'Skipping install of %s because it\'s a startosinstall item. '
                'Will install later.' % item['name'])
            continue
        if only_unattended:
            if not item.get('unattended_install'):
                skipped_installs.append(item)
                display.display_detail(
                    'Skipping install of %s because it\'s not unattended.'
                    % item['name'])
                continue
            if processes.blocking_applications_running(item):
                skipped_installs.append(item)
                display.display_detail(
                    'Skipping unattended install of %s because blocking '
                    'application(s) running.' % item['name'])
                continue

        skipped_prereqs = item_prereqs_in_skipped_items(item, skipped_installs)
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
            display.display_detail(
                format_str % (item['name'], ", ".join(skipped_prereqs)))
            continue

        if processes.stop_requested():
            return restartflag, skipped_installs

        display_name = item.get('display_name') or item.get('name')
        version_to_install = item.get('version_to_install', '')
        display.display_status_major(
            "Installing %s (%s of %s)"
            % (display_name, itemindex, len(installlist)))

        retcode = 0
        if 'preinstall_script' in item:
            retcode = scriptutils.run_embedded_script('preinstall_script', item)

        if retcode == 0 and 'installer_item' in item:
            installer_type = item.get("installer_type", "")

            itempath = os.path.join(dirpath, item["installer_item"])
            if installer_type != "nopkg" and not os.path.exists(itempath):
                # can't install, so we should stop. Since later items might
                # depend on this one, we shouldn't continue
                display.display_error(
                    "Installer item %s was not found.", item["installer_item"])
                return restartflag, skipped_installs
            # Adobe installs
            if installer_type.startswith("Adobe"):
                retcode = adobeutils.do_adobe_install(item)
                if retcode == 0 and requires_restart(item):
                    restartflag = True
                if retcode == 8:
                    # Adobe Setup says restart needed.
                    restartflag = True
                    retcode = 0
            # stage_os_installer install
            elif installer_type == "stage_os_installer":
                retcode = dmg.copy_from_dmg(itempath, item.get('items_to_copy'))
                if retcode == 0:
                    osinstaller.record_staged_os_installer(item)
            # copy_from_dmg install
            elif installer_type == "copy_from_dmg":
                retcode = dmg.copy_from_dmg(itempath, item.get('items_to_copy'))
                if retcode == 0 and requires_restart(item):
                    restartflag = True
            # appdmg install (deprecated)
            elif installer_type == "appdmg":
                display.display_warning(
                    "install_type 'appdmg' is deprecated. Use 'copy_from_dmg'.")
                retcode = dmg.copy_app_from_dmg(itempath)
            # configuration profile install
            elif installer_type == 'profile':
                # profiles.install_profile returns True/False
                retcode = 0
                identifier = item.get('PayloadIdentifier')
                if not profiles.install_profile(itempath, identifier):
                    retcode = -1
                if retcode == 0 and requires_restart(item):
                    restartflag = True
            # nopkg (Packageless) install
            elif installer_type == "nopkg":
                restartflag = restartflag or requires_restart(item)
            # unknown installer_type
            elif installer_type != "":
                # we've encountered an installer type
                # we don't know how to handle
                display.display_error(
                    "Unsupported install type: %s" % installer_type)
                retcode = -99
            # better be Apple installer package
            else:
                (retcode, need_to_restart) = handle_apple_package_install(
                    item, itempath)
                if need_to_restart:
                    restartflag = True

            if processes.stop_requested():
                return restartflag, skipped_installs

        # install succeeded. Do we have a postinstall_script?
        if retcode == 0 and 'postinstall_script' in item:
            # only run embedded postinstall script if the install did not
            # return a failure code
            retcode = scriptutils.run_embedded_script(
                'postinstall_script', item)
            if retcode:
                # we won't consider postinstall script failures as fatal
                # since the item has been installed via package/disk image
                # but admin should be notified
                display.display_warning(
                    'Postinstall script for %s returned %s'
                    % (item['name'], retcode))
                # reset retcode to 0 so we will mark this install
                # as successful
                retcode = 0

        # if install was successful and this is a SelfService OnDemand install
        # remove the item from the SelfServeManifest's managed_installs
        if retcode == 0 and item.get('OnDemand'):
            manifestutils.remove_from_selfserve_installs(item['name'])

        # record install success/failure
        if not 'InstallResults' in reports.report:
            reports.report['InstallResults'] = []

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
        munkilog.log(log_msg, "Install.log")

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
        reports.report['InstallResults'].append(install_result)

        # check to see if this installer item is needed by any additional
        # items in installinfo
        # this might happen if there are multiple things being installed
        # with choicesXML files applied to a metapackage or
        # multiple packages being installed from a single DMG
        stillneeded = False
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
                    stillneeded = True
                    break

        # check to see if the item is both precache and OnDemand
        if not stillneeded and item.get('precache') and item.get('OnDemand'):
            stillneeded = True
            break

        # need to check skipped_installs as well
        if not stillneeded:
            for skipped_item in skipped_installs:
                if (skipped_item.get('installer_item') ==
                        current_installer_item):
                    stillneeded = True
                    break

        # ensure package is not deleted from cache if installation
        # fails by checking retcode
        if not stillneeded and retcode == 0:
            # now remove the item from the install cache
            # (if it's still there)
            itempath = os.path.join(dirpath, current_installer_item)
            if os.path.exists(itempath):
                if os.path.isdir(itempath):
                    retcode = subprocess.call(["/bin/rm", "-rf", itempath])
                else:
                    # flat pkg or dmg
                    retcode = subprocess.call(["/bin/rm", itempath])
                    if pkgutils.hasValidDiskImageExt(itempath):
                        shadowfile = os.path.join(itempath, ".shadow")
                        if os.path.exists(shadowfile):
                            retcode = subprocess.call(["/bin/rm", shadowfile])

    return (restartflag, skipped_installs)


def skipped_items_that_require_this(item, skipped_items):
    '''Looks for items in the skipped_items that require or are update_for
    the current item. Returns a list of matches.'''

    # shortcut -- if we have no skipped items, just return an empty list
    # also reduces log noise in the common case
    if not skipped_items:
        return []

    display.display_debug1(
        'Checking for skipped items that require %s' % item['name'])

    matched_skipped_items = []
    for skipped_item in skipped_items:
        # get list of prerequisites for this skipped_item
        prerequisites = skipped_item.get('requires', [])
        prerequisites.extend(skipped_item.get('update_for', []))
        display.display_debug1(
            '%s has these prerequisites: %s'
            % (skipped_item['name'], ', '.join(prerequisites)))
        for prereq in prerequisites:
            (prereq_name, dummy_version) = catalogs.split_name_and_version(
                prereq)
            if prereq_name == item['name']:
                matched_skipped_items.append(skipped_item['name'])
    return matched_skipped_items


def process_removals(removallist, only_unattended=False):
    '''processes removals from the removal list'''
    restart_flag = False
    index = 0
    skipped_removals = []
    for item in removallist:
        if only_unattended:
            if not item.get('unattended_uninstall'):
                skipped_removals.append(item)
                display.display_detail(
                    ('Skipping removal of %s because it\'s not unattended.'
                     % item['name']))
                continue
            if processes.blocking_applications_running(item):
                skipped_removals.append(item)
                display.display_detail(
                    'Skipping unattended removal of %s because '
                    'blocking application(s) running.' % item['name'])
                continue

        dependent_skipped_items = skipped_items_that_require_this(
            item, skipped_removals)
        if dependent_skipped_items:
            # need to skip this too
            skipped_removals.append(item)
            display.display_detail(
                'Skipping removal of %s because these '
                'skipped items required it: %s'
                % (item['name'], ", ".join(dependent_skipped_items)))
            continue

        if processes.stop_requested():
            return restart_flag, skipped_removals
        if not item.get('installed'):
            # not installed, so skip it (this shouldn't happen...)
            continue

        index += 1
        display_name = item.get('display_name') or item.get('name')
        display.display_status_major(
            "Removing %s (%s of %s)...", display_name, index, len(removallist))

        retcode = 0
        # run preuninstall_script if it exists
        if 'preuninstall_script' in item:
            retcode = scriptutils.run_embedded_script(
                'preuninstall_script', item)

        if retcode == 0 and 'uninstall_method' in item:
            uninstallmethod = item['uninstall_method']
            if uninstallmethod == "removepackages":
                if 'packages' in item:
                    restart_flag = requires_restart(item)
                    retcode = rmpkgs.removepackages(item['packages'],
                                                    forcedeletebundles=True)
                    if retcode:
                        if retcode == -128:
                            message = (
                                "Uninstall of %s was cancelled." % display_name)
                        else:
                            message = "Uninstall of %s failed." % display_name
                        display.display_error(message)
                    else:
                        munkilog.log(
                            "Uninstall of %s was successful." % display_name)

            elif uninstallmethod == "uninstall_package":
                # install a package to remove the software
                if "uninstaller_item" in item:
                    managedinstallbase = prefs.pref('ManagedInstallDir')
                    itempath = os.path.join(managedinstallbase, 'Cache',
                                            item["uninstaller_item"])
                    if not os.path.exists(itempath):
                        display.display_error(
                            "%s package for %s was missing from the cache."
                            % (uninstallmethod, item['name']))
                        continue
                    (retcode, need_to_restart) = handle_apple_package_install(
                        item, itempath)
                    if need_to_restart:
                        restart_flag = True
                else:
                    display.display_error(
                        "No uninstall item specified for %s" % item['name'])
                    continue

            elif uninstallmethod.startswith("Adobe"):
                retcode = adobeutils.do_adobe_removal(item)

            elif uninstallmethod == "remove_copied_items":
                retcode = remove_copied_items(item.get('items_to_remove'))

            elif uninstallmethod == "remove_app":
                # deprecated with appdmg!
                remove_app_info = item.get('remove_app_info', None)
                if remove_app_info:
                    path_to_remove = remove_app_info['path']
                    display.display_status_minor(
                        'Removing %s' % path_to_remove)
                    retcode = subprocess.call(
                        ["/bin/rm", "-rf", path_to_remove])
                    if retcode:
                        display.display_error(
                            "Removal error for %s", path_to_remove)
                else:
                    display.display_error(
                        "Application removal info missing from %s",
                        display_name)

            elif uninstallmethod == 'remove_profile':
                identifier = item.get('PayloadIdentifier')
                if identifier:
                    retcode = 0
                    if not profiles.remove_profile(identifier):
                        retcode = -1
                        display.display_error(
                            "Profile removal error for %s", identifier)
                else:
                    display.display_error(
                        "Profile removal info missing from %s", display_name)

            elif uninstallmethod == 'uninstall_script':
                retcode = scriptutils.run_embedded_script(
                    'uninstall_script', item)
                if retcode == 0 and requires_restart(item):
                    restart_flag = True

            elif (os.path.exists(uninstallmethod) and
                  os.access(uninstallmethod, os.X_OK)):
                # it's a script or program to uninstall
                retcode = scriptutils.run_script(
                    display_name, uninstallmethod, 'uninstall script')
                if retcode == 0 and requires_restart(item):
                    restart_flag = True

            else:
                munkilog.log("Uninstall of %s failed because there was no "
                             "valid uninstall method." % display_name)
                retcode = -99

            if retcode == 0 and item.get('postuninstall_script'):
                retcode = scriptutils.run_embedded_script(
                    'postuninstall_script', item)
                if retcode:
                    # we won't consider postuninstall script failures as fatal
                    # since the item has been uninstalled
                    # but admin should be notified
                    display.display_warning(
                        'Postuninstall script for %s returned %s'
                        % (item['name'], retcode))
                    # reset retcode to 0 so we will mark this uninstall
                    # as successful
                    retcode = 0

        # record removal success/failure
        if not 'RemovalResults' in reports.report:
            reports.report['RemovalResults'] = []
        if retcode == 0:
            success_msg = "Removal of %s: SUCCESSFUL" % display_name
            munkilog.log(success_msg, "Install.log")
            manifestutils.remove_from_selfserve_uninstalls(item['name'])
        else:
            failure_msg = "Removal of %s: " % display_name + \
                          " FAILED with return code: %s" % retcode
            munkilog.log(failure_msg, "Install.log")
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
        reports.report['RemovalResults'].append(removal_result)

    return (restart_flag, skipped_removals)


def run(only_unattended=False):
    """Runs the install/removal session.

    Args:
      only_unattended: Boolean. If True, only do unattended_(un)install pkgs.
    """
    # pylint: disable=unused-variable
    # prevent sleep when idle so our installs complete. The Caffeinator class
    # automatically releases the Power Manager assertion when the variable
    # goes out of scope, so we only need to create it and hold a reference
    caffeinator = powermgr.Caffeinator()
    # pylint: enable=unused-variable

    managedinstallbase = prefs.pref('ManagedInstallDir')
    installdir = os.path.join(managedinstallbase, 'Cache')

    removals_need_restart = installs_need_restart = False

    if only_unattended:
        munkilog.log("### Beginning unattended installer session ###")
    else:
        munkilog.log("### Beginning managed installer session ###")

    installinfopath = os.path.join(managedinstallbase, 'InstallInfo.plist')
    if os.path.exists(installinfopath):
        try:
            installinfo = FoundationPlist.readPlist(installinfopath)
        except FoundationPlist.NSPropertyListSerializationException:
            display.display_error("Invalid %s" % installinfopath)
            return -1

        if prefs.pref('SuppressStopButtonOnInstall'):
            munkistatus.hideStopButton()

        if "removals" in installinfo:
            # filter list to items that need to be removed
            removallist = [item for item in installinfo['removals']
                           if item.get('installed')]
            reports.report['ItemsToRemove'] = removallist
            if removallist:
                if len(removallist) == 1:
                    munkistatus.message("Removing 1 item...")
                else:
                    munkistatus.message("Removing %i items..." %
                                        len(removallist))
                munkistatus.detail("")
                # set indeterminate progress bar
                munkistatus.percent(-1)
                munkilog.log("Processing removals")
                (removals_need_restart,
                 skipped_removals) = process_removals(
                     removallist, only_unattended=only_unattended)
                # if any removals were skipped, record them for later
                installinfo['removals'] = skipped_removals

        if "managed_installs" in installinfo:
            if not processes.stop_requested():
                # filter list to items that need to be installed
                installlist = [item for item in
                               installinfo['managed_installs']
                               if item.get('installed') is False]
                reports.report['ItemsToInstall'] = installlist
                if installlist:
                    if len(installlist) == 1:
                        munkistatus.message("Installing 1 item...")
                    else:
                        munkistatus.message(
                            "Installing %i items..." % len(installlist))
                    munkistatus.detail("")
                    # set indeterminate progress bar
                    munkistatus.percent(-1)
                    munkilog.log("Processing installs")
                    (installs_need_restart, skipped_installs) = (
                        install_with_info(installdir, installlist,
                                          only_unattended=only_unattended))
                    # if any installs were skipped record them for later
                    installinfo['managed_installs'] = skipped_installs

        # update optional_installs with new installation/removal status
        for removal in reports.report.get('RemovalResults', []):
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

        for install_item in reports.report.get('InstallResults', []):
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
            display.display_warning(
                "Could not write to %s" % installinfopath)

    else:
        if not only_unattended:  # no need to log that no unattended pkgs found.
            munkilog.log("No %s found." % installinfo)

    if only_unattended:
        munkilog.log("###    End unattended installer session    ###")
    else:
        munkilog.log("###    End managed installer session    ###")

    reports.savereport()
    if removals_need_restart or installs_need_restart:
        return constants.POSTACTION_RESTART
    return constants.POSTACTION_NONE


if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
