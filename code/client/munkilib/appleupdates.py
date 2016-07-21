#!/usr/bin/python
# encoding: utf-8
"""
appleupdates.py

Utilities for dealing with Apple Software Update.

"""
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


import glob
import gzip
import hashlib
import os
import re
import subprocess
import time
import urllib2
import urlparse
from xml.dom import minidom
from xml.parsers import expat

import FoundationPlist
import fetch
import launchd
import munkicommon
import munkistatus
import updatecheck

# PyLint cannot properly find names inside Cocoa libraries, so issues bogus
# No name 'Foo' in module 'Bar' warnings. Disable them.
# pylint: disable=E0611
from AppKit import NSAttributedString
from Foundation import NSDate
from Foundation import NSBundle
from CoreFoundation import CFPreferencesAppValueIsForced
from CoreFoundation import CFPreferencesCopyAppValue
from CoreFoundation import CFPreferencesCopyKeyList
from CoreFoundation import CFPreferencesCopyValue
from CoreFoundation import CFPreferencesSetValue
from CoreFoundation import CFPreferencesSynchronize
from CoreFoundation import kCFPreferencesAnyUser
#from CoreFoundation import kCFPreferencesCurrentUser
from CoreFoundation import kCFPreferencesCurrentHost
from LaunchServices import LSFindApplicationForInfo
# pylint: enable=E0611

# Disable PyLint complaining about 'invalid' camelCase names
# pylint: disable=C0103


# Apple Software Update Catalog URLs.
DEFAULT_CATALOG_URLS = {
    '10.6': ('http://swscan.apple.com/content/catalogs/others/'
             'index-leopard-snowleopard.merged-1.sucatalog'),
    '10.7': ('http://swscan.apple.com/content/catalogs/others/'
             'index-lion-snowleopard-leopard.merged-1.sucatalog'),
    '10.8': ('http://swscan.apple.com/content/catalogs/others/'
             'index-mountainlion-lion-snowleopard-leopard.merged-1.sucatalog'),
    '10.9': ('https://swscan.apple.com/content/catalogs/others/'
             'index-10.9-mountainlion-lion-snowleopard-leopard.merged-1'
             '.sucatalog'),
    '10.10': ('https://swscan.apple.com/content/catalogs/others/'
              'index-10.10-10.9-mountainlion-lion-snowleopard-leopard.merged-1'
              '.sucatalog'),
    '10.11': ('https://swscan.apple.com/content/catalogs/others/'
              'index-10.11-10.10-10.9-mountainlion-lion-snowleopard-leopard'
              '.merged-1.sucatalog'),
    '10.12': ('https://swscan.apple.com/content/catalogs/others/'
              'index-10.12-10.11-10.10-10.9-mountainlion-lion-snowleopard'
              '-leopard.merged-1.sucatalog')
}

# Preference domain for Apple Software Update.
APPLE_SOFTWARE_UPDATE_PREFS_DOMAIN = 'com.apple.SoftwareUpdate'

# Apple's index of downloaded updates
INDEX_PLIST = '/Library/Updates/index.plist'

# Path to the directory where local catalogs are stored, relative to
# munkicommon.pref('ManagedInstallDir') + /swupd/mirror/.
LOCAL_CATALOG_DIR_REL_PATH = 'content/catalogs/'

# The pristine, untouched, but potentially gzipped catalog.
APPLE_DOWNLOAD_CATALOG_NAME = 'apple.sucatalog'

# The pristine, untouched, and extracted catalog.
APPLE_EXTRACTED_CATALOG_NAME = 'apple_index.sucatalog'

# The catalog containing only applicable updates
# This is used to replicate a subset of the software update
# server data to our local cache.
FILTERED_CATALOG_NAME = 'filtered_index.sucatalog'

# The catalog containing only updates to be downloaded and installed.
# We use this one when downloading Apple updates.
# In this case package URLs are still pointing to the
# software update server so we can download them, but the rest of the
# URLs point to our local cache.
LOCAL_DOWNLOAD_CATALOG_NAME = 'local_download.sucatalog'

# Catalog with all URLs (including package URLs) pointed to local cache.
# We use this one during install phase.
# This causes softwareupdate -i -a to fail cleanly if we don't
# have the required packages already downloaded.
LOCAL_CATALOG_NAME = 'local_install.sucatalog'


class Error(Exception):
    """Class for domain specific exceptions."""


class ReplicationError(Error):
    """A custom error when replication fails."""


class CatalogNotFoundError(Error):
    """A catalog was not found."""


class AppleUpdates(object):

    """Class to installation of Apple Software Updates within Munki.

    This class handles update detection, as well as downloading and installation
    of those updates.
    """

    RESTART_ACTIONS = ['RequireRestart', 'RecommendRestart']
    ORIGINAL_CATALOG_URL_KEY = '_OriginalCatalogURL'

    def __init__(self):
        self._managed_install_dir = munkicommon.pref('ManagedInstallDir')

        # fix things if somehow we died last time before resetting the
        # original CatalogURL
        os_version_tuple = munkicommon.getOsVersion(as_tuple=True)
        if os_version_tuple in [(10, 9), (10, 10)]:
            self._ResetOriginalCatalogURL()

        real_cache_dir = os.path.join(self._managed_install_dir, 'swupd')
        if os.path.exists(real_cache_dir):
            if not os.path.isdir(real_cache_dir):
                munkicommon.display_error(
                    '%s exists but is not a dir.', real_cache_dir)
        else:
            os.mkdir(real_cache_dir)

        # symlink to work around an issue with paths containing spaces
        # in 10.8.2's SoftwareUpdate
        self.cache_dir = os.path.join('/tmp', 'munki_swupd_cache')
        try:
            if os.path.islink(self.cache_dir):
                # remove any pre-existing symlink
                os.unlink(self.cache_dir)
            if os.path.exists(self.cache_dir):
                # there should not be a file or directory at that path!
                # move it
                new_name = os.path.join(
                    '/tmp', ('munki_swupd_cache_moved_%s'
                             % time.strftime('%Y.%m.%d.%H.%M.%S')))
                os.rename(self.cache_dir, new_name)
            os.symlink(real_cache_dir, self.cache_dir)
        except (OSError, IOError) as err:
            # error in setting up the cache directories
            raise Error('Could not configure cache directory: %s' % err)

        self.temp_cache_dir = os.path.join(self.cache_dir, 'mirror')
        self.local_catalog_dir = os.path.join(
            self.cache_dir, LOCAL_CATALOG_DIR_REL_PATH)

        self.apple_updates_plist = os.path.join(
            self._managed_install_dir, 'AppleUpdates.plist')

        self.apple_download_catalog_path = os.path.join(
            self.temp_cache_dir, APPLE_DOWNLOAD_CATALOG_NAME)

        self.filtered_catalog_path = os.path.join(
            self.local_catalog_dir, FILTERED_CATALOG_NAME)
        self.local_catalog_path = os.path.join(
            self.local_catalog_dir, LOCAL_CATALOG_NAME)
        self.extracted_catalog_path = os.path.join(
            self.local_catalog_dir, APPLE_EXTRACTED_CATALOG_NAME)
        self.local_download_catalog_path = os.path.join(
            self.local_catalog_dir, LOCAL_DOWNLOAD_CATALOG_NAME)

        self._update_list_cache = None

        # apple_update_metadata support
        self.client_id = ''
        self.force_catalog_refresh = False

    def getRestartAction(self, restart_action_list):
        """Returns the highest-weighted restart action of those in the list"""
        # pylint: disable=no-self-use
        restart_actions = [
            'None', 'RequireLogout', 'RecommendRestart', 'RequireRestart']
        highest_action_index = 0
        for action in restart_action_list:
            try:
                highest_action_index = max(
                    restart_actions.index(action), highest_action_index)
            except ValueError:
                # action wasn't in our list
                pass
        return restart_actions[highest_action_index]

    def GetFirmwareAlertText(self, dom):
        '''If the update is a firmware update, returns some alert
        text to display to the user, otherwise returns an empty
        string. If we cannot read a custom firmware readme to use as
        the alert, return "_DEFAULT_FIRMWARE_ALERT_TEXT_" '''
        # pylint: disable=no-self-use
        type_is_firmware = False
        options = dom.getElementsByTagName('options')
        for option in options:
            if 'type' in option.attributes.keys():
                type_value = option.attributes['type'].value
                if type_value == 'firmware':
                    type_is_firmware = True
                    break
        if type_is_firmware:
            firmware_alert_text = '_DEFAULT_FIRMWARE_ALERT_TEXT_'
            readmes = dom.getElementsByTagName('readme')
            if len(readmes):
                html = readmes[0].firstChild.data
                html_data = buffer(html.encode('utf-8'))
                attributed_string, _ = NSAttributedString.alloc(
                    ).initWithHTML_documentAttributes_(html_data, None)
                firmware_alert_text = attributed_string.string()
            return firmware_alert_text
        return ''

    def parse_cdata(self, cdata_str):
        '''Parses the CDATA string from an Apple Software Update distribution
        file and returns a dictionary with key/value pairs.

        The data in the CDATA string is in the format of an OS X .strings file,
        which is generally:

        "KEY1" = "VALUE1";
        "KEY2"='VALUE2';
        "KEY3" = 'A value
        that spans
        multiple lines.
        ';

        Values can span multiple lines; either single or double-quotes can be
        used to quote the keys and values, and the alternative quote character
        is allowed as a literal inside the other, otherwise the quote character
        is escaped.

        //-style comments and blank lines are allowed in the string; these
        should be skipped by the parser unless within a value.

        '''
        # pylint: disable=no-self-use
        parsed_data = {}
        REGEX = (r"""^\s*"""
                 r"""(?P<key_quote>['"]?)(?P<key>[^'"]+)(?P=key_quote)"""
                 r"""\s*=\s*"""
                 r"""(?P<value_quote>['"])(?P<value>.*?)(?P=value_quote);$""")
        regex = re.compile(REGEX, re.MULTILINE | re.DOTALL)

        # iterate through the string, finding all possible non-overlapping
        # matches
        for match_obj in re.finditer(regex, cdata_str):
            match_dict = match_obj.groupdict()
            if 'key' in match_dict.keys() and 'value' in match_dict.keys():
                key = match_dict['key']
                value = match_dict['value']
                # now 'de-escape' escaped quotes
                quote = match_dict.get('value_quote')
                if quote:
                    escaped_quote = '\\' + quote
                    value = value.replace(escaped_quote, quote)
                parsed_data[key] = value

        return parsed_data

    def parseSUdist(self, filename):
        '''Parses a softwareupdate dist file, looking for information of
        interest. Returns a dictionary containing the info we discovered in a
        Munki-friendly format.'''
        try:
            dom = minidom.parse(filename)
        except expat.ExpatError:
            munkicommon.display_error(
                'Invalid XML in %s', filename)
            return None
        except IOError, err:
            munkicommon.display_error(
                'Error reading %s: %s', filename, err)
            return None

        su_choice_id_key = 'su'
        # look for <choices-outline ui='SoftwareUpdate'
        choice_outlines = dom.getElementsByTagName('choices-outline') or []
        for outline in choice_outlines:
            if 'ui' in outline.attributes.keys():
                if outline.attributes['ui'].value == 'SoftwareUpdate':
                    lines = outline.getElementsByTagName('line')
                    if lines:
                        if 'choice' in lines[0].attributes.keys():
                            su_choice_id_key = (
                                lines[0].attributes['choice'].value)

        # get values from choice id=su_choice_id_key
        # (there may be more than one!)
        pkgs = {}
        su_choice = {}
        choice_elements = dom.getElementsByTagName('choice') or []
        for choice in choice_elements:
            keys = choice.attributes.keys()
            if 'id' in keys:
                choice_id = choice.attributes['id'].value
                if choice_id == su_choice_id_key:
                    # this is the one Software Update uses
                    for key in keys:
                        su_choice[key] = choice.attributes[key].value
                    pkg_refs = choice.getElementsByTagName('pkg-ref') or []
                    for pkg in pkg_refs:
                        if 'id' in pkg.attributes.keys():
                            pkg_id = pkg.attributes['id'].value
                            if not pkg_id in pkgs.keys():
                                pkgs[pkg_id] = {}
                    # now get all pkg-refs so we can assemble all metadata
                    # there is additional metadata in pkg-refs outside of the
                    # choices element
                    pkg_refs = dom.getElementsByTagName('pkg-ref') or []
                    for pkg in pkg_refs:
                        if 'id' in pkg.attributes.keys():
                            pkg_id = pkg.attributes['id'].value
                            if not pkg_id in pkgs.keys():
                                # this pkg_id was not in our choice list
                                continue
                            if pkg.firstChild:
                                try:
                                    pkg_name = pkg.firstChild.wholeText
                                    if pkg_name:
                                        pkgs[pkg_id]['name'] = pkg_name
                                except AttributeError:
                                    pass
                            if 'onConclusion' in pkg.attributes.keys():
                                pkgs[pkg_id]['RestartAction'] = (
                                    pkg.attributes['onConclusion'].value)
                            if 'version' in pkg.attributes.keys():
                                pkgs[pkg_id]['version'] = (
                                    pkg.attributes['version'].value)
                            if 'installKBytes' in pkg.attributes.keys():
                                pkgs[pkg_id]['installed_size'] = int(
                                    pkg.attributes['installKBytes'].value)
                            if 'packageIdentifier' in pkg.attributes.keys():
                                pkgs[pkg_id]['packageid'] = (
                                    pkg.attributes['packageIdentifier'].value)

        # look for localization and parse CDATA
        cdata = {}
        localizations = dom.getElementsByTagName('localization')
        if localizations:
            string_elements = localizations[0].getElementsByTagName('strings')
            if string_elements:
                strings = string_elements[0]
                if strings.firstChild:
                    try:
                        text = strings.firstChild.wholeText
                        cdata = self.parse_cdata(text)
                    except AttributeError:
                        cdata = {}

        # get blocking_applications, if any.
        # First, find all the must-close items.
        must_close_app_ids = []
        must_close_items = dom.getElementsByTagName('must-close')
        for item in must_close_items:
            apps = item.getElementsByTagName('app')
            for app in apps:
                keys = app.attributes.keys()
                if 'id' in keys:
                    must_close_app_ids.append(app.attributes['id'].value)

        # next, we convert Apple's must-close items to
        # Munki's blocking_applications
        blocking_apps = []
        # this will only find blocking_applications that are currently installed
        # on the machine running this code, but that's OK for our needs
        #
        # use set() to eliminate any duplicate application ids
        for app_id in set(must_close_app_ids):
            dummy_resultcode, dummy_fileref, nsurl = LSFindApplicationForInfo(
                0, app_id, None, None, None)
            if nsurl and nsurl.isFileURL():
                pathname = nsurl.path()
                dirname = os.path.dirname(pathname)
                executable = munkicommon.getAppBundleExecutable(pathname)
                if executable:
                    # path to executable should be location agnostic
                    executable = executable[len(dirname + '/'):]
                blocking_apps.append(executable or pathname)

        # get firmware alert text if any
        firmware_alert_text = self.GetFirmwareAlertText(dom)

        # assemble!
        info = {}
        info['name'] = su_choice.get('suDisabledGroupID', '')
        info['display_name'] = su_choice.get('title', '')
        info['apple_product_name'] = info['display_name']
        info['version_to_install'] = su_choice.get('versStr', '')
        info['description'] = su_choice.get('description', '')
        for key in info.keys():
            if info[key].startswith('SU_'):
                # get value from cdata dictionary
                info[key] = cdata.get(info[key], info[key])
        #info['pkg_refs'] = pkgs
        installed_size = 0
        for pkg in pkgs.values():
            installed_size += pkg.get('installed_size', 0)
        info['installed_size'] = installed_size
        if blocking_apps:
            info['blocking_applications'] = blocking_apps
        restart_actions = [pkg['RestartAction']
                           for pkg in pkgs.values() if 'RestartAction' in pkg]
        effective_restart_action = self.getRestartAction(restart_actions)
        if effective_restart_action != 'None':
            info['RestartAction'] = effective_restart_action
        if firmware_alert_text:
            info['firmware_alert_text'] = firmware_alert_text

        return info

    def _ResetMunkiStatusAndDisplayMessage(self, message):
        """Resets MunkiStatus detail/percent, logs and msgs GUI.

        Args:
          message: str message to display to the user and log.
        """
        # pylint: disable=no-self-use
        munkicommon.display_status_major(message)

    def _GetURLPath(self, full_url):
        """Returns only the URL path.

        Args:
          full_url: a str URL, complete with schema, domain, path, etc.
        Returns:
          The str path of the URL.
        """
        # pylint: disable=no-self-use
        return urlparse.urlsplit(full_url)[2]  # (schema, netloc, path, ...)

    def RewriteURL(self, full_url):
        """Rewrites a single URL to point to our local replica.

        Args:
          full_url: a str URL, complete with schema, domain, path, etc.
        Returns:
          A str URL, rewritten if needed to point to the local cache.
        """
        local_base_url = 'file://localhost' + urllib2.quote(self.cache_dir)
        if full_url.startswith(local_base_url):
            return full_url  # url is already local, so just return it.
        return local_base_url + self._GetURLPath(full_url)

    def RewriteProductURLs(self, product, rewrite_pkg_urls=False):
        """Rewrites URLs in the product to point to our local cache.

        Args:
          product: list, of dicts, product info. This dict is changed by
              this function.
          rewrite_pkg_urls: bool, default False, if True package URLs are
              rewritten, otherwise only MetadataURLs are rewritten.
        """
        if 'ServerMetadataURL' in product:
            product['ServerMetadataURL'] = self.RewriteURL(
                product['ServerMetadataURL'])
        for package in product.get('Packages', []):
            if rewrite_pkg_urls and 'URL' in package:
                package['URL'] = self.RewriteURL(package['URL'])
            if 'MetadataURL' in package:
                package['MetadataURL'] = self.RewriteURL(
                    package['MetadataURL'])
        distributions = product['Distributions']
        for dist_lang in distributions.keys():
            distributions[dist_lang] = self.RewriteURL(
                distributions[dist_lang])

    def RewriteCatalogURLs(self, catalog, rewrite_pkg_urls=False):
        """Rewrites URLs in a catalog to point to our local replica.

        Args:
          rewrite_pkg_urls: Boolean, if True package URLs are rewritten,
              otherwise only MetadataURLs are rewritten.
        """
        if not 'Products' in catalog:
            return

        for product_key in catalog['Products'].keys():
            product = catalog['Products'][product_key]
            self.RewriteProductURLs(product, rewrite_pkg_urls=rewrite_pkg_urls)

    def RetrieveURLToCacheDir(self, full_url, copy_only_if_missing=False):
        """Downloads a URL and stores it in the same relative path on our
        filesystem. Returns a path to the replicated file.

        Args:
          full_url: str, full URL to retrieve.
          copy_only_if_missing: boolean, True to copy only if the file is not
              already cached, False to copy regardless of existence in cache.
        Returns:
          String path to the locally cached file.
        """
        relative_url = os.path.normpath(self._GetURLPath(full_url).lstrip('/'))
        local_file_path = os.path.join(self.cache_dir, relative_url)
        local_dir_path = os.path.dirname(local_file_path)
        if copy_only_if_missing and os.path.exists(local_file_path):
            return local_file_path
        if not os.path.exists(local_dir_path):
            try:
                os.makedirs(local_dir_path)
            except OSError as oserr:
                raise ReplicationError(oserr)
        try:
            self.GetSoftwareUpdateResource(
                full_url, local_file_path, resume=True)
        except fetch.MunkiDownloadError as err:
            raise ReplicationError(err)
        return local_file_path

    def GetSoftwareUpdateResource(self, url, destinationpath, resume=False):
        """Gets item from Apple Software Update Server.

        Args:
          url: str, URL of the resource to download.
          destinationpath: str, path of the destination to save the resource.
          resume: boolean, True to resume downloads, False to redownload.
        Returns:
          Boolean. True if a new download was required, False if the item was
          already in the local cache.
        """
        # pylint: disable=no-self-use
        machine = munkicommon.getMachineFacts()
        darwin_version = os.uname()[2]
        # Set the User-Agent header to match that used by Apple's
        # softwareupdate client for better compatibility.
        user_agent_header = (
            "User-Agent: managedsoftwareupdate/%s Darwin/%s (%s) (%s)"
            % (machine['munki_version'], darwin_version,
               machine['arch'], machine['machine_model']))
        return fetch.getResourceIfChangedAtomically(
            url, destinationpath, custom_headers=[user_agent_header],
            resume=resume, follow_redirects=True)

    def CacheUpdateMetadata(self):
        """Copies ServerMetadata (.smd), Metadata (.pkm), and
        Distribution (.dist) files for the available updates to the local
        machine and writes a new sucatalog that refers to the local copies
        of these files."""
        catalog = FoundationPlist.readPlist(self.filtered_catalog_path)
        if not 'Products' in catalog:
            munkicommon.display_warning(
                '"Products" not found in %s', self.filtered_catalog_path)
            return

        for product_key in catalog['Products'].keys():
            if munkicommon.stopRequested():
                break
            munkicommon.display_status_minor(
                'Caching metadata for product ID %s', product_key)
            product = catalog['Products'][product_key]
            if 'ServerMetadataURL' in product:
                self.RetrieveURLToCacheDir(
                    product['ServerMetadataURL'], copy_only_if_missing=True)

            for package in product.get('Packages', []):
                if munkicommon.stopRequested():
                    break
                if 'MetadataURL' in package:
                    munkicommon.display_status_minor(
                        'Caching package metadata for product ID %s',
                        product_key)
                    self.RetrieveURLToCacheDir(
                        package['MetadataURL'], copy_only_if_missing=True)
                # if 'URL' in package:
                #    munkicommon.display_status_minor(
                #        'Caching package for product ID %s',
                #        product_key)
                #    self.RetrieveURLToCacheDir(
                #        package['URL'], copy_only_if_missing=True)

            distributions = product['Distributions']
            for dist_lang in distributions.keys():
                if munkicommon.stopRequested():
                    break
                munkicommon.display_status_minor(
                    'Caching %s distribution for product ID %s',
                    dist_lang, product_key)
                dist_url = distributions[dist_lang]
                try:
                    self.RetrieveURLToCacheDir(
                        dist_url, copy_only_if_missing=True)
                except ReplicationError:
                    munkicommon.display_warning(
                        'Could not cache %s distribution for product ID %s',
                        dist_lang, product_key)

        if munkicommon.stopRequested():
            return

        if not os.path.exists(self.local_catalog_dir):
            try:
                os.makedirs(self.local_catalog_dir)
            except OSError as oserr:
                raise ReplicationError(oserr)

        # rewrite metadata URLs to point to local caches.
        self.RewriteCatalogURLs(catalog, rewrite_pkg_urls=False)
        FoundationPlist.writePlist(
            catalog, self.local_download_catalog_path)

        # rewrite all URLs, including pkgs, to point to local caches.
        self.RewriteCatalogURLs(catalog, rewrite_pkg_urls=True)
        FoundationPlist.writePlist(catalog, self.local_catalog_path)

    def _GetPreferredLocalization(self, list_of_localizations):
        '''Picks the best localization from a list of available
        localizations. Returns a single language/localization name.'''
        # pylint: disable=no-self-use
        localization_preferences = (
            munkicommon.pref('AppleSoftwareUpdateLanguages') or ['English'])
        preferred_langs = (
            NSBundle.preferredLocalizationsFromArray_forPreferences_(
                list_of_localizations, localization_preferences))
        if preferred_langs:
            return preferred_langs[0]

        # first fallback, return en or English
        if 'English' in list_of_localizations:
            return 'English'
        elif 'en' in list_of_localizations:
            return 'en'

        # if we get this far, just return the first language
        # in the list of available languages
        return list_of_localizations[0]

    def GetDistributionForProductKey(
            self, product_key, sucatalog, language=None):
        '''Returns the path to a distibution file from /Library/Updates
        or the local cache for the given product_key. If language is
        defined it will try to retrieve that specific language, otherwise
        it will use the available languages and the value of the
        AppleSoftwareUpdateLanguages preference to return the "best"
        language of those available.'''
        try:
            catalog = FoundationPlist.readPlist(sucatalog)
        except FoundationPlist.NSPropertyListSerializationException:
            return None
        product = catalog.get('Products', {}).get(product_key, {})
        if product:
            distributions = product.get('Distributions', {})
            if distributions:
                available_languages = distributions.keys()
                if language:
                    preferred_language = language
                else:
                    preferred_language = self._GetPreferredLocalization(
                        available_languages)
                url = distributions[preferred_language]
                # do we already have it in /Library/Updates?
                filename = os.path.basename(self._GetURLPath(url))
                dist_path = os.path.join(
                    '/Library/Updates', product_key, filename)
                if os.path.exists(dist_path):
                    return dist_path
                # look for it in the cache
                if url.startswith('file://localhost'):
                    fileurl = url[len('file://localhost'):]
                    dist_path = urllib2.unquote(fileurl)
                    if os.path.exists(dist_path):
                        return dist_path
                # we haven't downloaded this yet
                try:
                    return self.RetrieveURLToCacheDir(
                        url, copy_only_if_missing=True)
                except ReplicationError, err:
                    munkicommon.display_error(
                        'Could not retrieve %s: %s', url, err)
        return None

    def _WriteFilteredCatalog(self, product_ids, catalog_path):
        """Write out a sucatalog containing only the updates in product_ids.

        Args:
          product_ids: list of str, ProductIDs.
          catalog_path: str, path of catalog to write.
        """
        catalog = FoundationPlist.readPlist(self.extracted_catalog_path)
        product_ids = set(product_ids)  # convert to set for O(1) lookups.
        for product_id in list(catalog.get('Products', [])):
            if product_id not in product_ids:
                del catalog['Products'][product_id]
        FoundationPlist.writePlist(catalog, catalog_path)

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
        msg = 'Downloading available Apple Software Updates...'
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
            catalog_url = self._GetAppleCatalogURL()

        retcode = self._RunSoftwareUpdate(
            ['-d', '-a'], catalog_url=catalog_url, stop_allowed=True)
        if retcode:  # there was an error
            munkicommon.display_error('softwareupdate error: %s', retcode)
            return False
        return True

    def GetAvailableUpdateProductIDs(self):
        """Returns a list of product IDs of available Apple updates.

        Returns:
          A list of string Apple update products ids.
        """
        # pylint: disable=no-self-use
        if not os.path.exists(INDEX_PLIST):
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

    def ExtractAndCopyDownloadedCatalog(self, _open=open):
        """Copy the downloaded catalog to a new file, extracting if gzipped.

        Args:
          _open: func, default builtin open(), open method for unit testing.
        """
        if not os.path.exists(self.local_catalog_dir):
            try:
                os.makedirs(self.local_catalog_dir)
            except OSError as oserr:
                raise ReplicationError(oserr)

        local_apple_sus_catalog = os.path.join(
            self.local_catalog_dir, APPLE_EXTRACTED_CATALOG_NAME)

        f = _open(self.apple_download_catalog_path, 'rb')
        magic = f.read(2)
        contents = ''
        if magic == '\x1f\x8b':  # File is gzip compressed.
            f.close()  # Close the open handle first.
            f = gzip.open(self.apple_download_catalog_path, 'rb')
        else:  # Hopefully a nice plain plist.
            f.seek(0)
        contents = f.read()
        f.close()
        f = _open(local_apple_sus_catalog, 'wb')
        f.write(contents)
        f.close()

    def _GetAppleCatalogURL(self):
        """Returns the catalog URL of the Apple SU catalog for the current Mac.

        Returns:
          String catalog URL for the current Mac.
        Raises:
          CatalogNotFoundError: an Apple catalog was not found for this Mac.
        """
        # Prefer Munki's preferences file.
        munkisuscatalog = munkicommon.pref('SoftwareUpdateServerURL')
        if munkisuscatalog:
            return munkisuscatalog

        # Otherwise prefer MCX or /Library/Preferences/com.apple.SoftwareUpdate
        prefs_catalog_url = self.GetSoftwareUpdatePref('CatalogURL')
        if prefs_catalog_url:
            return prefs_catalog_url

        # Finally, fall back to using a hard-coded url in DEFAULT_CATALOG_URLS.
        os_version = munkicommon.getOsVersion()
        catalog_url = DEFAULT_CATALOG_URLS.get(os_version, None)
        if catalog_url:
            return catalog_url

        raise CatalogNotFoundError(
            'No default Software Update CatalogURL for: %s' % os_version)

    def CacheAppleCatalog(self):
        """Caches a local copy of the current Apple SUS catalog.

        Raises:
          CatalogNotFoundError: a catalog was not found to cache.
          ReplicationError: there was an error making the cache directory.
          fetch.MunkiDownloadError: error downloading the catalog.
        """
        try:
            catalog_url = self._GetAppleCatalogURL()
        except CatalogNotFoundError as err:
            munkicommon.display_error(unicode(err))
            raise
        if not os.path.exists(self.temp_cache_dir):
            try:
                os.makedirs(self.temp_cache_dir)
            except OSError as oserr:
                raise ReplicationError(oserr)
        msg = 'Checking Apple Software Update catalog...'
        self._ResetMunkiStatusAndDisplayMessage(msg)
        munkicommon.display_detail('Caching CatalogURL %s', catalog_url)
        try:
            dummy_file_changed = self.GetSoftwareUpdateResource(
                catalog_url, self.apple_download_catalog_path, resume=True)
            self.ExtractAndCopyDownloadedCatalog()
        except fetch.MunkiDownloadError:
            raise

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
        new_hash = munkicommon.getsha256hash(self.apple_download_catalog_path)
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
          Boolean. True if there are new updates, False otherwise.
        """
        before_hash = munkicommon.getsha256hash(
            self.apple_download_catalog_path)

        try:
            self.CacheAppleCatalog()
        except CatalogNotFoundError:
            return False
        except (ReplicationError, fetch.MunkiDownloadError) as err:
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
            if self.GetSoftwareUpdateInfo():
                return True
            else:
                return False

        if self.DownloadAvailableUpdates():  # Success; ready to install.
            munkicommon.set_pref('LastAppleSoftwareUpdateCheck', NSDate.date())
            product_ids = self.GetAvailableUpdateProductIDs()
            if not product_ids:
                # No updates found
                return False
            os_version_tuple = munkicommon.getOsVersion(as_tuple=True)
            if os_version_tuple < (10, 11):
                self._WriteFilteredCatalog(
                    product_ids, self.filtered_catalog_path)
                try:
                    self.CacheUpdateMetadata()
                except ReplicationError as err:
                    munkicommon.display_warning(
                        'Could not replicate software update metadata:')
                    munkicommon.display_warning('\t%s', unicode(err))
                    return False
            return True
        else:
            munkicommon.set_pref('LastAppleSoftwareUpdateCheck', NSDate.date())
            return False  # Download error, allow check again soon.

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
        """Uses /Library/Updates/index.plist to generate the AppleUpdates.plist,
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
        recommended_updates = self.GetSoftwareUpdatePref(
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

        if product_keys:
            os_version_tuple = munkicommon.getOsVersion(as_tuple=True)
            if os_version_tuple < (10, 11):
                sucatalog = self.local_catalog_path
            else:
                # use the cached Apple catalog
                sucatalog = self.extracted_catalog_path
            for product_key in product_keys:
                if not self.UpdateDownloaded(product_key):
                    munkicommon.display_warning(
                        'Product %s does not appear to be downloaded',
                        product_key)
                    continue
                localized_dist = self.GetDistributionForProductKey(
                    product_key, sucatalog)
                if not localized_dist:
                    munkicommon.display_warning(
                        'No dist file for product %s', product_key)
                    continue
                if (not recommended_updates and
                        not localized_dist.endswith('English.dist')):
                    # we need the English versions of some of the data
                    # see (https://groups.google.com/d/msg/munki-dev/
                    # _5HdMyy3kKU/YFxqslayDQAJ)
                    english_dist = self.GetDistributionForProductKey(
                        product_key, sucatalog, 'English')
                    if english_dist:
                        english_su_info = self.parseSUdist(english_dist)
                su_info = self.parseSUdist(localized_dist)
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
                        metadata_item = updatecheck.getItemDetail(
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

    def GetSoftwareUpdatePref(self, pref_name):
        """Returns a preference from com.apple.SoftwareUpdate.

        Uses CoreFoundation.

        Args:
          pref_name: str preference name to get.
        """
        # pylint: disable=no-self-use
        return CFPreferencesCopyAppValue(
            pref_name, APPLE_SOFTWARE_UPDATE_PREFS_DOMAIN)

    def _GetCatalogURL(self):
        """Returns Software Update's CatalogURL"""
        # pylint: disable=no-self-use
        return CFPreferencesCopyValue(
            'CatalogURL',
            APPLE_SOFTWARE_UPDATE_PREFS_DOMAIN,
            kCFPreferencesAnyUser, kCFPreferencesCurrentHost)

    def _SetCustomCatalogURL(self, catalog_url):
        """Sets Software Update's CatalogURL to custom value, storing the
        original"""
        software_update_key_list = CFPreferencesCopyKeyList(
            APPLE_SOFTWARE_UPDATE_PREFS_DOMAIN,
            kCFPreferencesAnyUser, kCFPreferencesCurrentHost) or []
        if self.ORIGINAL_CATALOG_URL_KEY not in software_update_key_list:
            # store the original CatalogURL
            original_catalog_url = self._GetCatalogURL()
            if not original_catalog_url:
                # can't store None as a CFPreference
                original_catalog_url = ""
            CFPreferencesSetValue(
                self.ORIGINAL_CATALOG_URL_KEY,
                original_catalog_url,
                APPLE_SOFTWARE_UPDATE_PREFS_DOMAIN,
                kCFPreferencesAnyUser, kCFPreferencesCurrentHost)
        # now set our custom CatalogURL
        os_version_tuple = munkicommon.getOsVersion(as_tuple=True)
        if os_version_tuple < (10, 11):
            CFPreferencesSetValue(
                'CatalogURL', catalog_url,
                APPLE_SOFTWARE_UPDATE_PREFS_DOMAIN,
                kCFPreferencesAnyUser, kCFPreferencesCurrentHost)
            # finally, sync things up
            if not CFPreferencesSynchronize(
                    APPLE_SOFTWARE_UPDATE_PREFS_DOMAIN,
                    kCFPreferencesAnyUser, kCFPreferencesCurrentHost):
                munkicommon.display_error(
                    'Error setting com.apple.SoftwareUpdate CatalogURL.')
        else:
            # use softwareupdate --set-catalog
            proc = subprocess.Popen(
                ['/usr/sbin/softwareupdate', '--set-catalog', catalog_url],
                bufsize=-1, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            (output, err) = proc.communicate()
            if output:
                munkicommon.display_detail(output)
            if err:
                munkicommon.display_error(err)

    def _ResetOriginalCatalogURL(self):
        """Resets SoftwareUpdate's CatalogURL to the original value"""
        software_update_key_list = CFPreferencesCopyKeyList(
            APPLE_SOFTWARE_UPDATE_PREFS_DOMAIN,
            kCFPreferencesAnyUser, kCFPreferencesCurrentHost) or []
        if self.ORIGINAL_CATALOG_URL_KEY not in software_update_key_list:
            # do nothing
            return
        original_catalog_url = CFPreferencesCopyValue(
            self.ORIGINAL_CATALOG_URL_KEY,
            APPLE_SOFTWARE_UPDATE_PREFS_DOMAIN,
            kCFPreferencesAnyUser, kCFPreferencesCurrentHost)
        if not original_catalog_url:
            original_catalog_url = None
        # reset CatalogURL to the one we stored
        os_version_tuple = munkicommon.getOsVersion(as_tuple=True)
        if os_version_tuple < (10, 11):
            CFPreferencesSetValue(
                'CatalogURL', original_catalog_url,
                APPLE_SOFTWARE_UPDATE_PREFS_DOMAIN,
                kCFPreferencesAnyUser, kCFPreferencesCurrentHost)
        else:
            if original_catalog_url:
                # use softwareupdate --set-catalog
                cmd = ['/usr/sbin/softwareupdate',
                       '--set-catalog', original_catalog_url]
            else:
                # use softwareupdate --clear-catalog
                cmd = ['/usr/sbin/softwareupdate', '--clear-catalog']
            proc = subprocess.Popen(cmd, bufsize=-1, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)
            (output, err) = proc.communicate()
            if output:
                munkicommon.display_detail(output)
            if err:
                munkicommon.display_error(err)

        # remove ORIGINAL_CATALOG_URL_KEY
        CFPreferencesSetValue(
            self.ORIGINAL_CATALOG_URL_KEY, None,
            APPLE_SOFTWARE_UPDATE_PREFS_DOMAIN,
            kCFPreferencesAnyUser, kCFPreferencesCurrentHost)
        # sync
        if not CFPreferencesSynchronize(
                APPLE_SOFTWARE_UPDATE_PREFS_DOMAIN,
                kCFPreferencesAnyUser, kCFPreferencesCurrentHost):
            munkicommon.display_error(
                'Error resetting com.apple.SoftwareUpdate CatalogURL.')

    def CatalogURLisManaged(self):
        """Returns True if Software Update's CatalogURL is managed
        via MCX or Profiles"""
        # pylint: disable=no-self-use
        return CFPreferencesAppValueIsForced(
            'CatalogURL', APPLE_SOFTWARE_UPDATE_PREFS_DOMAIN)

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
                self._SetCustomCatalogURL(catalog_url)

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
                self._ResetOriginalCatalogURL()

        retcode = job.returncode()
        if retcode == 0:
            # get SoftwareUpdate's LastResultCode
            last_result_code = self.GetSoftwareUpdatePref(
                'LastResultCode') or 0
            if last_result_code > 2:
                retcode = last_result_code

            if results['failures']:
                return 1

        return retcode

    # TODO(jrand): The below functions are externally called. Should all
    #   others be private?

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
            if not os.path.exists(self.local_catalog_path):
                munkicommon.display_error(
                    'Missing local Software Update catalog at %s',
                    self.local_catalog_path)
                return False  # didn't do anything, so no restart needed
            catalog_url = 'file://localhost' + urllib2.quote(
                self.local_catalog_path)

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
            self._WriteFilteredCatalog(product_ids, self.filtered_catalog_path)

        # clean up our now stale local cache
        if os.path.exists(self.cache_dir) and not only_unattended:
            # TODO(unassigned): change this to Pythonic delete.
            dummy_retcode = subprocess.call(['/bin/rm', '-rf', self.cache_dir])
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
        if suppress_check:
            # typically because we're doing a logout install; if
            # there are no waiting Apple Updates we shouldn't
            # trigger a check for them.
            pass
        elif force_check:
            # typically because user initiated the check from
            # Managed Software Update.app
            dummy_success = self.CheckForSoftwareUpdates(force_check=True)
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
                    interval = 24 * 60 * 60  # only force check every 24 hours.
                    next_su_check = last_su_check.dateByAddingTimeInterval_(
                        interval)
                except (ValueError, TypeError):
                    pass
            if now.timeIntervalSinceDate_(next_su_check) >= 0:
                dummy_success = self.CheckForSoftwareUpdates(force_check=True)
            else:
                dummy_success = self.CheckForSoftwareUpdates(force_check=False)
        # always update or remove AppleUpdates.plist
        count = self.WriteAppleUpdatesFile()
        if munkicommon.stopRequested():
            return 0
        return count

    def SoftwareUpdateList(self):
        """Returns a list of str update names using softwareupdate -l."""
        if self._update_list_cache is not None:
            return self._update_list_cache

        updates = []
        munkicommon.display_detail(
            'Getting list of available Apple Software Updates')
        cmd = ['/usr/sbin/softwareupdate', '-l']
        proc = subprocess.Popen(cmd, shell=False, bufsize=-1,
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output, dummy_err = proc.communicate()
        if proc.returncode == 0:
            updates = [str(item)[5:] for item in str(output).splitlines()
                       if str(item).startswith('   * ')]
        munkicommon.display_detail(
            'softwareupdate returned %d updates.', len(updates))
        self._update_list_cache = updates
        return updates

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


def softwareUpdateList():
    """Method for drop-in appleupdates replacement; see primary method docs."""
    return getAppleUpdatesInstance().SoftwareUpdateList()


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
    elif appleUpdatesObject.CatalogURLisManaged():
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
