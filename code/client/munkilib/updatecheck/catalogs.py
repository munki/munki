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
updatecheck.catalogs

Created by Greg Neagle on 2017-01-01.

Functions for working with Munki catalogs
"""
from __future__ import absolute_import, print_function

import os
import unicodedata

from . import download

from .. import display
from .. import info
from .. import pkgutils
from .. import prefs
from .. import utils
from .. import FoundationPlist
from ..wrappers import is_a_string


def make_catalog_db(catalogitems):
    """Takes an array of catalog items and builds some indexes so we can
    get our common data faster. Returns a dict we can use like a database"""
    name_table = {}
    pkgid_table = {}

    itemindex = -1
    for item in catalogitems:
        itemindex = itemindex + 1
        name = item.get('name', 'NO NAME')
        vers = item.get('version', 'NO VERSION')

        if name == 'NO NAME' or vers == 'NO VERSION':
            display.display_warning('Bad pkginfo: %s', item)

        # normalize the version number
        vers = pkgutils.trim_version_string(vers)
        
        # unicode normalize the name 
        name = unicodedata.normalize("NFC", name)

        # build indexes for items by name and version
        if not name in name_table:
            name_table[name] = {}
        if not vers in name_table[name]:
            name_table[name][vers] = []
        name_table[name][vers].append(itemindex)

        # build table of receipts
        for receipt in item.get('receipts', []):
            if 'packageid' in receipt and 'version' in receipt:
                pkg_id = receipt['packageid']
                version = receipt['version']
                if not pkg_id in pkgid_table:
                    pkgid_table[pkg_id] = {}
                if not version in pkgid_table[pkg_id]:
                    pkgid_table[pkg_id][version] = []
                pkgid_table[pkg_id][version].append(itemindex)

    # build table of update items with a list comprehension --
    # filter all items from the catalogitems that have a non-empty
    # 'update_for' list
    updaters = [item for item in catalogitems if item.get('update_for')]

    # now fix possible admin errors where 'update_for' is a string instead
    # of a list of strings
    for update in updaters:
        if is_a_string(update['update_for']):
            # convert to list of strings
            update['update_for'] = [update['update_for']]

    # build table of autoremove items with a list comprehension --
    # filter all items from the catalogitems that have a non-empty
    # 'autoremove' list
    # autoremove items are automatically removed if they are not in the
    # managed_install list (either directly or indirectly via included
    # manifests)
    autoremoveitems = [item.get('name') for item in catalogitems
                       if item.get('autoremove')]
    # convert to set and back to list to get list of unique names
    autoremoveitems = list(set(autoremoveitems))

    pkgdb = {}
    pkgdb['named'] = name_table
    pkgdb['receipts'] = pkgid_table
    pkgdb['updaters'] = updaters
    pkgdb['autoremoveitems'] = autoremoveitems
    pkgdb['items'] = catalogitems

    return pkgdb


def add_package_ids(catalogitems, itemname_to_pkgid, pkgid_to_itemname):
    """Adds packageids from each catalogitem to two dictionaries.
    One maps itemnames to receipt pkgids, the other maps receipt pkgids
    to itemnames"""
    for item in catalogitems:
        name = item.get('name')
        if not name:
            continue
        if item.get('receipts'):
            if not name in itemname_to_pkgid:
                itemname_to_pkgid[name] = {}

            for receipt in item['receipts']:
                if 'packageid' in receipt and 'version' in receipt:
                    pkgid = receipt['packageid']
                    vers = receipt['version']
                    if not pkgid in itemname_to_pkgid[name]:
                        itemname_to_pkgid[name][pkgid] = []
                    if not vers in itemname_to_pkgid[name][pkgid]:
                        itemname_to_pkgid[name][pkgid].append(vers)

                    if not pkgid in pkgid_to_itemname:
                        pkgid_to_itemname[pkgid] = {}
                    if not name in pkgid_to_itemname[pkgid]:
                        pkgid_to_itemname[pkgid][name] = []
                    if not vers in pkgid_to_itemname[pkgid][name]:
                        pkgid_to_itemname[pkgid][name].append(vers)


def split_name_and_version(some_string):
    """Splits a string into the name and version number.

    Name and version must be separated with a hyphen ('-')
    or double hyphen ('--').
    'TextWrangler-2.3b1' becomes ('TextWrangler', '2.3b1')
    'AdobePhotoshopCS3--11.2.1' becomes ('AdobePhotoshopCS3', '11.2.1')
    'MicrosoftOffice2008-12.2.1' becomes ('MicrosoftOffice2008', '12.2.1')
    """
    for delim in ('--', '-'):
        if some_string.count(delim) > 0:
            chunks = some_string.split(delim)
            vers = chunks.pop()
            name = delim.join(chunks)
            if vers and vers[0] in '0123456789':
                return (name, vers)

    return (some_string, '')


def get_all_items_with_name(name, cataloglist):
    """Searches the catalogs in a list for all items matching a given name.

    Returns:
      list of pkginfo items; sorted with newest version first. No precedence
      is given to catalog order.
    """

    def item_version(item):
        """Returns a MunkiLooseVersion for pkginfo item"""
        return pkgutils.MunkiLooseVersion(item['version'])

    itemlist = []
    # we'll throw away any included version info
    name = split_name_and_version(name)[0]

    display.display_debug1('Looking for all items matching: %s...', name)
    for catalogname in cataloglist:
        if not catalogname in list(_CATALOG.keys()):
            # in case catalogname refers to a non-existent catalog...
            continue
        # is name in the catalog name table?
        if name in _CATALOG[catalogname]['named']:
            versionsmatchingname = _CATALOG[catalogname]['named'][name]
            for vers in versionsmatchingname:
                if vers == 'latest':
                    continue
                indexlist = _CATALOG[catalogname]['named'][name][vers]
                for index in indexlist:
                    thisitem = _CATALOG[catalogname]['items'][index]
                    if not thisitem in itemlist:
                        display.display_debug1(
                            'Adding item %s, version %s from catalog %s...',
                            name, thisitem['version'], catalogname)
                        itemlist.append(thisitem)

    if itemlist:
        # sort so latest version is first
        itemlist.sort(key=item_version, reverse=True)
    return itemlist


def get_auto_removal_items(installinfo, cataloglist):
    """Gets a list of items marked for automatic removal from the catalogs
    in cataloglist. Filters those against items in the processed_installs
    list, which should contain everything that is supposed to be installed.
    Then filters against the removals list, which contains all the removals
    that have already been processed.
    """
    autoremovalnames = []
    for catalogname in cataloglist or []:
        if catalogname in list(_CATALOG.keys()):
            autoremovalnames += _CATALOG[catalogname]['autoremoveitems']

    processed_installs_names = [split_name_and_version(item)[0]
                                for item in installinfo['processed_installs']]
    autoremovalnames = [item for item in autoremovalnames
                        if item not in processed_installs_names
                        and item not in installinfo['processed_uninstalls']]
    return autoremovalnames


def look_for_updates(itemname, cataloglist):
    """Looks for updates for a given manifest item that is either
    installed or scheduled to be installed or removed. This handles not only
    specific application updates, but also updates that aren't simply
    later versions of the manifest item.
    For example, AdobeCameraRaw is an update for Adobe Photoshop, but
    doesn't update the version of Adobe Photoshop.
    Returns a list of manifestitem names that are updates for
    manifestitem.
    """

    display.display_debug1('Looking for updates for: %s', itemname)
    # get a list of catalog items that are updates for other items
    update_list = []
    for catalogname in cataloglist:
        if catalogname not in _CATALOG:
            # in case the list refers to a non-existent catalog
            continue

        updaters = _CATALOG[catalogname]['updaters']
        # list comprehension coming up...
        update_items = [catalogitem['name']
                        for catalogitem in updaters
                        if itemname in catalogitem.get('update_for', [])]
        if update_items:
            update_list.extend(update_items)

    # make sure the list has only unique items:
    update_list = list(set(update_list))

    if update_list:
        # updates were found, so let's display them
        num_updates = len(update_list)
        # format the update list for better on-screen viewing
        update_list_display = ", ".join(str(x) for x in update_list)
        display.display_debug1(
            'Found %s update(s): %s', num_updates, update_list_display)

    return update_list


def look_for_updates_for_version(itemname, itemversion, cataloglist):
    """Looks for updates for a specific version of an item. Since these
    can appear in manifests and pkginfo as item-version or item--version
    we have to search twice."""

    name_and_version = '%s-%s' % (itemname, itemversion)
    alt_name_and_version = '%s--%s' % (itemname, itemversion)
    update_list = look_for_updates(name_and_version, cataloglist)
    update_list.extend(look_for_updates(alt_name_and_version, cataloglist))

    # make sure the list has only unique items:
    update_list = list(set(update_list))

    return update_list


def best_version_match(vers_num, item_dict):
    '''Attempts to find the best match in item_dict for vers_num'''
    vers_tuple = vers_num.split('.')
    precision = 1
    while precision <= len(vers_tuple):
        test_vers = '.'.join(vers_tuple[0:precision])
        match_names = []
        for item in item_dict.keys():
            for item_version in item_dict[item]:
                if (item_version.startswith(test_vers) and
                        item not in match_names):
                    match_names.append(item)
        if len(match_names) == 1:
            return match_names[0]
        precision = precision + 1

    return None


@utils.Memoize
def analyze_installed_pkgs():
    """Analyze catalog data and installed packages in an attempt to determine
    what is installed."""
    pkgdata = {}
    itemname_to_pkgid = {}
    pkgid_to_itemname = {}
    for catalogname in _CATALOG:
        catalogitems = _CATALOG[catalogname]['items']
        add_package_ids(catalogitems, itemname_to_pkgid, pkgid_to_itemname)
    # itemname_to_pkgid now contains all receipts (pkgids) we know about
    # from items in all available catalogs

    installedpkgs = pkgutils.getInstalledPackages()

    installed = []
    partiallyinstalled = []
    installedpkgsmatchedtoname = {}
    for name in itemname_to_pkgid:
        # name is a Munki install item name
        foundpkgcount = 0
        for pkgid in itemname_to_pkgid[name]:
            if pkgid in installedpkgs:
                foundpkgcount += 1
                if not name in installedpkgsmatchedtoname:
                    installedpkgsmatchedtoname[name] = []
                # record this pkgid for Munki install item name
                installedpkgsmatchedtoname[name].append(pkgid)
        if foundpkgcount > 0:
            if foundpkgcount == len(itemname_to_pkgid[name]):
                # we found all receipts by pkgid on disk
                installed.append(name)
            else:
                # we found only some receipts for the item
                # on disk
                partiallyinstalled.append(name)

    # we pay special attention to the items that seem partially installed.
    # we need to see if there are any packages that are unique to this item
    # if there aren't, then this item probably isn't installed, and we're
    # just finding receipts that are shared with other items.
    for name in partiallyinstalled:
        # get a list of pkgs for this item that are installed
        pkgsforthisname = installedpkgsmatchedtoname[name]
        # now build a list of all the pkgs referred to by all the other
        # items that are either partially or entirely installed
        allotherpkgs = []
        for othername in installed:
            allotherpkgs.extend(installedpkgsmatchedtoname[othername])
        for othername in partiallyinstalled:
            if othername != name:
                allotherpkgs.extend(installedpkgsmatchedtoname[othername])
        # use Python sets to find pkgs that are unique to this name
        uniquepkgs = list(set(pkgsforthisname) - set(allotherpkgs))
        if uniquepkgs:
            installed.append(name)

    # now filter partiallyinstalled to remove those items we moved to installed
    partiallyinstalled = [item for item in partiallyinstalled
                          if item not in installed]

    # build our reference table. For each item we think is installed,
    # record the receipts on disk matched to the item
    references = {}
    for name in installed:
        for pkgid in installedpkgsmatchedtoname[name]:
            if not pkgid in references:
                references[pkgid] = []
            references[pkgid].append(name)

    # look through all our installedpkgs, looking for ones that have not been
    # attached to any Munki names yet
    orphans = [pkgid for pkgid in installedpkgs if pkgid not in references]

    # attempt to match orphans to Munki item names
    matched_orphans = []
    for pkgid in orphans:
        if pkgid in pkgid_to_itemname:
            installed_pkgid_version = installedpkgs[pkgid]
            possible_match_items = pkgid_to_itemname[pkgid]
            best_match = best_version_match(
                installed_pkgid_version, possible_match_items)
            if best_match:
                matched_orphans.append(best_match)

    # process matched_orphans
    for name in matched_orphans:
        if name not in installed:
            installed.append(name)
        if name in partiallyinstalled:
            partiallyinstalled.remove(name)
        for pkgid in installedpkgsmatchedtoname[name]:
            if not pkgid in references:
                references[pkgid] = []
            if not name in references[pkgid]:
                references[pkgid].append(name)

    pkgdata['receipts_for_name'] = installedpkgsmatchedtoname
    pkgdata['installed_names'] = installed
    pkgdata['pkg_references'] = references

    # left here for future debugging/testing use....
    #pkgdata['itemname_to_pkgid'] = itemname_to_pkgid
    #pkgdata['pkgid_to_itemname'] = pkgid_to_itemname
    #pkgdata['partiallyinstalled_names'] = partiallyinstalled
    #pkgdata['orphans'] = orphans
    #pkgdata['matched_orphans'] = matched_orphans
    #ManagedInstallDir = prefs.pref('ManagedInstallDir')
    #pkgdatapath = os.path.join(ManagedInstallDir, 'PackageData.plist')
    #try:
    #    FoundationPlist.writePlist(pkgdata, pkgdatapath)
    #except FoundationPlist.NSPropertyListWriteException:
    #    pass
    #catalogdbpath =  os.path.join(ManagedInstallDir, 'CatalogDB.plist')
    #try:
    #    FoundationPlist.writePlist(CATALOG, catalogdbpath)
    #except FoundationPlist.NSPropertyListWriteException:
    #    pass
    return pkgdata


def get_item_detail(name, cataloglist, vers='',
                    skip_min_os_check=False, suppress_warnings=False):
    """Searches the catalogs in list for an item matching the given name that
    can be installed on the current hardware/OS (optionally skipping the
    minimum OS check so we can return an item that requires a higher OS)

    If no version is supplied, but the version is appended to the name
    ('TextWrangler--2.3.0.0.0') that version is used.
    If no version is given at all, the latest version is assumed.
    Returns a pkginfo item, or None.
    """

    rejected_items = []
    machine = info.getMachineFacts()
    # condition check functions
    def munki_version_ok(item):
        '''Returns a boolean to indicate if the current Munki version is high
        enough to install this item. If not, also adds the failure reason to
        the rejected_items list.'''
        if item.get('minimum_munki_version'):
            min_munki_vers = item['minimum_munki_version']
            display.display_debug1(
                'Considering item %s, version %s '
                'with minimum Munki version required %s',
                item['name'], item['version'], min_munki_vers)
            display.display_debug1(
                'Our Munki version is %s', machine['munki_version'])
            if (pkgutils.MunkiLooseVersion(machine['munki_version'])
                    < pkgutils.MunkiLooseVersion(min_munki_vers)):
                reason = (
                    'Rejected item %s, version %s with minimum Munki version '
                    'required %s. Our Munki version is %s.'
                    % (item['name'], item['version'],
                       item['minimum_munki_version'], machine['munki_version']))
                rejected_items.append(reason)
                return False
        return True

    def os_version_ok(item, skip_min_os_check=False):
        '''Returns a boolean to indicate if the item is ok to install under
        the current OS. If not, also adds the failure reason to the
        rejected_items list. If skip_min_os_check is True, skips the minimum os
        version check.'''
        # Is the current OS version >= minimum_os_version for the item?
        if item.get('minimum_os_version') and not skip_min_os_check:
            min_os_vers = item['minimum_os_version']
            display.display_debug1(
                'Considering item %s, version %s '
                'with minimum os version required %s',
                item['name'], item['version'], min_os_vers)
            display.display_debug1(
                'Our OS version is %s', machine['os_vers'])
            if (pkgutils.MunkiLooseVersion(machine['os_vers']) <
                    pkgutils.MunkiLooseVersion(min_os_vers)):
                # skip this one, go to the next
                reason = (
                    'Rejected item %s, version %s with minimum os version '
                    'required %s. Our OS version is %s.'
                    % (item['name'], item['version'],
                       item['minimum_os_version'], machine['os_vers']))
                rejected_items.append(reason)
                return False

        # current OS version <= maximum_os_version?
        if item.get('maximum_os_version'):
            max_os_vers = item['maximum_os_version']
            display.display_debug1(
                'Considering item %s, version %s '
                'with maximum os version supported %s',
                item['name'], item['version'], max_os_vers)
            display.display_debug1(
                'Our OS version is %s', machine['os_vers'])
            if (pkgutils.MunkiLooseVersion(machine['os_vers']) >
                    pkgutils.MunkiLooseVersion(max_os_vers)):
                # skip this one, go to the next
                reason = (
                    'Rejected item %s, version %s with maximum os version '
                    'required %s. Our OS version is %s.'
                    % (item['name'], item['version'],
                       item['maximum_os_version'], machine['os_vers']))
                rejected_items.append(reason)
                return False
        return True

    def cpu_arch_ok(item):
        '''Returns a boolean to indicate if the item is ok to install under
        the current CPU architecture. If not, also adds the failure reason to
        the rejected_items list.'''

        if item.get('supported_architectures'):
            display.display_debug1(
                'Considering item %s, version %s '
                'with supported architectures: %s',
                item['name'], item['version'], item['supported_architectures'])
            display.display_debug1(
                'Our architecture is %s', machine['arch'])
            if machine['arch'] in item['supported_architectures']:
                return True
            if ('x86_64' in item['supported_architectures'] and
                    machine['arch'] == 'i386' and
                    machine['x86_64_capable'] is True):
                return True

            # we didn't find a supported architecture that
            # matches this machine
            reason = (
                'Rejected item %s, version %s with supported architectures: '
                '%s. Our architecture is %s.'
                % (item['name'], item['version'],
                   item['supported_architectures'], machine['arch']))
            rejected_items.append(reason)
            return False
        return True

    def installable_condition_ok(item):
        '''Returns a boolean to indicate if an installable_condition predicate
        in the current item passes. If not, also adds the failure reason to
        the rejected_items list.'''

        if item.get('installable_condition'):
            if not info.predicate_evaluates_as_true(
                    item['installable_condition']):
                rejected_items.append(
                    'Rejected item %s, version %s with installable_condition: '
                    '%s.' % (item['name'], item['version'],
                             item['installable_condition']))
                return False
        return True

    if vers == 'apple_update_metadata':
        vers = 'latest'
    else:
        (name, includedversion) = split_name_and_version(name)
        if includedversion and vers == '':
            vers = includedversion
        if vers:
            vers = pkgutils.trim_version_string(vers)
        else:
            vers = 'latest'

    if skip_min_os_check:
        display.display_debug1(
            'Looking for detail for: %s, version %s, '
            'ignoring minimum_os_version...', name, vers)
    else:
        display.display_debug1(
            'Looking for detail for: %s, version %s...', name, vers)

    for catalogname in cataloglist:
        # is name in the catalog?
        name = unicodedata.normalize("NFC", name)
        if catalogname in _CATALOG and name in _CATALOG[catalogname]['named']:
            itemsmatchingname = _CATALOG[catalogname]['named'][name]
            indexlist = []
            if vers == 'latest':
                # order all our items, highest version first
                versionlist = list(itemsmatchingname.keys())
                versionlist.sort(key=pkgutils.MunkiLooseVersion, reverse=True)
                for versionkey in versionlist:
                    indexlist.extend(itemsmatchingname[versionkey])
            elif vers in list(itemsmatchingname.keys()):
                # get the specific requested version
                indexlist = itemsmatchingname[vers]

            if indexlist:
                display.display_debug1(
                    'Considering %s items with name %s from catalog %s' %
                    (len(indexlist), name, catalogname))
            for index in indexlist:
                # iterate through list of items with matching name, highest
                # version first, looking for first one that passes all the
                # conditional tests (if any)
                item = _CATALOG[catalogname]['items'][index]
                if (munki_version_ok(item) and
                        os_version_ok(item,
                                      skip_min_os_check=skip_min_os_check) and
                        cpu_arch_ok(item) and
                        installable_condition_ok(item)):
                    display.display_debug1(
                        'Found %s, version %s in catalog %s',
                        item['name'], item['version'], catalogname)
                    return item

    # if we got this far, we didn't find it.
    display.display_debug1('Not found')
    for reason in rejected_items:
        if suppress_warnings:
            display.display_debug1(reason)
        else:
            display.display_warning(reason)
    return None


# global to hold our catalog DBs
_CATALOG = {}
def get_catalogs(cataloglist):
    """Retrieves the catalogs from the server and populates our catalogs
    dictionary.
    """
    #global _CATALOG
    for catalogname in cataloglist:
        if not catalogname in _CATALOG:
            catalogpath = download.download_catalog(catalogname)
            if catalogpath:
                try:
                    catalogdata = FoundationPlist.readPlist(catalogpath)
                except FoundationPlist.NSPropertyListSerializationException:
                    display.display_error(
                        'Retrieved catalog %s is invalid.', catalogname)
                    try:
                        os.unlink(catalogpath)
                    except (OSError, IOError):
                        pass
                else:
                    _CATALOG[catalogname] = make_catalog_db(catalogdata)


def clean_up():
    """Removes any catalog files that are no longer in use by this client"""
    catalog_dir = os.path.join(prefs.pref('ManagedInstallDir'),
                               'catalogs')
    for item in os.listdir(catalog_dir):
        if item not in _CATALOG:
            os.unlink(os.path.join(catalog_dir, item))


def catalogs():
    '''Returns our internal _CATALOG dict'''
    return _CATALOG


if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
