# encoding: utf-8
#
# Copyright 2011-2023 Greg Neagle.
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
fetch.py

Created by Greg Neagle on 2011-09-29.

"""
from __future__ import absolute_import, print_function

# standard libs
import calendar
import errno
import imp
import os
import shutil
import time
import xattr

try:
    # Python 2
    from urllib2 import unquote
except ImportError:
    # Python 3
    from urllib.parse import unquote
try:
    # Python 2
    from urlparse import urlparse, urlsplit
except ImportError:
    # Python 3
    from urllib.parse import urlparse, urlsplit

# Cocoa libs via PyObjC
# PyLint cannot properly find names inside Cocoa libraries, so issues bogus
# No name 'Foo' in module 'Bar' warnings. Disable them.
# pylint: disable=E0611
from Foundation import NSHTTPURLResponse
# pylint: enable=E0611

#our libs
from . import constants
from . import display
from . import info
from . import keychain
from . import munkihash
from . import munkilog
from . import osutils
from . import prefs


from .gurl import Gurl

# Disable PyLint complaining about 'invalid' camelCase names
# pylint: disable=C0103

# XATTR name storing the ETAG of the file when downloaded via http(s).
XATTR_ETAG = 'com.googlecode.munki.etag'
# XATTR name storing the sha256 of the file after original download by munki.
XATTR_SHA = 'com.googlecode.munki.sha256'

# default value for User-Agent header
munki_version = info.get_version()
darwin_version = os.uname()[2]
#python_version = "%d.%d.%d" % sys.version_info[:3]
#cfnetwork_version = FoundationPlist.readPlist(
#  "/System/Library/Frameworks/CFNetwork.framework/Resources/Info.plist")[
#       'CFBundleShortVersionString']
DEFAULT_USER_AGENT = "managedsoftwareupdate/%s Darwin/%s" % (
    munki_version, darwin_version)


def import_middleware():
    '''Check munki folder for a python file that starts with 'middleware'.
    If the file exists and has a callable 'process_request_options' attribute,
    the module is loaded under the 'middleware' name'''
    required_function_name = 'process_request_options'
    munki_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    for filename in os.listdir(munki_dir):
        if (filename.startswith('middleware')
                and os.path.splitext(filename)[1] == '.py'):
            name = os.path.splitext(filename)[0]
            filepath = os.path.join(munki_dir, filename)
            try:
                _tmp = imp.load_source(name, filepath)
                if hasattr(_tmp, required_function_name):
                    if callable(getattr(_tmp, required_function_name)):
                        display.display_debug1(
                            'Loading middleware module %s' % filename)
                        globals()['middleware'] = _tmp
                        return
                    else:
                        display.display_warning(
                            '%s attribute in %s is not callable.'
                            % (required_function_name, filepath))
                        display.display_warning('Ignoring %s' % filepath)
                else:
                    display.display_warning(
                        '%s does not have a %s function'
                        % (filepath, required_function_name))
                    display.display_warning('Ignoring %s' % filepath)
            except BaseException:
                display.display_warning(
                    'Ignoring %s because of error importing module.' % filepath)
    return


middleware = None
import_middleware()


class Error(Exception):
    """Base exception for fetch errors"""
    pass


class GurlError(Error):
    """General exception for gurl errors"""
    pass


class ConnectionError(GurlError):
    """General exception for gurl connection errors"""
    pass


class HTTPError(GurlError):
    """General exception for http/https errors"""
    pass


class DownloadError(Error):
    """Base exception for download errors"""
    pass


class GurlDownloadError(DownloadError):
    """Gurl failed to download the item"""
    pass


class FileCopyError(DownloadError):
    """Download failed because of file copy errors."""
    pass


class PackageVerificationError(DownloadError):
    """Package failed verification"""
    pass


def getxattr(pathname, attr):
    """Get a named xattr from a file. Return None if not present"""
    if attr in xattr.listxattr(pathname):
        return xattr.getxattr(pathname, attr)
    return None


def writeCachedChecksum(file_path, fhash=None):
    """Write the sha256 checksum of a file to an xattr so we do not need to
       calculate it again. Optionally pass the recently calculated hash value.
    """
    if not fhash:
        fhash = munkihash.getsha256hash(file_path)
    if len(fhash) == 64:
        xattr.setxattr(file_path, XATTR_SHA, fhash.encode("UTF-8"))
        return fhash
    return None


def header_dict_from_list(array):
    """Given a list of strings in http header format, return a dict.
    A User-Agent header is added if none is present in the list.
    If array is None, returns a dict with only the User-Agent header."""
    header_dict = {}
    header_dict["User-Agent"] = DEFAULT_USER_AGENT

    if array is None:
        return header_dict
    for item in array:
        (key, sep, value) = item.partition(':')
        if sep and value:
            header_dict[key.strip()] = value.strip()
    return header_dict


def get_url(url, destinationpath,
            custom_headers=None, message=None, onlyifnewer=False,
            resume=False, follow_redirects=False, pkginfo=None):
    """Gets an HTTP or HTTPS URL and stores it in
    destination path. Returns a dictionary of headers, which includes
    http_result_code and http_result_description.
    Will raise ConnectionError if Gurl has a connection error.
    Will raise HTTPError if HTTP Result code is not 2xx or 304.
    Will raise GurlError if Gurl has some other error.
    If destinationpath already exists, you can set 'onlyifnewer' to true to
    indicate you only want to download the file only if it's newer on the
    server.
    If you set resume to True, Gurl will attempt to resume an
    interrupted download."""

    tempdownloadpath = destinationpath + '.download'
    if os.path.exists(tempdownloadpath) and not resume:
        os.remove(tempdownloadpath)

    cache_data = None
    if onlyifnewer and os.path.exists(destinationpath):
        # create a temporary Gurl object so we can extract the
        # stored caching data so we can download only if the
        # file has changed on the server
        gurl_obj = Gurl.alloc().initWithOptions_({'file': destinationpath})
        cache_data = gurl_obj.getStoredHeaders()
        del gurl_obj

    # only works with NSURLSession (10.9 and newer)
    ignore_system_proxy = prefs.pref('IgnoreSystemProxies')

    options = {'url': url,
               'file': tempdownloadpath,
               'follow_redirects': follow_redirects,
               'ignore_system_proxy': ignore_system_proxy,
               'can_resume': resume,
               'additional_headers': header_dict_from_list(custom_headers),
               'download_only_if_changed': onlyifnewer,
               'cache_data': cache_data,
               'logging_function': display.display_debug2,
               'pkginfo': pkginfo}
    display.display_debug2('Options: %s' % options)

    # Allow middleware to modify options
    if middleware:
        display.display_debug2('Processing options through middleware')
        # middleware module must have process_request_options function
        # and must return usable options
        options = middleware.process_request_options(options)
        display.display_debug2('Options: %s' % options)

    connection = Gurl.alloc().initWithOptions_(options)
    stored_percent_complete = -1
    stored_bytes_received = 0
    connection.start()
    try:
        while True:
            # if we did `while not connection.isDone()` we'd miss printing
            # messages and displaying percentages if we exit the loop first
            connection_done = connection.isDone()
            if message and connection.status and connection.status != 304:
                # log always, display if verbose is 1 or more
                # also display in MunkiStatus detail field
                display.display_status_minor(message)
                # now clear message so we don't display it again
                message = None
            if (str(connection.status).startswith('2')
                    and connection.percentComplete != -1):
                if connection.percentComplete != stored_percent_complete:
                    # display percent done if it has changed
                    stored_percent_complete = connection.percentComplete
                    display.display_percent_done(
                        stored_percent_complete, 100)
            elif connection.bytesReceived != stored_bytes_received:
                # if we don't have percent done info, log bytes received
                stored_bytes_received = connection.bytesReceived
                display.display_detail(
                    'Bytes received: %s', stored_bytes_received)
            if connection_done:
                break

    except (KeyboardInterrupt, SystemExit):
        # safely kill the connection then re-raise
        connection.cancel()
        raise
    except Exception as err:  # too general, I know
        # Let us out! ... Safely! Unexpectedly quit dialogs are annoying...
        connection.cancel()
        # Re-raise the error as a GurlError
        raise GurlError(-1, str(err))

    if connection.error is not None:
        # gurl returned an error
        display.display_detail(
            'Download error %s: %s', connection.error.code(),
            connection.error.localizedDescription())
        if connection.SSLerror:
            display.display_detail(
                'SSL error detail: %s', str(connection.SSLerror))
            keychain.debug_output()
        display.display_detail('Headers: %s', connection.headers)
        if os.path.exists(tempdownloadpath) and not resume:
            os.remove(tempdownloadpath)
        raise ConnectionError(connection.error.code(),
                              connection.error.localizedDescription())

    if connection.response is not None:
        display.display_debug1('Status: %s', connection.status)
        display.display_debug1('Headers: %s', connection.headers)
    if connection.redirection != []:
        display.display_debug1('Redirection: %s', connection.redirection)

    temp_download_exists = os.path.isfile(tempdownloadpath)
    connection.headers['http_result_code'] = str(connection.status)
    description = NSHTTPURLResponse.localizedStringForStatusCode_(
        connection.status)
    connection.headers['http_result_description'] = description

    if str(connection.status).startswith('2') and temp_download_exists:
        try:
            os.rename(tempdownloadpath, destinationpath)
        except OSError as err:
            # Re-raise the error as a GurlError
            raise GurlError(-1, str(err))
        return connection.headers
    elif connection.status == 304:
        # unchanged on server
        display.display_debug1('Item is unchanged on the server.')
        return connection.headers
    else:
        # there was an HTTP error of some sort; remove our temp download.
        if os.path.exists(tempdownloadpath):
            try:
                os.unlink(tempdownloadpath)
            except OSError:
                pass
        raise HTTPError(connection.status,
                        connection.headers.get('http_result_description', ''))


def getResourceIfChangedAtomically(url,
                                   destinationpath,
                                   custom_headers=None,
                                   expected_hash=None,
                                   message=None,
                                   resume=False,
                                   verify=False,
                                   follow_redirects=False,
                                   pkginfo=None):
    """Gets file from a URL.
       Checks first if there is already a file with the necessary checksum.
       Then checks if the file has changed on the server, resuming or
       re-downloading as necessary.

       If the file has changed verify the pkg hash if so configured.

       Supported schemes are http, https, file.

       Returns True if a new download was required; False if the
       item is already in the local cache.

       Raises a FetchError derived exception if there is an error."""

    changed = False

    # If we already have a downloaded file & its (cached) hash matches what
    # we need, do nothing, return unchanged.
    if resume and expected_hash and os.path.isfile(destinationpath):
        xattr_hash = getxattr(destinationpath, XATTR_SHA)
        if not xattr_hash:
            xattr_hash = writeCachedChecksum(destinationpath)
        else:
            xattr_hash = xattr_hash.decode('UTF-8')
        if xattr_hash == expected_hash:
            #File is already current, no change.
            munkilog.log("        Cached item is current.")
            return False
        elif prefs.pref(
                'PackageVerificationMode').lower() in ['hash_strict', 'hash']:
            try:
                os.unlink(destinationpath)
            except OSError:
                pass
        munkilog.log('Cached item does not match hash in catalog, '
                     'will check if changed and redownload: %s'
                     % destinationpath)
        # continue with normal if-modified-since/etag update methods.

    if follow_redirects is not True:
        # If we haven't explicitly said to follow redirect,
        # the preference decides
        follow_redirects = prefs.pref('FollowHTTPRedirects')

    url_parse = urlparse(url)
    if url_parse.scheme in ['http', 'https']:
        changed = getHTTPfileIfChangedAtomically(
            url, destinationpath,
            custom_headers=custom_headers,
            message=message, resume=resume, follow_redirects=follow_redirects,
            pkginfo=pkginfo)
    elif url_parse.scheme == 'file':
        changed = getFileIfChangedAtomically(url_parse.path, destinationpath)
    else:
        raise Error(
            'Unsupported scheme for %s: %s' % (url, url_parse.scheme))

    if changed and verify:
        (verify_ok, fhash) = verifySoftwarePackageIntegrity(destinationpath,
                                                            expected_hash,
                                                            always_hash=True)
        if not verify_ok:
            try:
                os.unlink(destinationpath)
            except OSError:
                pass
            raise PackageVerificationError()
        if fhash:
            writeCachedChecksum(destinationpath, fhash=fhash)

    return changed


def munki_resource(
        url, destinationpath, message=None, resume=False, expected_hash=None,
        verify=False, pkginfo=None):

    '''The high-level function for getting resources from the Munki repo.
    Gets a given URL from the Munki server.
    Adds any additional headers to the request if present'''

    # Add any additional headers specified in ManagedInstalls.plist.
    # AdditionalHttpHeaders must be an array of strings with valid HTTP
    # header format. For example:
    # <key>AdditionalHttpHeaders</key>
    # <array>
    #   <string>Key-With-Optional-Dashes: Foo Value</string>
    #   <string>another-custom-header: bar value</string>
    # </array>
    custom_headers = prefs.pref(constants.ADDITIONAL_HTTP_HEADERS_KEY)

    return getResourceIfChangedAtomically(url,
                                          destinationpath,
                                          custom_headers=custom_headers,
                                          expected_hash=expected_hash,
                                          message=message,
                                          resume=resume,
                                          verify=verify,
                                          pkginfo=pkginfo)


def getFileIfChangedAtomically(path, destinationpath):
    """Gets file from path, checking first to see if it has changed on the
       source.

       Returns True if a new copy was required; False if the
       item is already in the local cache.

       Raises FileCopyError if there is an error."""
    path = unquote(path)
    try:
        st_src = os.stat(path)
    except OSError:
        raise FileCopyError('Source does not exist: %s' % path)

    try:
        st_dst = os.stat(destinationpath)
    except OSError:
        st_dst = None

    # if the destination exists, with same mtime and size, already cached
    if st_dst is not None and (
            st_src.st_mtime == st_dst.st_mtime and
            st_src.st_size == st_dst.st_size):
        return False

    # write to a temporary destination
    tmp_destinationpath = '%s.download' % destinationpath

    # remove the temporary destination if it exists
    try:
        if st_dst:
            os.unlink(tmp_destinationpath)
    except OSError as err:
        if err.args[0] == errno.ENOENT:
            pass  # OK
        else:
            raise FileCopyError('Removing %s: %s' % (
                tmp_destinationpath, str(err)))

    # copy from source to temporary destination
    try:
        shutil.copy2(path, tmp_destinationpath)
    except IOError as err:
        raise FileCopyError('Copy IOError: %s' % str(err))

    # rename temp destination to final destination
    try:
        os.rename(tmp_destinationpath, destinationpath)
    except OSError as err:
        raise FileCopyError('Renaming %s: %s' % (destinationpath, str(err)))

    return True


def getHTTPfileIfChangedAtomically(url, destinationpath,
                                   custom_headers=None,
                                   message=None, resume=False,
                                   follow_redirects=False,
                                   pkginfo=None):
    """Gets file from HTTP URL, checking first to see if it has changed on the
       server.

       Returns True if a new download was required; False if the
       item is already in the local cache.

       Raises GurlDownloadError if there is an error."""

    etag = None
    getonlyifnewer = False
    if os.path.exists(destinationpath):
        getonlyifnewer = True
        # see if we have an etag attribute
        etag = getxattr(destinationpath, XATTR_ETAG)
        if etag:
            getonlyifnewer = False

    try:
        header = get_url(url,
                         destinationpath,
                         custom_headers=custom_headers,
                         message=message,
                         onlyifnewer=getonlyifnewer,
                         resume=resume,
                         follow_redirects=follow_redirects,
                         pkginfo=pkginfo)

    except ConnectionError:
        # connection errors should be handled differently; don't re-raise
        # them as GurlDownloadError
        raise

    except HTTPError as err:
        err = 'HTTP result %s: %s' % (err.args[0], err.args[1])
        raise GurlDownloadError(err)

    except GurlError as err:
        err = 'Error %s: %s' % (err.args[0], err.args[1])
        raise GurlDownloadError(err)

    err = None
    if header['http_result_code'] == '304':
        # not modified, return existing file
        display.display_debug1('%s already exists and is up-to-date.',
                               destinationpath)
        # file is in cache and is unchanged, so we return False
        return False
    else:
        if header.get('last-modified'):
            # set the modtime of the downloaded file to the modtime of the
            # file on the server
            modtimestr = header['last-modified']
            modtimetuple = time.strptime(modtimestr,
                                         '%a, %d %b %Y %H:%M:%S %Z')
            modtimeint = calendar.timegm(modtimetuple)
            os.utime(destinationpath, (time.time(), modtimeint))
        if header.get('etag'):
            # store etag in extended attribute for future use
            xattr.setxattr(destinationpath, XATTR_ETAG, header['etag'])
        return True


def getURLitemBasename(url):
    """For a URL, absolute or relative, return the basename string.

    e.g. "http://foo/bar/path/foo.dmg" => "foo.dmg"
         "/path/foo.dmg" => "foo.dmg"
    """

    url_parse = urlparse(url)
    return os.path.basename(url_parse.path)


def verifySoftwarePackageIntegrity(file_path, item_hash, always_hash=False):
    """Verifies the integrity of the given software package.

    The feature is controlled through the PackageVerificationMode key in
    the ManagedInstalls.plist. Following modes currently exist:
        none: No integrity check is performed.
        hash: Integrity check is performed by calculating a SHA-256 hash of
            the given file and comparing it against the reference value in
            catalog. Only applies for package plists that contain the
            item_key; for packages without the item_key, verification always
            returns True.
        hash_strict: Same as hash, but returns False for package plists that
            do not contain the item_key.

    Args:
        file_path: The file to check integrity on.
        item_hash: the sha256 hash expected.
        always_hash: True/False always check (& return) the hash even if not
                necessary for this function.

    Returns:
        (True/False, sha256-hash)
        True if the package integrity could be validated. Otherwise, False.
    """
    mode = prefs.pref('PackageVerificationMode')
    chash = None
    item_name = getURLitemBasename(file_path)
    if always_hash:
        chash = munkihash.getsha256hash(file_path)

    if not mode:
        return (True, chash)
    elif mode.lower() == 'none':
        display.display_warning('Package integrity checking is disabled.')
        return (True, chash)
    elif mode.lower() == 'hash' or mode.lower() == 'hash_strict':
        if item_hash:
            display.display_status_minor('Verifying package integrity...')
            if not chash:
                chash = munkihash.getsha256hash(file_path)
            if item_hash == chash:
                return (True, chash)
            # item_hash != chash
            display.display_error(
                'Hash value integrity check for %s failed.' %
                item_name)
            return (False, chash)
        else:
            if mode.lower() == 'hash_strict':
                display.display_error(
                    'Reference hash value for %s is missing in catalog.'
                    % item_name)
                return (False, chash)
            # mode.lower() != 'hash_strict'
            display.display_warning(
                'Reference hash value missing for %s -- package '
                'integrity verification skipped.' % item_name)
            return (True, chash)
    else:
        display.display_error(
            'The PackageVerificationMode in the ManagedInstalls.plist has an '
            'illegal value: %s' % prefs.pref('PackageVerificationMode'))

    return (False, chash)


def getDataFromURL(url):
    '''Returns data from url as string. We use the existing
    munki_resource function so any custom
    authentication/authorization headers are reused'''
    urldata = os.path.join(osutils.tmpdir(), 'urldata')
    if os.path.exists(urldata):
        try:
            os.unlink(urldata)
        except (IOError, OSError) as err:
            display.display_warning('Error in getDataFromURL: %s', err)
    dummy_result = munki_resource(url, urldata)
    try:
        fdesc = open(urldata)
        data = fdesc.read()
        fdesc.close()
        os.unlink(urldata)
        return data
    except (IOError, OSError) as err:
        display.display_warning('Error in getDataFromURL: %s', err)
        return ''


def check_server(url):
    """A function we can call to check to see if the server is
    available before we kick off a full run. This can be fooled by
    ISPs that return results for non-existent web servers...
    Returns a tuple (error_code, error_description)"""
    # rewritten 12 Dec 2016 to use gurl so we use system proxies, if any

    # deconstruct URL to get scheme
    url_parts = urlsplit(url)
    if url_parts.scheme in ('http', 'https'):
        pass
    elif url_parts.scheme == 'file':
        if url_parts.hostname not in [None, '', 'localhost']:
            return (-1, 'Non-local hostnames not supported for file:// URLs')
        if os.path.exists(url_parts.path):
            return (0, 'OK')
        return (-1, 'Path %s does not exist' % url_parts.path)
    else:
        return (-1, 'Unsupported URL scheme')

    # we have an HTTP or HTTPS URL
    try:
        # attempt to get something at the url
        dummy_data = getDataFromURL(url)
    except ConnectionError as err:
        # err.args should contain a tuple with code and description
        return (err.args[0], err.args[1])
    except (GurlError, DownloadError):
        # HTTP errors, etc are OK -- we just need to be able to connect
        pass
    return (0, 'OK')


if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
