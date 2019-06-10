# encoding: utf-8
#
# Copyright 2017-2019 Greg Neagle.
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
makecatalogslib

Created by Greg Neagle on 2017-11-19.
Routines used by makecatalogs
"""
from __future__ import absolute_import, print_function

# std libs
import hashlib
import os

# our libs
from .common import list_items_of_kind, AttributeDict
from ..colors import colorize
from .. import munkirepo
from ..wrappers import readPlistFromString, writePlistToString
from ..colorize import colorize


class MakeCatalogsError(Exception):
    '''Error to raise when there is problem making catalogs'''
    pass


def hash_icons(repo, options, output_fn=None):
    '''Builds a dictionary containing hashes for all our repo icons'''
    errors = []
    icons = {}
    color = options.color
    ENDC = color['end']
    if output_fn:
        output_fn("Getting list of icons...")
    icon_list = repo.itemlist('icons')
    # Don't hash the hashes, they aren't icons.
    if '_icon_hashes.plist' in icon_list:
        icon_list.remove('_icon_hashes.plist')
    for icon_ref in icon_list:
        if output_fn:
            output_fn(
                color['ok_green'] + "Hashing " + ENDC +
                "%s..." % (icon_ref))
        # Try to read the icon file
        try:
            icondata = repo.get('icons/' + icon_ref)
            icons[icon_ref] = hashlib.sha256(icondata).hexdigest()
        except munkirepo.RepoError as err:
            errors.append(u'RepoError for %s: %s' % (icon_ref, unicode(err)))
        except IOError as err:
            errors.append(u'IO error for %s: %s' % (icon_ref, err))
        except BaseException as err:
            errors.append(u'Unexpected error for %s: %s' % (icon_ref, err))
    return icons, errors


def verify_pkginfo(pkginfo_ref, pkginfo, pkgs_list, errors, options):
    '''Returns True if referenced installer items are present,
    False otherwise. Adds errors/warnings to the errors list'''
    WARNC = options.color['warning']
    ENDC = options.color['end']
    installer_type = pkginfo.get('installer_type')
    if installer_type in ['nopkg', 'apple_update_metadata']:
        # no associated installer item (pkg) for these types
        return True
    if pkginfo.get('PackageCompleteURL') or pkginfo.get('PackageURL'):
        # installer item may be on a different server
        return True

    if not 'installer_item_location' in pkginfo:
        errors.append(
            WARNC + "WARNING: " + ENDC + "%s is missing installer_item_location" 
            % pkginfo_ref)
        return False

    # Try to form a path and fail if the
    # installer_item_location is not a valid type
    try:
        installeritempath = os.path.join(
            "pkgs", pkginfo['installer_item_location'])
    except TypeError:
        errors.append(
            WARNC + "WARNING: " + ENDC + "invalid installer_item_location in %s"
            % pkginfo_ref)
        return False

    # Check if the installer item actually exists
    if not installeritempath in pkgs_list:
        # do a case-insensitive comparison
        found_caseinsensitive_match = False
        for repo_pkg in pkgs_list:
            if installeritempath.lower() == repo_pkg.lower():
                errors.append(
                    WARNC + "WARNING: " + ENDC +
                    "%s refers to installer item: %s. "
                    "The pathname of the item in the repo has "
                    "different case: %s. This may cause issues "
                    "depending on the case-sensitivity of the "
                    "underlying filesystem."
                    % (pkginfo_ref,
                       pkginfo['installer_item_location'], repo_pkg))
                found_caseinsensitive_match = True
                break
        if not found_caseinsensitive_match:
            errors.append(
                WARNC + "WARNING: " + ENDC +
                "%s refers to missing installer item: %s"
                % (pkginfo_ref, pkginfo['installer_item_location']))
            return False

    #uninstaller sanity checking
    uninstaller_type = pkginfo.get('uninstall_method')
    if uninstaller_type in ['AdobeCCPUninstaller']:
        # uninstaller_item_location is required
        if not 'uninstaller_item_location' in pkginfo:
            errors.append(
                WARNC + "WARNING: " + ENDC +
                "%s is missing uninstaller_item_location"
                % pkginfo_ref)
            return False

    # if an uninstaller_item_location is specified, sanity-check it
    if 'uninstaller_item_location' in pkginfo:
        try:
            uninstalleritempath = os.path.join(
                "pkgs", pkginfo['uninstaller_item_location'])
        except TypeError:
            errors.append(
                WARNC + "WARNING: " + ENDC +
                "invalid uninstaller_item_location "
                "in %s" % pkginfo_ref)
            return False

        # Check if the uninstaller item actually exists
        if not uninstalleritempath in pkgs_list:
            # do a case-insensitive comparison
            found_caseinsensitive_match = False
            for repo_pkg in pkgs_list:
                if uninstalleritempath.lower() == repo_pkg.lower():
                    errors.append(
                        WARNC + "WARNING: " + ENDC +
                        "%s refers to uninstaller item: %s. "
                        "The pathname of the item in the repo has "
                        "different case: %s. This may cause issues "
                        "depending on the case-sensitivity of the "
                        "underlying filesystem."
                        % (pkginfo_ref,
                           pkginfo['uninstaller_item_location'], repo_pkg))
                    found_caseinsensitive_match = True
                    break
            if not found_caseinsensitive_match:
                errors.append(
                    WARNC + "WARNING: " + ENDC +
                    "%s refers to missing uninstaller item: %s"
                    % (pkginfo_ref, pkginfo['uninstaller_item_location']))
                return False

    # if we get here we passed all the checks
    return True


def process_pkgsinfo(repo, options, output_fn=None):
    '''Processes pkginfo files and returns a dictionary of catalogs'''
    errors = []
    catalogs = {}
    color =  options.color
    ENDC = color['end']
    # get a list of pkgsinfo items
    if output_fn:
        output_fn("Getting list of pkgsinfo...")
    try:
        pkgsinfo_list = list_items_of_kind(repo, 'pkgsinfo')
    except munkirepo.RepoError as err:
        raise MakeCatalogsError(
            color['fail'] + "Error getting list of pkgsinfo items: " + ENDC + 
            "%s" % unicode(err))

    # get a list of pkgs items
    if output_fn:
        output_fn("Getting list of pkgs...")
    try:
        pkgs_list = list_items_of_kind(repo, 'pkgs')
    except munkirepo.RepoError as err:
        raise MakeCatalogsError(
            color['fail'] + "Error getting list of pkgs items: " + ENDC +
            "%s" % unicode(err))

    # start with empty catalogs dict
    catalogs = {}
    catalogs['all'] = []

    # Walk through the pkginfo files
    for pkginfo_ref in pkgsinfo_list:
        # Try to read the pkginfo file
        try:
            data = repo.get(pkginfo_ref)
            pkginfo = readPlistFromString(data)
        except IOError as err:
            errors.append("IO error for %s: %s" % (pkginfo_ref, err))
            continue
        except BaseException as err:
            errors.append("Unexpected error for %s: %s" % (pkginfo_ref, err))
            continue

        if not 'name' in pkginfo:
            errors.append(
                color['warning'] + "WARNING: " + ENDC + 
                "%s is missing name" % pkginfo_ref)
            continue

        # don't copy admin notes to catalogs.
        if pkginfo.get('notes'):
            del pkginfo['notes']
        # strip out any keys that start with "_"
        # (example: pkginfo _metadata)
        for key in list(pkginfo.keys()):
            if key.startswith('_'):
                del pkginfo[key]

        # sanity checking
        if not options.skip_payload_check:
            verified = verify_pkginfo(pkginfo_ref, pkginfo, pkgs_list, errors, options)
            if not verified and not options.force:
                # Skip this pkginfo unless we're running with force flag
                continue

        # append the pkginfo to the relevant catalogs
        catalogs['all'].append(pkginfo)
        for catalogname in pkginfo.get("catalogs", []):
            if not catalogname:
                errors.append(
                    color['warning'] + "WARNING: " + ENDC +
                    "%s has an empty catalogs array!"
                    % pkginfo_ref)
                continue
            if not catalogname in catalogs:
                catalogs[catalogname] = []
            catalogs[catalogname].append(pkginfo)
            if output_fn:
                output_fn(
                    color['ok_green'] + "Adding " + ENDC + 
                    "%s to %s..." 
                    % (pkginfo_ref, catalogname))

    # look for catalog names that differ only in case
    duplicate_catalogs = []
    for key in catalogs:
        if key.lower() in [item.lower() for item in catalogs if item != key]:
            duplicate_catalogs.append(key)
    if duplicate_catalogs:
        errors.append(
            color['warning'] + "WARNING: " + ENDC +
            "There are catalogs with names that differ only "
            "by case. This may cause issues depending on the case-"
            "sensitivity of the underlying filesystem: %s"
            % duplicate_catalogs)

    return catalogs, errors


def makecatalogs(repo, options, output_fn=None):
    '''Assembles all pkginfo files into catalogs.
    User calling this needs to be able to write to the repo/catalogs
    directory.'''

    if isinstance(options, dict):
        options = AttributeDict(options)
    color_pref = options.color

    if os.path.exists(repo.root + "/.colorize"):
        output_fn("Color preferences set in %s./colorize" % repo.root)
        options.color = True

    options.color = colorize(options.color)
    color = options.color
    ENDC = color['end']

    icons, errors = hash_icons(repo, options, output_fn=output_fn)

    catalogs, catalog_errors = process_pkgsinfo(
        repo, options, output_fn=output_fn)

    errors.extend(catalog_errors)

    # clear out old catalogs
    try:
        catalog_list = repo.itemlist('catalogs')
    except munkirepo.RepoError:
        catalog_list = []
    for catalog_name in catalog_list:
        if catalog_name not in catalogs.keys():
            catalog_ref = os.path.join('catalogs', catalog_name)
            try:
                repo.delete(catalog_ref)
            except munkirepo.RepoError:
                errors.append(
                    color['fail'] + 'Could not delete catalog' + ENDC + '%s' 
                    % catalog_name)

    # write the new catalogs
    for key in catalogs:
        catalogpath = os.path.join("catalogs", key)
        if catalogs[key] != "":
            catalog_data = writePlistToString(catalogs[key])
            try:
                repo.put(catalogpath, catalog_data)
                if output_fn:
                    output_fn(
                        color['ok_blue'] + "Created " + ENDC + "%s..." 
                        % catalogpath)
            except munkirepo.RepoError, err:
                errors.append(
                    color['fail'] + u'Failed to create catalog' + ENDC + 
                    ' %s: %s' % (key, unicode(err)))
        else:
            errors.append(
                color['warning'] + "WARNING: " + ENDC + 
                "Did not create catalog %s because it is empty" 
                % key)

    if icons:
        icon_hashes_plist = os.path.join("icons", "_icon_hashes.plist")
        icon_hashes = writePlistToString(icons)
        try:
            repo.put(icon_hashes_plist, icon_hashes)
            print(
                color['ok_blue'] + "Created " + ENDC + "%s..." 
                % (icon_hashes_plist))
        except munkirepo.RepoError, err:
            errors.append(
                color['fail'] + u'Failed to create ' + ENDC +
                '%s: %s' 
                % (icon_hashes_plist, unicode(err)))

    # Return any errors
    return errors
