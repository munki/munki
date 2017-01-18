# encoding: utf-8
#
# Copyright 2009-2017 Greg Neagle.
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
updatecheck.download

Created by Greg Neagle on 2016-12-31.


Functions for downloading resources from the Munki server
"""

import os
import urllib2
import urlparse

from .. import display
from .. import fetch
from .. import info
from .. import munkihash
from .. import osutils
from .. import prefs
from .. import reports


def enough_disk_space(item_pl, installlist=None, uninstalling=False, warn=True):
    """Determine if there is enough disk space to download the installer
    item."""
    # fudgefactor is set to 100MB
    fudgefactor = 102400
    alreadydownloadedsize = 0
    if 'installer_item_location' in item_pl:
        download = get_download_cache_path(item_pl['installer_item_location'])
        if os.path.exists(download):
            alreadydownloadedsize = os.path.getsize(download)
    installeritemsize = int(item_pl.get('installer_item_size', 0))
    installedsize = int(item_pl.get('installed_size', installeritemsize))
    if uninstalling:
        installedsize = 0
        if 'uninstaller_item_size' in item_pl:
            installeritemsize = int(item_pl['uninstaller_item_size'])
    diskspaceneeded = (installeritemsize - alreadydownloadedsize +
                       installedsize + fudgefactor)

    # info.available_disk_space() returns KB
    availablediskspace = info.available_disk_space()
    if installlist:
        for item in installlist:
            # subtract space needed for other items that are to be installed
            if item.get('installer_item'):
                availablediskspace = availablediskspace - \
                                     int(item.get('installed_size', 0))

    if availablediskspace > diskspaceneeded:
        return True
    elif warn:
        if uninstalling:
            display.display_warning('There is insufficient disk space to '
                                    'download the uninstaller for %s.',
                                    item_pl.get('name'))
        else:
            display.display_warning('There is insufficient disk space to '
                                    'download and install %s.',
                                    item_pl.get('name'))
        display.display_warning(
            '    %sMB needed; %sMB available',
            diskspaceneeded/1024, availablediskspace/1024)
    return False


def get_url_basename(url):
    """For a URL, absolute or relative, return the basename string.

    e.g. "http://foo/bar/path/foo.dmg" => "foo.dmg"
         "/path/foo.dmg" => "foo.dmg"
    """

    url_parse = urlparse.urlparse(url)
    return os.path.basename(url_parse.path)


def get_download_cache_path(url):
    """For a URL, return the path that the download should cache to.

    Returns a string."""
    cachedir = os.path.join(prefs.pref('ManagedInstallDir'), 'Cache')
    return os.path.join(cachedir, get_url_basename(url))


def download_installeritem(item_pl, installinfo, uninstalling=False):
    """Downloads an (un)installer item.
    Returns True if the item was downloaded, False if it was already cached.
    Raises an error if there are issues..."""

    download_item_key = 'installer_item_location'
    item_hash_key = 'installer_item_hash'
    if uninstalling and 'uninstaller_item_location' in item_pl:
        download_item_key = 'uninstaller_item_location'
        item_hash_key = 'uninstaller_item_hash'

    location = item_pl.get(download_item_key)
    if not location:
        raise fetch.DownloadError(
            "No %s in item info." % download_item_key)

    # allow pkginfo preferences to override system munki preferences
    downloadbaseurl = item_pl.get('PackageCompleteURL') or \
                      item_pl.get('PackageURL') or \
                      prefs.pref('PackageURL') or \
                      prefs.pref('SoftwareRepoURL') + '/pkgs/'

    # build a URL, quoting the the location to encode reserved characters
    if item_pl.get('PackageCompleteURL'):
        pkgurl = downloadbaseurl
    else:
        if not downloadbaseurl.endswith('/'):
            downloadbaseurl = downloadbaseurl + '/'
        pkgurl = downloadbaseurl + urllib2.quote(location.encode('UTF-8'))

    pkgname = get_url_basename(location)
    display.display_debug2('Download base URL is: %s', downloadbaseurl)
    display.display_debug2('Package name is: %s', pkgname)
    display.display_debug2('Download URL is: %s', pkgurl)

    destinationpath = get_download_cache_path(location)
    display.display_debug2('Downloading to: %s', destinationpath)

    display.display_detail('Downloading %s from %s', pkgname, location)

    if not os.path.exists(destinationpath):
        # check to see if there is enough free space to download and install
        if not enough_disk_space(item_pl, installinfo['managed_installs'],
                                 uninstalling=uninstalling):
            raise fetch.DownloadError(
                'Insufficient disk space to download and install %s' % pkgname)
        else:
            display.display_detail(
                'Downloading %s from %s', pkgname, location)

    dl_message = 'Downloading %s...' % pkgname
    expected_hash = item_pl.get(item_hash_key, None)
    return fetch.munki_resource(pkgurl, destinationpath,
                                resume=True,
                                message=dl_message,
                                expected_hash=expected_hash,
                                verify=True)


def clean_up_icons_dir(icons_to_keep):
    '''Remove any cached/downloaded icons that aren't in the list of ones to
    keep'''
    # remove no-longer needed icons from the local directory
    icon_dir = os.path.join(prefs.pref('ManagedInstallDir'), 'icons')
    for (dirpath, dummy_dirnames, filenames) in os.walk(
            icon_dir, topdown=False):
        for filename in filenames:
            icon_path = os.path.join(dirpath, filename)
            rel_path = icon_path[len(icon_dir):].lstrip('/')
            if rel_path not in icons_to_keep:
                try:
                    os.unlink(icon_path)
                except (IOError, OSError):
                    pass
        if len(osutils.listdir(dirpath)) == 0:
            # did we empty out this directory (or is it already empty)?
            # if so, remove it
            try:
                os.rmdir(dirpath)
            except (IOError, OSError):
                pass


def download_icons(item_list):
    '''Attempts to download icons (actually image files) for items in
       item_list'''
    icons_to_keep = []
    icon_known_exts = ['.bmp', '.gif', '.icns', '.jpg', '.jpeg', '.png', '.psd',
                       '.tga', '.tif', '.tiff', '.yuv']
    icon_base_url = (prefs.pref('IconURL') or
                     prefs.pref('SoftwareRepoURL') + '/icons/')
    # make sure the icon_base_url ends with exactly one slash
    icon_base_url = icon_base_url.rstrip('/') + '/'
    display.display_debug2('Icon base URL is: %s', icon_base_url)
    icon_dir = os.path.join(prefs.pref('ManagedInstallDir'), 'icons')
    for item in item_list:
        icon_name = item.get('icon_name') or item['name']
        pkginfo_icon_hash = item.get('icon_hash')
        if not os.path.splitext(icon_name)[1] in icon_known_exts:
            icon_name += '.png'
        icons_to_keep.append(icon_name)
        icon_path = os.path.join(icon_dir, icon_name)
        if os.path.isfile(icon_path):
            # have we already downloaded it? If so get the hash
            local_hash = fetch.getxattr(icon_path, fetch.XATTR_SHA)
            if not local_hash:
                local_hash = munkihash.getsha256hash(icon_path)
                fetch.writeCachedChecksum(icon_path, local_hash)
        else:
            local_hash = 'nonexistent'
        icon_subdir = os.path.dirname(icon_path)
        if not os.path.isdir(icon_subdir):
            try:
                os.makedirs(icon_subdir, 0755)
            except OSError, err:
                display.display_error('Could not create %s' % icon_subdir)
                return
        if pkginfo_icon_hash != local_hash:
            # hashes don't match, so download the icon
            item_name = item.get('display_name') or item['name']
            message = 'Getting icon %s for %s...' % (icon_name, item_name)
            icon_url = icon_base_url + urllib2.quote(icon_name.encode('UTF-8'))
            try:
                fetch.munki_resource(
                    icon_url, icon_path, message=message)
            except fetch.Error, err:
                display.display_debug1(
                    'Could not retrieve icon %s from the server: %s',
                    icon_name, err)
            else:
                # if we downloaded it, store the hash for later use
                if os.path.isfile(icon_path):
                    fetch.writeCachedChecksum(icon_path)

    # delete any previously downloaded icons we no longer need
    clean_up_icons_dir(icons_to_keep)


def download_client_resources():
    """Download client customization resources (if any)."""
    # Munki's preferences can specify an explicit name
    # under ClientResourcesFilename
    # if that doesn't exist, use the primary manifest name as the
    # filename. If that fails, try site_default.zip
    filenames = []
    resources_name = prefs.pref('ClientResourcesFilename')
    if resources_name:
        if os.path.splitext(resources_name)[1] != '.zip':
            resources_name += '.zip'
        filenames.append(resources_name)
    else:
        filenames.append(reports.report['ManifestName'] + '.zip')
    filenames.append('site_default.zip')

    resource_base_url = (
        prefs.pref('ClientResourceURL') or
        prefs.pref('SoftwareRepoURL') + '/client_resources/')
    resource_base_url = resource_base_url.rstrip('/') + '/'
    resource_dir = os.path.join(
        prefs.pref('ManagedInstallDir'), 'client_resources')
    display.display_debug2(
        'Client resources base URL is: %s', resource_base_url)
    # make sure local resource directory exists
    if not os.path.isdir(resource_dir):
        try:
            os.makedirs(resource_dir, 0755)
        except OSError, err:
            display.display_error(
                'Could not create %s' % resource_dir)
            return
    resource_archive_path = os.path.join(resource_dir, 'custom.zip')
    message = 'Getting client resources...'
    downloaded_resource_path = None
    for filename in filenames:
        resource_url = resource_base_url + urllib2.quote(
            filename.encode('UTF-8'))
        try:
            fetch.munki_resource(
                resource_url, resource_archive_path, message=message)
            downloaded_resource_path = resource_archive_path
            break
        except fetch.Error, err:
            display.display_debug1(
                'Could not retrieve client resources with name %s: %s',
                filename, err)
    if downloaded_resource_path is None:
        # make sure we don't have an old custom.zip hanging around
        if os.path.exists(resource_archive_path):
            try:
                os.unlink(resource_archive_path)
            except (OSError, IOError), err:
                display.display_error(
                    'Could not remove stale %s: %s', resource_archive_path, err)


def download_catalog(catalogname):
    '''Attempt to download a catalog from the Munki server, Returns the path to
    the downlaoded catalog file'''
    catalogbaseurl = (prefs.pref('CatalogURL') or
                      prefs.pref('SoftwareRepoURL') + '/catalogs/')
    if not catalogbaseurl.endswith('?') and not catalogbaseurl.endswith('/'):
        catalogbaseurl = catalogbaseurl + '/'
    display.display_debug2('Catalog base URL is: %s', catalogbaseurl)
    catalog_dir = os.path.join(prefs.pref('ManagedInstallDir'), 'catalogs')
    catalogurl = catalogbaseurl + urllib2.quote(catalogname.encode('UTF-8'))
    catalogpath = os.path.join(catalog_dir, catalogname)
    display.display_detail('Getting catalog %s...', catalogname)
    message = 'Retrieving catalog "%s"...' % catalogname
    try:
        fetch.munki_resource(catalogurl, catalogpath, message=message)
        return catalogpath
    except fetch.Error, err:
        display.display_error(
            'Could not retrieve catalog %s from server: %s',
            catalogname, err)
        return None


if __name__ == '__main__':
    print 'This is a library of support tools for the Munki Suite.'
