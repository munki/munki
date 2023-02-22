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
updatecheck.download

Created by Greg Neagle on 2016-12-31.


Functions for downloading resources from the Munki server
"""
from __future__ import absolute_import, print_function

import os

try:
    # Python 2
    from urllib2 import quote
except ImportError:
    # Python 3
    from urllib.parse import quote
try:
    # Python 2
    from urlparse import urlparse
except ImportError:
    # Python 3
    from urllib.parse import urlparse

from .. import display
from .. import fetch
from .. import info
from .. import launchd
from .. import munkihash
from .. import osutils
from .. import prefs
from .. import reports
from .. import FoundationPlist


ICON_HASHES_PLIST_NAME = '_icon_hashes.plist'

def get_url_basename(url):
    """For a URL, absolute or relative, return the basename string.

    e.g. "http://foo/bar/path/foo.dmg" => "foo.dmg"
         "/path/foo.dmg" => "foo.dmg"
    """

    url_parse = urlparse(url)
    return os.path.basename(url_parse.path)


def get_download_cache_path(url):
    """For a URL, return the path that the download should cache to.

    Returns a string."""
    cachedir = os.path.join(prefs.pref('ManagedInstallDir'), 'Cache')
    return os.path.join(cachedir, get_url_basename(url))


def enough_disk_space(item_pl, installlist=None,
                      uninstalling=False, warn=True, precaching=False):
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
                availablediskspace = (availablediskspace -
                                      int(item.get('installed_size', 0)))

    if diskspaceneeded > availablediskspace and not precaching:
        # try to clear space by deleting some precached items
        uncache(diskspaceneeded - availablediskspace)
        availablediskspace = info.available_disk_space()

    if availablediskspace >= diskspaceneeded:
        return True

    # we don't have enough space
    if warn:
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
            int(diskspaceneeded/1024), int(availablediskspace/1024))
    return False


def download_installeritem(item_pl,
                           installinfo, uninstalling=False, precaching=False):
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
        pkgurl = downloadbaseurl + quote(location.encode('UTF-8'))

    pkgname = get_url_basename(location)
    display.display_debug2('Download base URL is: %s', downloadbaseurl)
    display.display_debug2('Package name is: %s', pkgname)
    display.display_debug2('Download URL is: %s', pkgurl)

    destinationpath = get_download_cache_path(location)
    display.display_debug2('Downloading to: %s', destinationpath)

    display.display_detail('Downloading %s from %s', pkgname, location)

    if not os.path.exists(destinationpath):
        # check to see if there is enough free space to download and install
        if not enough_disk_space(item_pl,
                                 installinfo['managed_installs'],
                                 uninstalling=uninstalling,
                                 precaching=precaching):
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
                                verify=True,
                                pkginfo=item_pl)


def clean_up_icons_dir(icons_to_keep):
    '''Remove any cached/downloaded icons that aren't in the list of ones to
    keep'''
    # remove no-longer needed icons from the local directory
    icons_to_keep.append(ICON_HASHES_PLIST_NAME)
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
        if osutils.listdir(dirpath):
            # did we empty out this directory (or is it already empty)?
            # if so, remove it
            try:
                os.rmdir(dirpath)
            except (IOError, OSError):
                pass


def get_icon_hashes(icon_base_url):
    '''Attempts to download the list of compiled icon hashes'''
    icon_hashes = None
    icon_hashes_url = icon_base_url + ICON_HASHES_PLIST_NAME
    icon_dir = os.path.join(prefs.pref('ManagedInstallDir'), 'icons')
    icon_hashes_plist = os.path.join(icon_dir, ICON_HASHES_PLIST_NAME)
    try:
        fetch.munki_resource(icon_hashes_url, icon_hashes_plist,
                             message="Getting list of available icons")
        icon_hashes = FoundationPlist.readPlist(icon_hashes_plist)
    except (fetch.Error, FoundationPlist.FoundationPlistException):
        pass
    return icon_hashes


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
    icon_hashes = get_icon_hashes(icon_base_url)

    for item in item_list:
        icon_name = item.get('icon_name') or item['name']
        if not os.path.splitext(icon_name)[1] in icon_known_exts:
            icon_name += '.png'
        server_icon_hash = item.get('icon_hash')
        if not server_icon_hash and icon_hashes:
            server_icon_hash = icon_hashes.get(icon_name)
        icons_to_keep.append(icon_name)
        icon_path = os.path.join(icon_dir, icon_name)
        if os.path.isfile(icon_path):
            # have we already downloaded it? If so get the hash
            local_hash = fetch.getxattr(icon_path, fetch.XATTR_SHA)
            if not local_hash:
                local_hash = munkihash.getsha256hash(icon_path)
                fetch.writeCachedChecksum(icon_path, local_hash)
            else:
                # make sure it's a string and not a bytearray
                local_hash = local_hash.decode("UTF-8")
        else:
            local_hash = 'nonexistent'
        icon_subdir = os.path.dirname(icon_path)
        if not os.path.isdir(icon_subdir):
            try:
                os.makedirs(icon_subdir, 0o755)
            except OSError as err:
                display.display_error('Could not create %s' % icon_subdir)
                return
        if server_icon_hash != local_hash:
            # hashes don't match, so download the icon
            if icon_hashes and icon_name not in icon_hashes:
                # if we have a list of icon hashes, and the icon name is not
                # in that list, then there's no point in attempting to
                # download this icon
                continue
            item_name = item.get('display_name') or item['name']
            icon_url = icon_base_url + quote(icon_name.encode('UTF-8'))
            try:
                fetch.munki_resource(
                    icon_url,
                    icon_path,
                    message='Getting icon %s for %s...' % (icon_name, item_name)
                )
                fetch.writeCachedChecksum(icon_path)
            except fetch.Error as err:
                display.display_debug1(
                    'Error when retrieving icon %s from the server: %s',
                    icon_name, err)

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
            os.makedirs(resource_dir, 0o755)
        except OSError as err:
            display.display_error(
                'Could not create %s' % resource_dir)
            return
    resource_archive_path = os.path.join(resource_dir, 'custom.zip')
    message = 'Getting client resources...'
    downloaded_resource_path = None
    for filename in filenames:
        resource_url = resource_base_url + quote(filename.encode('UTF-8'))
        try:
            fetch.munki_resource(
                resource_url, resource_archive_path, message=message)
            downloaded_resource_path = resource_archive_path
            break
        except fetch.Error as err:
            display.display_debug1(
                'Could not retrieve client resources with name %s: %s',
                filename, err)
    if downloaded_resource_path is None:
        # make sure we don't have an old custom.zip hanging around
        if os.path.exists(resource_archive_path):
            try:
                os.unlink(resource_archive_path)
            except (OSError, IOError) as err:
                display.display_error(
                    'Could not remove stale %s: %s', resource_archive_path, err)


def download_catalog(catalogname):
    '''Attempt to download a catalog from the Munki server, Returns the path to
    the downloaded catalog file'''
    catalogbaseurl = (prefs.pref('CatalogURL') or
                      prefs.pref('SoftwareRepoURL') + '/catalogs/')
    if not catalogbaseurl.endswith('?') and not catalogbaseurl.endswith('/'):
        catalogbaseurl = catalogbaseurl + '/'
    display.display_debug2('Catalog base URL is: %s', catalogbaseurl)
    catalog_dir = os.path.join(prefs.pref('ManagedInstallDir'), 'catalogs')
    catalogurl = catalogbaseurl + quote(catalogname.encode('UTF-8'))
    catalogpath = os.path.join(catalog_dir, catalogname)
    display.display_detail('Getting catalog %s...', catalogname)
    message = 'Retrieving catalog "%s"...' % catalogname
    try:
        fetch.munki_resource(catalogurl, catalogpath, message=message)
        return catalogpath
    except fetch.Error as err:
        display.display_error(
            'Could not retrieve catalog %s from server: %s',
            catalogname, err)
        return None


### precaching support ###

def _installinfo():
    '''Get the install info from InstallInfo.plist'''
    managed_install_dir = prefs.pref('ManagedInstallDir')
    install_info_plist = os.path.join(managed_install_dir, 'InstallInfo.plist')
    try:
        return FoundationPlist.readPlist(install_info_plist)
    except FoundationPlist.FoundationPlistException:
        return {}


def _items_to_precache(install_info):
    '''Returns a list of items from InstallInfo.plist's optional_installs
    that have precache=True and (installed=False or needs_update=True)'''
    optional_install_items = install_info.get('optional_installs', [])
    precache_items = [item for item in optional_install_items
                      if item.get('precache')
                      and (not item.get('installed')
                           or item.get('needs_update'))]
    return precache_items


def cache():
    '''Download any applicable precache items into our Cache folder'''
    display.display_info("###   Beginning precaching session   ###")
    install_info = _installinfo()
    for item in _items_to_precache(install_info):
        try:
            download_installeritem(item, install_info, precaching=True)
        except fetch.Error as err:
            display.display_warning(
                u'Failed to precache the installer for %s because %s',
                item['name'], err)
    display.display_info("###    Ending precaching session     ###")


def uncache(space_needed_in_kb):
    '''Discard precached items to free up space for managed installs'''
    install_info = _installinfo()
    # make a list of names of precachable items
    precachable_items = [
        [os.path.basename(item['installer_item_location'])]
        for item in _items_to_precache(install_info)
        if item.get('installer_item_location')]
    if not precachable_items:
        return

    cachedir = os.path.join(prefs.pref('ManagedInstallDir'), 'Cache')
    # now filter our list to items actually downloaded
    items_in_cache = osutils.listdir(cachedir)
    precached_items = [item for item in precachable_items
                       if item in items_in_cache]
    if not precached_items:
        return

    precached_size = 0
    for item in precached_items:
        # item is [itemname]
        item_path = os.path.join(cachedir, item[0])
        try:
            itemsize = int(os.path.getsize(item_path)/1024)
        except OSError as err:
            display.display_warning("Could not get size of %s: %s"
                                    % (item_path, err))
            itemsize = 0
        precached_size += itemsize
        item.append(itemsize)
        # item is now [itemname, itemsize]

    if precached_size < space_needed_in_kb:
        # we can't clear enough space, so don't bother removing anything.
        # otherwise we'll clear some space, but still can't download the large
        # managed install, but then we'll have enough space to redownload the
        # precachable items and so we will (and possibly do this over and
        # over -- delete some, redownload, delete some, redownload...)
        return

    # sort reversed by size; smallest at end
    precached_items.sort(key=lambda x: x[1], reverse=True)
    deleted_kb = 0
    while precached_items:
        if deleted_kb >= space_needed_in_kb:
            break
        # remove and return last item in precached_items
        # we delete the smallest item first, proceeeding until we've freed up
        # enough space or deleted all the items
        item = precached_items.pop()
        item_path = os.path.join(cachedir, item[0])
        item_size = item[1]
        try:
            os.remove(item_path)
            deleted_kb += item_size
        except OSError as err:
            display.display_error(
                "Could not remove precached item %s: %s" % (item_path, err))


PRECACHING_AGENT_LABEL = "com.googlecode.munki.precache_agent"

def run_precaching_agent():
    '''Kick off a run of our precaching agent, which allows the precaching to
    run in the background after a normal Munki run'''
    if not _items_to_precache(_installinfo()):
        # nothing to precache
        display.display_debug1('Nothing found to precache.')
        return
    parent_dir = (
        os.path.dirname(
            os.path.dirname(
                os.path.dirname(
                    os.path.abspath(__file__)))))
    precache_agent_path = os.path.join(parent_dir, 'precache_agent')
    if not os.path.exists(precache_agent_path):
        # try absolute path in Munki's normal install dir
        precache_agent_path = '/usr/local/munki/precache_agent'
    if os.path.exists(precache_agent_path):
        display.display_info("Starting precaching agent")
        display.display_debug1(
            'Launching precache_agent from %s', precache_agent_path)
        try:
            job = launchd.Job([precache_agent_path],
                              job_label=PRECACHING_AGENT_LABEL,
                              cleanup_at_exit=False)
            job.start()
        except launchd.LaunchdJobException as err:
            display.display_error(
                'Error with launchd job (%s): %s', precache_agent_path, err)
    else:
        display.display_error("Could not find precache_agent")


def stop_precaching_agent():
    '''Stop the precaching_agent if it's running'''
    agent_info = launchd.job_info(PRECACHING_AGENT_LABEL)
    if agent_info.get('state') != 'unknown':
        # it's either running or stopped. Removing it will stop it.
        if agent_info.get('state') == 'running':
            display.display_info("Stopping precaching agent")
        try:
            launchd.remove_job(PRECACHING_AGENT_LABEL)
        except launchd.LaunchdJobException as err:
            display.display_error('Error stopping precaching agent: %s', err)


if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
