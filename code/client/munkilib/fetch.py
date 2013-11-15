#!/usr/bin/python
# encoding: utf-8
#
# Copyright 2011-2013 Greg Neagle.
#
# Licensed under the Apache License, Version 2.0 (the 'License');
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
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

#standard libs
import calendar
import errno
import os
import re
import shutil
import subprocess
import time
import urllib2
import urlparse
import xattr

#our libs
import munkicommon
#import munkistatus


# XATTR name storing the ETAG of the file when downloaded via http(s).
XATTR_ETAG = 'com.googlecode.munki.etag'
# XATTR name storing the sha256 of the file after original download by munki.
XATTR_SHA = 'com.googlecode.munki.sha256'


class CurlError(Exception):
    pass

class HTTPError(Exception):
    pass

class MunkiDownloadError(Exception):
    """Base exception for download errors"""
    pass

class CurlDownloadError(MunkiDownloadError):
    """Curl failed to download the item"""
    pass

class FileCopyError(MunkiDownloadError):
    """Download failed because of file copy errors."""
    pass
    
class PackageVerificationError(MunkiDownloadError):
    """Package failed verification"""
    pass


def getxattr(pathname, attr):
    """Get a named xattr from a file. Return None if not present"""
    if attr in xattr.listxattr(pathname):
        return xattr.getxattr(pathname, attr)
    else:
        return None


def writeCachedChecksum(file_path, fhash=None):
    """Write the sha256 checksum of a file to an xattr so we do not need to
       calculate it again. Optionally pass the recently calculated hash value.
    """
    if not fhash:
        fhash = munkicommon.getsha256hash(file_path)
    if len(fhash) == 64:
        xattr.setxattr(file_path, XATTR_SHA, fhash)
        return fhash
    return None


WARNINGSLOGGED = {}
def curl(url, destinationpath,
         cert_info=None, custom_headers=None, donotrecurse=False, etag=None,
         message=None, onlyifnewer=False, resume=False, follow_redirects=False):
    """Gets an HTTP or HTTPS URL and stores it in
    destination path. Returns a dictionary of headers, which includes
    http_result_code and http_result_description.
    Will raise CurlError if curl returns an error.
    Will raise HTTPError if HTTP Result code is not 2xx or 304.
    If destinationpath already exists, you can set 'onlyifnewer' to true to
    indicate you only want to download the file only if it's newer on the
    server.
    If you have an ETag from the current destination path, you can pass that
    to download the file only if it is different.
    Finally, if you set resume to True, curl will attempt to resume an
    interrupted download. You'll get an error if the existing file is
    complete; if the file has changed since the first download attempt, you'll
    get a mess."""

    header = {}
    header['http_result_code'] = '000'
    header['http_result_description'] = ''

    curldirectivepath = os.path.join(munkicommon.tmpdir, 'curl_temp')
    tempdownloadpath = destinationpath + '.download'

    # we're writing all the curl options to a file and passing that to
    # curl so we avoid the problem of URLs showing up in a process listing
    try:
        fileobj = open(curldirectivepath, mode='w')
        print >> fileobj, 'silent'          # no progress meter
        print >> fileobj, 'show-error'      # print error msg to stderr
        print >> fileobj, 'no-buffer'       # don't buffer output
        print >> fileobj, 'fail'            # throw error if download fails
        print >> fileobj, 'dump-header -'   # dump headers to stdout
        print >> fileobj, 'speed-time = 30' # give up if too slow d/l
        print >> fileobj, 'output = "%s"' % tempdownloadpath
        print >> fileobj, 'ciphers = HIGH,!ADH' #use only secure >=128 bit SSL
        print >> fileobj, 'url = "%s"' % url
        
        munkicommon.display_debug2('follow_redirects is %s', follow_redirects)
        if follow_redirects:
            print >> fileobj, 'location'    # follow redirects
        
        if cert_info:
            cacert = cert_info.get('cacert')
            capath = cert_info.get('capath')
            cert = cert_info.get('cert')
            key = cert_info.get('key')
            if cacert:
                if not os.path.isfile(cacert):
                    raise CurlError(-1, 'No CA cert at %s' % cacert)
                print >> fileobj, 'cacert = "%s"' % cacert
            if capath:
                if not os.path.isdir(capath):
                    raise CurlError(-2, 'No CA directory at %s' % capath)
                print >> fileobj, 'capath = "%s"' % capath
            if cert:
                if not os.path.isfile(cert):
                    raise CurlError(-3, 'No client cert at %s' % cert)
                print >> fileobj, 'cert = "%s"' % cert
            if key:
                if not os.path.isfile(key):
                    raise CurlError(-4, 'No client key at %s' % key)
                print >> fileobj, 'key = "%s"' % key

        if os.path.exists(destinationpath):
            if etag:
                escaped_etag = etag.replace('"','\\"')
                print >> fileobj, ('header = "If-None-Match: %s"'
                                                        % escaped_etag)
            elif onlyifnewer:
                print >> fileobj, 'time-cond = "%s"' % destinationpath
            else:
                os.remove(destinationpath)

        if os.path.exists(tempdownloadpath):
            if resume and not os.path.exists(destinationpath):
                # let's try to resume this download
                print >> fileobj, 'continue-at -'
                # if an existing etag, only resume if etags still match.
                tempetag = getxattr(tempdownloadpath, XATTR_ETAG)
                if tempetag:
                    # Note: If-Range is more efficient, but the response
                    # confuses curl (Error: 33 if etag not match).
                    escaped_etag = tempetag.replace('"','\\"')
                    print >> fileobj, ('header = "If-Match: %s"'
                                        % escaped_etag)
            else:
                os.remove(tempdownloadpath)

        # Add any additional headers specified in custom_headers
        # custom_headers must be an array of strings with valid HTTP
        # header format.
        if custom_headers:
            for custom_header in custom_headers:
                custom_header = custom_header.strip().encode('utf-8')
                if re.search(r'^[\w-]+:.+', custom_header):
                    print >> fileobj, ('header = "%s"' % custom_header)
                else:
                    munkicommon.display_warning(
                        'Skipping invalid HTTP header: %s' % custom_header)

        fileobj.close()
    except Exception, e:
        raise CurlError(-5, 'Error writing curl directive: %s' % str(e))

    # In Mavericks we need to wrap our call to curl with a utility
    # that makes curl think it is connected to a tty-like
    # device so its output is unbuffered so we can get progress info
    cmd = []
    minor_os_version = munkicommon.getOsVersion(as_tuple=True)[1]
    if minor_os_version > 8:
        # Try to find our ptyexec tool
        # first look in the parent directory of this file's directory
        # (../)
        parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ptyexec_path = os.path.join(parent_dir, 'ptyexec')
        if not os.path.exists(ptyexec_path):
            # try absolute path in munki's normal install dir
            ptyexec_path = '/usr/local/munki/ptyexec'
        if os.path.exists(ptyexec_path):
            cmd = [ptyexec_path]

    # Workaround for current issue in OS X 10.9's included curl
    # Allows for alternate curl binary path as Apple's included curl currently
    # broken for client-side certificate usage
    curl_path = munkicommon.pref('CurlPath') or '/usr/bin/curl'
    cmd.extend([curl_path,
                '-q',                    # don't read .curlrc file
                '--config',              # use config file
                curldirectivepath])

    proc = subprocess.Popen(cmd, shell=False, bufsize=1,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    targetsize = 0
    downloadedpercent = -1
    donewithheaders = False
    maxheaders = 15

    while True:
        if not donewithheaders:
            info = proc.stdout.readline().strip('\r\n')
            if info:
                munkicommon.display_debug2(info)
                if info.startswith('HTTP/'):
                    header['http_result_code'] = info.split(None, 2)[1]
                    header['http_result_description'] = info.split(None, 2)[2]
                elif ': ' in info:
                    part = info.split(None, 1)
                    fieldname = part[0].rstrip(':').lower()
                    header[fieldname] = part[1]
            else:
                # we got an empty line; end of headers (or curl exited)
                if follow_redirects:
                    if header.get('http_result_code') in ['301', '302', '303']:
                        # redirect, so more headers are coming.
                        # Throw away the headers we've received so far
                        header = {}
                        header['http_result_code'] = '000'
                        header['http_result_description'] = ''
                else:
                    donewithheaders = True
                    try:
                        # Prefer Content-Length header to determine download 
                        # size, otherwise fall back to a custom X-Download-Size 
                        # header.
                        # This is primary for servers that use chunked transfer
                        # encoding, when Content-Length is forbidden by 
                        # RFC2616 4.4. An example of such a server is
                        # Google App Engine Blobstore.
                        targetsize = (
                            header.get('content-length') or
                            header.get('x-download-size'))
                        targetsize = int(targetsize)
                    except (ValueError, TypeError):
                        targetsize = 0
                    if header.get('http_result_code') == '206':
                        # partial content because we're resuming
                        munkicommon.display_detail(
                            'Resuming partial download for %s' %
                                            os.path.basename(destinationpath))
                        contentrange = header.get('content-range')
                        if contentrange.startswith('bytes'):
                            try:
                                targetsize = int(contentrange.split('/')[1])
                            except (ValueError, TypeError):
                                targetsize = 0

                    if message and header.get('http_result_code') != '304':
                        if message:
                            # log always, display if verbose is 1 or more
                            # also display in MunkiStatus detail field
                            munkicommon.display_status_minor(message)

        elif targetsize and header.get('http_result_code').startswith('2'):
            # display progress if we get a 2xx result code
            if os.path.exists(tempdownloadpath):
                downloadedsize = os.path.getsize(tempdownloadpath)
                percent = int(float(downloadedsize)
                                    /float(targetsize)*100)
                if percent != downloadedpercent:
                    # percent changed; update display
                    downloadedpercent = percent
                    munkicommon.display_percent_done(downloadedpercent, 100)
            time.sleep(0.1)
        else:
            # Headers have finished, but not targetsize or HTTP2xx.
            # It's possible that Content-Length was not in the headers.
            # so just sleep and loop again. We can't show progress.
            time.sleep(0.1)

        if (proc.poll() != None):
            # For small download files curl may exit before all headers
            # have been parsed, don't immediately exit.
            maxheaders -= 1
            if donewithheaders or maxheaders <= 0:
                break

    retcode = proc.poll()
    if retcode:
        curlerr = ''
        try:
            curlerr = proc.stderr.read().rstrip('\n')
            curlerr = curlerr.split(None, 2)[2]
        except IndexError:
            pass
        if retcode == 22:
            # 22 means any 400 series return code. Note: header seems not to
            # be dumped to STDOUT for immediate failures. Hence
            # http_result_code is likely blank/000. Read it from stderr.
            if re.search(r'URL returned error: [0-9]+$', curlerr):
                header['http_result_code'] = curlerr[curlerr.rfind(' ')+1:]

        if os.path.exists(tempdownloadpath):
            if not resume:
                os.remove(tempdownloadpath)
            elif retcode == 33 or header.get('http_result_code') == '412':
                # 33: server doesn't support range requests
                # 412: Etag didn't match (precondition failed), could not
                #   resume partial download as file on server has changed.
                if retcode == 33 and not 'HTTPRange' in WARNINGSLOGGED:
                    # use display_info instead of display_warning so these
                    # don't get reported but are available in the log
                    # and in command-line output
                    munkicommon.display_info('WARNING: Web server refused '
                            'partial/range request. Munki cannot run '
                            'efficiently when this support is absent for '
                            'pkg urls. URL: %s' % url)
                    WARNINGSLOGGED['HTTPRange'] = 1
                os.remove(tempdownloadpath)
                # The partial failed immediately as not supported.
                # Try a full download again immediately.
                if not donotrecurse:
                    return curl(url, destinationpath, 
                                cert_info=cert_info,
                                custom_headers=custom_headers,
                                donotrecurse=True,
                                etag=etag,
                                message=message,
                                onlyifnewer=onlyifnewer,
                                resume=resume,
                                follow_redirects=follow_redirects)
            elif retcode == 22:
                # TODO: Made http(s) connection but 400 series error.
                # What should we do?
                # 403 could be ok, just that someone is currently offsite and
                # the server is refusing the service them while there.
                # 404 could be an interception proxy at a public wifi point.
                # The partial may still be ok later.
                # 416 could be dangerous - the targeted resource may now be
                # different / smaller. We need to delete the temp or retrying
                # will never work.
                if header.get('http_result_code') == 416:
                    # Bad range request.
                    os.remove(tempdownloadpath)
                elif header.get('http_result_code') == 503:
                    # Web server temporarily unavailable.
                    pass
                elif not header.get('http_result_code').startswith('4'):
                    # 500 series, or no error code parsed.
                    # Perhaps the webserver gets really confused by partial
                    # requests. It is likely majorly misconfigured so we won't
                    # try asking it anything challenging.
                    os.remove(tempdownloadpath)
            elif header.get('etag'):
                xattr.setxattr(tempdownloadpath, XATTR_ETAG, header['etag'])
        # TODO: should we log this diagnostic here (we didn't previously)?
        # Currently for a pkg all that is logged on failure is:
        # "WARNING: Download of Firefox failed." with no detail. Logging at
        # the place where this exception is caught has to be done in many
        # places.
        munkicommon.display_detail('Download error: %s. Failed (%s) with: %s'
                                    % (url,retcode,curlerr))
        raise CurlError(retcode, curlerr)
    else:
        temp_download_exists = os.path.isfile(tempdownloadpath)
        http_result = header.get('http_result_code')
        if http_result.startswith('2') and temp_download_exists:
            downloadedsize = os.path.getsize(tempdownloadpath)
            if downloadedsize >= targetsize:
                if targetsize and not downloadedpercent == 100:
                    # need to display a percent done of 100%
                    munkicommon.display_percent_done(100, 100)
                os.rename(tempdownloadpath, destinationpath)
                if (resume and not header.get('etag')
                    and not 'HTTPetag' in WARNINGSLOGGED):
                    # use display_info instead of display_warning so these
                    # don't get reported but are available in the log
                    # and in command-line output
                    munkicommon.display_info(
                        'WARNING: '
                        'Web server did not return an etag. Munki cannot '
                        'safely resume downloads without etag support on the '
                        'web server. URL: %s' % url)
                    WARNINGSLOGGED['HTTPetag'] = 1
                return header
            else:
                # not enough bytes retreived
                if not resume and temp_download_exists:
                    os.remove(tempdownloadpath)
                raise CurlError(-5, 'Expected %s bytes, got: %s' %
                                        (targetsize, downloadedsize))
        elif http_result == '304':
            return header
        else:
            # there was a download error of some sort; clean all relevant
            # downloads that may be in a bad state.
            for f in [tempdownloadpath, destinationpath]:
                try:
                    os.unlink(f)
                except OSError:
                    pass
            raise HTTPError(http_result,
                                header.get('http_result_description',''))


def getResourceIfChangedAtomically(url, 
                                   destinationpath,
                                   cert_info=None,
                                   custom_headers=None,
                                   expected_hash=None,
                                   message=None, 
                                   resume=False,
                                   verify=False,
                                   follow_redirects=False):
    """Gets file from a URL.
       Checks first if there is already a file with the necessary checksum.
       Then checks if the file has changed on the server, resuming or
       re-downloading as necessary.

       If the file has changed verify the pkg hash if so configured.

       Supported schemes are http, https, file.

       Returns True if a new download was required; False if the
       item is already in the local cache.

       Raises a MunkiDownloadError derived class if there is an error."""

    changed = False

    # If we already have a downloaded file & its (cached) hash matches what
    # we need, do nothing, return unchanged.
    if resume and expected_hash and os.path.isfile(destinationpath):
        xattr_hash = getxattr(destinationpath, XATTR_SHA)
        if not xattr_hash:
            xattr_hash = writeCachedChecksum(destinationpath)
        if xattr_hash == expected_hash:
            #File is already current, no change.
            return False
        elif munkicommon.pref(
             'PackageVerificationMode').lower() in ['hash_strict', 'hash']:
            try:
                os.unlink(destinationpath)
            except OSError:
                pass
        munkicommon.log('Cached payload does not match hash in catalog, '
                'will check if changed and redownload: %s' % destinationpath)
        #continue with normal if-modified-since/etag update methods.

    url_parse = urlparse.urlparse(url)
    if url_parse.scheme in ['http', 'https']:
        changed = getHTTPfileIfChangedAtomically(
            url, destinationpath,
            cert_info=cert_info, custom_headers=custom_headers,
            message=message, resume=resume, follow_redirects=follow_redirects)
    elif url_parse.scheme == 'file':
        changed = getFileIfChangedAtomically(url_parse.path, destinationpath)
    else:
        raise MunkiDownloadError(
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


def getFileIfChangedAtomically(path, destinationpath):
    """Gets file from path, checking first to see if it has changed on the
       source.

       Returns True if a new copy was required; False if the
       item is already in the local cache.

       Raises FileCopyError if there is an error."""
    path = urllib2.unquote(path)
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
    except OSError, e:
        if e.args[0] == errno.ENOENT:
            pass  # OK
        else:
            raise FileCopyError('Removing %s: %s' % (
                tmp_destinationpath, str(e)))

    # copy from source to temporary destination
    try:
        shutil.copy2(path, tmp_destinationpath)
    except IOError, e:
        raise FileCopyError('Copy IOError: %s' % str(e))

    # rename temp destination to final destination
    try:
        os.rename(tmp_destinationpath, destinationpath)
    except OSError, e:
        raise FileCopyError('Renaming %s: %s' % (destinationpath, str(e)))

    return True


def getHTTPfileIfChangedAtomically(url, destinationpath,
                                   cert_info=None, custom_headers=None,
                                   message=None, resume=False,
                                   follow_redirects=False):
    """Gets file from HTTP URL, checking first to see if it has changed on the
       server.

       Returns True if a new download was required; False if the
       item is already in the local cache.

       Raises CurlDownloadError if there is an error."""

    etag = None
    getonlyifnewer = False
    if os.path.exists(destinationpath):
        getonlyifnewer = True
        # see if we have an etag attribute
        etag = getxattr(destinationpath, XATTR_ETAG)
        if etag:
            getonlyifnewer = False

    try:
        header = curl(url,
                      destinationpath,
                      cert_info=cert_info,
                      custom_headers=custom_headers,
                      etag=etag,
                      message=message,
                      onlyifnewer=getonlyifnewer,
                      resume=resume,
                      follow_redirects=follow_redirects)

    except CurlError, err:
        err = 'Error %s: %s' % tuple(err)
        raise CurlDownloadError(err)

    except HTTPError, err:
        err = 'HTTP result %s: %s' % tuple(err)
        raise CurlDownloadError(err)

    err = None
    if header['http_result_code'] == '304':
        # not modified, return existing file
        munkicommon.display_debug1('%s already exists and is up-to-date.'
                                        % destinationpath)
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

    url_parse = urlparse.urlparse(url)
    return os.path.basename(url_parse.path)


def verifySoftwarePackageIntegrity(file_path, item_hash, always_hash=False):
    """Verifies the integrity of the given software package.

    The feature is controlled through the PackageVerificationMode key in
    the ManagedInstalls.plist. Following modes currently exist:
        none: No integrity check is performed.
        hash: Integrity check is performed by calcualting a SHA-256 hash of
            the given file and comparing it against the reference value in
            catalog. Only applies for package plists that contain the
            item_key; for packages without the item_key, verifcation always
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
    mode = munkicommon.pref('PackageVerificationMode')
    chash = None
    item_name = getURLitemBasename(file_path)
    if always_hash:
        chash = munkicommon.getsha256hash(file_path)

    if not mode:
        return (True, chash)
    elif mode.lower() == 'none':
        munkicommon.display_warning('Package integrity checking is disabled.')
        return (True, chash)
    elif mode.lower() == 'hash' or mode.lower() == 'hash_strict':
        if item_hash:
            munkicommon.display_status_minor('Verifying package integrity...')
            if not chash:
                chash = munkicommon.getsha256hash(file_path)
            if item_hash == chash:
                return (True, chash)
            else:
                munkicommon.display_error(
                    'Hash value integrity check for %s failed.' %
                    item_name)
                return (False, chash)
        else:
            if mode.lower() == 'hash_strict':
                munkicommon.display_error(
                    'Reference hash value for %s is missing in catalog.'
                    % item_name)
                return (False, chash)
            else:
                munkicommon.display_warning(
                    'Reference hash value missing for %s -- package '
                    'integrity verification skipped.' % item_name)
                return (True, chash)
    else:
        munkicommon.display_error(
            'The PackageVerificationMode in the ManagedInstalls.plist has an '
            'illegal value: %s' % munkicommon.pref('PackageVerificationMode'))

    return (False, chash)


