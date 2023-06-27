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
appleupdates.sync

Created by Greg Neagle on 2017-01-06.

Utilities for replicating and retrieving Apple software update metadata
"""
from __future__ import absolute_import, print_function

import gzip
import os
import subprocess
import time
import xattr

# pylint: disable=ungrouped-imports
try:
    # Python 2
    from urllib2 import quote, unquote
except ImportError:
    # Python 3
    from urllib.parse import quote, unquote
try:
    # Python 2
    from urlparse import urlsplit
except ImportError:
    # Python 3
    from urllib.parse import urlsplit
# pylint: enable=ungrouped-imports


# PyLint cannot properly find names inside Cocoa libraries, so issues bogus
# No name 'Foo' in module 'Bar' warnings. Disable them.
# pylint: disable=E0611
from Foundation import NSBundle
# pylint: enable=E0611

from . import su_prefs

from .. import display
from .. import fetch
from .. import info
from .. import osutils
from .. import prefs
from .. import processes
from .. import FoundationPlist
from ..wrappers import unicode_or_str


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
              '-leopard.merged-1.sucatalog'),
    '10.13': ('https://swscan.apple.com/content/catalogs/others/'
              'index-10.13-10.12-10.11-10.10-10.9-mountainlion-lion-snowleopard'
              '-leopard.merged-1.sucatalog'),
    '10.14': ('https://swscan.apple.com/content/catalogs/others/'
              'index-10.14-10.13-10.12-10.11-10.10-10.9-mountainlion-lion-'
              'snowleopard-leopard.merged-1.sucatalog'),
    '10.15': ('https://swscan.apple.com/content/catalogs/others/'
              'index-10.15-10.14-10.13-10.12-10.11-10.10-10.9-mountainlion-'
              'lion-snowleopard-leopard.merged-1.sucatalog'),
    '10.16': ('https://swscan.apple.com/content/catalogs/others/'
              'index-10.16-10.15-10.14-10.13-10.12-10.11-10.10-10.9-'
              'mountainlion-lion-snowleopard-leopard.merged-1.sucatalog'),
    '11': ('https://swscan.apple.com/content/catalogs/others/'
           'index-10.16-10.15-10.14-10.13-10.12-10.11-10.10-10.9-'
           'mountainlion-lion-snowleopard-leopard.merged-1.sucatalog'),
    '12': ('https://swscan.apple.com/content/catalogs/others/'
           'index-12-10.16-10.15-10.14-10.13-10.12-10.11-10.10-10.9-'
           'mountainlion-lion-snowleopard-leopard.merged-1.sucatalog'),
    '13': ('https://swscan.apple.com/content/catalogs/others/'
           'index-13-12-10.16-10.15-10.14-10.13-10.12-10.11-10.10-10.9-'
           'mountainlion-lion-snowleopard-leopard.merged-1.sucatalog'),
    '14': ('https://swscan.apple.com/content/catalogs/others/'
           'index-14-13-12-10.16-10.15-10.14-10.13-10.12-10.11-10.10-10.9-'
           'mountainlion-lion-snowleopard-leopard.merged-1.sucatalog'),
}

# Preference domain for Apple Software Update.
APPLE_SOFTWARE_UPDATE_PREFS_DOMAIN = 'com.apple.SoftwareUpdate'

# Path to the directory where local catalogs are stored, relative to
# prefs.pref('ManagedInstallDir') + /swupd/mirror/.
LOCAL_CATALOG_DIR_REL_PATH = 'content/catalogs/'

# The pristine, untouched, but potentially gzipped catalog.
APPLE_DOWNLOAD_CATALOG_NAME = 'apple.sucatalog'

# The pristine, untouched, and extracted catalog.
APPLE_EXTRACTED_CATALOG_NAME = 'apple_index.sucatalog'

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

# extended attribute name for storing the OS version when the sucatalog was
# downloaded
XATTR_OS_VERS = 'com.googlecode.munki.os_version'


class Error(Exception):
    """Class for domain specific exceptions."""


class ReplicationError(Error):
    """A custom error when replication fails."""


class CatalogNotFoundError(Error):
    """A catalog was not found."""


class AppleUpdateSync(object):
    '''Object that handles local replication of Apple Software Update data'''

    def __init__(self):
        '''Set 'em all up '''
        real_cache_dir = os.path.join(prefs.pref('ManagedInstallDir'), 'swupd')
        if os.path.exists(real_cache_dir):
            if not os.path.isdir(real_cache_dir):
                display.display_error(
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

        self.apple_download_catalog_path = os.path.join(
            self.temp_cache_dir, APPLE_DOWNLOAD_CATALOG_NAME)

        self.local_catalog_path = os.path.join(
            self.local_catalog_dir, LOCAL_CATALOG_NAME)
        self.extracted_catalog_path = os.path.join(
            self.local_catalog_dir, APPLE_EXTRACTED_CATALOG_NAME)
        self.local_download_catalog_path = os.path.join(
            self.local_catalog_dir, LOCAL_DOWNLOAD_CATALOG_NAME)

    def get_apple_catalogurl(self):
        """Returns the catalog URL of the Apple SU catalog for the current Mac.

        Returns:
          String catalog URL for the current Mac.
        Raises:
          CatalogNotFoundError: an Apple catalog was not found for this Mac.
        """
        # pylint: disable=no-self-use
        os_version_tuple = osutils.getOsVersion(as_tuple=True)
        # Prefer Munki's preferences file in OS X <= 10.10
        munkisuscatalog = prefs.pref('SoftwareUpdateServerURL')
        if munkisuscatalog:
            if os_version_tuple < (10, 11):
                # only pay attention to Munki's SoftwareUpdateServerURL pref
                # in 10.10 and earlier
                return munkisuscatalog

        # Otherwise prefer MCX or /Library/Preferences/com.apple.SoftwareUpdate
        prefs_catalog_url = su_prefs.pref('CatalogURL')
        if prefs_catalog_url:
            return prefs_catalog_url

        # Finally, fall back to using a hard-coded url in DEFAULT_CATALOG_URLS.
        os_version = osutils.getOsVersion()
        catalog_url = DEFAULT_CATALOG_URLS.get(os_version, None)
        if catalog_url:
            return catalog_url

        raise CatalogNotFoundError(
            'No default Software Update CatalogURL for macOS %s' % os_version)

    def copy_downloaded_catalog(self, _open=open):
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

        fileref = _open(self.apple_download_catalog_path, 'rb')
        magic = fileref.read(2)
        contents = ''
        if magic == '\x1f\x8b':  # File is gzip compressed.
            fileref.close()  # Close the open handle first.
            fileref = gzip.open(self.apple_download_catalog_path, 'rb')
        else:  # Hopefully a nice plain plist.
            fileref.seek(0)
        contents = fileref.read()
        fileref.close()
        fileref = _open(local_apple_sus_catalog, 'wb')
        fileref.write(contents)
        fileref.close()

    def cache_apple_catalog(self):
        """Caches a local copy of the current Apple SUS catalog.

        Raises:
          CatalogNotFoundError: a catalog was not found to cache.
          ReplicationError: there was an error making the cache directory.
          fetch.MunkiDownloadError: error downloading the catalog.
        """
        os_vers = osutils.getOsVersion()
        try:
            catalog_url = self.get_apple_catalogurl()
        except CatalogNotFoundError as err:
            display.display_error(unicode_or_str(err))
            raise
        if not os.path.exists(self.temp_cache_dir):
            try:
                os.makedirs(self.temp_cache_dir)
            except OSError as oserr:
                raise ReplicationError(oserr)
        if os.path.exists(self.apple_download_catalog_path):
            stored_os_vers = str(fetch.getxattr(
                self.apple_download_catalog_path, XATTR_OS_VERS))
            if stored_os_vers != os_vers:
                try:
                    # remove the cached apple catalog
                    os.unlink(self.apple_download_catalog_path)
                except OSError as oserr:
                    raise ReplicationError(oserr)

        display.display_detail('Caching CatalogURL %s', catalog_url)
        try:
            dummy_file_changed = self.get_su_resource(
                catalog_url, self.apple_download_catalog_path, resume=True)
            xattr.setxattr(self.apple_download_catalog_path,
                           XATTR_OS_VERS, os_vers.encode("UTF-8"))
            self.copy_downloaded_catalog()
        except fetch.Error:
            raise

    def _get_url_path(self, full_url):
        """Returns only the URL path.

        Args:
          full_url: a str URL, complete with schema, domain, path, etc.
        Returns:
          The str path of the URL.
        """
        # pylint: disable=no-self-use
        return urlsplit(full_url)[2]  # (schema, netloc, path, ...)

    def rewrite_url(self, full_url):
        """Rewrites a single URL to point to our local replica.

        Args:
          full_url: a str URL, complete with schema, domain, path, etc.
        Returns:
          A str URL, rewritten if needed to point to the local cache.
        """
        local_base_url = 'file://localhost' + quote(self.cache_dir)
        if full_url.startswith(local_base_url):
            return full_url  # url is already local, so just return it.
        return local_base_url + self._get_url_path(full_url)

    def rewrite_product_urls(self, product, rewrite_pkg_urls=False):
        """Rewrites URLs in the product to point to our local cache.

        Args:
          product: list, of dicts, product info. This dict is changed by
              this function.
          rewrite_pkg_urls: bool, default False, if True package URLs are
              rewritten, otherwise only MetadataURLs are rewritten.
        """
        if 'ServerMetadataURL' in product:
            product['ServerMetadataURL'] = self.rewrite_url(
                product['ServerMetadataURL'])
        for package in product.get('Packages', []):
            if rewrite_pkg_urls and 'URL' in package:
                package['URL'] = self.rewrite_url(package['URL'])
            if 'MetadataURL' in package:
                package['MetadataURL'] = self.rewrite_url(
                    package['MetadataURL'])
        distributions = product['Distributions']
        # coerce distributions.keys() to list so we don't mutate the dictionary
        # while enumerating it in Python 3
        for dist_lang in list(distributions.keys()):
            distributions[dist_lang] = self.rewrite_url(
                distributions[dist_lang])

    def rewrite_catalog_urls(self, catalog, rewrite_pkg_urls=False):
        """Rewrites URLs in a catalog to point to our local replica.

        Args:
          rewrite_pkg_urls: Boolean, if True package URLs are rewritten,
              otherwise only MetadataURLs are rewritten.
        """
        if not 'Products' in catalog:
            return

        for product_key in catalog['Products'].keys():
            product = catalog['Products'][product_key]
            self.rewrite_product_urls(product, rewrite_pkg_urls=rewrite_pkg_urls)

    def retrieve_url_to_cache_dir(self, full_url, copy_only_if_missing=False):
        """Downloads a URL and stores it in the same relative path on our
        filesystem. Returns a path to the replicated file.

        Args:
          full_url: str, full URL to retrieve.
          copy_only_if_missing: boolean, True to copy only if the file is not
              already cached, False to copy regardless of existence in cache.
        Returns:
          String path to the locally cached file.
        """
        relative_url = os.path.normpath(self._get_url_path(full_url).lstrip('/'))
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
            self.get_su_resource(
                full_url, local_file_path, resume=True)
        except fetch.Error as err:
            raise ReplicationError(err)
        return local_file_path

    def get_su_resource(self, url, destinationpath, resume=False):
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
        machine = info.getMachineFacts()
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

    def cache_update_metadata(self, product_ids):
        """Copies ServerMetadata (.smd), Metadata (.pkm), and
        Distribution (.dist) files for the available updates to the local
        machine and writes a new sucatalog that refers to the local copies
        of these files."""
        catalog = FoundationPlist.readPlist(self.extracted_catalog_path)
        if not 'Products' in catalog:
            display.display_warning(
                '"Products" not found in %s', self.extracted_catalog_path)
            return

        for product_key in product_ids:
            if processes.stop_requested():
                return
            if product_key not in catalog['Products']:
                if product_key.startswith("MSU_UPDATE_"):
                    # BigSur+ updates don't have metadata in the sucatalog
                    display.display_info(
                        'Skipping metadata caching for product ID %s'
                        % product_key)
                else:
                    display.display_warning(
                        'Could not cache metadata for product ID %s'
                        % product_key)
                continue
            display.display_status_minor(
                'Caching metadata for product ID %s', product_key)
            product = catalog['Products'][product_key]
            if 'ServerMetadataURL' in product:
                self.retrieve_url_to_cache_dir(
                    product['ServerMetadataURL'], copy_only_if_missing=True)

            for package in product.get('Packages', []):
                if processes.stop_requested():
                    return
                if 'MetadataURL' in package:
                    display.display_status_minor(
                        'Caching package metadata for product ID %s',
                        product_key)
                    self.retrieve_url_to_cache_dir(
                        package['MetadataURL'], copy_only_if_missing=True)
                # if 'URL' in package:
                #    display.display_status_minor(
                #        'Caching package for product ID %s',
                #        product_key)
                #    self.retrieve_url_to_cache_dir(
                #        package['URL'], copy_only_if_missing=True)

            distributions = product['Distributions']
            for dist_lang in distributions.keys():
                if processes.stop_requested():
                    return
                display.display_status_minor(
                    'Caching %s distribution for product ID %s',
                    dist_lang, product_key)
                dist_url = distributions[dist_lang]
                try:
                    self.retrieve_url_to_cache_dir(
                        dist_url, copy_only_if_missing=True)
                except ReplicationError:
                    display.display_warning(
                        'Could not cache %s distribution for product ID %s',
                        dist_lang, product_key)

        if not os.path.exists(self.local_catalog_dir):
            try:
                os.makedirs(self.local_catalog_dir)
            except OSError as oserr:
                raise ReplicationError(oserr)

        # rewrite metadata URLs to point to local caches.
        self.rewrite_catalog_urls(catalog, rewrite_pkg_urls=False)
        FoundationPlist.writePlist(
            catalog, self.local_download_catalog_path)

        # rewrite all URLs, including pkgs, to point to local caches.
        self.rewrite_catalog_urls(catalog, rewrite_pkg_urls=True)
        FoundationPlist.writePlist(
            catalog, self.local_catalog_path)

    def _preferred_localization(self, list_of_localizations):
        '''Picks the best localization from a list of available
        localizations. Returns a single language/localization name.'''
        # pylint: disable=no-self-use
        localization_preferences = (
            prefs.pref('AppleSoftwareUpdateLanguages') or ['English'])
        preferred_langs = (
            NSBundle.preferredLocalizationsFromArray_forPreferences_(
                list(list_of_localizations), localization_preferences))
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

    def distribution_for_product_key(self, product_key, language=None):
        '''Returns the path to a distribution file from /Library/Updates
        or the local cache for the given product_key. If language is
        defined it will try to retrieve that specific language, otherwise
        it will use the available languages and the value of the
        AppleSoftwareUpdateLanguages preference to return the "best"
        language of those available.'''
        os_version_tuple = osutils.getOsVersion(as_tuple=True)
        if os_version_tuple < (10, 11):
            # use our filtered catalog
            sucatalog = self.local_catalog_path
        else:
            # use the cached Apple catalog
            sucatalog = self.extracted_catalog_path
        try:
            catalog = FoundationPlist.readPlist(sucatalog)
        except FoundationPlist.NSPropertyListSerializationException:
            return None
        product = catalog.get('Products', {}).get(product_key, {})
        if product:
            distributions = product.get('Distributions', {})
            if distributions:
                available_languages = list(distributions.keys())
                if language:
                    preferred_language = language
                else:
                    preferred_language = self._preferred_localization(
                        available_languages)
                url = distributions[preferred_language]
                # do we already have it in /Library/Updates?
                filename = os.path.basename(self._get_url_path(url))
                dist_path = os.path.join(
                    '/Library/Updates', product_key, filename)
                if os.path.exists(dist_path):
                    return dist_path
                # look for it in the cache
                if url.startswith('file://localhost'):
                    fileurl = url[len('file://localhost'):]
                    dist_path = unquote(fileurl)
                    if os.path.exists(dist_path):
                        return dist_path
                # we haven't downloaded this yet
                try:
                    return self.retrieve_url_to_cache_dir(
                        url, copy_only_if_missing=True)
                except ReplicationError as err:
                    display.display_error(
                        'Could not retrieve %s: %s', url, err)
        return None

    def clean_up_cache(self):
        """Clean up our cache dir"""
        content_cache = os.path.join(self.cache_dir, 'content')
        if os.path.exists(content_cache):
            dummy_retcode = subprocess.call(['/bin/rm', '-rf', content_cache])


if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
