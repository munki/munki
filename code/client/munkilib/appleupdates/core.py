#!/usr/bin/python
# encoding: utf-8
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
appleupdates.py

Utilities for dealing with Apple Software Update.

"""

import glob
import gzip
import hashlib
import os
import subprocess
import time
import urllib2
import urlparse

# PyLint cannot properly find names inside Cocoa libraries, so issues bogus
# No name 'Foo' in module 'Bar' warnings. Disable them.
# pylint: disable=E0611
from Foundation import NSDate
from Foundation import NSBundle
# pylint: enable=E0611

from . import dist
from . import su_prefs
from . import sync

from ..updatecheck import catalogs

from .. import fetch
from .. import launchd
from .. import munkicommon
from .. import munkistatus
from .. import updatecheck
from .. import FoundationPlist


# Disable PyLint complaining about 'invalid' camelCase names
# pylint: disable=C0103


# Apple's index of downloaded updates
INDEX_PLIST = '/Library/Updates/index.plist'


class AppleUpdates(object):

    """Class for installation of Apple Software Updates within Munki.

    This class handles update detection, as well as downloading and installation
    of those updates.
    """

    RESTART_ACTIONS = ['RequireRestart', 'RecommendRestart']

    def __init__(self):
        self._managed_install_dir = munkicommon.pref('ManagedInstallDir')
        self.apple_updates_plist = os.path.join(
            self._managed_install_dir, 'AppleUpdates.plist')

        # fix things if somehow we died last time before resetting the
        # original CatalogURL
        os_version_tuple = munkicommon.getOsVersion(as_tuple=True)
        if os_version_tuple in [(10, 9), (10, 10)]:
            su_prefs.ResetOriginalCatalogURL()

        self.applesync = sync.AppleUpdateSync()

        self._update_list_cache = None

        # apple_update_metadata support
        self.client_id = ''
        self.force_catalog_refresh = False

    def _ResetMunkiStatusAndDisplayMessage(self, message):
        """Resets MunkiStatus detail/percent, logs and msgs GUI.

        Args:
          message: str message to display to the user and log.
        """
        # pylint: disable=no-self-use
        munkicommon.display_status_major(message)

    def IsRestartNeeded(self):
        """Returns True if any update requires an restart."""
        try:
            apple_updates = FoundationPlist.readPlist(self.apple_updates_plist)
        except FoundationPlist.NSPropertyListSerializationException:
            return True
        for item in apple_updates.get('AppleUpdates', []):
            if item.get('RestartAction') in self.RESTART_ACTIONS:
                return True
        # if we get this far, there must be no items that require restart
        return False

    def ClearAppleUpdateInfo(self):
        """Clears Apple update info.

        This is called after performing munki updates because the Apple updates
        may no longer be relevant.
        """
        try:
            os.unlink(self.apple_updates_plist)
        except (OSError, IOError):
            pass

    def DownloadAvailableUpdates(self):
        """Downloads available Apple updates.

        Returns:
          Boolean. True if successful, False otherwise.
        """
        #msg = 'Downloading available Apple Software Updates...'
        msg = 'Checking for available Apple Software Updates...'
        self._ResetMunkiStatusAndDisplayMessage(msg)

        if os.path.exists(INDEX_PLIST):
            # try to remove old/stale /Library/Updates/index.plist
            # in some older versions of OS X this can hang around
            # and is not always cleaned up when /usr/sbin/softwareupdate
            # finds no updates
            try:
                os.unlink(INDEX_PLIST)
            except OSError:
                pass

        os_version_tuple = munkicommon.getOsVersion(as_tuple=True)
        if os_version_tuple >= (10, 11):
            catalog_url = None
        else:
            catalog_url = self.applesync.GetAppleCatalogURL()

        retcode = self._RunSoftwareUpdate(
            ['-d', '-a'], catalog_url=catalog_url, stop_allowed=True)
        if retcode:  # there was an error
            munkicommon.display_error('softwareupdate error: %s', retcode)
            return False
        # not sure all older OS X versions set LastSessionSuccessful, so
        # react only if it's explicitly set to False
        last_session_successful = su_prefs.GetSoftwareUpdatePref(
            'LastSessionSuccessful')
        if last_session_successful is False:
            munkicommon.display_error(
                'softwareupdate reported an unsuccessful download session.')
            return False
        return True

    def GetAvailableUpdateProductIDs(self):
        """Returns a list of product IDs of available Apple updates.

        Returns:
          A list of string Apple update products ids.
        """

        # first, try to get the list from com.apple.SoftwareUpdate preferences
        recommended_updates = su_prefs.GetSoftwareUpdatePref(
            'RecommendedUpdates')
        if recommended_updates:
            return [item['Product Key'] for item in recommended_updates
                    if 'Product Key' in item]

        # not in com.apple.SoftwareUpdate preferences, try index.plist
        if not os.path.exists(INDEX_PLIST):
            munkicommon.display_debug1('%s does not exist.' % INDEX_PLIST)
            return []

        try:
            product_index = FoundationPlist.readPlist(INDEX_PLIST)
            products = product_index.get('ProductPaths', {})
            return products.keys()
        except (FoundationPlist.FoundationPlistException,
                KeyError, AttributeError), err:
            munkicommon.display_error(
                "Error processing %s: %s", INDEX_PLIST, err)
            return []


    def InstalledApplePackagesHaveChanged(self):
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
        old_apple_packages_checksum = munkicommon.pref(
            'InstalledApplePackagesChecksum')

        if current_apple_packages_checksum == old_apple_packages_checksum:
            return False
        else:
            munkicommon.set_pref('InstalledApplePackagesChecksum',
                                 current_apple_packages_checksum)
            return True

    def _IsForceCheckNeccessary(self, original_hash):
        """Returns True if a force check is needed, False otherwise.

        Args:
          original_hash: the SHA-256 hash of the Apple catalog before being
              redownloaded.
        Returns:
          Boolean. True if a force check is needed, False otherwise.
        """
        new_hash = munkicommon.getsha256hash(
            self.applesync.apple_download_catalog_path)
        if original_hash != new_hash:
            munkicommon.log('Apple update catalog has changed.')
            return True

        if self.InstalledApplePackagesHaveChanged():
            munkicommon.log('Installed Apple packages have changed.')
            return True

        if not self.AvailableUpdatesAreDownloaded():
            munkicommon.log('Downloaded updates do not match our list '
                            'of available updates.')
            return True

        return False

    def CheckForSoftwareUpdates(self, force_check=True):
        """Check if Apple Software Updates are available, if needed or forced.

        Args:
          force_check: Boolean. If True, forces a check, otherwise only checks
              if the last check is deemed outdated.
        Returns:
          Boolean. True if there are updates, False otherwise.
        """
        before_hash = munkicommon.getsha256hash(
            self.applesync.apple_download_catalog_path)

        msg = 'Checking Apple Software Update catalog...'
        self._ResetMunkiStatusAndDisplayMessage(msg)
        try:
            self.applesync.CacheAppleCatalog()
        except sync.CatalogNotFoundError:
            return False
        except (sync.ReplicationError, fetch.Error) as err:
            munkicommon.display_warning(
                'Could not download Apple SUS catalog:')
            munkicommon.display_warning('\t%s', unicode(err))
            return False

        if not force_check and not self._IsForceCheckNeccessary(before_hash):
            munkicommon.display_info(
                'Skipping Apple Software Update check '
                'because sucatalog is unchanged, installed Apple packages are '
                'unchanged and we recently did a full check.')
            # return True if we have cached updates
            # False otherwise
            return bool(self.GetSoftwareUpdateInfo())

        if self.DownloadAvailableUpdates():  # Success; ready to install.
            munkicommon.set_pref('LastAppleSoftwareUpdateCheck', NSDate.date())
            product_ids = self.GetAvailableUpdateProductIDs()
            if not product_ids:
                # No updates found
                # TO-DO: clear metadata cache
                return False
            os_version_tuple = munkicommon.getOsVersion(as_tuple=True)
            if os_version_tuple < (10, 11):
                self.applesync.WriteFilteredCatalog(product_ids)
            try:
                self.applesync.CacheUpdateMetadata(product_ids)
            except sync.ReplicationError as err:
                munkicommon.display_warning(
                    'Could not replicate software update metadata:')
                munkicommon.display_warning('\t%s', unicode(err))
                return False
            return True
        else:
            # Download error, allow check again soon.
            munkicommon.display_error(
                'Could not download all available Apple updates.')
            munkicommon.set_pref('LastAppleSoftwareUpdateCheck', None)
            return False

    def UpdateDownloaded(self, product_key):
        """Verifies that a given update appears to be downloaded.
        Returns a boolean."""
        # pylint: disable=no-self-use
        product_dir = os.path.join('/Library/Updates', product_key)
        if not os.path.isdir(product_dir):
            munkicommon.log(
                'Apple Update product directory %s is missing'
                % product_key)
            return False
        else:
            pkgs = glob.glob(os.path.join(product_dir, '*.pkg'))
            if not pkgs:
                munkicommon.log(
                    'Apple Update product directory %s contains no pkgs'
                    % product_key)
                return False
        return True

    def AvailableUpdatesAreDownloaded(self):
        """Verifies that applicable/available updates have been downloaded.

        Returns:
          Boolean. False if a product directory are missing,
                   True otherwise (including when there are no available
                                   updates).
        """
        apple_updates = self.GetSoftwareUpdateInfo()
        if not apple_updates:
            return True

        for update in apple_updates:
            if not self.UpdateDownloaded(update.get('productKey')):
                return False
        return True

    def GetSoftwareUpdateInfo(self):
        """Uses /Library/Preferences/com.apple.SoftwareUpdate.plist or
        /Library/Updates/index.plist to generate the AppleUpdates.plist,
        which records available updates in the format that
        Managed Software Update.app expects.

        Returns:
          List of dictionary update data.
        """
        update_display_names = {}
        update_versions = {}
        product_keys = []
        english_su_info = {}
        apple_updates = []

        # first, try to get the list from com.apple.SoftwareUpdate preferences
        recommended_updates = su_prefs.GetSoftwareUpdatePref(
            'RecommendedUpdates')
        if recommended_updates:
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

        if not product_keys:
            # next, try to get the applicable/recommended updates from
            # /Library/Updates/index.plist
            if os.path.exists(INDEX_PLIST):
                try:
                    product_index = FoundationPlist.readPlist(INDEX_PLIST)
                    products = product_index.get('ProductPaths', {})
                    product_keys = products.keys()
                except (FoundationPlist.FoundationPlistException,
                        AttributeError, TypeError), err:
                    munkicommon.display_error(
                        "Error parsing %s: %s", INDEX_PLIST, err)

        for product_key in product_keys:
            if not self.UpdateDownloaded(product_key):
                munkicommon.display_warning(
                    'Product %s does not appear to be downloaded',
                    product_key)
                continue
            localized_dist = self.applesync.GetDistributionForProductKey(
                product_key)
            if not localized_dist:
                munkicommon.display_warning(
                    'No dist file for product %s', product_key)
                continue
            if (not recommended_updates and
                    not localized_dist.endswith('English.dist')):
                # we need the English versions of some of the data
                # see (https://groups.google.com/d/msg/munki-dev/
                # _5HdMyy3kKU/YFxqslayDQAJ)
                english_dist = self.applesync.GetDistributionForProductKey(
                    product_key, 'English')
                if english_dist:
                    english_su_info = dist.parse_su_dist(
                        english_dist)
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
                su_info['version_to_install'] = (
                    update_versions[product_key])
            elif english_su_info:
                su_info['version_to_install'] = (
                    english_su_info['version_to_install'])
            apple_updates.append(su_info)

        return apple_updates

    def WriteAppleUpdatesFile(self):
        """Writes a file used by the MSU GUI to display available updates.

        Returns:
          Integer. Count of available Apple updates.
        """
        apple_updates = self.GetSoftwareUpdateInfo()
        if apple_updates:
            if not munkicommon.pref('AppleSoftwareUpdatesOnly'):
                cataloglist = updatecheck.getPrimaryManifestCatalogs(
                    self.client_id, force_refresh=self.force_catalog_refresh)
                if cataloglist:
                    # Check for apple_update_metadata
                    munkicommon.display_detail(
                        '**Checking for Apple Update Metadata**')
                    for item in apple_updates:
                        # Find matching metadata item
                        metadata_item = catalogs.get_item_detail(
                            item['productKey'], cataloglist,
                            vers='apple_update_metadata')
                        if metadata_item:
                            munkicommon.display_debug1(
                                'Processing metadata for %s, %s...',
                                item['productKey'], item['display_name'])
                            self.copyUpdateMetadata(item, metadata_item)
            plist = {'AppleUpdates': apple_updates}
            FoundationPlist.writePlist(plist, self.apple_updates_plist)
            return len(apple_updates)
        else:
            try:
                os.unlink(self.apple_updates_plist)
            except (OSError, IOError):
                pass
            return 0

    def DisplayAppleUpdateInfo(self):
        """Prints Apple update information and updates ManagedInstallReport."""
        try:
            pl_dict = FoundationPlist.readPlist(self.apple_updates_plist)
        except FoundationPlist.FoundationPlistException:
            munkicommon.display_error(
                'Error reading: %s', self.apple_updates_plist)
            return
        apple_updates = pl_dict.get('AppleUpdates', [])
        if not apple_updates:
            munkicommon.display_info('No available Apple Software Updates.')
            return
        munkicommon.report['AppleUpdates'] = apple_updates
        munkicommon.display_info(
            'The following Apple Software Updates are available to '
            'install:')
        for item in apple_updates:
            munkicommon.display_info(
                '    + %s-%s' % (
                    item.get('display_name', ''),
                    item.get('version_to_install', '')))
            if item.get('RestartAction') in self.RESTART_ACTIONS:
                munkicommon.display_info('       *Restart required')
                munkicommon.report['RestartRequired'] = True
            elif item.get('RestartAction') == 'RequireLogout':
                munkicommon.display_info('       *Logout required')
                munkicommon.report['LogoutRequired'] = True

    def _RunSoftwareUpdate(
            self, options_list, catalog_url=None, stop_allowed=False,
            mode=None, results=None):
        """Runs /usr/sbin/softwareupdate with options.

        Provides user feedback via command line or MunkiStatus.

        Args:
          options_list: sequence of options to send to softwareupdate.
          stopped_allowed:
          mode:
          results:
        Returns:
          Integer softwareupdate exit code.
        """
        if results is None:
            # we're not interested in the results,
            # but need to create a temporary dict anyway
            results = {}

        # we need to wrap our call to /usr/sbin/softwareupdate with a utility
        # that makes softwareupdate think it is connected to a tty-like
        # device so its output is unbuffered so we can get progress info
        #
        # Try to find our ptyexec tool
        # first look in the parent directory of this file's directory
        # (../)
        parent_dir = os.path.dirname(
            os.path.dirname(
                os.path.abspath(__file__)))
        ptyexec_path = os.path.join(parent_dir, 'ptyexec')
        if not os.path.exists(ptyexec_path):
            # try absolute path in munki's normal install dir
            ptyexec_path = '/usr/local/munki/ptyexec'
        if os.path.exists(ptyexec_path):
            cmd = [ptyexec_path]
        else:
            # fall back to /usr/bin/script
            # this is not preferred because it uses way too much CPU
            # checking stdin for input that will never come...
            cmd = ['/usr/bin/script', '-q', '-t', '1', '/dev/null']
        cmd.extend(['/usr/sbin/softwareupdate', '--verbose'])

        os_version_tuple = munkicommon.getOsVersion(as_tuple=True)
        if catalog_url:
            # OS version-specific stuff to use a specific CatalogURL
            if os_version_tuple < (10, 9):
                cmd.extend(['--CatalogURL', catalog_url])
            elif os_version_tuple in [(10, 9), (10, 10)]:
                su_prefs.SetCustomCatalogURL(catalog_url)

        cmd.extend(options_list)

        munkicommon.display_debug1('softwareupdate cmd: %s', cmd)

        try:
            job = launchd.Job(cmd)
            job.start()
        except launchd.LaunchdJobException as err:
            munkicommon.display_warning(
                'Error with launchd job (%s): %s', cmd, err)
            munkicommon.display_warning('Skipping softwareupdate run.')
            return -3

        results['installed'] = []
        results['download'] = []
        results['failures'] = []

        last_output = None
        while True:
            if stop_allowed and munkicommon.stopRequested():
                job.stop()
                break

            output = job.stdout.readline()
            if not output:
                if job.returncode() is not None:
                    break
                else:
                    # no data, but we're still running
                    # sleep a bit before checking for more output
                    time.sleep(1)
                    continue

            # Don't bother parsing the stdout output if it hasn't changed since
            # the last loop iteration.
            if last_output == output:
                continue
            last_output = output

            output = output.decode('UTF-8').strip()
            # send the output to STDOUT or MunkiStatus as applicable
            if output.startswith('Progress: '):
                # Snow Leopard/Lion progress info with '-v' flag
                try:
                    percent = int(output[10:].rstrip('%'))
                except ValueError:
                    percent = -1
                munkicommon.display_percent_done(percent, 100)
            elif output.startswith('Software Update Tool'):
                # don't display this
                pass
            elif output.startswith('Copyright 2'):
                # don't display this
                pass
            elif output.startswith('Installing ') and mode == 'install':
                item = output[11:]
                if item:
                    self._ResetMunkiStatusAndDisplayMessage(output)
            elif output.startswith('Downloaded ') and mode == 'install':
                # don't display this
                pass
            elif output.startswith('Installed '):
                # 10.6 / 10.7 / 10.8. Successful install of package name.
                if mode == 'install':
                    munkicommon.display_status_minor(output)
                    results['installed'].append(output[10:])
                else:
                    pass
                    # don't display.
                    # softwareupdate logging "Installed" at the end of a
                    # successful download-only session is odd.
            elif output.startswith('Done with ') and mode == 'install':
                # 10.9 successful install
                munkicommon.display_status_minor(output)
                results['installed'].append(output[10:])
            elif output.startswith('Done '):
                # 10.5. Successful install of package name.
                munkicommon.display_status_minor(output)
                results['installed'].append(output[5:])
            elif output.startswith('Downloading ') and mode == 'install':
                # This is 10.5 & 10.7 behavior for a missing subpackage.
                munkicommon.display_warning(
                    'A necessary subpackage is not available on disk '
                    'during an Apple Software Update installation '
                    'run: %s' % output)
                results['download'].append(output[12:])
            elif output.startswith('Package failed:'):
                # Doesn't tell us which package.
                munkicommon.display_error(
                    'Apple update failed to install: %s' % output)
                results['failures'].append(output)
            elif output.startswith('x '):
                # don't display this, it's just confusing
                pass
            elif 'Missing bundle identifier' in output:
                # don't display this, it's noise
                pass
            elif output == '':
                pass
            else:
                munkicommon.display_status_minor(output)

        if catalog_url:
            # reset CatalogURL if needed
            if os_version_tuple in [(10, 9), (10, 10)]:
                su_prefs.ResetOriginalCatalogURL()

        retcode = job.returncode()
        if retcode == 0:
            # get SoftwareUpdate's LastResultCode
            last_result_code = su_prefs.GetSoftwareUpdatePref(
                'LastResultCode') or 0
            if last_result_code > 2:
                retcode = last_result_code

            if results['failures']:
                return 1

        return retcode

    def InstallAppleUpdates(self, only_unattended=False):
        """Uses softwareupdate to install previously downloaded updates.

        Returns:
          Boolean. True if a restart is needed after install, False otherwise.
        """
        # disable Stop button if we are presenting GUI status
        if munkicommon.munkistatusoutput:
            munkistatus.hideStopButton()

        # Get list of unattended_installs
        if only_unattended:
            msg = 'Installing unattended Apple Software Updates...'
            # Creating an 'unattended_install' filtered catalog
            # against the existing filtered catalog is not an option as
            # cached downloads are purged if they do not exist in the
            # filtered catalog.  Instead, get a list of updates, and their
            # product_ids, that are eligible for unattended_install.
            unattended_install_items, unattended_install_product_ids = \
                self.GetUnattendedInstalls()
            # ensure that we don't restart for unattended installations
            restartneeded = False
            if not unattended_install_items:
                return False  # didn't find any unattended installs
        else:
            msg = 'Installing available Apple Software Updates...'
            restartneeded = self.IsRestartNeeded()

        self._ResetMunkiStatusAndDisplayMessage(msg)

        installlist = self.GetSoftwareUpdateInfo()
        installresults = {'installed': [], 'download': []}

        su_options = ['-i']

        if only_unattended:
            # Append list of unattended_install items
            su_options.extend(unattended_install_items)
            # Filter installist to only include items
            # which we're attempting to install
            installlist = [item for item in installlist
                           if item.get('productKey') in
                           unattended_install_product_ids]
        else:
            # We're installing all available updates; add all their names
            for item in installlist:
                su_options.append(
                    item['name'] + '-' + item['version_to_install'])

        # new in 10.11: '--no-scan' flag to tell softwareupdate to just install
        # and not rescan for available updates.
        os_version_tuple = munkicommon.getOsVersion(as_tuple=True)
        if os_version_tuple >= (10, 11):
            su_options.append('--no-scan')
            # 10.11 seems not to like file:// URLs, and we don't really need
            # to switch to a local file URL anyway since we now have the
            # --no-scan option
            catalog_url = None
        else:
            # use our filtered local catalog
            if not os.path.exists(self.applesync.local_catalog_path):
                munkicommon.display_error(
                    'Missing local Software Update catalog at %s',
                    self.applesync.local_catalog_path)
                return False  # didn't do anything, so no restart needed
            catalog_url = 'file://localhost' + urllib2.quote(
                self.applesync.local_catalog_path)

        retcode = self._RunSoftwareUpdate(
            su_options, mode='install', catalog_url=catalog_url,
            results=installresults)
        if not 'InstallResults' in munkicommon.report:
            munkicommon.report['InstallResults'] = []

        munkicommon.display_debug1(
            'Raw Apple Update install results: %s', installresults)
        for item in installlist:
            rep = {}
            rep['name'] = item.get('apple_product_name')
            rep['version'] = item.get('version_to_install', '')
            rep['applesus'] = True
            rep['time'] = NSDate.new()
            rep['productKey'] = item.get('productKey', '')
            message = 'Apple Software Update install of %s-%s: %s'
            if rep['name'] in installresults['installed']:
                rep['status'] = 0
                install_status = 'SUCCESSFUL'
            elif ('display_name' in item and
                  item['display_name'] in installresults['installed']):
                rep['status'] = 0
                install_status = 'SUCCESSFUL'
            elif rep['name'] in installresults['download']:
                rep['status'] = -1
                install_status = 'FAILED due to missing package.'
                munkicommon.display_warning(
                    'Apple update %s, %s failed. A sub-package was missing '
                    'on disk at time of install.'
                    % (rep['name'], rep['productKey']))
            else:
                rep['status'] = -2
                install_status = 'FAILED for unknown reason'
                munkicommon.display_warning(
                    'Apple update %s, %s may have failed to install. No record '
                    'of success or failure.', rep['name'], rep['productKey'])
                if installresults['installed']:
                    munkicommon.display_warning(
                        'softwareupdate recorded these installations: %s',
                        installresults['installed'])

            munkicommon.report['InstallResults'].append(rep)
            log_msg = message % (rep['name'], rep['version'], install_status)
            munkicommon.log(log_msg, 'Install.log')

        if retcode:  # there was an error
            munkicommon.display_error('softwareupdate error: %s' % retcode)

        # Refresh Applicable updates and catalogs
        # since we may have performed some unattended installs
        if only_unattended:
            product_ids = self.GetAvailableUpdateProductIDs()
            self.applesync.WriteFilteredCatalog(product_ids)

        # clean up our now stale local cache
        if not only_unattended:
            self.applesync.clean_up_cache()
        # remove the now invalid AppleUpdates.plist and AvailableUpdates.plist
        self.ClearAppleUpdateInfo()
        # Also clear our pref value for last check date. We may have
        # just installed an update which is a pre-req for some other update.
        # Let's check again soon.
        munkicommon.set_pref('LastAppleSoftwareUpdateCheck', None)

        # show stop button again
        if munkicommon.munkistatusoutput:
            munkistatus.showStopButton()

        return restartneeded

    def AppleSoftwareUpdatesAvailable(
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
            success = self.CheckForSoftwareUpdates(force_check=True)
        else:
            # have we checked recently?  Don't want to check with
            # Apple Software Update server too frequently
            now = NSDate.new()
            next_su_check = now
            last_su_check_string = munkicommon.pref(
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
                success = self.CheckForSoftwareUpdates(force_check=True)
            else:
                success = self.CheckForSoftwareUpdates(force_check=False)
        munkicommon.display_debug1(
            'CheckForSoftwareUpdates result: %s' % success)
        if success:
            count = self.WriteAppleUpdatesFile()
        else:
            self.ClearAppleUpdateInfo()
            return 0
        return count

    def copyUpdateMetadata(self, item, metadata):
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

        # Mapping of supported RestartActions to
        # equal or greater auxiliary actions
        RestartActions = {
            'RequireRestart': ['RequireRestart', 'RecommendRestart'],
            'RecommendRestart': ['RequireRestart', 'RecommendRestart'],
            'RequireLogout': ['RequireRestart', 'RecommendRestart',
                              'RequireLogout'],
            'None': ['RequireRestart', 'RecommendRestart',
                     'RequireLogout']
        }

        for key in metadata:
            # Apply 'white-listed', non-empty metadata keys
            if key in metadata_to_copy and metadata[key]:
                if key == 'RestartAction':
                    # Ensure that a heavier weighted 'RestartAction' is not
                    # overridden by one supplied in metadata
                    if metadata[key] not in RestartActions.get(
                            item.get(key, 'None')):
                        munkicommon.display_debug2(
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
                        munkicommon.display_warning(
                            '\tIgnoring unattended_install key for Apple '
                            'update %s (ProductKey %s) '
                            'because metadata RestartAction is %s.',
                            item.get('name'), item.get('productKey'),
                            metadata.get('RestartAction'))
                        continue
                    if item.get('RestartAction', 'None') != 'None':
                        munkicommon.display_warning(
                            '\tIgnoring unattended_install key for Apple '
                            'update %s (ProductKey %s) '
                            'because item RestartAction is %s.'
                            % (item.get('name'), item.get('productKey'),
                               item.get('RestartAction')))
                        continue
                munkicommon.display_debug2('\tApplying %s...' % key)
                item[key] = metadata[key]
        return item

    def GetUnattendedInstalls(self):
        """Processes AppleUpdates.plist to return a list
        of NAME-VERSION formatted items and a list of product_ids
        which are elgible for unattended installation.
        """
        item_list = []
        product_ids = []
        try:
            pl_dict = FoundationPlist.readPlist(self.apple_updates_plist)
        except FoundationPlist.FoundationPlistException:
            munkicommon.display_error(
                'Error reading: %s', self.apple_updates_plist)
            return item_list, product_ids
        apple_updates = pl_dict.get('AppleUpdates', [])
        os_version_tuple = munkicommon.getOsVersion(as_tuple=True)
        for item in apple_updates:
            if (item.get('unattended_install') or
                    (munkicommon.pref('UnattendedAppleUpdates') and
                     item.get('RestartAction', 'None') is 'None' and
                     os_version_tuple >= (10, 10))):
                if munkicommon.blockingApplicationsRunning(item):
                    munkicommon.display_detail(
                        'Skipping unattended install of %s because '
                        'blocking application(s) running.'
                        % item['display_name'])
                    continue
                install_item = item['name'] + '-' + item['version_to_install']
                item_list.append(install_item)
                product_ids.append(item['productKey'])
            else:
                munkicommon.display_detail(
                    'Skipping install of %s because it\'s not unattended.'
                    % item['display_name'])
        return item_list, product_ids


# Make the new appleupdates module easily dropped in with exposed funcs
# for now.

apple_updates_object = None
def getAppleUpdatesInstance():
    """Returns either an AppleUpdates instance, either cached or new."""
    global apple_updates_object
    if apple_updates_object is None:
        apple_updates_object = AppleUpdates()
    return apple_updates_object


def clearAppleUpdateInfo():
    """Method for drop-in appleupdates replacement; see primary method docs."""
    return getAppleUpdatesInstance().ClearAppleUpdateInfo()


def installAppleUpdates(only_unattended=False):
    """Method for drop-in appleupdates replacement; see primary method docs."""
    return getAppleUpdatesInstance().InstallAppleUpdates(
        only_unattended=only_unattended)


def appleSoftwareUpdatesAvailable(forcecheck=False, suppresscheck=False,
                                  client_id='', forcecatalogrefresh=False):
    """Method for drop-in appleupdates replacement; see primary method docs."""
    appleUpdatesObject = getAppleUpdatesInstance()
    os_version_tuple = munkicommon.getOsVersion(as_tuple=True)
    munkisuscatalog = munkicommon.pref('SoftwareUpdateServerURL')
    if os_version_tuple >= (10, 11):
        if munkisuscatalog:
            munkicommon.display_warning(
                "Custom softwareupate catalog %s in Munki's preferences will "
                "be ignored." % munkisuscatalog)
    elif su_prefs.CatalogURLisManaged():
        munkicommon.display_warning(
            "Cannot efficiently manage Apple Software updates because "
            "softwareupdate's CatalogURL is managed via MCX or profiles. "
            "You may see unexpected or undesirable results.")
    appleUpdatesObject.client_id = client_id
    appleUpdatesObject.force_catalog_refresh = forcecatalogrefresh

    return appleUpdatesObject.AppleSoftwareUpdatesAvailable(
        force_check=forcecheck, suppress_check=suppresscheck)


def displayAppleUpdateInfo():
    """Method for drop-in appleupdates replacement; see primary method docs."""
    getAppleUpdatesInstance().DisplayAppleUpdateInfo()


if __name__ == '__main__':
    print 'This is a library of support tools for the Munki Suite.'
