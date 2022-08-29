# encoding: utf-8
'''Defines FileRepo plugin. See docstring for FileRepo class'''
# This code is largely still compatible with Python 2, so for now, turn off
# Python 3 style warnings
# pylint: disable=consider-using-f-string
# pylint: disable=redundant-u-string-prefix

from __future__ import absolute_import, print_function

import errno
import getpass
import os
import shutil
import subprocess
import sys

try:
    # Python 2
    from urllib import unquote
except ImportError:
    # Python 3
    from urllib.parse import unquote

try:
    # Python 2
    from urlparse import urlparse
except ImportError:
    # Python 3
    from urllib.parse import urlparse

from munkilib.munkirepo import Repo, RepoError
from munkilib.wrappers import get_input


# NetFS share mounting code borrowed and liberally adapted from Michael Lynn's
# work here: https://gist.github.com/pudquick/1362a8908be01e23041d
try:
    import objc
    from CoreFoundation import CFURLCreateWithString

    class Attrdict(dict):
        '''Custom dict class'''
        __getattr__ = dict.__getitem__
        __setattr__ = dict.__setitem__

    # pylint: disable=invalid-name
    NetFS = Attrdict()
    # Can cheat and provide 'None' for the identifier, it'll just use
    # frameworkPath instead
    # scan_classes=False means only add the contents of this Framework
    NetFS_bundle = objc.initFrameworkWrapper(
        'NetFS', frameworkIdentifier=None,
        frameworkPath=objc.pathForFramework('NetFS.framework'),
        globals=NetFS, scan_classes=False)
    # pylint: enable=invalid-name

    # https://developer.apple.com/library/mac/documentation/Cocoa/Conceptual/
    # ObjCRuntimeGuide/Articles/ocrtTypeEncodings.html
    # Fix NetFSMountURLSync signature
    del NetFS['NetFSMountURLSync']
    # pylint: disable=no-member
    objc.loadBundleFunctions(
        NetFS_bundle, NetFS, [('NetFSMountURLSync', b'i@@@@@@o^@')])
    # pylint: enable=no-member
    NETFSMOUNTURLSYNC_AVAILABLE = True
except (ImportError, KeyError):
    NETFSMOUNTURLSYNC_AVAILABLE = False


class ShareMountException(Exception):
    '''An exception raised if share mounting failed'''
    #pass


class ShareAuthenticationNeededException(ShareMountException):
    '''An exception raised if authentication is needed'''
    #pass


def unicodeize(path):
    '''Convert a path to unicode'''
    # pylint: disable=unicode-builtin
    # Python 3 all paths are unicode!
    if sys.version_info.major > 2:
        return path
    # below executes only under Python 2
    # by pylint3 flags "unicode" as undefined
    # pylint: disable=undefined-variable
    if isinstance(path, str):
        return unicode(path, 'utf-8')
    if not isinstance(path, unicode):
        return unicode(path)
    return path


def mount_share(share_url):
    '''Mounts a share at /Volumes, returns the mount point or raises an error'''
    # Uses some constants defined in NetFS.h
    # /Applications/Xcode.app/Contents/Developer/Platforms/MacOSX.platform/
    #    Developer/SDKs/MacOSX.sdk/System/Library/Frameworks/NetFS.framework/
    #    Versions/A/Headers/NetFS.h
    sh_url = CFURLCreateWithString(None, share_url, None)
    # Set UI to reduced interaction
    #open_options = {NetFS.kNAUIOptionKey: NetFS.kNAUIOptionNoUI}
    # can't look up the values for those constants in 10.13, so we'll just
    # hardcode them
    open_options = {'UIOption': 'NoUI'}
    # Allow mounting sub-directories of root shares
    #mount_options = {NetFS.kNetFSAllowSubMountsKey: True}
    # can't look up the values for those constants in 10.13, so we'll just
    # hardcode them
    mount_options = {'AllowSubMounts': True}
    # Mount!
    result, mountpoints = NetFS.NetFSMountURLSync(
        sh_url, None, None, None, open_options, mount_options, None)
    # Check if it worked
    if result != 0:
        if result in (-6600, errno.EINVAL, errno.ENOTSUP, errno.EAUTH):
            # -6600 is kNetAuthErrorInternal in NetFS.h 10.9+
            # errno.EINVAL is returned if an afp share needs a login in some
            #               versions of OS X
            # errno.ENOTSUP is returned if an afp share needs a login in some
            #               versions of OS X
            # errno.EAUTH is returned if authentication fails (SMB for sure)
            raise ShareAuthenticationNeededException()
        raise ShareMountException('Error mounting url "%s": %s, error %s'
                                  % (share_url, os.strerror(result), result))
    # Return the mountpath
    return str(mountpoints[0])


def mount_share_with_credentials(share_url, username, password):
    '''Mounts a share at /Volumes, returns the mount point or raises an error
    Include username and password as parameters, not in the share_path URL'''
    sh_url = CFURLCreateWithString(None, share_url, None)
    # Set UI to reduced interaction
    #open_options = {NetFS.kNAUIOptionKey: NetFS.kNAUIOptionNoUI}
    # can't look up the values for those constants in 10.13, so we'll just
    # hardcode them
    open_options = {'UIOption': 'NoUI'}
    # Allow mounting sub-directories of root shares
    #mount_options = {NetFS.kNetFSAllowSubMountsKey: True}
    # can't look up the values for those constants in 10.13, so we'll just
    # hardcode them
    mount_options = {'AllowSubMounts': True}
    # Mount!
    result, mountpoints = NetFS.NetFSMountURLSync(
        sh_url, None, username, password, open_options, mount_options, None)
    # Check if it worked
    if result != 0:
        raise ShareMountException('Error mounting url "%s": %s, error %s'
                                  % (share_url, os.strerror(result), result))
    # Return the mountpath
    return str(mountpoints[0])


def mount_share_url(share_url):
    '''Mount a share url under /Volumes, prompting for password if needed
    Raises ShareMountException if there's an error'''
    try:
        mountpoint = mount_share(share_url)
    except ShareAuthenticationNeededException:
        username = get_input('Username: ')
        password = getpass.getpass()
        mountpoint = mount_share_with_credentials(share_url, username, password)
    return mountpoint


class FileRepo(Repo):
    '''Handles local filesystem repo and repos mounted via filesharing'''

    # pylint: disable=super-init-not-called
    def __init__(self, baseurl):
        '''Constructor'''
        self.baseurl = baseurl
        url_parts = urlparse(baseurl)
        self.url_scheme = url_parts.scheme
        if self.url_scheme == 'file':
            # local file repo
            self.root = unicodeize(unquote(url_parts.path))
        else:
            # repo is on a fileshare that will be mounted under /Volumes
            self.root = os.path.join(
                u'/Volumes',
                unicodeize(unquote(url_parts.path).lstrip('/')))
        self.we_mounted_repo = False
        self._connect()
    # pylint: enable=super-init-not-called

    def __del__(self):
        '''Destructor -- unmount the fileshare if we mounted it'''
        if self.we_mounted_repo and os.path.exists(self.root):
            cmd = ['/sbin/umount', self.root]
            subprocess.call(cmd)

    def _connect(self):
        '''If self.root is present, return. Otherwise, if the url scheme is not
        "file:" then try to mount the share url.'''
        if not os.path.exists(self.root) and self.url_scheme != 'file':
            print(u'Attempting to mount fileshare %s:' % self.baseurl)
            if NETFSMOUNTURLSYNC_AVAILABLE:
                try:
                    self.root = mount_share_url(self.baseurl)
                except ShareMountException as err:
                    raise RepoError(err) from err
                else:
                    self.we_mounted_repo = True
            else:
                try:
                    os.mkdir(self.root)
                except (OSError, IOError) as err:
                    raise RepoError(u'Could not make repo mountpoint: %s' % err) from err
                if self.baseurl.startswith('afp:'):
                    cmd = ['/sbin/mount_afp', '-i', self.baseurl, self.root]
                elif self.baseurl.startswith('smb:'):
                    cmd = ['/sbin/mount_smbfs', self.baseurl[4:], self.root]
                elif self.baseurl.startswith('nfs://'):
                    cmd = ['/sbin/mount_nfs', self.baseurl[6:], self.root]
                else:
                    print('Unsupported filesystem URL!', file=sys.stderr)
                    return
                retcode = subprocess.call(cmd)
                if retcode:
                    os.rmdir(self.root)
                else:
                    self.we_mounted_repo = True
        # mount attempt complete; check again for existence of self.root
        if not os.path.exists(self.root):
            raise RepoError(u'%s does not exist' % self.root)

    def itemlist(self, kind):
        '''Returns a list of identifiers for each item of kind.
        Kind might be 'catalogs', 'manifests', 'pkgsinfo', 'pkgs', or 'icons'.
        For a file-backed repo this would be a list of pathnames.'''
        kind = unicodeize(kind)
        search_dir = os.path.join(self.root, kind)
        file_list = []
        try:
            for (dirpath, dirnames, filenames) in os.walk(search_dir,
                                                          followlinks=True):
                # don't recurse into directories that start with a period.
                dirnames[:] = [name
                               for name in dirnames if not name.startswith('.')]
                for name in filenames:
                    if name.startswith('.'):
                        # skip files that start with a period as well
                        continue
                    abs_path = os.path.join(dirpath, name)
                    rel_path = abs_path[len(search_dir):].lstrip("/")
                    file_list.append(rel_path)
            return file_list
        except (OSError, IOError) as err:
            raise RepoError(err) from err

    def get(self, resource_identifier):
        '''Returns the content of item with given resource_identifier.
        For a file-backed repo, a resource_identifier of
        'pkgsinfo/apps/Firefox-52.0.plist' would return the contents of
        <repo_root>/pkgsinfo/apps/Firefox-52.0.plist.
        Avoid using this method with the 'pkgs' kind as it might return a
        really large blob of data.'''
        resource_identifier = unicodeize(resource_identifier)
        repo_filepath = os.path.join(self.root, resource_identifier)
        try:
            fileref = open(repo_filepath, 'rb')
            data = fileref.read()
            fileref.close()
            return data
        except (OSError, IOError) as err:
            raise RepoError(err) from err

    def get_to_local_file(self, resource_identifier, local_file_path):
        '''Gets the contents of item with given resource_identifier and saves
        it to local_file_path.
        For a file-backed repo, a resource_identifier
        of 'pkgsinfo/apps/Firefox-52.0.plist' would copy the contents of
        <repo_root>/pkgsinfo/apps/Firefox-52.0.plist to a local file given by
        local_file_path.'''
        resource_identifier = unicodeize(resource_identifier)
        repo_filepath = os.path.join(self.root, resource_identifier)
        local_file_path = unicodeize(local_file_path)
        try:
            shutil.copyfile(repo_filepath, local_file_path)
        except (OSError, IOError) as err:
            raise RepoError(err) from err

    def put(self, resource_identifier, content):
        '''Stores content on the repo based on resource_identifier.
        For a file-backed repo, a resource_identifier of
        'pkgsinfo/apps/Firefox-52.0.plist' would result in the content being
        saved to <repo_root>/pkgsinfo/apps/Firefox-52.0.plist.'''
        resource_identifier = unicodeize(resource_identifier)
        repo_filepath = os.path.join(self.root, resource_identifier)
        dir_path = os.path.dirname(repo_filepath)
        if not os.path.exists(dir_path):
            os.makedirs(dir_path, 0o755)
        try:
            fileref = open(repo_filepath, 'wb')
            fileref.write(content)
            fileref.close()
        except (OSError, IOError) as err:
            raise RepoError(err) from err

    def put_from_local_file(self, resource_identifier, local_file_path):
        '''Copies the content of local_file_path to the repo based on
        resource_identifier. For a file-backed repo, a resource_identifier
        of 'pkgsinfo/apps/Firefox-52.0.plist' would result in the content
        being saved to <repo_root>/pkgsinfo/apps/Firefox-52.0.plist.'''
        resource_identifier = unicodeize(resource_identifier)
        repo_filepath = os.path.join(self.root, resource_identifier)
        local_file_path = unicodeize(local_file_path)
        if os.path.normpath(local_file_path) == os.path.normpath(repo_filepath):
            # nothing to do!
            return
        dir_path = os.path.dirname(repo_filepath)
        if not os.path.exists(dir_path):
            os.makedirs(dir_path, 0o755)
        try:
            shutil.copyfile(local_file_path, repo_filepath)
        except (OSError, IOError) as err:
            raise RepoError(err) from err

    def local_path(self, resource_identifier):
        '''Returns the local file path for resource_identifier'''
        resource_identifier = unicodeize(resource_identifier)
        return os.path.join(self.root, resource_identifier)

    def delete(self, resource_identifier):
        '''Deletes a repo object located by resource_identifier.
        For a file-backed repo, a resource_identifier of
        'pkgsinfo/apps/Firefox-52.0.plist' would result in the deletion of
        <repo_root>/pkgsinfo/apps/Firefox-52.0.plist.'''
        resource_identifier = unicodeize(resource_identifier)
        repo_filepath = os.path.join(self.root, resource_identifier)
        try:
            os.remove(repo_filepath)
        except (OSError, IOError) as err:
            raise RepoError(err) from err
