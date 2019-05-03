# encoding: utf-8
#
# Copyright 2009-2019 Greg Neagle.
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
appleupdates.py

Created by Greg Neagle on 2017-01-06.

AppleUpdates object defined here
"""

import glob
import hashlib
import os
import subprocess
import urllib2

# PyLint cannot properly find names inside Cocoa libraries, so issues bogus
# No name 'Foo' in module 'Bar' warnings. Disable them.
# pylint: disable=E0611
from Foundation import NSDate
# pylint: enable=E0611

from . import dist
from . import su_prefs
from . import su_tool
from . import sync

from ..updatecheck import catalogs
from ..constants import POSTACTION_NONE, POSTACTION_RESTART, POSTACTION_SHUTDOWN

from .. import display
from .. import fetch
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

        # fix things if somehow we died last time before resetting the
        # original CatalogURL
        os_version_tuple = osutils.getOsVersion(as_tuple=True)
        if os_version_tuple < (10, 10):
            display.display_warning(
                'macOS versions below 10.10 are no longer supported')
        if os_version_tuple == (10, 10):
            su_prefs.reset_original_catalogurl()

        self.applesync = sync.AppleUpdateSync()

        self._update_list_cache = None
        self.shutdown_instead_of_restart = False

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
        try:
            os.unlink(self.apple_updates_plist)
        except (OSError, IOError):
            pass

    def download_available_updates(self):
        """Downloads available Apple updates.

        Returns:
          Boolean. True if successful, False otherwise.
        """
        msg = 'Checking for available Apple Software Updates...'
        display.display_status_major(msg)

        os_version_tuple = osutils.getOsVersion(as_tuple=True)
        if os_version_tuple >= (10, 11):
            catalog_url = None
        else:
            catalog_url = self.applesync.get_apple_catalogurl()

        # before we call softwareupdate,
        # clear stored value for LastSessionSuccessful
        su_prefs.set_pref('LastSessionSuccessful', None)
        results = su_tool.run(
            ['-d', '-a'], catalog_url=catalog_url, stop_allowed=True)
        retcode = results.get('exit_code', 0)
        if retcode:  # there was an error
            display.display_error('softwareupdate error: %s', retcode)
            return False
        # not sure all older OS X versions set LastSessionSuccessful, so
        # react only if it's explicitly set to False
        last_session_successful = su_prefs.pref('LastSessionSuccessful')
        if last_session_successful is False:
            display.display_error(
                'softwareupdate reported an unsuccessful download session.')
            return False
        return True

    def get_filtered_recommendedupdates(self):
        """Returns the list of RecommendedUpdates from com.apple.SoftwareUpdate
        preferences, filtered by the output of `softwareupdate -l`"""
        # pylint: disable=no-self-use
        os_version_tuple = osutils.getOsVersion(as_tuple=True)
        if os_version_tuple < (10, 10):
            display.display_warning(
                'macOS versions below 10.10 are no longer supported')
        recommended_updates = su_prefs.pref('RecommendedUpdates') or []
        if os_version_tuple < (10, 11):
            # --no-scan flag is not supported; just return the
            # RecommendedUpdates without filtering. We never saw the issues
            # that this filtering is meant to address in 10.10 anyway!
            return recommended_updates
        su_results = su_tool.run(['-l', '--no-scan'])
        filtered_updates = []
        for item in su_results.get('updates', []):
            for update in recommended_updates:
                if (item.get('identifier') == update.get('Identifier') and
                        item.get('version') == update.get('Display Version')):
                    # add update to filtered_updates only if it is also listed
                    # in `softwareupdate -l` output
                    filtered_updates.append(update)
        return filtered_updates

    def available_update_product_ids(self):
        """Returns a list of product IDs of available Apple updates.

        Returns:
          A list of string Apple update product ids.
        """
        recommended_updates = self.get_filtered_recommendedupdates()
        try:
            return [item['Product Key'] for item in recommended_updates
                    if 'Product Key' in item]
        except IndexError:
            # RecommendedUpdates is an empty list
            pass
        except (KeyError, AttributeError):
            # RecommendedUpdates is in an unexpected format
            display.display_debug1(
                'com.apple.SoftwareUpdate RecommendedUpdates is in an '
                'unexpected format: %s', recommended_updates)
        return []

    def installed_apple_pkgs_changed(self):
        """Generates a SHA-256 checksum of the info for all packages in the
        receipts database whose id matches com.apple.* and compares it to a
        stored version of this checksum.

        Returns:
          Boolean. False if the checksums match, True if they differ."""
        # pylint: disable=no-self-use
        cmd = ['/usr/sbin/pkgutil', '--regexp', '--pkg-info-plist',
               r'com\.apple\.*']
        proc = subprocess.Popen(cmd, shell=False, bufsize=1,
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output, dummy_err = proc.communicate()

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

        if not self.available_updates_downloaded():
            munkilog.log('Downloaded updates do not match our list of '
                         'available updates.')
            return True

        return False

    def check_for_software_updates(self, force_check=True):
        """Check if Apple Software Updates are available, if needed or forced.

        Args:
          force_check: Boolean. If True, forces a check, otherwise only checks
              if the last check is deemed outdated.
        Returns:
          Boolean. True if there are updates, False otherwise.
        """
        before_hash = munkihash.getsha256hash(
            self.applesync.apple_download_catalog_path)

        msg = 'Checking Apple Software Update catalog...'
        display.display_status_major(msg)
        try:
            self.applesync.cache_apple_catalog()
        except sync.CatalogNotFoundError:
            return False
        except (sync.ReplicationError, fetch.Error) as err:
            display.display_warning(
                'Could not download Apple SUS catalog:')
            display.display_warning('\t%s', unicode(err))
            return False

        if not force_check and not self._force_check_necessary(before_hash):
            display.display_info(
                'Skipping Apple Software Update check '
                'because sucatalog is unchanged, installed Apple packages are '
                'unchanged and we recently did a full check.')
            # return True if we have cached updates; False otherwise
            return bool(self.software_update_info())

        if self.download_available_updates():  # Success; ready to install.
            prefs.set_pref('LastAppleSoftwareUpdateCheck', NSDate.date())
            product_ids = self.available_update_product_ids()
            if not product_ids:
                # No updates found
                self.applesync.clean_up_cache()
                return False
            try:
                self.applesync.cache_update_metadata(product_ids)
            except sync.ReplicationError as err:
                display.display_warning(
                    'Could not replicate software update metadata:')
                display.display_warning('\t%s', unicode(err))
                return False
            return True
        else:
            # Download error, allow check again soon.
            display.display_error(
                'Could not download all available Apple updates.')
            prefs.set_pref('LastAppleSoftwareUpdateCheck', None)
            return False

    def update_downloaded(self, product_key):
        """Verifies that a given update appears to be downloaded.
        Returns a boolean."""
        # pylint: disable=no-self-use
        product_dir = os.path.join('/Library/Updates', product_key)
        if not os.path.isdir(product_dir):
            munkilog.log(
                'Apple Update product directory %s is missing'
                % product_key)
            return False
        else:
            pkgs = glob.glob(os.path.join(product_dir, '*.pkg'))
            if not pkgs:
                munkilog.log(
                    'Apple Update product directory %s contains no pkgs'
                    % product_key)
                return False
        return True

    def available_updates_downloaded(self):
        """Verifies that applicable/available updates have been downloaded.

        Returns:
          Boolean. False if a product directory are missing,
                   True otherwise (including when there are no available
                                   updates).
        """
        apple_updates = self.software_update_info()
        if not apple_updates:
            return True

        for update in apple_updates:
            if not self.update_downloaded(update.get('productKey')):
                return False
        return True

    def software_update_info(self):
        """Uses /Library/Preferences/com.apple.SoftwareUpdate.plist to generate
        the AppleUpdates.plist, which records available updates in the format
        that Managed Software Center.app expects.

        Returns:
          List of dictionary update data.
        """
        update_display_names = {}
        update_versions = {}
        product_keys = []
        english_su_info = {}
        apple_updates = []

        # first, try to get the list from com.apple.SoftwareUpdate preferences
        recommended_updates = self.get_filtered_recommendedupdates()
        for item in recommended_updates:
            try:
                update_display_names[item['Product Key']] = (
                    item['Display Name'])
            except (TypeError, AttributeError, KeyError):
                pass
            try:
                update_versions[item['Product Key']] = (
                    item['Display Version'])
            except (TypeError, AttributeError, KeyError):
                pass
        try:
            product_keys = [item['Product Key']
                            for item in recommended_updates]
        except (TypeError, AttributeError, KeyError):
            pass

        for product_key in product_keys:
            if not self.update_downloaded(product_key):
                display.display_warning(
                    'Product %s does not appear to be downloaded',
                    product_key)
                continue
            localized_dist = self.applesync.distribution_for_product_key(
                product_key)
            if not localized_dist:
                display.display_warning(
                    'No dist file for product %s', product_key)
                continue
            if (not recommended_updates and
                    not localized_dist.endswith('English.dist')):
                # we need the English versions of some of the data
                # see (https://groups.google.com/d/msg/munki-dev/
                # _5HdMyy3kKU/YFxqslayDQAJ)
                english_dist = self.applesync.distribution_for_product_key(
                    product_key, 'English')
                if english_dist:
                    english_su_info = dist.parse_su_dist(english_dist)
            su_info = dist.parse_su_dist(localized_dist)
            su_info['productKey'] = product_key
            if su_info['name'] == '':
                su_info['name'] = product_key
            if product_key in update_display_names:
                su_info['apple_product_name'] = (
                    update_display_names[product_key])
            elif english_su_info:
                su_info['apple_product_name'] = (
                    english_su_info['apple_product_name'])
            if product_key in update_versions:
                su_info['version_to_install'] = update_versions[product_key]
            elif english_su_info:
                su_info['version_to_install'] = (
                    english_su_info['version_to_install'])
            apple_updates.append(su_info)

        return apple_updates

    def write_appleupdates_file(self):
        """Writes a file used by the MSU GUI to display available updates.

        Returns:
          Integer. Count of available Apple updates.
        """
        apple_updates = self.software_update_info()
        if apple_updates:
            if not prefs.pref('AppleSoftwareUpdatesOnly'):
                cataloglist = updatecheck.get_primary_manifest_catalogs(
                    self.client_id, force_refresh=self.force_catalog_refresh)
                if cataloglist:
                    # Check for apple_update_metadata
                    display.display_detail(
                        '**Checking for Apple Update Metadata**')
                    for item in apple_updates:
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
        else:
            try:
                os.unlink(self.apple_updates_plist)
            except (OSError, IOError):
                pass
            return 0

    def display_apple_update_info(self):
        """Prints Apple update information and updates ManagedInstallReport."""
        try:
            pl_dict = FoundationPlist.readPlist(self.apple_updates_plist)
        except FoundationPlist.FoundationPlistException:
            display.display_error(
                'Error reading: %s', self.apple_updates_plist)
            return
        apple_updates = pl_dict.get('AppleUpdates', [])
        if not apple_updates:
            display.display_info('No available Apple Software Updates.')
            return
        reports.report['AppleUpdates'] = apple_updates
        display.display_info(
            'The following Apple Software Updates are available to '
            'install:')
        for item in apple_updates:
            display.display_info(
                '    + %s-%s' % (
                    item.get('display_name', ''),
                    item.get('version_to_install', '')))
            if item.get('RestartAction') in self.RESTART_ACTIONS:
                display.display_info('       *Restart required')
                reports.report['RestartRequired'] = True
            elif item.get('RestartAction') == 'RequireLogout':
                display.display_info('       *Logout required')
                reports.report['LogoutRequired'] = True

    def install_apple_updates(self, only_unattended=False):
        """Uses softwareupdate to install previously downloaded updates.

        Returns:
          Boolean. True if a restart is needed after install, False otherwise.
        """
        # disable Stop button if we are presenting GUI status
        if display.munkistatusoutput:
            munkistatus.hideStopButton()

        self.shutdown_instead_of_restart = False
        # Get list of unattended_installs
        if only_unattended:
            msg = 'Installing unattended Apple Software Updates...'
            unattended_install_items, unattended_install_product_ids = \
                self.get_unattended_installs()
            # ensure that we don't restart for unattended installations
            restart_action = POSTACTION_NONE
            if not unattended_install_items:
                return False  # didn't find any unattended installs
        else:
            msg = 'Installing available Apple Software Updates...'
            restart_action = self.restart_action_for_updates()

        display.display_status_major(msg)

        installlist = self.software_update_info()
        remaining_apple_updates = []
        installresults = {'installed': [], 'download': []}

        su_options = ['-i']

        if only_unattended:
            # Append list of unattended_install items
            su_options.extend(unattended_install_items)
            # Filter installlist to only include items
            # which we're attempting to install
            filtered_installlist = [item for item in installlist
                                    if item.get('productKey') in
                                    unattended_install_product_ids]
            # record items we aren't planning to attempt to install
            remaining_apple_updates = [item for item in installlist
                                       if item not in filtered_installlist]
            installlist = filtered_installlist

        else:
            # We're installing all available updates; add all their names
            for item in installlist:
                su_options.append(
                    item['name'] + '-' + item['version_to_install'])

        # new in 10.11: '--no-scan' flag to tell softwareupdate to just install
        # and not rescan for available updates.
        os_version_tuple = osutils.getOsVersion(as_tuple=True)
        if os_version_tuple >= (10, 11):
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
            # 10.11 seems not to like file:// URLs, and we don't really need
            # to switch to a local file URL anyway since we now have the
            # --no-scan option
            catalog_url = None
        else:
            # use our local catalog
            if not os.path.exists(self.applesync.local_catalog_path):
                display.display_error(
                    'Missing local Software Update catalog at %s',
                    self.applesync.local_catalog_path)
                return False  # didn't do anything, so no restart needed
            catalog_url = 'file://localhost' + urllib2.quote(
                self.applesync.local_catalog_path)

        su_start_date = NSDate.new()
        installresults = su_tool.run(su_options, catalog_url=catalog_url)
        retcode = installresults.get('exit_code', 0)
        self.shutdown_instead_of_restart = installresults.get(
            'post_action') == POSTACTION_SHUTDOWN
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
        success = True
        if suppress_check:
            # don't check at all --
            # typically because we are doing a logout install
            # just return any AppleUpdates info we already have
            if not os.path.exists(self.apple_updates_plist):
                return 0
            try:
                plist = FoundationPlist.readPlist(self.apple_updates_plist)
            except FoundationPlist.FoundationPlistException:
                plist = {}
            return len(plist.get('AppleUpdates', []))
        if force_check:
            # typically because user initiated the check from
            # Managed Software Update.app
            success = self.check_for_software_updates(force_check=True)
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
                success = self.check_for_software_updates(force_check=True)
            else:
                success = self.check_for_software_updates(force_check=False)
        display.display_debug1(
            'CheckForSoftwareUpdates result: %s' % success)
        if success:
            count = self.write_appleupdates_file()
        else:
            self.clear_apple_update_info()
            return 0
        return count

    def copy_update_metadata(self, item, metadata):
        """Applies metadata to Apple update item restricted
        to keys contained in 'metadata_to_copy'.
        """
        # pylint: disable=no-self-use
        metadata_to_copy = ['blocking_applications',
                            'description',
                            'display_name',
                            'force_install_after_date',
                            'unattended_install',
                            'RestartAction']

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
        of NAME-VERSION formatted items and a list of product_ids
        which are eligible for unattended installation.
        """
        item_list = []
        product_ids = []
        try:
            pl_dict = FoundationPlist.readPlist(self.apple_updates_plist)
        except FoundationPlist.FoundationPlistException:
            display.display_error(
                'Error reading: %s', self.apple_updates_plist)
            return item_list, product_ids
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
                install_item = item['name'] + '-' + item['version_to_install']
                item_list.append(install_item)
                product_ids.append(item['productKey'])
            else:
                display.display_detail(
                    'Skipping install of %s because it\'s not unattended.'
                    % item['display_name'])
        return item_list, product_ids


if __name__ == '__main__':
    print 'This is a library of support tools for the Munki Suite.'
