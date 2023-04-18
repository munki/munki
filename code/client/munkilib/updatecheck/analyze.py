# encoding: utf-8
#
# Copyright 2009-2023 Greg Neagle.
#
# Licensed under the Apache License, Version 2.0 (the 'License');
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an 'AS IS' BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
updatecheck.analyze

Created by Greg Neagle on 2017-01-10.

"""
# This code is largely still compatible with Python 2, so for now, turn off
# Python 3 style warnings
# pylint: disable=consider-using-f-string
# pylint: disable=redundant-u-string-prefix

from __future__ import absolute_import, print_function

import datetime
import os

from . import catalogs
from . import compare
from . import download
from . import installationstate
from . import manifestutils
from . import selfservice
from . import unused_software

from .. import display
from .. import fetch
from .. import info
from .. import munkilog
from .. import osinstaller
from .. import prefs
from .. import processes
from ..wrappers import is_a_string


def item_in_installinfo(item_pl, thelist, vers=''):
    """Determines if an item is in a list of processed items.

    Returns True if the item has already been processed (it's in the list)
    and, optionally, the version is the same or greater.
    """
    for listitem in thelist:
        try:
            if listitem['name'] == item_pl['name']:
                if not vers:
                    return True
                #if the version already installed or processed to be
                #installed is the same or greater, then we're good.
                if listitem.get('installed') and (compare.compare_versions(
                        listitem.get('installed_version'), vers) in (1, 2)):
                    return True
                if (compare.compare_versions(
                        listitem.get('version_to_install'), vers) in (1, 2)):
                    return True
        except KeyError:
            # item is missing 'name', so doesn't match
            pass

    return False


def is_apple_item(item_pl):
    """Returns True if the item to be installed or removed appears to be from
    Apple. If we are installing or removing any Apple items in a check/install
    cycle, we skip checking/installing Apple updates from an Apple Software
    Update server so we don't stomp on each other"""
    # is this a startosinstall item?
    if item_pl.get('installer_type') == 'startosinstall':
        return True
    # check receipts
    for receipt in item_pl.get('receipts', []):
        if receipt.get('packageid', '').startswith('com.apple.'):
            return True
    # check installs items
    for install_item in item_pl.get('installs', []):
        if install_item.get('CFBundleIdentifier', '').startswith('com.apple.'):
            return True
    # if we get here, no receipts or installs items have Apple
    # identifiers
    return False


def already_processed(itemname, installinfo, sections):
    '''Returns True if itemname has already been added to installinfo in one
    of the given sections'''
    description = {'processed_installs': 'install',
                   'processed_uninstalls': 'uninstall',
                   'managed_updates': 'update',
                   'optional_installs': 'optional install'}
    for section in sections:
        if itemname in installinfo[section]:
            display.display_debug1(
                '%s has already been processed for %s.',
                itemname, description[section])
            return True
    return False


def process_managed_update(manifestitem, cataloglist, installinfo):
    """Process a managed_updates item to see if it is installed, and if so,
    if it needs an update.
    """
    manifestitemname = os.path.split(manifestitem)[1]
    display.display_debug1(
        '* Processing manifest item %s for update', manifestitemname)

    if already_processed(
            manifestitemname, installinfo,
            ['managed_updates', 'processed_installs', 'processed_uninstalls']):
        return

    item_pl = catalogs.get_item_detail(manifestitem, cataloglist)
    if not item_pl:
        display.display_warning(
            'Could not process item %s for update. No pkginfo found in '
            'catalogs: %s ', manifestitem, ', '.join(cataloglist))
        return

    # we only offer to update if some version of the item is already
    # installed, so let's check
    if installationstate.some_version_installed(item_pl):
        # add to the list of processed managed_updates
        installinfo['managed_updates'].append(manifestitemname)
        dummy_result = process_install(
            manifestitem, cataloglist, installinfo, is_managed_update=True)
    else:
        display.display_debug1(
            '%s does not appear to be installed, so no managed updates...',
            manifestitemname)


def process_optional_install(manifestitem, cataloglist, installinfo):
    """Process an optional install item to see if it should be added to
    the list of optional installs.
    """
    manifestitemname = os.path.split(manifestitem)[1]
    display.display_debug1(
        "* Processing manifest item %s for optional install" % manifestitemname)

    if already_processed(
            manifestitemname, installinfo,
            ['optional_installs',
             'processed_installs', 'processed_uninstalls']):
        return

    # check to see if item (any version) is already in the
    # optional_install list:
    for item in installinfo['optional_installs']:
        if manifestitemname == item['name']:
            display.display_debug1(
                '%s has already been processed for optional install.',
                manifestitemname)
            return

    item_pl = catalogs.get_item_detail(manifestitem, cataloglist,
                                       suppress_warnings=True)
    if not item_pl and prefs.pref('ShowOptionalInstallsForHigherOSVersions'):
        # could not find an item valid for the current OS and hardware
        # try again to see if there is an item for a higher OS
        item_pl = catalogs.get_item_detail(
            manifestitem, cataloglist, skip_min_os_check=True,
            suppress_warnings=True)
        if item_pl:
            # found an item that requires a higher OS version
            display.display_debug1(
                'Found %s, version %s that requires a higher os version',
                item_pl['name'], item_pl['version'])
            # insert a note about the OS version requirement
            item_pl['note'] = ('Requires macOS version %s.'
                               % item_pl['minimum_os_version'])
            item_pl['update_available'] = True
    if not item_pl:
        # could not find anything that matches and is applicable
        display.display_warning(
            'Could not process item %s for optional install. No pkginfo '
            'found in catalogs: %s ', manifestitem, ', '.join(cataloglist))
        return

    is_currently_installed = installationstate.some_version_installed(item_pl)
    needs_update = False
    if is_currently_installed:
        if unused_software.should_be_removed(item_pl):
            process_removal(manifestitem, cataloglist, installinfo)
            manifestutils.remove_from_selfserve_installs(manifestitem)
            return
        if not 'installcheck_script' in item_pl:
            # installcheck_scripts can be expensive and only tell us if
            # an item is installed or not. So if iteminfo['installed'] is
            # True, and we're using an installcheck_script,
            # installationstate.installed_state is going to return 1
            # (which does not equal 0), so we can avoid running it again.
            # We should really revisit all of this in the future to avoid
            # repeated checks of the same data.
            # (installcheck_script isn't called if OnDemand is True, but if
            # OnDemand is true, is_currently_installed would be False, and
            # therefore we would not be here!)
            #
            # TL;DR: only check installed_state if no installcheck_script
            installation_state = installationstate.installed_state(item_pl)
            if item_pl.get('installer_type') == 'stage_os_installer':
                # 1 means installer is staged, but not _installed_
                needs_update = installation_state != 2
            else:
                needs_update = installation_state == 0


        if (not needs_update and
                prefs.pref('ShowOptionalInstallsForHigherOSVersions')):
            # the version we have installed is the newest for the current OS.
            # check again to see if there is a newer version for a higher OS
            display.display_debug1(
                'Checking for versions of %s that require a higher OS version',
                manifestitem)
            another_item_pl = catalogs.get_item_detail(
                manifestitem, cataloglist, skip_min_os_check=True,
                suppress_warnings=True)
            if another_item_pl != item_pl:
                # we found a different item. Replace the one we found
                # previously with this one.
                item_pl = another_item_pl
                display.display_debug1(
                    'Found %s, version %s that requires a higher os version',
                    item_pl['name'], item_pl['version'])
                # insert a note about the OS version requirement
                item_pl['note'] = ('Requires macOS version %s.'
                                   % item_pl['minimum_os_version'])
                item_pl['update_available'] = True

    # if we get to this point we can add this item
    # to the list of optional installs
    iteminfo = {}
    iteminfo['name'] = item_pl.get('name', manifestitemname)
    iteminfo['description'] = item_pl.get('description', '')
    iteminfo['version_to_install'] = item_pl.get('version', 'UNKNOWN')
    iteminfo['display_name'] = item_pl.get('display_name', '')
    for key in ['category', 'developer', 'featured', 'icon_name', 'icon_hash',
                'requires', 'RestartAction']:
        if key in item_pl:
            iteminfo[key] = item_pl[key]
    iteminfo['installed'] = is_currently_installed
    iteminfo['needs_update'] = needs_update
    iteminfo['licensed_seat_info_available'] = item_pl.get(
        'licensed_seat_info_available', False)
    iteminfo['uninstallable'] = (
        item_pl.get('uninstallable', False)
        and (item_pl.get('uninstall_method', '') != ''))
    # If the item is a precache item, record the precache flag
    # and also the installer item location (as long as item doesn't have a note
    # explaining why it's not available and as long as available seats is not 0)
    if (item_pl.get('installer_item_location') and
            item_pl.get('precache') and
            not 'note' in item_pl and
            (not 'licensed_seats_available' in item_pl or
             item_pl['licensed_seats_available'])):
        iteminfo['precache'] = True
        iteminfo['installer_item_location'] = item_pl['installer_item_location']
        for key in ['installer_item_hash', 'PackageCompleteURL', 'PackageURL']:
            if key in item_pl:
                iteminfo[key] = item_pl[key]
    iteminfo['installer_item_size'] = \
        item_pl.get('installer_item_size', 0)
    iteminfo['installed_size'] = item_pl.get(
        'installer_item_size', iteminfo['installer_item_size'])
    if item_pl.get('note'):
        # catalogs.get_item_detail() passed us a note about this item;
        # pass it along
        iteminfo['note'] = item_pl['note']
    elif needs_update or not is_currently_installed:
        if not download.enough_disk_space(
                item_pl, installinfo.get('managed_installs', []), warn=False):
            iteminfo['note'] = (
                'Insufficient disk space to download and install.')
            if needs_update:
                iteminfo['needs_update'] = False
                iteminfo['update_available'] = True
    optional_keys = ['preinstall_alert',
                     'preuninstall_alert',
                     'preupgrade_alert',
                     'OnDemand',
                     'minimum_os_version',
                     'update_available',
                     'localized_strings']
    for key in optional_keys:
        if key in item_pl:
            iteminfo[key] = item_pl[key]

    display.display_debug1(
        'Adding %s to the optional install list', iteminfo['name'])
    installinfo['optional_installs'].append(iteminfo)


def process_install(manifestitem, cataloglist, installinfo,
                    is_managed_update=False,
                    is_optional_install=False):
    """Processes a manifest item for install. Determines if it needs to be
    installed, and if so, if any items it is dependent on need to
    be installed first.  Installation detail is added to
    installinfo['managed_installs']
    Calls itself recursively as it processes dependencies.
    Returns a boolean; when processing dependencies, a false return
    will stop the installation of a dependent item
    """

    manifestitemname = os.path.split(manifestitem)[1]
    display.display_debug1(
        '* Processing manifest item %s for install', manifestitemname)
    (manifestitemname_withoutversion, includedversion) = (
        catalogs.split_name_and_version(manifestitemname))

    # have we processed this already?
    if manifestitemname in installinfo['processed_installs']:
        display.display_debug1(
            '%s has already been processed for install.', manifestitemname)
        return True
    if manifestitemname_withoutversion in installinfo['processed_uninstalls']:
        display.display_warning(
            'Will not process %s for install because it has already '
            'been processed for uninstall!', manifestitemname)
        return False

    item_pl = catalogs.get_item_detail(manifestitem, cataloglist)
    if not item_pl:
        display.display_warning(
            'Could not process item %s for install. No pkginfo found in '
            'catalogs: %s ', manifestitem, ', '.join(cataloglist))
        return False

    if item_in_installinfo(item_pl, installinfo['managed_installs'],
                           vers=item_pl.get('version')):
        # has this item already been added to the list of things to install?
        display.display_debug1(
            '%s is or will be installed.', manifestitemname)
        return True

    # check dependencies
    dependencies_met = True

    # there are two kinds of dependencies/relationships.
    #
    # 'requires' are prerequisites:
    #  package A requires package B be installed first.
    #  if package A is removed, package B is unaffected.
    #  requires can be a one to many relationship.
    #
    #  The second type of relationship is 'update_for'.
    #  This signifies that that current package should be considered an update
    #  for the packages listed in the 'update_for' array. When processing a
    #  package, we look through the catalogs for other packages that declare
    #  they are updates for the current package and install them if needed.
    #  This can be a one-to-many relationship - one package can be an update
    #  for several other packages; for example, 'PhotoshopCS4update-11.0.1'
    #  could be an update for PhotoshopCS4 and for AdobeCS4DesignSuite.
    #
    #  When removing an item, any updates for that item are removed as well.

    if 'requires' in item_pl:
        dependencies = item_pl['requires']
        # fix things if 'requires' was specified as a string
        # instead of an array of strings
        if is_a_string(dependencies):
            dependencies = [dependencies]
        for item in dependencies:
            display.display_detail(
                '%s-%s requires %s. Getting info on %s...'
                % (item_pl.get('name', manifestitemname),
                   item_pl.get('version', ''), item, item))
            success = process_install(item, cataloglist, installinfo,
                                      is_managed_update=is_managed_update)
            if not success:
                dependencies_met = False

    iteminfo = {}
    iteminfo['name'] = item_pl.get('name', '')
    iteminfo['display_name'] = item_pl.get('display_name', iteminfo['name'])
    iteminfo['description'] = item_pl.get('description', '')

    if item_pl.get('localized_strings'):
        iteminfo['localized_strings'] = item_pl['localized_strings']

    if not dependencies_met:
        display.display_warning(
            'Didn\'t attempt to install %s because could not resolve all '
            'dependencies.', manifestitemname)
        # add information to managed_installs so we have some feedback
        # to display in MSC.app
        iteminfo['installed'] = False
        iteminfo['note'] = ('Can\'t install %s because could not resolve all '
                            'dependencies.' % iteminfo['display_name'])
        iteminfo['version_to_install'] = item_pl.get('version', 'UNKNOWN')
        installinfo['managed_installs'].append(iteminfo)
        return False

    installed_state = installationstate.installed_state(item_pl)
    if installed_state == 0:
        display.display_detail('Need to install %s', manifestitemname)
        iteminfo['installer_item_size'] = item_pl.get(
            'installer_item_size', 0)
        iteminfo['installed_size'] = item_pl.get(
            'installed_size', iteminfo['installer_item_size'])
        try:
            # Get a timestamp, then download the installer item.
            start = datetime.datetime.now()
            if item_pl.get('installer_type', 0) == 'nopkg':
                # Packageless install
                download_speed = 0
                filename = 'packageless_install'
            else:
                if download.download_installeritem(item_pl, installinfo):
                    # Record the download speed to the InstallResults output.
                    end = datetime.datetime.now()
                    download_seconds = (end - start).seconds
                    try:
                        if iteminfo['installer_item_size'] < 1024:
                            # ignore downloads under 1 MB or speeds will
                            # be skewed.
                            download_speed = 0
                        else:
                            # installer_item_size is KBytes, so divide
                            # by seconds.
                            download_speed = int(
                                iteminfo['installer_item_size'] /
                                download_seconds)
                    except (TypeError, ValueError, ZeroDivisionError):
                        download_speed = 0
                else:
                    # Item was already in cache; set download_speed to 0.
                    download_speed = 0

                filename = download.get_url_basename(
                    item_pl['installer_item_location'])

            iteminfo['download_kbytes_per_sec'] = download_speed
            if download_speed:
                display.display_detail(
                    '%s downloaded at %d KB/s', filename, download_speed)

            # required keys
            iteminfo['installer_item'] = filename
            iteminfo['installed'] = False
            iteminfo['version_to_install'] = item_pl.get('version', 'UNKNOWN')

            # we will ignore the unattended_install key if the item needs a
            # restart or logout...
            if (item_pl.get('unattended_install') or
                    item_pl.get('forced_install')):
                if item_pl.get('RestartAction', 'None') != 'None':
                    display.display_warning(
                        'Ignoring unattended_install key for %s because '
                        'RestartAction is %s.',
                        item_pl['name'], item_pl.get('RestartAction'))
                else:
                    iteminfo['unattended_install'] = True

            # optional keys to copy if they exist
            optional_keys = [
                'additional_startosinstall_options',
                'allow_untrusted',
                'suppress_bundle_relocation',
                'installer_choices_xml',
                'installer_environment',
                'adobe_install_info',
                'RestartAction',
                'installer_type',
                'adobe_package_name',
                'package_path',
                'blocking_applications',
                'installs',
                'requires',
                'update_for',
                'payloads',
                'preinstall_script',
                'postinstall_script',
                'items_to_copy',  # used w/ copy_from_dmg
                'copy_local',     # used w/ AdobeCS5 Updaters
                'force_install_after_date',
                'apple_item',
                'category',
                'developer',
                'icon_name',
                'PayloadIdentifier',
                'icon_hash',
                'OnDemand',
                'precache',
                'display_name_staged', # used w/ stage_os_installer
                'description_staged',
                'installed_size_staged'
            ]

            if (is_optional_install and
                    not installationstate.some_version_installed(item_pl)):
                # For optional installs where no version is installed yet
                # we do not enforce force_install_after_date
                optional_keys.remove('force_install_after_date')

            for key in optional_keys:
                if key in item_pl:
                    iteminfo[key] = item_pl[key]

            if 'apple_item' not in iteminfo:
                # admin did not explicitly mark this item; let's determine if
                # it's from Apple
                if is_apple_item(item_pl):
                    munkilog.log(
                        'Marking %s as apple_item - this will block '
                        'Apple SUS updates' % iteminfo['name'])
                    iteminfo['apple_item'] = True

            installinfo['managed_installs'].append(iteminfo)

            update_list = []
            # (manifestitemname_withoutversion, includedversion) =
            # nameAndVersion(manifestitemname)
            if includedversion:
                # a specific version was specified in the manifest
                # so look only for updates for this specific version
                update_list = catalogs.look_for_updates_for_version(
                    manifestitemname_withoutversion,
                    includedversion, cataloglist)
            else:
                # didn't specify a specific version, so
                # now look for all updates for this item
                update_list = catalogs.look_for_updates(
                    manifestitemname_withoutversion, cataloglist)
                # now append any updates specifically
                # for the version to be installed
                update_list.extend(
                    catalogs.look_for_updates_for_version(
                        manifestitemname_withoutversion,
                        iteminfo['version_to_install'],
                        cataloglist))

            for update_item in update_list:
                # call processInstall recursively so we get the
                # latest version and dependencies
                dummy_result = process_install(
                    update_item, cataloglist, installinfo,
                    is_managed_update=is_managed_update)

        except fetch.PackageVerificationError:
            display.display_warning(
                'Can\'t install %s because the integrity check failed.',
                manifestitem)
            iteminfo['installed'] = False
            iteminfo['note'] = 'Integrity check failed'
            iteminfo['version_to_install'] = item_pl.get('version', 'UNKNOWN')
            for key in ['developer', 'icon_name']:
                if key in item_pl:
                    iteminfo[key] = item_pl[key]
            installinfo['managed_installs'].append(iteminfo)
            #if manifestitemname in installinfo['processed_installs']:
            #    installinfo['processed_installs'].remove(manifestitemname)
            return False
        except (fetch.GurlError, fetch.GurlDownloadError) as errmsg:
            display.display_warning(
                'Download of %s failed: %s', manifestitem, errmsg)
            iteminfo['installed'] = False
            iteminfo['note'] = u'Download failed (%s)' % errmsg
            iteminfo['partial_installer_item'] = download.get_url_basename(
                item_pl['installer_item_location'])
            iteminfo['version_to_install'] = item_pl.get('version', 'UNKNOWN')
            for key in ['developer', 'icon_name']:
                if key in item_pl:
                    iteminfo[key] = item_pl[key]
            installinfo['managed_installs'].append(iteminfo)
            #if manifestitemname in installinfo['processed_installs']:
            #    installinfo['processed_installs'].remove(manifestitemname)
            return False
        except fetch.Error as errmsg:
            display.display_warning(
                'Can\'t install %s because: %s', manifestitemname, errmsg)
            iteminfo['installed'] = False
            iteminfo['note'] = '%s' % errmsg
            iteminfo['partial_installer_item'] = download.get_url_basename(
                item_pl['installer_item_location'])
            iteminfo['version_to_install'] = item_pl.get('version', 'UNKNOWN')
            for key in ['developer', 'icon_name']:
                if key in item_pl:
                    iteminfo[key] = item_pl[key]
            installinfo['managed_installs'].append(iteminfo)
            #if manifestitemname in installinfo['processed_installs']:
            #    installinfo['processed_installs'].remove(manifestitemname)
            return False
    else: # some version installed
        iteminfo['installed'] = True

        if item_pl.get("installer_type") == "stage_os_installer" and installed_state == 1:
            # installer appears to be staged; make sure the info is recorded
            # so we know we can launch the installer later
            # TO-DO: maybe filter the actual info recorded
            display.display_info("Recording staged macOS installer...")
            osinstaller.record_staged_os_installer(item_pl)

        # record installed size for reporting
        iteminfo['installed_size'] = item_pl.get(
            'installed_size', item_pl.get('installer_item_size', 0))
        if installed_state == 1:
            # just use the version from the pkginfo
            iteminfo['installed_version'] = item_pl['version']
        else:
            # might be newer; attempt to figure out the version
            installed_version = compare.get_installed_version(item_pl)
            if installed_version == "UNKNOWN":
                installed_version = '(newer than %s)' % item_pl['version']
            iteminfo['installed_version'] = installed_version
        installinfo['managed_installs'].append(iteminfo)
        # remove included version number if any
        (name, includedversion) = catalogs.split_name_and_version(
            manifestitemname)
        display.display_detail('%s version %s (or newer) is already installed.',
                               name, item_pl['version'])
        update_list = []
        if not includedversion:
            # no specific version is specified;
            # the item is already installed;
            # now look for updates for this item
            update_list = catalogs.look_for_updates(name, cataloglist)
            # and also any for this specific version
            installed_version = iteminfo['installed_version']
            if not installed_version.startswith('(newer than '):
                update_list.extend(
                    catalogs.look_for_updates_for_version(
                        name, installed_version, cataloglist))
        elif compare.compare_versions(
                includedversion, iteminfo['installed_version']) == 1:
            # manifest specifies a specific version
            # if that's what's installed, look for any updates
            # specific to this version
            update_list = catalogs.look_for_updates_for_version(
                manifestitemname_withoutversion, includedversion, cataloglist)
        # if we have any updates, process them
        for update_item in update_list:
            # call processInstall recursively so we get updates
            # and any dependencies
            dummy_result = process_install(
                update_item, cataloglist, installinfo,
                is_managed_update=is_managed_update)

    # done successfully processing this install; add it to our list
    # of processed installs so we don't process it again in the future
    # (unless it is a managed_update)
    if not is_managed_update:
        display.display_debug2(
            'Adding %s to list of processed installs' % manifestitemname)
        installinfo['processed_installs'].append(manifestitemname)

    return True


def process_manifest_for_key(manifest, manifest_key, installinfo,
                             parentcatalogs=None):
    """Processes keys in manifests to build the lists of items to install and
    remove.

    Can be recursive if manifests include other manifests.
    Probably doesn't handle circular manifest references well.

    manifest can be a path to a manifest file or a dictionary object.
    """
    if is_a_string(manifest):
        display.display_debug1(
            "** Processing manifest %s for %s",
            os.path.basename(manifest), manifest_key)
        manifestdata = manifestutils.get_manifest_data(manifest)
    else:
        manifestdata = manifest
        manifest = 'embedded manifest'

    cataloglist = manifestdata.get('catalogs')
    if cataloglist:
        catalogs.get_catalogs(cataloglist)
    elif parentcatalogs:
        cataloglist = parentcatalogs

    if not cataloglist:
        display.display_warning('Manifest %s has no catalogs', manifest)
        return

    for item in manifestdata.get('included_manifests', []):
        if item: # only process if item is not empty
            nestedmanifestpath = manifestutils.get_manifest(item)
            if not nestedmanifestpath:
                raise manifestutils.ManifestException
            if processes.stop_requested():
                return
            process_manifest_for_key(nestedmanifestpath, manifest_key,
                                     installinfo, cataloglist)

    conditionalitems = manifestdata.get('conditional_items', [])
    if conditionalitems:
        display.display_debug1(
            '** Processing conditional_items in %s', manifest)
    # conditionalitems should be an array of dicts
    # each dict has a predicate; the rest consists of the
    # same keys as a manifest
    for item in conditionalitems:
        try:
            predicate = item['condition']
        except (AttributeError, KeyError):
            display.display_warning(
                'Missing predicate for conditional_item %s', item)
            continue
        except Exception:
            display.display_warning(
                'Conditional item is malformed: %s', item)
            continue
        if info.predicate_evaluates_as_true(
                predicate, additional_info={'catalogs': cataloglist}):
            conditionalmanifest = item
            process_manifest_for_key(
                conditionalmanifest, manifest_key, installinfo, cataloglist)

    if manifest_key == 'default_installs':
        selfservice.process_default_installs(manifestdata.get(manifest_key, []))
    else:
        for item in manifestdata.get(manifest_key, []):
            if processes.stop_requested():
                return
            if manifest_key == 'managed_installs':
                dummy_result = process_install(item, cataloglist, installinfo)
            elif manifest_key == 'managed_updates':
                process_managed_update(item, cataloglist, installinfo)
            elif manifest_key == 'optional_installs':
                process_optional_install(item, cataloglist, installinfo)
            elif manifest_key == 'managed_uninstalls':
                dummy_result = process_removal(item, cataloglist, installinfo)
            elif manifest_key == 'featured_items':
                installinfo['featured_items'].append(item)


def process_removal(manifestitem, cataloglist, installinfo):
    """Processes a manifest item; attempts to determine if it
    needs to be removed, and if it can be removed.

    Unlike installs, removals aren't really version-specific -
    If we can figure out how to remove the currently installed
    version, we do, unless the admin specifies a specific version
    number in the manifest. In that case, we only attempt a
    removal if the version installed matches the specific version
    in the manifest.

    Any items dependent on the given item need to be removed first.
    Items to be removed are added to installinfo['removals'].

    Calls itself recursively as it processes dependencies.
    Returns a boolean; when processing dependencies, a false return
    will stop the removal of a dependent item.
    """
    def get_receipts_to_remove(item):
        """Returns a list of receipts to remove for item"""
        name = item['name']
        pkgdata = catalogs.analyze_installed_pkgs()
        if name in pkgdata['receipts_for_name']:
            return pkgdata['receipts_for_name'][name]
        return []

    manifestitemname_withversion = os.path.split(manifestitem)[1]
    display.display_debug1(
        '* Processing manifest item %s for removal' %
        manifestitemname_withversion)

    (manifestitemname, includedversion) = catalogs.split_name_and_version(
        manifestitemname_withversion)

    # have we processed this already?
    if manifestitemname in [catalogs.split_name_and_version(item)[0]
                            for item in installinfo['processed_installs']]:
        display.display_warning(
            'Will not attempt to remove %s because some version of it is in '
            'the list of managed installs, or it is required by another'
            ' managed install.', manifestitemname)
        return False
    if manifestitemname in installinfo['processed_uninstalls']:
        display.display_debug1(
            '%s has already been processed for removal.', manifestitemname)
        return True
    installinfo['processed_uninstalls'].append(manifestitemname)

    infoitems = []
    if includedversion:
        # a specific version was specified
        item_pl = catalogs.get_item_detail(
            manifestitemname, cataloglist, includedversion)
        if item_pl:
            infoitems.append(item_pl)
    else:
        # get all items matching the name provided
        infoitems = catalogs.get_all_items_with_name(
            manifestitemname, cataloglist)

    if not infoitems:
        display.display_warning(
            'Could not process item %s for removal. No pkginfo found in '
            'catalogs: %s ', manifestitemname, ', '.join(cataloglist))
        return False

    install_evidence = False
    found_item = None
    for item in infoitems:
        display.display_debug2('Considering item %s-%s for removal info',
                               item['name'], item['version'])
        if installationstate.evidence_this_is_installed(item):
            install_evidence = True
            found_item = item
            break
        #else:
        display.display_debug2(
            '%s-%s not installed.', item['name'], item['version'])

    if not install_evidence:
        display.display_detail(
            '%s doesn\'t appear to be installed.', manifestitemname_withversion)
        iteminfo = {}
        iteminfo['name'] = manifestitemname
        iteminfo['installed'] = False
        installinfo['removals'].append(iteminfo)
        return True

    # if we get here, install_evidence is true, and found_item
    # holds the item we found install evidence for, so we
    # should use that item to do the removal
    uninstall_item = None
    packages_to_remove = []
    # check for uninstall info
    # and grab the first uninstall method we find.
    if found_item.get('uninstallable') and 'uninstall_method' in found_item:
        uninstallmethod = found_item['uninstall_method']
        if uninstallmethod == 'removepackages':
            packages_to_remove = get_receipts_to_remove(found_item)
            if packages_to_remove:
                uninstall_item = found_item
        elif uninstallmethod.startswith('Adobe'):
            # Adobe CS3/CS4/CS5/CS6/CC product
            uninstall_item = found_item
        elif uninstallmethod in ['remove_copied_items',
                                 'remove_app',
                                 'uninstall_script',
                                 'remove_profile',
                                 'uninstall_package']:
            uninstall_item = found_item
        else:
            # uninstall_method is a local script.
            # Check to see if it exists and is executable
            if os.path.exists(uninstallmethod) and \
               os.access(uninstallmethod, os.X_OK):
                uninstall_item = found_item

    if not uninstall_item:
        # the uninstall info for the item couldn't be matched
        # to what's on disk
        display.display_warning('Could not find uninstall info for %s.',
                                manifestitemname_withversion)
        return False

    # if we got this far, we have enough info to attempt an uninstall.
    # the pkginfo is in uninstall_item
    # Now check for dependent items
    #
    # First, look through catalogs for items that are required by this item;
    # if any are installed, we need to remove them as well
    #
    # still not sure how to handle references to specific versions --
    # if another package says it requires SomePackage--1.0.0.0.0
    # and we're supposed to remove SomePackage--1.0.1.0.0... what do we do?
    #
    dependentitemsremoved = True

    uninstall_item_name = uninstall_item.get('name')
    uninstall_name_w_version = (
        '%s-%s' % (uninstall_item.get('name'), uninstall_item.get('version')))
    alt_uninstall_name_w_version = (
        '%s--%s' % (uninstall_item.get('name'), uninstall_item.get('version')))
    processednames = []
    for catalogname in cataloglist:
        if not catalogname in catalogs.catalogs():
            # in case the list refers to a non-existent catalog
            continue
        for item_pl in catalogs.catalogs()[catalogname]['items']:
            name = item_pl.get('name')
            if name not in processednames:
                if 'requires' in item_pl:
                    if (uninstall_item_name in item_pl['requires'] or
                            uninstall_name_w_version
                            in item_pl['requires'] or
                            alt_uninstall_name_w_version
                            in item_pl['requires']):
                        display.display_debug1(
                            '%s requires %s, checking to see if it\'s '
                            'installed...', item_pl.get('name'),
                            manifestitemname)
                        if installationstate.evidence_this_is_installed(
                                item_pl):
                            display.display_detail(
                                '%s requires %s. %s must be removed as well.',
                                item_pl.get('name'), manifestitemname,
                                item_pl.get('name'))
                            success = process_removal(
                                item_pl.get('name'), cataloglist, installinfo)
                            if not success:
                                dependentitemsremoved = False
                                break
                # record this name so we don't process it again
                processednames.append(name)

    if not dependentitemsremoved:
        display.display_warning('Will not attempt to remove %s because could '
                                'not remove all items dependent on it.',
                                manifestitemname_withversion)
        return False

    # Finally! We can record the removal information!
    iteminfo = {}
    iteminfo['name'] = uninstall_item.get('name', '')
    iteminfo['display_name'] = uninstall_item.get('display_name', '')
    iteminfo['description'] = 'Will be removed.'

    # we will ignore the unattended_uninstall key if the item needs a restart
    # or logout...
    if (uninstall_item.get('unattended_uninstall') or
            uninstall_item.get('forced_uninstall')):
        if uninstall_item.get('RestartAction', 'None') != 'None':
            display.display_warning(
                'Ignoring unattended_uninstall key for %s '
                'because RestartAction is %s.',
                uninstall_item['name'],
                uninstall_item.get('RestartAction'))
        else:
            iteminfo['unattended_uninstall'] = True

    # some keys we'll copy if they exist
    optional_keys = ['blocking_applications',
                     'installs',
                     'requires',
                     'update_for',
                     'payloads',
                     'preuninstall_script',
                     'postuninstall_script',
                     'apple_item',
                     'category',
                     'developer',
                     'icon_name',
                     'PayloadIdentifier']
    for key in optional_keys:
        if key in uninstall_item:
            iteminfo[key] = uninstall_item[key]

    if 'apple_item' not in iteminfo:
        # admin did not explicitly mark this item; let's determine if
        # it's from Apple
        if is_apple_item(item_pl):
            iteminfo['apple_item'] = True

    if packages_to_remove:
        # remove references for each package
        packages_to_really_remove = []
        for pkg in packages_to_remove:
            display.display_debug1('Considering %s for removal...', pkg)
            # find pkg in pkgdata['pkg_references'] and remove the reference
            # so we only remove packages if we're the last reference to it
            pkgdata = catalogs.analyze_installed_pkgs()
            if pkg in pkgdata['pkg_references']:
                display.display_debug1('%s references are: %s', pkg,
                                       pkgdata['pkg_references'][pkg])
                if iteminfo['name'] in pkgdata['pkg_references'][pkg]:
                    pkgdata['pkg_references'][pkg].remove(iteminfo['name'])
                    if not pkgdata['pkg_references'][pkg]:
                        # no other items reference this pkg
                        display.display_debug1(
                            'Adding %s to removal list.', pkg)
                        packages_to_really_remove.append(pkg)
            else:
                # This shouldn't happen
                display.display_warning('pkg id %s missing from pkgdata', pkg)
        if packages_to_really_remove:
            iteminfo['packages'] = packages_to_really_remove
        else:
            # no packages that belong to this item only.
            display.display_warning('could not find unique packages to remove '
                                    'for %s', iteminfo['name'])
            return False

    iteminfo['uninstall_method'] = uninstallmethod
    if uninstallmethod.startswith('Adobe'):
        if (uninstallmethod == "AdobeCS5AAMEEPackage" and
                'adobe_install_info' in uninstall_item):
            iteminfo['adobe_install_info'] = uninstall_item['adobe_install_info']
        else:
            if 'uninstaller_item_location' in uninstall_item:
                location = uninstall_item['uninstaller_item_location']
            else:
                location = uninstall_item['installer_item_location']
            try:
                download.download_installeritem(
                    uninstall_item, installinfo, uninstalling=True)
                filename = os.path.split(location)[1]
                iteminfo['uninstaller_item'] = filename
                iteminfo['adobe_package_name'] = uninstall_item.get(
                    'adobe_package_name', '')
            except fetch.PackageVerificationError:
                display.display_warning(
                    'Can\'t uninstall %s because the integrity check '
                    'failed.', iteminfo['name'])
                return False
            except fetch.Error as errmsg:
                display.display_warning(
                    'Failed to download the uninstaller for %s because %s',
                    iteminfo['name'], errmsg)
                return False
    elif uninstallmethod == 'remove_copied_items':
        iteminfo['items_to_remove'] = uninstall_item.get('items_to_copy', [])
    elif uninstallmethod == 'remove_app':
        if uninstall_item.get('installs', None):
            iteminfo['remove_app_info'] = uninstall_item['installs'][0]
    elif uninstallmethod == 'uninstall_script':
        iteminfo['uninstall_script'] = uninstall_item.get('uninstall_script', '')
    elif uninstallmethod == "uninstall_package":
        location = uninstall_item.get('uninstaller_item_location')
        if not location:
            display.display_warning(
                'Can\'t uninstall %s because there is no URL for the uninstall '
                'package.', iteminfo['name'])
            return False
        try:
            download.download_installeritem(
                uninstall_item, installinfo, uninstalling=True)
            filename = os.path.split(location)[1]
            iteminfo['uninstaller_item'] = filename
        except fetch.PackageVerificationError:
            display.display_warning(
                'Can\'t uninstall %s because the integrity check '
                'failed.', iteminfo['name'])
            return False
        except fetch.Error as errmsg:
            display.display_warning(
                'Failed to download the uninstaller for %s because %s',
                iteminfo['name'], errmsg)
            return False
    # before we add this removal to the list,
    # check for installed updates and add them to the
    # removal list as well:
    update_list = catalogs.look_for_updates(uninstall_item_name, cataloglist)
    update_list.extend(catalogs.look_for_updates(
        uninstall_name_w_version, cataloglist))
    update_list.extend(catalogs.look_for_updates(
        alt_uninstall_name_w_version, cataloglist))
    for update_item in update_list:
        # call us recursively...
        dummy_result = process_removal(update_item, cataloglist, installinfo)

    # finish recording info for this removal
    iteminfo['installed'] = True
    iteminfo['installed_version'] = uninstall_item.get('version')
    if 'RestartAction' in uninstall_item:
        iteminfo['RestartAction'] = uninstall_item['RestartAction']
    installinfo['removals'].append(iteminfo)
    display.display_detail(
        'Removal of %s added to ManagedInstaller tasks.',
        manifestitemname_withversion)
    return True


if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
