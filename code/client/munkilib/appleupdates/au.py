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
au.py

Created by Greg Neagle on 2017-01-06.

AppleUpdates object defined here
"""
# This code is largely still compatible with Python 2, so for now, turn off
# Python 3 style warnings
# pylint: disable=consider-using-f-string
# pylint: disable=redundant-u-string-prefix

from __future__ import absolute_import, print_function

import hashlib
import os
import subprocess

# PyLint cannot properly find names inside Cocoa libraries, so issues bogus
# No name 'Foo' in module 'Bar' warnings. Disable them.
# pylint: disable=E0611,E0401
from Foundation import NSDate
# pylint: enable=E0611,E0401

from . import dist
from . import su_prefs
from . import su_tool
from . import sync

from ..updatecheck import catalogs
from ..constants import POSTACTION_NONE, POSTACTION_RESTART, POSTACTION_SHUTDOWN

from .. import display
from .. import fetch
from .. import info
from .. import munkistatus
from .. import munkihash
from .. import munkilog
from .. import osutils
from .. import prefs
from .. import processes
from .. import reports
from .. import updatecheck
from .. import FoundationPlist

INSTALLHISTORY_PLIST = '/Library/Receipts/InstallHistory.plist'

def softwareupdated_installhistory(start_date=None, end_date=None):
    '''Returns softwareupdated items from InstallHistory.plist that are
    within the given date range. (dates must be NSDates)'''
    start_date = start_date or NSDate.distantPast()
    end_date = end_date or NSDate.distantFuture()
    try:
        installhistory = FoundationPlist.readPlist(INSTALLHISTORY_PLIST)
    except FoundationPlist.FoundationPlistException:
        return []
    return [item for item in installhistory
            if item.get('processName') == 'softwareupdated'
            and item['date'] >= start_date and item['date'] <= end_date]


class AppleUpdates(object):

    """Class for installation of Apple Software Updates within Munki.

    This class handles update detection, as well as downloading and installation
    of those updates.
    """

    SHUTDOWN_ACTIONS = ['RequireShutdown']
    RESTART_ACTIONS = ['RequireRestart', 'RecommendRestart']

    def __init__(self):
        self._managed_install_dir = prefs.pref('ManagedInstallDir')
        self.apple_updates_plist = os.path.join(
            self._managed_install_dir, 'AppleUpdates.plist')

        os_version_tuple = osutils.getOsVersion(as_tuple=True)
        if os_version_tuple < (10, 11):
            display.display_warning(
                'macOS versions below 10.11 are no longer supported')

        self.applesync = sync.AppleUpdateSync()

        self._update_list_cache = None
        self.shutdown_instead_of_restart = False

        # list of available_updates (set to None initially so we know we didn't
        # check yet)
        self.apple_updates = None

        # apple_update_metadata support
        self.client_id = ''
        self.force_catalog_refresh = False

    def restart_action_for_updates(self):
        """Returns the most heavily weighted postaction"""
        try:
            apple_updates = FoundationPlist.readPlist(self.apple_updates_plist)
        except FoundationPlist.NSPropertyListSerializationException:
            return POSTACTION_RESTART
        for item in apple_updates.get('AppleUpdates', []):
            if item.get('RestartAction') in self.SHUTDOWN_ACTIONS:
                return POSTACTION_SHUTDOWN
        for item in apple_updates.get('AppleUpdates', []):
            if item.get('RestartAction') in self.RESTART_ACTIONS:
                return POSTACTION_RESTART
        # if we get this far, there must be no items that require restart
        return POSTACTION_NONE

    def clear_apple_update_info(self):
        """Clears Apple update info.

        This is called after performing munki updates because the Apple updates
        may no longer be relevant.
        """
        self.apple_updates = None
        try:
            os.unlink(self.apple_updates_plist)
        except (OSError, IOError):
            pass

    def filter_out_major_os_updates(self, update_list):
        """Filters out any updates whose Label starts with 'macOS ' and
        whose major version is higher than the major version of the current
        OS
        Labels can be in the format:
            'macOS Ventura 13.2.1-22D68' or
            'macOS\xa0Ventura\xa013.2.1-22D68'
        """
        current_major_version = osutils.getOsVersion().split(".", maxsplit=1)[0]
        filtered_updates = []
        for update in update_list:
            if update.get("Label", "").split()[0] == "macOS":
                this_major_version = update.get(
                    "Version", "0").split(".", maxsplit=1)[0]
                try:
                    if int(this_major_version) > int(current_major_version):
                        display.display_debug1(
                            "Filtering out %s-%s from available Apple updates",
                            update.get("Label"), update.get("Version"))
                        continue
                except ValueError:
                    # something wasn't an integer!
                    pass
            filtered_updates.append(update)
        return filtered_updates

    def get_recommended_updates(self, suppress_scan=False):
        """Returns the list of available updates
           based on the output of `softwareupdate -l`, adding additional data
           from com.apple.SoftwareUpdate RecommendedUpdates"""
        msg = 'Checking for available Apple Software Updates...'
        display.display_status_major(msg)
        os_version_tuple = osutils.getOsVersion(as_tuple=True)
        if os_version_tuple < (10, 11):
            display.display_warning(
                'macOS versions below 10.11 are no longer supported')
        su_options = ["-l"]
        if suppress_scan and os_version_tuple < (11, 0):
            su_options.append("--no-scan")
        if os_version_tuple > (10, 11):
            # --include-config-data, which anecedotally causes softwareupdate
            # to actually show all the recommended updates more reliably
            # (at the cost of also showing config-data updates)
            su_options.append("--include-config-data")
        # should not take more than five minutes to get a list of
        # available updates
        su_results = su_tool.run(su_options, timeout=60*5)
        recommended_updates = su_prefs.pref('RecommendedUpdates') or []
        processed_updates = []
        for item in su_results.get('updates', []):
            if item.get('Deferred') != "YES":
                for update in recommended_updates:
                    # if we find a matching update, update the item info and
                    # add it to the list of recommended updates
                    if (item.get('Title') == update.get('Display Name') and
                            item.get('Version') == update.get('Display Version')
                        ):
                        item.update(update)
                        processed_updates.append(item)
        if not prefs.pref('AppleSoftwareUpdatesIncludeMajorOSUpdates'):
            processed_updates = self.filter_out_major_os_updates(processed_updates)
        return processed_updates

    def get_apple_updates(self, suppress_scan=False):
        """Uses info from /Library/Preferences/com.apple.SoftwareUpdate.plist
        and softwareupdate -l to determine the list of available Apple updates.

        Returns:
          List of dictionaries describing available Apple updates.
        """
        apple_updates = []

        # first, try to get the list from com.apple.SoftwareUpdate preferences
        # and softwareupdate -l
        available_updates = self.get_recommended_updates(
            suppress_scan=suppress_scan)
        for item in available_updates:
            if not "Label" in item:
                continue
            su_info = {}
            su_info['Label'] = item["Label"]
            su_info['name'] = item.get('Display Name', item.get('Title', ""))
            su_info['apple_product_name'] = su_info['name']
            su_info['display_name'] = su_info['name']
            su_info['version_to_install'] = item.get(
                'Display Version', item.get("Version", ""))
            su_info['description'] = ''
            try:
                size = int(item.get('Size', '0K')[:-1])
                su_info['installer_item_size'] = size
                su_info['installed_size'] = size
            except (ValueError, TypeError, IndexError):
                su_info['installed_size'] = 0
            if item.get('Action') == 'restart':
                su_info['RestartAction'] = 'RequireRestart'

            # try to get additional info from sucatalog, dist, etc
            if "Product Key" in item:
                su_info['productKey'] = item["Product Key"]
                if not item.get('MobileSoftwareUpdate'):
                    # get additional metadata from replicated catalog,etc data
                    localized_dist = self.applesync.distribution_for_product_key(
                        su_info['productKey'])
                    if not localized_dist:
                        display.display_warning(
                            'No dist file for product %s', su_info['productKey'])
                        continue
                    su_dist_info = dist.parse_su_dist(localized_dist)
                    su_info.update(su_dist_info)

            apple_updates.append(su_info)

        return apple_updates

    def software_update_list(self, suppress_scan=False):
        """Returns:
          List of dictionaries describing available Apple updates. May trigger
          a run of `softwareupdate -l`
        """
        if self.apple_updates is None:
            self.apple_updates = self.get_apple_updates(
                suppress_scan=suppress_scan)
        return self.apple_updates

    def download_available_updates(self):
        """Downloads available Apple updates if possible.

        Returns:
          Boolean. True if successful, False otherwise.
        """
        if info.is_apple_silicon():
            # don't actually download since this can trigger a prompt for
            # credentials
            return True

        download_list = self.software_update_list()
        filtered_download_list = []
        os_version_tuple = osutils.getOsVersion(as_tuple=True)
        if os_version_tuple >= (10, 14):
            # filter out items that require a restart
            # (typically OS or security updates), as downloading these has
            # proven problematic
            filtered_download_list = [
                item for item in download_list
                if item.get('RestartAction', 'None') == 'None'
            ]
            download_list = filtered_download_list

        if not download_list:
            display.display_info("No Apple updates we should download")
            return True

        msg = 'Downloading available Apple Software Updates...'
        display.display_status_major(msg)

        # before we call softwareupdate,
        # clear stored value for LastSessionSuccessful
        su_prefs.set_pref('LastSessionSuccessful', None)
        su_options = ["-d"]
        for item in download_list:
            su_options.append(item['Label'])

        results = su_tool.run(su_options, stop_allowed=True)
        retcode = results.get('exit_code', 0)
        if retcode:  # there was an error
            display.display_error('softwareupdate error: %s', retcode)
            return False
        # not sure all older macOS versions set LastSessionSuccessful, so
        # react only if it's explicitly set to False
        last_session_successful = su_prefs.pref('LastSessionSuccessful')
        if last_session_successful is False:
            display.display_error(
                'softwareupdate reported an unsuccessful download session.')
            return False
        return True

    def install_apple_updates(self, only_unattended=False):
        """Uses softwareupdate to install available updates.

        Returns:
          restart_action -- an integer indicating the action to take later:
                            none, logout, restart, shutdown
        """
        if info.is_apple_silicon():
            # can't install Apple softwareupdates on Apple Silicon
            return POSTACTION_NONE

        # disable Stop button if we are presenting GUI status
        if display.munkistatusoutput:
            munkistatus.hideStopButton()

        self.shutdown_instead_of_restart = False
        os_version_tuple = osutils.getOsVersion(as_tuple=True)

        installlist = self.software_update_list(suppress_scan=True)
        remaining_apple_updates = []
        installresults = {'installed': [], 'download': []}
        su_options = ['-i']

        if only_unattended:
            msg = 'Installing unattended Apple Software Updates...'
            restart_action = POSTACTION_NONE
            unattended_install_product_ids = self.get_unattended_installs()
            # Filter installlist to only include items
            # which we're attempting to install
            filtered_installlist = [item for item in installlist
                                    if item.get('productKey') in
                                    unattended_install_product_ids]
            # record items we aren't planning to attempt to install
            remaining_apple_updates = [item for item in installlist
                                       if item not in filtered_installlist]
            # set the list of items to install to our newly-filted list
            installlist = filtered_installlist

        elif os_version_tuple >= (10, 14):
            msg = ('Installing Apple Software Updates that do not require '
                   'restart...')
            restart_action = POSTACTION_NONE
            # in Mojave and beyond, it's too risky to
            # install OS or Security updates because softwareupdate is just
            # not reliable at this any longer. So skip any updates that require
            # a restart -- users will need to install these using Apple's GUI
            # tools. We can still install other updates that don't require a
            # restart (for now)
            filtered_installlist = [
                item for item in installlist
                if item.get('RestartAction', 'None') == 'None'
            ]
            # record items we aren't planning to attempt to install
            remaining_apple_updates = [item for item in installlist
                                       if item not in filtered_installlist]
            for item in remaining_apple_updates:
                display.display_debug1(
                    "Skipping install of %s-%s because it requires a restart.",
                    item['name'], item['version_to_install']
                )
            # set the list of items to install to our newly-filtered list
            installlist = filtered_installlist

        else:
            msg = 'Installing available Apple Software Updates...'
            restart_action = self.restart_action_for_updates()

        if not installlist:
            return POSTACTION_NONE  # our list of items to install is empty

        display.display_status_major(msg)

        # Add the current (possibly filtered) installlist items to the
        # softwareupdate install options
        for item in installlist:
            su_options.append(item['Label'])

        try:
            # attempt to fetch the apple catalog to confirm connectivity
            # to the Apple Software Update server
            self.applesync.cache_apple_catalog()
        except (sync.Error, fetch.Error):
            # network or catalog server not available, suppress scan
            # (we used to do this all the time, but this led to issues
            #  with updates cached "too long" in 10.12+)
            munkilog.log(
                "WARNING: Cannot reach Apple Software Update server while "
                "installing Apple updates")
            su_options.append('--no-scan')

        su_start_date = NSDate.new()
        installresults = su_tool.run(su_options)
        retcode = installresults.get('exit_code', 0)
        self.shutdown_instead_of_restart = (
            installresults.get('post_action') == POSTACTION_SHUTDOWN or
            osutils.bridgeos_update_staged()
        )
        su_end_date = NSDate.new()

        # get the items that were just installed from InstallHistory.plist
        installed_items = softwareupdated_installhistory(
            start_date=su_start_date, end_date=su_end_date)
        display.display_debug2(
            'InstallHistory.plist items:\n%s', installed_items)
        if not 'InstallResults' in reports.report:
            reports.report['InstallResults'] = []

        display.display_debug1(
            'Raw Apple Update install results: %s', installresults)
        for item in installlist:
            rep = {}
            rep['name'] = item.get('apple_product_name')
            rep['version'] = item.get('version_to_install', '')
            rep['applesus'] = True
            rep['time'] = su_end_date
            rep['productKey'] = item.get('productKey', '')
            message = 'Apple Software Update install of %s-%s: %s'
            # first try to match against the items from InstallHistory.plist
            matched_installed_items = [
                ih_item for ih_item in installed_items
                if ih_item['displayName'] in [
                    item.get('apple_product_name'), item.get('display_name')]
                and ih_item['displayVersion'] == item.get('version_to_install')
            ]
            if matched_installed_items:
                display.display_debug2('Matched %s in InstallHistory.plist',
                                       item.get('apple_product_name'))
                rep['status'] = 0
                rep['time'] = matched_installed_items[0]['date']
                install_status = 'SUCCESSFUL'
            elif rep['name'] in installresults['installed']:
                rep['status'] = 0
                install_status = 'SUCCESSFUL'
            elif ('display_name' in item and
                  item['display_name'] in installresults['installed']):
                rep['status'] = 0
                install_status = 'SUCCESSFUL'
            elif rep['name'] in installresults['download']:
                rep['status'] = -1
                install_status = 'FAILED due to missing package.'
                display.display_warning(
                    'Apple update %s, %s failed. A sub-package was missing '
                    'on disk at time of install.'
                    % (rep['name'], rep['productKey']))
            else:
                rep['status'] = -2
                install_status = 'FAILED for unknown reason'
                display.display_warning(
                    'Apple update %s, %s may have failed to install. No record '
                    'of success or failure.', rep['name'], rep['productKey'])
                if installresults['installed']:
                    display.display_warning(
                        'softwareupdate recorded these installations: %s',
                        installresults['installed'])

            reports.report['InstallResults'].append(rep)
            log_msg = message % (rep['name'], rep['version'], install_status)
            munkilog.log(log_msg, 'Install.log')

        if retcode:  # there was an error
            display.display_error('softwareupdate error: %s' % retcode)

        if not remaining_apple_updates:
            # clean up our now stale local cache
            self.applesync.clean_up_cache()
            # remove the now invalid AppleUpdates.plist
            self.clear_apple_update_info()
        else:
            # we installed some of the updates, but some are still uninstalled.
            # re-write the apple_update_info to match
            self.apple_updates = remaining_apple_updates
            plist = {'AppleUpdates': remaining_apple_updates}
            FoundationPlist.writePlist(plist, self.apple_updates_plist)

        # Also clear our pref value for last check date. We may have
        # just installed an update which is a pre-req for some other update.
        # Let's check again soon.
        prefs.set_pref('LastAppleSoftwareUpdateCheck', None)

        # show stop button again
        if display.munkistatusoutput:
            munkistatus.showStopButton()

        if self.shutdown_instead_of_restart:
            display.display_info(
                'One or more Apple updates requires a shutdown instead of '
                'restart.')
            restart_action = POSTACTION_SHUTDOWN

        return restart_action

    def write_appleupdates_file(self):
        """Writes a file used by the MSC GUI to display available updates.

        Returns:
          Integer. Count of available Apple updates.
        """
        apple_updates = self.software_update_list()
        if apple_updates:
            if not prefs.pref('AppleSoftwareUpdatesOnly'):
                cataloglist = updatecheck.get_primary_manifest_catalogs(
                    self.client_id, force_refresh=self.force_catalog_refresh)
                if cataloglist:
                    # Check for apple_update_metadata
                    display.display_detail(
                        '**Checking for Apple Update Metadata**')
                    for item in apple_updates:
                        if 'productKey' in item:
                            # Find matching metadata item
                            metadata_item = catalogs.get_item_detail(
                                item['productKey'], cataloglist,
                                vers='apple_update_metadata')
                            if metadata_item:
                                display.display_debug1(
                                    'Processing metadata for %s, %s...',
                                    item['productKey'], item['display_name'])
                                self.copy_update_metadata(item, metadata_item)
            plist = {'AppleUpdates': apple_updates}
            FoundationPlist.writePlist(plist, self.apple_updates_plist)
            return len(apple_updates)
        try:
            os.unlink(self.apple_updates_plist)
        except (OSError, IOError):
            pass
        return 0

    def display_apple_update_info(self):
        """Prints Apple update information and updates ManagedInstallReport."""
        if not os.path.exists(self.apple_updates_plist):
            return
        try:
            pl_dict = FoundationPlist.readPlist(self.apple_updates_plist)
        except FoundationPlist.FoundationPlistException:
            display.display_error(
                'Error reading: %s', self.apple_updates_plist)
            return
        apple_updates = pl_dict.get('AppleUpdates', [])
        display.display_info('')
        if not apple_updates:
            display.display_info('No available Apple Software Updates.')
            return
        reports.report['AppleUpdates'] = apple_updates
        display.display_info(
            'The following Apple Software Updates are available to '
            'install:')
        munki_installable_updates = self.installable_updates(apple_updates)
        for item in apple_updates:
            display.display_info(
                '    + %s-%s' % (
                    item.get('display_name', item.get('name', '')),
                    item.get('version_to_install', '')))
            if item.get('RestartAction') in self.RESTART_ACTIONS:
                display.display_info('       *Restart required')
                reports.report['RestartRequired'] = True
            elif item.get('RestartAction') == 'RequireLogout':
                display.display_info('       *Logout required')
                reports.report['LogoutRequired'] = True
            if item not in munki_installable_updates:
                display.display_info(
                    "       *Must be manually installed with Apple's tools")

    def installable_updates(self, apple_updates=None):
        """Returns a list of installable Apple updates.
        This may filter out updates that require a restart. On Apple silicon,
        it returns an empty list since we can't use softwareupdate to install
        at all."""
        if info.is_apple_silicon():
            # can't install any!
            return []
        if not apple_updates:
            apple_updates = self.apple_updates or []
        os_version_tuple = osutils.getOsVersion(as_tuple=True)
        if os_version_tuple >= (10, 14):
            # in Mojave and beyond, it's too risky to
            # install OS or Security updates because softwareupdate is just
            # not reliable at this any longer. So filter out updates that
            # require a restart
            filtered_apple_updates = [
                item for item in apple_updates
                if item.get('RestartAction', 'None') == 'None'
            ]
            return filtered_apple_updates
        return apple_updates

    def cached_update_count(self):
        """Returns the count of updates in the cached AppleUpdates.plist"""
        if not os.path.exists(self.apple_updates_plist):
            return 0
        try:
            plist = FoundationPlist.readPlist(self.apple_updates_plist)
        except FoundationPlist.FoundationPlistException:
            plist = {}
        return len(plist.get('AppleUpdates', []))

    def software_updates_available(
            self, force_check=False, suppress_check=False):
        """Checks for available Apple Software Updates, trying not to hit the
        SUS more than needed.

        Args:
          force_check: Boolean. If True, forces a softwareupdate run.
          suppress_check: Boolean. If True, skips a softwareupdate run.
        Returns:
          Integer. Count of available Apple updates.
        """
        if suppress_check:
            # don't check at all --
            # typically because we are doing a logout install
            # just return any AppleUpdates info we already have
            return self.cached_update_count()
        if force_check:
            # typically because user initiated the check from
            # Managed Software Update.app
            updatecount = self.check_for_software_updates(force_check=True)
        else:
            # have we checked recently?  Don't want to check with
            # Apple Software Update server too frequently
            now = NSDate.new()
            next_su_check = now
            last_su_check_string = prefs.pref(
                'LastAppleSoftwareUpdateCheck')
            if last_su_check_string:
                try:
                    last_su_check = NSDate.dateWithString_(
                        last_su_check_string)
                    # dateWithString_ returns None if invalid date string.
                    if not last_su_check:
                        raise ValueError
                    interval = 24 * 60 * 60
                    # only force check every 24 hours.
                    next_su_check = last_su_check.dateByAddingTimeInterval_(
                        interval)
                except (ValueError, TypeError):
                    pass
            if now.timeIntervalSinceDate_(next_su_check) >= 0:
                updatecount = self.check_for_software_updates(force_check=True)
            else:
                updatecount = self.check_for_software_updates(force_check=False)
        display.display_debug1(
            'CheckForSoftwareUpdates result: %s' % updatecount)
        if updatecount == -1:
            # some (transient?) communications error with the su server; return
            # cached AppleInfo
            return self.cached_update_count()
        if updatecount == 0:
            self.clear_apple_update_info()
        else:
            _ = self.write_appleupdates_file()
        return updatecount

    def copy_update_metadata(self, item, metadata):
        """Applies metadata to Apple update item restricted
        to keys contained in 'metadata_to_copy'.
        """
        metadata_to_copy = ['blocking_applications',
                            'description',
                            'display_name',
                            'unattended_install',
                            'RestartAction']
        # we support force_install_after_date only on macOS earlier than Mojave
        os_version_tuple = osutils.getOsVersion(as_tuple=True)
        if os_version_tuple < (10, 14):
            metadata_to_copy.append('force_install_after_date')

        # Mapping of supported restart_actions to
        # equal or greater auxiliary actions
        restart_actions = {
            'RequireShutdown': ['RequireShutdown'],
            'RequireRestart': ['RequireRestart', 'RecommendRestart'],
            'RecommendRestart': ['RequireRestart', 'RecommendRestart'],
            'RequireLogout': ['RequireRestart', 'RecommendRestart',
                              'RequireLogout'],
            'None': ['RequireShutdown', 'RequireRestart', 'RecommendRestart',
                     'RequireLogout', 'None']
        }

        for key in metadata:
            # Apply 'white-listed', non-empty metadata keys
            if key in metadata_to_copy and metadata[key]:
                if key == 'RestartAction':
                    # Ensure that a heavier weighted 'RestartAction' is not
                    # overridden by one supplied in metadata
                    if metadata[key] not in restart_actions.get(
                            item.get(key, 'None')):
                        display.display_debug2(
                            '\tSkipping metadata RestartAction\'%s\' '
                            'for item %s (ProductKey %s), '
                            'item\'s original \'%s\' is preferred.',
                            metadata[key], item.get('name'),
                            item.get('productKey'), item[key])
                        continue
                elif key == 'unattended_install':
                    # Don't apply unattended_install if a RestartAction exists
                    # in either the original item or metadata
                    if metadata.get('RestartAction', 'None') != 'None':
                        display.display_warning(
                            '\tIgnoring unattended_install key for Apple '
                            'update %s (ProductKey %s) '
                            'because metadata RestartAction is %s.',
                            item.get('name'), item.get('productKey'),
                            metadata.get('RestartAction'))
                        continue
                    if item.get('RestartAction', 'None') != 'None':
                        display.display_warning(
                            '\tIgnoring unattended_install key for Apple '
                            'update %s (ProductKey %s) '
                            'because item RestartAction is %s.'
                            % (item.get('name'), item.get('productKey'),
                               item.get('RestartAction')))
                        continue
                display.display_debug2('\tApplying %s...' % key)
                item[key] = metadata[key]
        return item

    def get_unattended_installs(self):
        """Processes AppleUpdates.plist to return a list
        of product_ids which are eligible for unattended installation.
        """
        product_ids = []
        if not os.path.exists(self.apple_updates_plist):
            return product_ids
        try:
            pl_dict = FoundationPlist.readPlist(self.apple_updates_plist)
        except FoundationPlist.FoundationPlistException:
            display.display_error(
                'Error reading: %s', self.apple_updates_plist)
            return product_ids
        apple_updates = pl_dict.get('AppleUpdates', [])
        for item in apple_updates:
            if (item.get('unattended_install') or
                    (prefs.pref('UnattendedAppleUpdates') and
                     item.get('RestartAction', 'None') == 'None')):
                if processes.blocking_applications_running(item):
                    display.display_detail(
                        'Skipping unattended install of %s because '
                        'blocking application(s) running.'
                        % item['display_name'])
                    continue
                product_ids.append(item['productKey'])
            else:
                display.display_detail(
                    'Skipping install of %s because it\'s not unattended.'
                    % item['display_name'])
        return product_ids

    def installed_apple_pkgs_changed(self):
        """Generates a SHA-256 checksum of the info for all packages in the
        receipts database whose id matches com.apple.* and compares it to a
        stored version of this checksum.

        Returns:
          Boolean. False if the checksums match, True if they differ."""
        cmd = ['/usr/sbin/pkgutil', '--regexp', '--pkg-info-plist',
               r'com\.apple\.*']
        proc = subprocess.Popen(cmd, shell=False,
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output = proc.communicate()[0] # don't decode because we need the bytes

        current_apple_packages_checksum = hashlib.sha256(output).hexdigest()
        old_apple_packages_checksum = prefs.pref(
            'InstalledApplePackagesChecksum')

        if current_apple_packages_checksum == old_apple_packages_checksum:
            return False

        prefs.set_pref('InstalledApplePackagesChecksum',
                       current_apple_packages_checksum)
        return True

    def _force_check_necessary(self, original_hash):
        """Returns True if a force check is needed, False otherwise.

        Args:
          original_hash: the SHA-256 hash of the Apple catalog before being
              redownloaded.
        Returns:
          Boolean. True if a force check is needed, False otherwise.
        """
        new_hash = munkihash.getsha256hash(
            self.applesync.apple_download_catalog_path)
        if original_hash != new_hash:
            munkilog.log('Apple update catalog has changed.')
            return True

        if self.installed_apple_pkgs_changed():
            munkilog.log('Installed Apple packages have changed.')
            return True

        return False

    def check_for_software_updates(self, force_check=True):
        """Check if Apple Software Updates are available, if needed or forced.

        Args:
          force_check: Boolean. If True, forces a check, otherwise only checks
              if the last check is deemed outdated.
        Returns:
          Integer. -1 if there was an error, otherwise the number of available
            updates.
        """
        before_hash = munkihash.getsha256hash(
            self.applesync.apple_download_catalog_path)

        msg = 'Checking Apple Software Update catalog...'
        display.display_status_major(msg)
        try:
            self.applesync.cache_apple_catalog()
        except sync.CatalogNotFoundError:
            return -1
        except (sync.ReplicationError, fetch.Error) as err:
            display.display_warning(
                'Could not download Apple SUS catalog:')
            display.display_warning(u'\t%s', err)
            return -1

        if not force_check and not self._force_check_necessary(before_hash):
            display.display_info(
                'Skipping full Apple Software Update check '
                'because sucatalog is unchanged, installed Apple packages are '
                'unchanged and we recently did a full check.')
            # return count of cached updates
            return self.cached_update_count()

        if self.download_available_updates():  # Success; ready to install.
            prefs.set_pref('LastAppleSoftwareUpdateCheck', NSDate.date())
            update_list = self.software_update_list()
            if not update_list:
                # No updates found
                self.applesync.clean_up_cache()
                return 0
            try:
                product_ids = [item['productKey']
                               for item in update_list
                               if 'productKey' in item]
                self.applesync.cache_update_metadata(product_ids)
            except sync.ReplicationError as err:
                display.display_warning(
                    'Could not replicate software update metadata:')
                display.display_warning(u'\t%s', err)
                return -1
            return len(product_ids)
        # Download error, allow check again soon.
        display.display_error(
            'Could not download all available Apple updates.')
        prefs.set_pref('LastAppleSoftwareUpdateCheck', None)
        return 0

if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
