#!/usr/bin/python
# encoding: utf-8
#
# Copyright 2009-2016 Greg Neagle.
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
updatecheck.py

Created by Greg Neagle on 2008-11-13.

"""

# standard libs
import datetime
import os

# our libs
from . import catalogs
from . import compare
from . import download
from . import fetch
from . import installationstate
from . import keychain
from . import licensing
from . import manifestutils
from . import munkicommon
from . import munkistatus
from . import FoundationPlist


# Disable PyLint complaining about 'invalid' camelCase names
# pylint: disable=C0103


def isItemInInstallInfo(item_pl, thelist, vers=''):
    """Determines if an item is in a list of processed items.

    Returns True if the item has already
    been processed (it's in the list) and, optionally,
    the version is the same or greater.
    """
    for listitem in thelist:
        try:
            if listitem['name'] == item_pl['name']:
                if not vers:
                    return True
                #if the version already installed or processed to be
                #installed is the same or greater, then we're good.
                if listitem.get('installed') and (compare.compareVersions(
                        listitem.get('installed_version'), vers) in (1, 2)):
                    return True
                if (compare.compareVersions(
                        listitem.get('version_to_install'), vers) in (1, 2)):
                    return True
        except KeyError:
            # item is missing 'name', so doesn't match
            pass

    return False


def isAppleItem(item_pl):
    """Returns True if the item to be installed or removed appears to be from
    Apple. If we are installing or removing any Apple items in a check/install
    cycle, we skip checking/installing Apple updates from an Apple Software
    Update server so we don't stomp on each other"""
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


def processManagedUpdate(manifestitem, cataloglist, installinfo):
    """Process a managed_updates item to see if it is installed, and if so,
    if it needs an update.
    """
    manifestitemname = os.path.split(manifestitem)[1]
    munkicommon.display_debug1(
        '* Processing manifest item %s for update', manifestitemname)

    # check to see if item is already in the update list:
    if manifestitemname in installinfo['managed_updates']:
        munkicommon.display_debug1(
            '%s has already been processed for update.', manifestitemname)
        return
    # check to see if item is already in the installlist:
    if manifestitemname in installinfo['processed_installs']:
        munkicommon.display_debug1(
            '%s has already been processed for install.', manifestitemname)
        return
    # check to see if item is already in the removallist:
    if manifestitemname in installinfo['processed_uninstalls']:
        munkicommon.display_debug1(
            '%s has already been processed for uninstall.', manifestitemname)
        return

    item_pl = catalogs.get_item_detail(manifestitem, cataloglist)
    if not item_pl:
        munkicommon.display_warning(
            'Could not process item %s for update. '
            'No pkginfo found in catalogs: %s ',
            manifestitem, ', '.join(cataloglist))
        return

    # we only offer to update if some version of the item is already
    # installed, so let's check
    if installationstate.some_version_installed(item_pl):
        # add to the list of processed managed_updates
        installinfo['managed_updates'].append(manifestitemname)
        dummy_result = processInstall(manifestitem, cataloglist, installinfo,
                                      is_managed_update=True)
    else:
        munkicommon.display_debug1(
            '%s does not appear to be installed, so no managed updates...',
            manifestitemname)


def processOptionalInstall(manifestitem, cataloglist, installinfo):
    """Process an optional install item to see if it should be added to
    the list of optional installs.
    """
    manifestitemname = os.path.split(manifestitem)[1]
    munkicommon.display_debug1(
        "* Processing manifest item %s for optional install" %
        manifestitemname)

    # have we already processed this?
    if manifestitemname in installinfo['optional_installs']:
        munkicommon.display_debug1(
            '%s has already been processed for optional install.',
            manifestitemname)
        return
    elif manifestitemname in installinfo['processed_installs']:
        munkicommon.display_debug1(
            '%s has already been processed for install.', manifestitemname)
        return
    elif manifestitemname in installinfo['processed_uninstalls']:
        munkicommon.display_debug1(
            '%s has already been processed for uninstall.', manifestitemname)
        return

    # check to see if item (any version) is already in the
    # optional_install list:
    for item in installinfo['optional_installs']:
        if manifestitemname == item['name']:
            munkicommon.display_debug1(
                '%s has already been processed for optional install.',
                manifestitemname)
            return

    item_pl = catalogs.get_item_detail(manifestitem, cataloglist)
    if not item_pl:
        munkicommon.display_warning(
            'Could not process item %s for optional install. '
            'No pkginfo found in catalogs: %s ',
            manifestitem, ', '.join(cataloglist))
        return

    # if we get to this point we can add this item
    # to the list of optional installs
    iteminfo = {}
    iteminfo['name'] = item_pl.get('name', manifestitemname)
    iteminfo['description'] = item_pl.get('description', '')
    iteminfo['version_to_install'] = item_pl.get('version', 'UNKNOWN')
    iteminfo['display_name'] = item_pl.get('display_name', '')
    for key in ['category', 'developer', 'icon_name', 'icon_hash',
                'requires', 'RestartAction']:
        if key in item_pl:
            iteminfo[key] = item_pl[key]
    iteminfo['installed'] = installationstate.some_version_installed(item_pl)
    if iteminfo['installed']:
        iteminfo['needs_update'] = (
            installationstate.installed_state(item_pl) == 0)
    iteminfo['licensed_seat_info_available'] = item_pl.get(
        'licensed_seat_info_available', False)
    iteminfo['uninstallable'] = (
        item_pl.get('uninstallable', False)
        and (item_pl.get('uninstall_method', '') != ''))
    iteminfo['installer_item_size'] = \
        item_pl.get('installer_item_size', 0)
    iteminfo['installed_size'] = item_pl.get(
        'installer_item_size', iteminfo['installer_item_size'])
    if (not iteminfo['installed']) or (iteminfo.get('needs_update')):
        if not download.enough_disk_space(
                item_pl, installinfo.get('managed_installs', []), warn=False):
            iteminfo['note'] = (
                'Insufficient disk space to download and install.')
    optional_keys = ['preinstall_alert',
                     'preuninstall_alert',
                     'preupgrade_alert',
                     'OnDemand']
    for key in optional_keys:
        if key in item_pl:
            iteminfo[key] = item_pl[key]

    munkicommon.display_debug1(
        'Adding %s to the optional install list', iteminfo['name'])
    installinfo['optional_installs'].append(iteminfo)


def processInstall(manifestitem, cataloglist, installinfo,
                   is_managed_update=False):
    """Processes a manifest item for install. Determines if it needs to be
    installed, and if so, if any items it is dependent on need to
    be installed first.  Installation detail is added to
    installinfo['managed_installs']
    Calls itself recursively as it processes dependencies.
    Returns a boolean; when processing dependencies, a false return
    will stop the installation of a dependent item
    """

    manifestitemname = os.path.split(manifestitem)[1]
    munkicommon.display_debug1(
        '* Processing manifest item %s for install', manifestitemname)
    (manifestitemname_withoutversion, includedversion) = (
        catalogs.split_name_and_version(manifestitemname))
    # have we processed this already?
    if manifestitemname in installinfo['processed_installs']:
        munkicommon.display_debug1(
            '%s has already been processed for install.', manifestitemname)
        return True
    elif (manifestitemname_withoutversion in
          installinfo['processed_uninstalls']):
        munkicommon.display_warning(
            'Will not process %s for install because it has already '
            'been processed for uninstall!', manifestitemname)
        return False

    item_pl = catalogs.get_item_detail(manifestitem, cataloglist)
    if not item_pl:
        munkicommon.display_warning(
            'Could not process item %s for install. '
            'No pkginfo found in catalogs: %s ',
            manifestitem, ', '.join(cataloglist))
        return False
    elif is_managed_update:
        # we're processing this as a managed update, so don't
        # add it to the processed_installs list
        pass
    else:
        # we found it, so add it to our list of procssed installs
        # so we don't process it again in the future
        munkicommon.display_debug2('Adding %s to list of processed installs'
                                   % manifestitemname)
        installinfo['processed_installs'].append(manifestitemname)

    if isItemInInstallInfo(item_pl, installinfo['managed_installs'],
                           vers=item_pl.get('version')):
        # has this item already been added to the list of things to install?
        munkicommon.display_debug1(
            '%s is or will be installed.', manifestitemname)
        return True

    # check dependencies
    dependenciesMet = True

    # there are two kinds of dependencies/relationships.
    #
    # 'requires' are prerequistes:
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
        if isinstance(dependencies, basestring):
            dependencies = [dependencies]
        for item in dependencies:
            munkicommon.display_detail(
                '%s-%s requires %s. Getting info on %s...'
                % (item_pl.get('name', manifestitemname),
                   item_pl.get('version', ''), item, item))
            success = processInstall(item, cataloglist, installinfo,
                                     is_managed_update=is_managed_update)
            if not success:
                dependenciesMet = False

    iteminfo = {}
    iteminfo['name'] = item_pl.get('name', '')
    iteminfo['display_name'] = item_pl.get('display_name', iteminfo['name'])
    iteminfo['description'] = item_pl.get('description', '')

    if not dependenciesMet:
        munkicommon.display_warning('Didn\'t attempt to install %s '
                                    'because could not resolve all '
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
        munkicommon.display_detail('Need to install %s', manifestitemname)
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
                munkicommon.display_detail(
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
                    munkicommon.display_warning(
                        'Ignoring unattended_install key for %s '
                        'because RestartAction is %s.',
                        item_pl['name'], item_pl.get('RestartAction'))
                else:
                    iteminfo['unattended_install'] = True

            # optional keys
            optional_keys = ['suppress_bundle_relocation',
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
                             'OnDemand']

            for key in optional_keys:
                if key in item_pl:
                    iteminfo[key] = item_pl[key]

            if 'apple_item' not in iteminfo:
                # admin did not explicitly mark this item; let's determine if
                # it's from Apple
                if isAppleItem(item_pl):
                    munkicommon.log(
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
                dummy_result = processInstall(
                    update_item, cataloglist, installinfo,
                    is_managed_update=is_managed_update)
            return True
        except fetch.PackageVerificationError:
            munkicommon.display_warning(
                'Can\'t install %s because the integrity check failed.',
                manifestitem)
            iteminfo['installed'] = False
            iteminfo['note'] = 'Integrity check failed'
            iteminfo['version_to_install'] = item_pl.get('version', 'UNKNOWN')
            installinfo['managed_installs'].append(iteminfo)
            if manifestitemname in installinfo['processed_installs']:
                installinfo['processed_installs'].remove(manifestitemname)
            return False
        except (fetch.GurlError, fetch.GurlDownloadError), errmsg:
            munkicommon.display_warning(
                'Download of %s failed: %s', manifestitem, errmsg)
            iteminfo['installed'] = False
            iteminfo['note'] = u'Download failed (%s)' % errmsg
            iteminfo['version_to_install'] = item_pl.get('version', 'UNKNOWN')
            installinfo['managed_installs'].append(iteminfo)
            if manifestitemname in installinfo['processed_installs']:
                installinfo['processed_installs'].remove(manifestitemname)
            return False
        except fetch.Error, errmsg:
            munkicommon.display_warning(
                'Can\'t install %s because: %s', manifestitemname, errmsg)
            iteminfo['installed'] = False
            iteminfo['note'] = '%s' % errmsg
            iteminfo['version_to_install'] = item_pl.get('version', 'UNKNOWN')
            installinfo['managed_installs'].append(iteminfo)
            if manifestitemname in installinfo['processed_installs']:
                installinfo['processed_installs'].remove(manifestitemname)
            return False
    else:
        iteminfo['installed'] = True
        # record installed size for reporting
        iteminfo['installed_size'] = item_pl.get(
            'installed_size', item_pl.get('installer_item_size', 0))
        if installed_state == 1:
            # just use the version from the pkginfo
            iteminfo['installed_version'] = item_pl['version']
        else:
            # might be newer; attempt to figure out the version
            installed_version = compare.getInstalledVersion(item_pl)
            if installed_version == "UNKNOWN":
                installed_version = '(newer than %s)' % item_pl['version']
            iteminfo['installed_version'] = installed_version
        installinfo['managed_installs'].append(iteminfo)
        # remove included version number if any
        (name, includedversion) = catalogs.split_name_and_version(manifestitemname)
        munkicommon.display_detail('%s version %s (or newer) is already '
                                   'installed.', name, item_pl['version'])
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
        elif compare.compareVersions(
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
            dummy_result = processInstall(
                update_item, cataloglist, installinfo,
                is_managed_update=is_managed_update)

        return True


def processManifestForKey(manifest, manifest_key, installinfo,
                          parentcatalogs=None):
    """Processes keys in manifests to build the lists of items to install and
    remove.

    Can be recursive if manifests include other manifests.
    Probably doesn't handle circular manifest references well.

    manifest can be a path to a manifest file or a dictionary object.
    """
    if isinstance(manifest, basestring):
        munkicommon.display_debug1(
            "** Processing manifest %s for %s" %
            (os.path.basename(manifest), manifest_key))
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
        munkicommon.display_warning('Manifest %s has no catalogs', manifest)
        return

    for item in manifestdata.get('included_manifests', []):
        nestedmanifestpath = manifestutils.get_manifest(item)
        if not nestedmanifestpath:
            raise manifestutils.ManifestException
        if munkicommon.stopRequested():
            return {}
        processManifestForKey(nestedmanifestpath, manifest_key,
                              installinfo, cataloglist)

    conditionalitems = manifestdata.get('conditional_items', [])
    if conditionalitems:
        munkicommon.display_debug1(
            '** Processing conditional_items in %s', manifest)
    # conditionalitems should be an array of dicts
    # each dict has a predicate; the rest consists of the
    # same keys as a manifest
    for item in conditionalitems:
        try:
            predicate = item['condition']
        except (AttributeError, KeyError):
            munkicommon.display_warning(
                'Missing predicate for conditional_item %s', item)
            continue
        except BaseException:
            munkicommon.display_warning(
                'Conditional item is malformed: %s', item)
            continue
        if munkicommon.predicateEvaluatesAsTrue(
                predicate, additional_info={'catalogs': cataloglist}):
            conditionalmanifest = item
            processManifestForKey(
                conditionalmanifest, manifest_key, installinfo, cataloglist)

    for item in manifestdata.get(manifest_key, []):
        if munkicommon.stopRequested():
            return {}
        if manifest_key == 'managed_installs':
            dummy_result = processInstall(item, cataloglist, installinfo)
        elif manifest_key == 'managed_updates':
            processManagedUpdate(item, cataloglist, installinfo)
        elif manifest_key == 'optional_installs':
            processOptionalInstall(item, cataloglist, installinfo)
        elif manifest_key == 'managed_uninstalls':
            dummy_result = processRemoval(item, cataloglist, installinfo)


def processRemoval(manifestitem, cataloglist, installinfo):
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
    munkicommon.display_debug1(
        '* Processing manifest item %s for removal' %
        manifestitemname_withversion)

    (manifestitemname, includedversion) = catalogs.split_name_and_version(
        manifestitemname_withversion)

    # have we processed this already?
    if manifestitemname in [catalogs.split_name_and_version(item)[0]
                            for item in installinfo['processed_installs']]:
        munkicommon.display_warning(
            'Will not attempt to remove %s because some version of it is in '
            'the list of managed installs, or it is required by another'
            ' managed install.', manifestitemname)
        return False
    elif manifestitemname in installinfo['processed_uninstalls']:
        munkicommon.display_debug1(
            '%s has already been processed for removal.', manifestitemname)
        return True
    else:
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
        munkicommon.display_warning(
            'Could not process item %s for removal. No pkginfo found in '
            'catalogs: %s ', manifestitemname, ', '.join(cataloglist))
        return False

    installEvidence = False
    for item in infoitems:
        munkicommon.display_debug2('Considering item %s-%s for removal info',
                                   item['name'], item['version'])
        if installationstate.evidence_this_is_installed(item):
            installEvidence = True
            break
        else:
            munkicommon.display_debug2(
                '%s-%s not installed.', item['name'], item['version'])

    if not installEvidence:
        munkicommon.display_detail(
            '%s doesn\'t appear to be installed.', manifestitemname_withversion)
        iteminfo = {}
        iteminfo['name'] = manifestitemname
        iteminfo['installed'] = False
        installinfo['removals'].append(iteminfo)
        return True

    # if we get here, installEvidence is true, and item
    # holds the item we found install evidence for, so we
    # should use that item to do the removal
    uninstall_item = None
    packagesToRemove = []
    # check for uninstall info
    # and grab the first uninstall method we find.
    if item.get('uninstallable') and 'uninstall_method' in item:
        uninstallmethod = item['uninstall_method']
        if uninstallmethod == 'removepackages':
            packagesToRemove = get_receipts_to_remove(item)
            if packagesToRemove:
                uninstall_item = item
        elif uninstallmethod.startswith('Adobe'):
            # Adobe CS3/CS4/CS5/CS6/CC product
            uninstall_item = item
        elif uninstallmethod in ['remove_copied_items',
                                 'remove_app',
                                 'uninstall_script',
                                 'remove_profile']:
            uninstall_item = item
        else:
            # uninstall_method is a local script.
            # Check to see if it exists and is executable
            if os.path.exists(uninstallmethod) and \
               os.access(uninstallmethod, os.X_OK):
                uninstall_item = item

    if not uninstall_item:
        # the uninstall info for the item couldn't be matched
        # to what's on disk
        munkicommon.display_warning('Could not find uninstall info for %s.',
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
    uninstall_item_name_with_version = (
        '%s-%s' % (uninstall_item.get('name'), uninstall_item.get('version')))
    alt_uninstall_item_name_with_version = (
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
                            uninstall_item_name_with_version
                            in item_pl['requires'] or
                            alt_uninstall_item_name_with_version
                            in item_pl['requires']):
                        munkicommon.display_debug1(
                            '%s requires %s, checking to see if it\'s '
                            'installed...', item_pl.get('name'),
                            manifestitemname)
                        if installationstate.evidence_this_is_installed(
                                item_pl):
                            munkicommon.display_detail(
                                '%s requires %s. %s must be removed as well.',
                                item_pl.get('name'), manifestitemname,
                                item_pl.get('name'))
                            success = processRemoval(
                                item_pl.get('name'), cataloglist, installinfo)
                            if not success:
                                dependentitemsremoved = False
                                break
                # record this name so we don't process it again
                processednames.append(name)

    if not dependentitemsremoved:
        munkicommon.display_warning('Will not attempt to remove %s because '
                                    'could not remove all items dependent '
                                    'on it.', manifestitemname_withversion)
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
            munkicommon.display_warning(
                'Ignoring unattended_uninstall key for %s '
                'because RestartAction is %s.',
                uninstall_item['name'],
                uninstall_item.get('RestartAction'))
        else:
            iteminfo['unattended_uninstall'] = True

    # some keys we'll copy if they exist
    optionalKeys = ['blocking_applications',
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
    for key in optionalKeys:
        if key in uninstall_item:
            iteminfo[key] = uninstall_item[key]

    if 'apple_item' not in iteminfo:
        # admin did not explicitly mark this item; let's determine if
        # it's from Apple
        if isAppleItem(item_pl):
            iteminfo['apple_item'] = True

    if packagesToRemove:
        # remove references for each package
        packagesToReallyRemove = []
        for pkg in packagesToRemove:
            munkicommon.display_debug1('Considering %s for removal...', pkg)
            # find pkg in pkgdata['pkg_references'] and remove the reference
            # so we only remove packages if we're the last reference to it
            pkgdata = catalogs.analyze_installed_pkgs()
            if pkg in pkgdata['pkg_references']:
                munkicommon.display_debug1('%s references are: %s', pkg,
                                           pkgdata['pkg_references'][pkg])
                if iteminfo['name'] in pkgdata['pkg_references'][pkg]:
                    pkgdata['pkg_references'][pkg].remove(iteminfo['name'])
                    if len(pkgdata['pkg_references'][pkg]) == 0:
                        munkicommon.display_debug1(
                            'Adding %s to removal list.', pkg)
                        packagesToReallyRemove.append(pkg)
            else:
                # This shouldn't happen
                munkicommon.display_warning(
                    'pkg id %s missing from pkgdata', pkg)
        if packagesToReallyRemove:
            iteminfo['packages'] = packagesToReallyRemove
        else:
            # no packages that belong to this item only.
            munkicommon.display_warning('could not find unique packages to '
                                        'remove for %s', iteminfo['name'])
            return False

    iteminfo['uninstall_method'] = uninstallmethod
    if uninstallmethod.startswith('Adobe'):
        if (uninstallmethod == "AdobeCS5AAMEEPackage" and
                'adobe_install_info' in item):
            iteminfo['adobe_install_info'] = item['adobe_install_info']
        else:
            if 'uninstaller_item_location' in item:
                location = uninstall_item['uninstaller_item_location']
            else:
                location = uninstall_item['installer_item_location']
            try:
                download.download_installeritem(
                    item, installinfo, uninstalling=True)
                filename = os.path.split(location)[1]
                iteminfo['uninstaller_item'] = filename
                iteminfo['adobe_package_name'] = uninstall_item.get(
                    'adobe_package_name', '')
            except fetch.PackageVerificationError:
                munkicommon.display_warning(
                    'Can\'t uninstall %s because the integrity check '
                    'failed.', iteminfo['name'])
                return False
            except fetch.Error, errmsg:
                munkicommon.display_warning(
                    'Failed to download the uninstaller for %s because %s',
                    iteminfo['name'], errmsg)
                return False
    elif uninstallmethod == 'remove_copied_items':
        iteminfo['items_to_remove'] = item.get('items_to_copy', [])
    elif uninstallmethod == 'remove_app':
        if uninstall_item.get('installs', None):
            iteminfo['remove_app_info'] = uninstall_item['installs'][0]
    elif uninstallmethod == 'uninstall_script':
        iteminfo['uninstall_script'] = item.get('uninstall_script', '')

    # before we add this removal to the list,
    # check for installed updates and add them to the
    # removal list as well:
    update_list = catalogs.look_for_updates(uninstall_item_name, cataloglist)
    update_list.extend(catalogs.look_for_updates(
        uninstall_item_name_with_version, cataloglist))
    update_list.extend(catalogs.look_for_updates(
        alt_uninstall_item_name_with_version, cataloglist))
    for update_item in update_list:
        # call us recursively...
        dummy_result = processRemoval(update_item, cataloglist, installinfo)

    # finish recording info for this removal
    iteminfo['installed'] = True
    iteminfo['installed_version'] = uninstall_item.get('version')
    if 'RestartAction' in uninstall_item:
        iteminfo['RestartAction'] = uninstall_item['RestartAction']
    installinfo['removals'].append(iteminfo)
    munkicommon.display_detail(
        'Removal of %s added to ManagedInstaller tasks.',
        manifestitemname_withversion)
    return True


class UpdateCheckAbortedError(Exception):
    '''Exception used to break out of checking for updates'''
    pass


def check(client_id='', localmanifestpath=None):
    """Checks for available new or updated managed software, downloading
    installer items if needed. Returns 1 if there are available updates,
    0 if there are no available updates, and -1 if there were errors."""

    munkicommon.report['MachineInfo'] = munkicommon.getMachineFacts()

    # initialize our Munki keychain if we are using custom certs or CAs
    dummy_keychain_obj = keychain.MunkiKeychain()

    ManagedInstallDir = munkicommon.pref('ManagedInstallDir')
    if munkicommon.munkistatusoutput:
        munkistatus.activate()

    munkicommon.log('### Beginning managed software check ###')
    munkicommon.display_status_major('Checking for available updates...')
    munkistatus.percent('-1')
    munkistatus.detail('')

    installinfo = {}

    try:
        if localmanifestpath:
            mainmanifestpath = localmanifestpath
        else:
            try:
                mainmanifestpath = manifestutils.get_primary_manifest(client_id)
            except manifestutils.ManifestException:
                munkicommon.display_error(
                    'Could not retrieve managed install primary manifest.')
                raise

        if munkicommon.stopRequested():
            return 0

        # initialize our installinfo record
        installinfo['processed_installs'] = []
        installinfo['processed_uninstalls'] = []
        installinfo['managed_updates'] = []
        installinfo['optional_installs'] = []
        installinfo['managed_installs'] = []
        installinfo['removals'] = []

        # record info object for conditional item comparisons
        munkicommon.report['Conditions'] = munkicommon.predicateInfoObject()

        munkicommon.display_detail('**Checking for installs**')
        processManifestForKey(
            mainmanifestpath, 'managed_installs', installinfo)
        if munkicommon.stopRequested():
            return 0

        # reset progress indicator and detail field
        munkistatus.message('Checking for additional changes...')
        munkistatus.percent('-1')
        munkistatus.detail('')

        # now generate a list of items to be uninstalled
        munkicommon.display_detail('**Checking for removals**')
        processManifestForKey(
            mainmanifestpath, 'managed_uninstalls', installinfo)
        if munkicommon.stopRequested():
            return 0

        # now check for implicit removals
        # use catalogs from main manifest
        cataloglist = manifestutils.get_manifest_value_for_key(
            mainmanifestpath, 'catalogs')
        autoremovalitems = catalogs.get_auto_removal_items(installinfo, cataloglist)
        if autoremovalitems:
            munkicommon.display_detail('**Checking for implicit removals**')
        for item in autoremovalitems:
            if munkicommon.stopRequested():
                return 0
            dummy_result = processRemoval(item, cataloglist, installinfo)

        # look for additional updates
        munkicommon.display_detail('**Checking for managed updates**')
        processManifestForKey(
            mainmanifestpath, 'managed_updates', installinfo)
        if munkicommon.stopRequested():
            return 0

        # build list of optional installs
        processManifestForKey(
            mainmanifestpath, 'optional_installs', installinfo)
        if munkicommon.stopRequested():
            return 0

        # verify available license seats for optional installs
        if installinfo.get('optional_installs'):
            licensing.update_available_license_seats(installinfo)

        # process LocalOnlyManifest installs
        localonlymanifestname = munkicommon.pref('LocalOnlyManifest')
        if localonlymanifestname:
            localonlymanifest = os.path.join(
                ManagedInstallDir, 'manifests', localonlymanifestname)

            # if the manifest already exists, the name is being reused
            if localonlymanifestname in manifestutils.manifests():
                munkicommon.display_error(
                    "LocalOnlyManifest %s has the same name as an existing "
                    "manifest, skipping...", localonlymanifestname
                )
            elif os.path.exists(localonlymanifest):
                manifestutils.set_manifest(
                    localonlymanifestname, localonlymanifest)
                # use catalogs from main manifest for local only manifest
                cataloglist = manifestutils.get_manifest_value_for_key(
                    mainmanifestpath, 'catalogs')
                munkicommon.display_detail(
                    '**Processing local-only choices**'
                )

                localonlyinstalls = manifestutils.get_manifest_value_for_key(
                    localonlymanifest, 'managed_installs') or []
                for item in localonlyinstalls:
                    dummy_result = processInstall(
                        item,
                        cataloglist,
                        installinfo
                    )

                localonlyuninstalls = manifestutils.get_manifest_value_for_key(
                    localonlymanifest, 'managed_uninstalls') or []
                for item in localonlyuninstalls:
                    dummy_result = processRemoval(
                        item,
                        cataloglist,
                        installinfo
                    )
            else:
                munkicommon.display_debug1(
                    "LocalOnlyManifest %s is set but is not present. "
                    "Skipping...", localonlymanifestname
                )

        # now process any self-serve choices
        usermanifest = '/Users/Shared/.SelfServeManifest'
        selfservemanifest = os.path.join(
            ManagedInstallDir, 'manifests', 'SelfServeManifest')
        if os.path.exists(usermanifest):
            # copy user-generated SelfServeManifest to our
            # ManagedInstallDir
            try:
                plist = FoundationPlist.readPlist(usermanifest)
                if plist:
                    FoundationPlist.writePlist(plist, selfservemanifest)
                    # now remove the user-generated manifest
                    try:
                        os.unlink(usermanifest)
                    except OSError:
                        pass
            except FoundationPlist.FoundationPlistException:
                # problem reading the usermanifest
                # better remove it
                munkicommon.display_error('Could not read %s', usermanifest)
                try:
                    os.unlink(usermanifest)
                except OSError:
                    pass

        if os.path.exists(selfservemanifest):
            # use catalogs from main manifest for self-serve manifest
            cataloglist = manifestutils.get_manifest_value_for_key(
                mainmanifestpath, 'catalogs')
            munkicommon.display_detail('**Processing self-serve choices**')
            selfserveinstalls = manifestutils.get_manifest_value_for_key(
                selfservemanifest, 'managed_installs')

            # build list of items in the optional_installs list
            # that have not exceeded available seats
            available_optional_installs = [
                item['name']
                for item in installinfo.get('optional_installs', [])
                if (not 'licensed_seats_available' in item
                    or item['licensed_seats_available'])]
            if selfserveinstalls:
                # filter the list, removing any items not in the current list
                # of available self-serve installs
                selfserveinstalls = [item for item in selfserveinstalls
                                     if item in available_optional_installs]
                for item in selfserveinstalls:
                    dummy_result = processInstall(
                        item, cataloglist, installinfo)

            # we don't need to filter uninstalls
            selfserveuninstalls = manifestutils.get_manifest_value_for_key(
                selfservemanifest, 'managed_uninstalls') or []
            for item in selfserveuninstalls:
                dummy_result = processRemoval(item, cataloglist, installinfo)

            # update optional_installs with install/removal info
            for item in installinfo['optional_installs']:
                if (not item.get('installed') and
                        isItemInInstallInfo(
                            item, installinfo['managed_installs'])):
                    item['will_be_installed'] = True
                elif (item.get('installed') and
                      isItemInInstallInfo(item, installinfo['removals'])):
                    item['will_be_removed'] = True

        # filter managed_installs to get items already installed
        installed_items = [item.get('name', '')
                           for item in installinfo['managed_installs']
                           if item.get('installed')]
        # filter managed_installs to get problem items:
        # not installed, but no installer item
        problem_items = [item
                         for item in installinfo['managed_installs']
                         if item.get('installed') is False and
                         not item.get('installer_item')]
        # filter removals to get items already removed
        # (or never installed)
        removed_items = [item.get('name', '')
                         for item in installinfo['removals']
                         if item.get('installed') is False]

        if os.path.exists(selfservemanifest):
            # for any item in the managed_uninstalls in the self-serve
            # manifest that is not installed, we should remove it from
            # the list
            try:
                plist = FoundationPlist.readPlist(selfservemanifest)
            except FoundationPlist.FoundationPlistException:
                pass
            else:
                plist['managed_uninstalls'] = [
                    item for item in plist.get('managed_uninstalls', [])
                    if item not in removed_items]
                try:
                    FoundationPlist.writePlist(plist, selfservemanifest)
                except FoundationPlist.FoundationPlistException:
                    pass

        # record detail before we throw it away...
        munkicommon.report['ManagedInstalls'] = installinfo['managed_installs']
        munkicommon.report['InstalledItems'] = installed_items
        munkicommon.report['ProblemInstalls'] = problem_items
        munkicommon.report['RemovedItems'] = removed_items

        munkicommon.report['managed_installs_list'] = installinfo[
            'processed_installs']
        munkicommon.report['managed_uninstalls_list'] = installinfo[
            'processed_uninstalls']
        munkicommon.report['managed_updates_list'] = installinfo[
            'managed_updates']

        # filter managed_installs and removals lists
        # so they have only items that need action
        installinfo['managed_installs'] = [
            item for item in installinfo['managed_installs']
            if item.get('installer_item')]
        installinfo['removals'] = [
            item for item in installinfo['removals']
            if item.get('installed')]

        # also record problem items so MSC.app can provide feedback
        installinfo['problem_items'] = problem_items

        # download display icons for optional installs
        # and active installs/removals
        item_list = list(installinfo.get('optional_installs', []))
        item_list.extend(installinfo['managed_installs'])
        item_list.extend(installinfo['removals'])
        download.download_icons(item_list)

        # get any custom client resources
        download.download_client_resources()

        # record the filtered lists
        munkicommon.report['ItemsToInstall'] = installinfo['managed_installs']
        munkicommon.report['ItemsToRemove'] = installinfo['removals']

        # clean up catalogs directory
        catalogs.clean_up()

        # clean up manifests directory
        manifestutils.clean_up_manifests()

        # clean up cache dir
        # remove any item in the cache that isn't scheduled
        # to be used for an install or removal
        # this could happen if an item is downloaded on one
        # updatecheck run, but later removed from the manifest
        # before it is installed or removed - so the cached item
        # is no longer needed.
        cache_list = [item['installer_item']
                      for item in installinfo.get('managed_installs', [])]
        cache_list.extend([item['uninstaller_item']
                           for item in installinfo.get('removals', [])
                           if item.get('uninstaller_item')])
        cachedir = os.path.join(ManagedInstallDir, 'Cache')
        for item in munkicommon.listdir(cachedir):
            if item.endswith('.download'):
                # we have a partial download here
                # remove the '.download' from the end of the filename
                fullitem = os.path.splitext(item)[0]
                if os.path.exists(os.path.join(cachedir, fullitem)):
                    # we have a partial and a full download
                    # for the same item. (This shouldn't happen.)
                    # remove the partial download.
                    os.unlink(os.path.join(cachedir, item))
                elif problem_items == []:
                    # problem items is our list of items
                    # that need to be installed but are missing
                    # the installer_item; these might be partial
                    # downloads. So if we have no problem items, it's
                    # OK to get rid of any partial downloads hanging
                    # around.
                    os.unlink(os.path.join(cachedir, item))
            elif item not in cache_list:
                munkicommon.display_detail('Removing %s from cache', item)
                os.unlink(os.path.join(cachedir, item))

        # write out install list so our installer
        # can use it to install things in the right order
        installinfochanged = True
        installinfopath = os.path.join(ManagedInstallDir, 'InstallInfo.plist')
        if os.path.exists(installinfopath):
            try:
                oldinstallinfo = FoundationPlist.readPlist(installinfopath)
            except FoundationPlist.NSPropertyListSerializationException:
                oldinstallinfo = None
                munkicommon.display_error(
                    'Could not read InstallInfo.plist. Deleting...')
                try:
                    os.unlink(installinfopath)
                except OSError, err:
                    munkicommon.display_error(
                        'Failed to delete InstallInfo.plist: %s', str(err))
            if oldinstallinfo == installinfo:
                installinfochanged = False
                munkicommon.display_detail('No change in InstallInfo.')

        if installinfochanged:
            FoundationPlist.writePlist(
                installinfo,
                os.path.join(ManagedInstallDir, 'InstallInfo.plist'))

    except (manifestutils.ManifestException, UpdateCheckAbortedError):
        # Update check aborted. Check to see if we have a valid
        # install/remove list from an earlier run.
        installinfopath = os.path.join(ManagedInstallDir, 'InstallInfo.plist')
        if os.path.exists(installinfopath):
            try:
                installinfo = FoundationPlist.readPlist(installinfopath)
            except FoundationPlist.NSPropertyListSerializationException:
                installinfo = {}
            munkicommon.report['ItemsToInstall'] = \
                installinfo.get('managed_installs', [])
            munkicommon.report['ItemsToRemove'] = \
                installinfo.get('removals', [])

    munkicommon.savereport()
    munkicommon.log('###    End managed software check    ###')

    installcount = len(installinfo.get('managed_installs', []))
    removalcount = len(installinfo.get('removals', []))

    if installcount or removalcount:
        return 1
    else:
        return 0


def getPrimaryManifestCatalogs(client_id='', force_refresh=False):
    """Return list of catalogs from primary client manifest

    Args:
      force_refresh: Boolean. If True, downloads primary manifest
      and listed catalogs; False, uses locally cached information.
    Returns:
      cataloglist: list of catalogs from primary manifest
    """
    cataloglist = []
    if (force_refresh or
            manifestutils.PRIMARY_MANIFEST_TAG
            not in manifestutils.manifests()):
        # Fetch manifest from repo
        manifest = manifestutils.get_primary_manifest(client_id)
        # set force_refresh = True so we'll also download any missing catalogs
        force_refresh = True
    else:
        # Use cached manifest if available
        manifest_dir = os.path.join(
            munkicommon.pref('ManagedInstallDir'), 'manifests')
        manifest = os.path.join(
            manifest_dir,
            manifestutils.get_manifest(manifestutils.PRIMARY_MANIFEST_TAG))

    if manifest:
        manifestdata = manifestutils.get_manifest_data(manifest)
        cataloglist = manifestdata.get('catalogs')
        if cataloglist and force_refresh:
            # download catalogs since we might not have them
            catalogs.get_catalogs(cataloglist)

    return cataloglist


if __name__ == '__main__':
    print 'This is a library of support tools for the Munki Suite.'
