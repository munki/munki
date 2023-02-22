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
info.py

Created by Greg Neagle on 2016-12-14.

Utilities that retrieve information from the current machine.
"""
from __future__ import absolute_import, print_function

# standard libs
import ctypes
import ctypes.util
import fcntl
import os
import select
import struct
import subprocess
import sys

# Apple's libs
import objc
import LaunchServices
# PyLint cannot properly find names inside Cocoa libraries, so issues bogus
# No name 'Foo' in module 'Bar' warnings. Disable them.
# pylint: disable=E0611
from Foundation import NSMetadataQuery, NSPredicate, NSRunLoop
from Foundation import NSBundle, NSDate, NSTimeZone
from Foundation import NSString, NSUTF8StringEncoding
# pylint: enable=E0611

# our libs
from . import display
from . import munkilog
from . import osutils
from . import pkgutils
from . import powermgr
from . import prefs
from . import reports
from . import utils
from . import FoundationPlist
from .wrappers import unicode_or_str

try:
    _ = xrange # pylint: disable=xrange-builtin
except NameError:
    # no xrange in Python 3
    xrange = range # pylint: disable=redefined-builtin,invalid-name

# Always ignore these directories when discovering applications.
APP_DISCOVERY_EXCLUSION_DIRS = set([
    'Volumes', 'tmp', '.vol', '.Trashes', '.MobileBackups', '.Spotlight-V100',
    '.fseventsd', 'Network', 'net', 'home', 'cores', 'dev', 'private',
    ])


class Error(Exception):
    """Class for domain specific exceptions."""


class TimeoutError(Error):
    """Timeout limit exceeded since last I/O."""


def set_file_nonblock(fileobj, non_blocking=True):
    """Set non-blocking flag on a file object.

    Args:
      fileobj: file
      non_blocking: bool, default True, non-blocking mode or not
    """
    flags = fcntl.fcntl(fileobj.fileno(), fcntl.F_GETFL)
    if bool(flags & os.O_NONBLOCK) != non_blocking:
        flags ^= os.O_NONBLOCK
    fcntl.fcntl(fileobj.fileno(), fcntl.F_SETFL, flags)


class Popen(subprocess.Popen):
    """Subclass of subprocess.Popen to add support for timeouts."""

    def timed_readline(self, fileobj, timeout):
        """Perform readline-like operation with timeout.

        Args:
            fileobj: file object to .readline() on
            timeout: int, seconds of inactivity to raise error at
        Raises:
            TimeoutError, if timeout is reached
        """
        # pylint: disable=no-self-use
        set_file_nonblock(fileobj)

        output = []
        inactive = 0
        while True:
            (rlist, dummy_wlist, dummy_xlist) = select.select(
                [fileobj], [], [], 1.0)

            if not rlist:
                inactive += 1  # approx -- py select doesn't return tv
                if inactive >= timeout:
                    break
            else:
                inactive = 0
                char = fileobj.read(1)
                output.append(char)  # keep newline
                if char == '' or char == '\n':
                    break

        set_file_nonblock(fileobj, non_blocking=False)

        if inactive >= timeout:
            raise TimeoutError  # note, an incomplete line can be lost
        else:
            return ''.join(output)

    def communicate(self, std_in=None, timeout=0):
        """Communicate, optionally ending after a timeout of no activity.

        Args:
            std_in: str, to send on stdin
            timeout: int, seconds of inactivity to raise error at
        Returns:
            (str or None, str or None) for stdout, stderr
        Raises:
            TimeoutError, if timeout is reached
        """
        # pylint: disable=arguments-differ
        if timeout <= 0:
            return super(Popen, self).communicate(input=std_in)

        fds = []
        stdout = []
        stderr = []

        if self.stdout is not None:
            set_file_nonblock(self.stdout)
            fds.append(self.stdout)
        if self.stderr is not None:
            set_file_nonblock(self.stderr)
            fds.append(self.stderr)

        if std_in is not None and sys.stdin is not None:
            try:
                # Python 3
                sys.stdin.buffer.write(std_in)
            except AttributeError:
                # Python 2
                sys.stdin.write(std_in)

        returncode = None
        inactive = 0
        while returncode is None:
            (rlist, dummy_wlist, dummy_xlist) = select.select(
                fds, [], [], 1.0)

            if not rlist:
                inactive += 1
                if inactive >= timeout:
                    raise TimeoutError
            else:
                inactive = 0
                for filedescr in rlist:
                    if filedescr is self.stdout:
                        stdout.append(filedescr.read())
                    elif filedescr is self.stderr:
                        stderr.append(filedescr.read())

            returncode = self.poll()

        if self.stdout is not None:
            stdout_str = b''.join(stdout)
        else:
            stdout_str = None
        if self.stderr is not None:
            stderr_str = b''.join(stderr)
        else:
            stderr_str = None

        return (stdout_str, stderr_str)


def _unsigned(i):
    """Translate a signed int into an unsigned int.  Int type returned
    is longer than the original since Python has no unsigned int."""
    return i & 0xFFFFFFFF


def _asciiz_to_bytestr(a_bytestring):
    """Transform a null-terminated string of any length into a Python str.
    Returns a normal Python str that has been terminated.
    """
    i = a_bytestring.find(b'\0')
    if i > -1:
        a_bytestring = a_bytestring[0:i]
    return a_bytestring


def _f_flags_to_set(f_flags):
    """Transform an int f_flags parameter into a set of mount options.
    Returns a set.
    """
    # see /usr/include/sys/mount.h for the bitmask constants.
    flags = set()
    if f_flags & 0x1:
        flags.add('read-only')
    if f_flags & 0x1000:
        flags.add('local')
    if f_flags & 0x4000:
        flags.add('rootfs')
    if f_flags & 0x4000000:
        flags.add('automounted')
    return flags


def is_apple_silicon():
    """Returns True if we're running on Apple Silicon"""
    arch = os.uname()[4]
    if arch == 'x86_64':
        # we might be natively Intel64, or running under Rosetta.
        # os.uname()[4] returns the current execution arch, which under Rosetta
        # will be x86_64. Since what we want here is the _native_ arch, we're
        # going to use a hack for now to see if we're natively arm64
        uname_version = os.uname()[3]
        if 'ARM64' in uname_version:
            arch = 'arm64'
    return arch == 'arm64'

def get_filesystems():
    """Get a list of all mounted filesystems on this system.

    Return value is dict, e.g. {
        int st_dev: {
            'f_fstypename': 'nfs',
            'f_mntonname': '/mountedpath',
            'f_mntfromname': 'homenfs:/path',
        },
    }

    Note: st_dev values are static for potentially only one boot, but
    static for multiple mount instances.
    """

    mnt_nowait = 2

    libc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("c"))
    # see man GETFSSTAT(2) for struct
    statfs_32_struct = b'=hh ll ll ll lQ lh hl 2l 15s 90s 90s x 16x'
    statfs_64_struct = b'=Ll QQ QQ Q ll l LLL 16s 1024s 1024s 32x'
    os_version = osutils.getOsVersion(as_tuple=True)
    if os_version <= (10, 5):
        mode = 32
    else:
        mode = 64

    if mode == 64:
        statfs_struct = statfs_64_struct
    else:
        statfs_struct = statfs_32_struct

    sizeof_statfs_struct = struct.calcsize(statfs_struct)
    bufsize = 30 * sizeof_statfs_struct  # only supports 30 mounted fs
    buf = ctypes.create_string_buffer(bufsize)

    if mode == 64:
        # some 10.6 boxes return 64-bit structures on getfsstat(), some do not.
        # forcefully call the 64-bit version in cases where we think
        # a 64-bit struct will be returned.
        no_of_structs = libc.getfsstat64(ctypes.byref(buf), bufsize, mnt_nowait)
    else:
        no_of_structs = libc.getfsstat(ctypes.byref(buf), bufsize, mnt_nowait)

    if no_of_structs < 0:
        display.display_debug1('getfsstat() returned errno %d' % no_of_structs)
        return {}

    ofs = 0
    output = {}
    # struct_unpack returns lots of values, but we use only a few
    # pylint: disable=unused-variable
    for i in xrange(0, no_of_structs):
        if mode == 64:
            (f_bsize, f_iosize, f_blocks, f_bfree, f_bavail, f_files,
             f_ffree, f_fsid_0, f_fsid_1, f_owner, f_type, f_flags,
             f_fssubtype,
             f_fstypename, f_mntonname, f_mntfromname) = struct.unpack(
                 statfs_struct, bytes(buf[ofs:ofs+sizeof_statfs_struct]))
        elif mode == 32:
            (f_otype, f_oflags, f_bsize, f_iosize, f_blocks, f_bfree, f_bavail,
             f_files, f_ffree, f_fsid, f_owner, f_reserved1, f_type, f_flags,
             f_reserved2_0, f_reserved2_1, f_fstypename, f_mntonname,
             f_mntfromname) = struct.unpack(
                 statfs_struct, bytes(buf[ofs:ofs+sizeof_statfs_struct]))

        try:
            stat_val = os.stat(_asciiz_to_bytestr(f_mntonname))
            output[stat_val.st_dev] = {
                'f_flags_set': _f_flags_to_set(f_flags),
                'f_fstypename': _asciiz_to_bytestr(f_fstypename),
                'f_mntonname': _asciiz_to_bytestr(f_mntonname),
                'f_mntfromname': _asciiz_to_bytestr(f_mntfromname),
            }
        except OSError:
            pass

        ofs += sizeof_statfs_struct
    # pylint: enable=unused-variable

    return output


FILESYSTEMS = {}
def is_excluded_filesystem(path, _retry=False):
    """Gets filesystem information for a path and determine if it should be
    excluded from application searches.

    Returns True if path is located on NFS, is read only, or
    is not marked local.
    Returns False if none of these conditions are true.
    Returns None if it cannot be determined.
    """
    global FILESYSTEMS

    if not path:
        return None

    path_components = path.split('/')
    if len(path_components) > 1:
        if path_components[1] in APP_DISCOVERY_EXCLUSION_DIRS:
            return True

    if not FILESYSTEMS or _retry:
        FILESYSTEMS = get_filesystems()

    try:
        stat_val = os.stat(path)
    except OSError:
        stat_val = None

    if stat_val is None or stat_val.st_dev not in FILESYSTEMS:
        if not _retry:
            # perhaps the stat() on the path caused autofs to mount
            # the required filesystem and now it will be available.
            # try one more time to look for it after flushing the cache.
            display.display_debug1(
                'Trying isExcludedFilesystem again for %s' % path)
            return is_excluded_filesystem(path, True)
        # _retry defined
        display.display_debug1(
            'Could not match path %s to a filesystem' % path)
        return None

    exc_flags = ('read-only' in FILESYSTEMS[stat_val.st_dev]['f_flags_set'] or
                 'local' not in FILESYSTEMS[stat_val.st_dev]['f_flags_set'])
    is_nfs = FILESYSTEMS[stat_val.st_dev]['f_fstypename'] == 'nfs'

    if is_nfs or exc_flags:
        display.display_debug1(
            'Excluding %s (flags %s, nfs %s)' % (path, exc_flags, is_nfs))

    return is_nfs or exc_flags


def find_apps_in_dirs(dirlist):
    """Do spotlight search for type applications within the
    list of directories provided. Returns a list of paths to applications
    these appear to always be some form of unicode string.
    """
    applist = []
    query = NSMetadataQuery.alloc().init()
    query.setPredicate_(
        NSPredicate.predicateWithFormat_('(kMDItemKind = "Application")'))
    query.setSearchScopes_(dirlist)
    query.startQuery()
    # Spotlight isGathering phase - this is the initial search. After the
    # isGathering phase Spotlight keeps running returning live results from
    # filesystem changes, we are not interested in that phase.
    # Run for 0.3 seconds then check if isGathering has completed.
    runtime = 0
    maxruntime = 20
    while query.isGathering() and runtime <= maxruntime:
        runtime += 0.3
        NSRunLoop.currentRunLoop(
            ).runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.3))
    query.stopQuery()

    if runtime >= maxruntime:
        display.display_warning(
            'Spotlight search for applications terminated due to excessive '
            'time. Possible causes: Spotlight indexing is turned off for a '
            'volume; Spotlight is reindexing a volume.')

    for item in query.results():
        pathname = item.valueForAttribute_('kMDItemPath')
        if pathname and not is_excluded_filesystem(pathname):
            applist.append(pathname)

    return applist


def spotlight_installed_apps():
    """Get paths of currently installed applications per Spotlight.
    Return value is list of paths.
    Excludes most non-boot volumes.
    In future may include local r/w volumes.
    """
    dirlist = []
    applist = []

    for filename in osutils.listdir(u'/'):
        pathname = os.path.join(u'/', filename)
        if (os.path.isdir(pathname) and not os.path.islink(pathname) and
                not is_excluded_filesystem(pathname)):
            if filename.endswith('.app'):
                applist.append(pathname)
            else:
                dirlist.append(pathname)

    # Future code changes may mean we wish to look for Applications
    # installed on any r/w local volume.
    #for f in osutils.listdir(u'/Volumes'):
    #    p = os.path.join(u'/Volumes', f)
    #    if os.path.isdir(p) and not os.path.islink(p) \
    #                        and not is_excluded_filesystem(p):
    #        dirlist.append(p)

    # /Users is not currently excluded, so no need to add /Users/Shared.
    #dirlist.append(u'/Users/Shared')

    applist.extend(find_apps_in_dirs(dirlist))
    return applist


def launchservices_installed_apps():
    """Get paths of currently installed applications per LaunchServices.
    Return value is list of paths.
    Ignores apps installed on other volumes
    """
    # PyLint cannot properly find names inside Cocoa libraries, so issues bogus
    # "Module 'Foo' has no 'Bar' member" warnings. Disable them.
    # pylint: disable=E1101
    # we access a "protected" function from LaunchServices
    # pylint: disable=W0212

    apps = LaunchServices._LSCopyAllApplicationURLs(None) or []
    applist = []
    for app in apps:
        app_path = app.path()
        if (app_path and not is_excluded_filesystem(app_path) and
                os.path.exists(app_path)):
            applist.append(app_path)

    return applist


@utils.Memoize
def sp_application_data():
    '''Uses system profiler to get application info for this machine'''
    cmd = ['/usr/sbin/system_profiler', 'SPApplicationsDataType', '-xml']
    # uses our internal Popen instead of subprocess's so we can timeout
    proc = Popen(cmd, shell=False, bufsize=-1,
                 stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                 stderr=subprocess.PIPE)
    try:
        output, dummy_error = proc.communicate(timeout=60)
    except TimeoutError:
        display.display_error(
            'system_profiler hung; skipping SPApplicationsDataType query')
        # return empty dict
        return {}
    try:
        plist = FoundationPlist.readPlistFromString(output)
        # system_profiler xml is an array
        application_data = {}
        for item in plist[0]['_items']:
            application_data[item.get('path')] = item
    except BaseException:
        application_data = {}
    return application_data


@utils.Memoize
def app_data():
    """Gets info on currently installed apps.
    Returns a list of dicts containing path, name, version and bundleid"""
    application_data = []
    display.display_debug1(
        'Getting info on currently installed applications...')
    applist = set(launchservices_installed_apps())
    applist.update(spotlight_installed_apps())
    for pathname in applist:
        iteminfo = {}
        iteminfo['name'] = os.path.splitext(os.path.basename(pathname))[0]
        iteminfo['path'] = pathname
        plistpath = os.path.join(pathname, 'Contents', 'Info.plist')
        if os.path.exists(plistpath):
            try:
                plist = FoundationPlist.readPlist(plistpath)
                iteminfo['bundleid'] = plist.get('CFBundleIdentifier', '')
                if 'CFBundleName' in plist:
                    iteminfo['name'] = plist['CFBundleName']
                iteminfo['version'] = pkgutils.getBundleVersion(pathname)
                application_data.append(iteminfo)
            except BaseException:
                pass
        else:
            # possibly a non-bundle app. Use system_profiler data
            # to get app name and version
            sp_app_data = sp_application_data()
            if pathname in sp_app_data:
                item = sp_app_data[pathname]
                iteminfo['bundleid'] = ''
                iteminfo['version'] = item.get('version') or '0.0.0.0.0'
                if item.get('_name'):
                    iteminfo['name'] = item['_name']
                application_data.append(iteminfo)
    return application_data


@utils.Memoize
def filtered_app_data():
    '''Returns a filtered version of app_data, filtering out apps in user
    home directories for use by compare.compare_application_version()'''
    return [item for item in app_data()
            if not (item['path'].startswith('/Users/') and
                    not item['path'].startswith('/Users/Shared/'))]


@utils.Memoize
def get_version():
    """Returns version of munkitools, reading version.plist"""
    vers = "UNKNOWN"
    build = ""
    # find the munkilib directory, and the version file
    munkilibdir = os.path.dirname(os.path.abspath(__file__))
    versionfile = os.path.join(munkilibdir, "version.plist")
    if os.path.exists(versionfile):
        try:
            vers_plist = FoundationPlist.readPlist(versionfile)
        except FoundationPlist.NSPropertyListSerializationException:
            pass
        else:
            try:
                vers = vers_plist['CFBundleShortVersionString']
                build = vers_plist['BuildNumber']
            except KeyError:
                pass
    if build:
        vers = vers + "." + build
    return vers


def get_sp_data(data_type):
    '''Uses system profiler to get info of data_type for this machine'''
    cmd = ['/usr/sbin/system_profiler', data_type, '-xml']
    proc = subprocess.Popen(cmd, shell=False, bufsize=-1,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output = proc.communicate()[0]
    try:
        plist = FoundationPlist.readPlistFromString(output)
        # system_profiler xml is an array
        sp_dict = plist[0]
        items = sp_dict['_items']
        sp_items_dict = items[0]
        return sp_items_dict
    except BaseException:
        return {}


def get_hardware_info():
    '''Uses system profiler to get hardware info for this machine'''
    return get_sp_data('SPHardwareDataType')


def get_ibridge_info():
    '''Uses system profiler to get iBridge info for this machine'''
    return get_sp_data('SPiBridgeDataType')


def get_ip_addresses(kind):
    '''Uses system profiler to get active IP addresses for this machine
    kind must be one of 'IPv4' or 'IPv6' '''
    ip_addresses = []
    cmd = ['/usr/sbin/system_profiler', 'SPNetworkDataType', '-xml']
    proc = subprocess.Popen(cmd, shell=False, bufsize=-1,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output = proc.communicate()[0]
    try:
        plist = FoundationPlist.readPlistFromString(output)
        # system_profiler xml is an array of length 1
        sp_dict = plist[0]
        items = sp_dict['_items']
    except BaseException:
        # something is wrong with system_profiler output
        # so bail
        return ip_addresses

    for item in items:
        try:
            ip_addresses.extend(item[kind]['Addresses'])
        except KeyError:
            # 'IPv4", 'IPv6' or 'Addresses' is empty, so we ignore
            # this item
            pass
    return ip_addresses


def get_serial_number():
    """Returns the serial number of this Mac _without_ calling system_profiler."""
    # Borrowed with love from
    # https://github.com/chilcote/unearth/blob/master/artifacts/serial_number.py
    # thanks, Joe!
    IOKit_bundle = NSBundle.bundleWithIdentifier_("com.apple.framework.IOKit")

    functions = [
        ("IOServiceGetMatchingService", b"II@"),
        ("IOServiceMatching", b"@*"),
        ("IORegistryEntryCreateCFProperty", b"@I@@I"),
    ]
    objc.loadBundleFunctions(IOKit_bundle, globals(), functions)

    kIOMasterPortDefault = 0
    kIOPlatformSerialNumberKey = "IOPlatformSerialNumber"
    kCFAllocatorDefault = None

    platformExpert = IOServiceGetMatchingService(
        kIOMasterPortDefault, IOServiceMatching(b"IOPlatformExpertDevice")
    )
    serial = IORegistryEntryCreateCFProperty(
        platformExpert, kIOPlatformSerialNumberKey, kCFAllocatorDefault, 0
    )

    return serial

def product_name():
    """Returns the product name from IORegistry"""
    IOKit_bundle = NSBundle.bundleWithIdentifier_("com.apple.framework.IOKit")

    functions = [
        ("IOServiceGetMatchingService", b"II@"),
        ("IOServiceNameMatching", b"@*"),
        ("IORegistryEntryCreateCFProperty", b"@I@@I"),
    ]
    objc.loadBundleFunctions(IOKit_bundle, globals(), functions)

    kIOMasterPortDefault = 0
    kCFAllocatorDefault = None

    product = IOServiceGetMatchingService(
        kIOMasterPortDefault, IOServiceNameMatching(b"product")
    )
    product_name_data = IORegistryEntryCreateCFProperty(
        product, "product-name", kCFAllocatorDefault, 0
    )

    if product_name_data:
        return NSString.alloc().initWithData_encoding_(product_name_data[0:-1], NSUTF8StringEncoding)
    else:
        return None

def hardware_model():
    libc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("c"))

    size = ctypes.c_size_t()
    buf = ctypes.c_int()
    size.value = ctypes.sizeof(buf)

    libc.sysctlbyname(
        b"hw.model", None, ctypes.byref(size), None, 0)
    buf = ctypes.create_string_buffer(size.value)
    libc.sysctlbyname(
        b"hw.model", ctypes.byref(buf), ctypes.byref(size), None, 0)
    return buf.value.decode("utf-8")


def has_intel64support():
    """Does this machine support 64-bit Intel instruction set?"""
    libc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("c"))

    size = ctypes.c_size_t()
    buf = ctypes.c_int()
    size.value = ctypes.sizeof(buf)

    libc.sysctlbyname(
        b"hw.optional.x86_64", ctypes.byref(buf), ctypes.byref(size), None, 0)

    return buf.value == 1

def available_disk_space(volumepath='/'):
    """Returns available diskspace in KBytes.

    Args:
      volumepath: str, optional, default '/'
    Returns:
      int, KBytes in free space available
    """
    if volumepath is None:
        volumepath = '/'
    try:
        stat_val = os.statvfs(volumepath)
    except OSError as err:
        display.display_error(
            'Error getting disk space in %s: %s', volumepath, str(err))
        return 0
     # f_bavail matches df(1) output
    return int(stat_val.f_frsize * stat_val.f_bavail / 1024) # pylint: disable=old-division


def get_os_build():
    '''Returns the OS Build "number" (example 16G1212).'''
    try:
        system_version_plist = FoundationPlist.readPlist(
            '/System/Library/CoreServices/SystemVersion.plist')
        return system_version_plist['ProductBuildVersion']
    except (FoundationPlist.FoundationPlistException, KeyError, AttributeError):
        return ''


@utils.Memoize
def getMachineFacts():
    """Gets some facts about this machine we use to determine if a given
    installer is applicable to this OS or hardware"""
    # pylint: disable=C0103
    machine = dict()
    machine['hostname'] = unicode_or_str(os.uname()[1])
    arch = os.uname()[4]
    if arch == 'x86_64':
        # we might be natively Intel64, or running under Rosetta.
        # os.uname()[4] returns the current execution arch, which under Rosetta
        # will be x86_64. Since what we want here is the _native_ arch, we're
        # going to use a hack for now to see if we're natively arm64
        uname_version = os.uname()[3]
        if 'ARM64' in uname_version:
            arch = 'arm64'
    machine['arch'] = arch
    machine['os_vers'] = osutils.getOsVersion(only_major_minor=False)
    machine['os_build_number'] = get_os_build()
    machine['machine_model'] = hardware_model() or 'UNKNOWN'
    machine['munki_version'] = get_version()
    machine['ipv4_address'] = get_ip_addresses('IPv4')
    machine['ipv6_address'] = get_ip_addresses('IPv6')
    machine['serial_number'] = get_serial_number() or 'UNKNOWN'
    machine['product_name'] = product_name() or 'Intel Mac'
    ibridge_info = get_ibridge_info()
    machine['ibridge_model_name'] = ibridge_info.get(
        'ibridge_model_name', 'NO IBRIDGE CHIP')
    if machine['arch'] == 'x86_64':
        machine['x86_64_capable'] = True
    elif machine['arch'] == 'i386':
        machine['x86_64_capable'] = has_intel64support()
    return machine


def valid_plist(path):
    """Uses plutil to determine if path contains a valid plist.
    Returns True or False."""
    retcode = subprocess.call(['/usr/bin/plutil', '-lint', '-s', path])
    return retcode == 0


@utils.Memoize
def get_conditions():
    """Fetches key/value pairs from condition scripts
    which can be placed into /usr/local/munki/conditions"""
    # define path to conditions directory which would contain
    # admin created scripts
    scriptdir = os.path.realpath(os.path.dirname(sys.argv[0]))
    conditionalscriptdir = os.path.join(scriptdir, "conditions")
    # define path to ConditionalItems.plist
    conditionalitemspath = os.path.join(
        prefs.pref('ManagedInstallDir'), 'ConditionalItems.plist')
    try:
        # delete CondtionalItems.plist so that we're starting fresh
        os.unlink(conditionalitemspath)
    except (OSError, IOError):
        pass
    if os.path.exists(conditionalscriptdir):
        for conditionalscript in sorted(osutils.listdir(conditionalscriptdir)):
            if conditionalscript.startswith('.'):
                # skip files that start with a period
                continue
            conditionalscriptpath = os.path.join(
                conditionalscriptdir, conditionalscript)
            if os.path.isdir(conditionalscriptpath):
                # skip directories in conditions directory
                continue
            try:
                # attempt to execute condition script
                dummy_result, dummy_stdout, dummy_stderr = (
                    utils.runExternalScript(conditionalscriptpath))
            except utils.ScriptNotFoundError:
                pass  # script is not required, so pass
            except utils.RunExternalScriptError as err:
                print(unicode_or_str(err), file=sys.stderr)
    else:
        # /usr/local/munki/conditions does not exist
        pass
    if (os.path.exists(conditionalitemspath) and
            valid_plist(conditionalitemspath)):
        # import conditions into conditions dict
        conditions = FoundationPlist.readPlist(conditionalitemspath)
        os.unlink(conditionalitemspath)
    else:
        # either ConditionalItems.plist does not exist
        # or does not pass validation
        conditions = {}
    return conditions


def saveappdata():
    """Save installed application data"""
    # data from app_data() is meant for use by updatecheck
    # we need to massage it a bit for more general usage
    munkilog.log('Saving application inventory...')
    app_inventory = []
    for item in app_data():
        inventory_item = {}
        inventory_item['CFBundleName'] = item.get('name')
        inventory_item['bundleid'] = item.get('bundleid')
        inventory_item['version'] = item.get('version')
        inventory_item['path'] = item.get('path', '')
        # use last path item (minus '.app' if present) as name
        inventory_item['name'] = \
            os.path.splitext(os.path.basename(inventory_item['path']))[0]
        app_inventory.append(inventory_item)
    try:
        FoundationPlist.writePlist(
            app_inventory,
            os.path.join(
                prefs.pref('ManagedInstallDir'), 'ApplicationInventory.plist'))
    except FoundationPlist.NSPropertyListSerializationException as err:
        display.display_warning(
            'Unable to save inventory report: %s' % err)


# conditional/predicate info functions
def subtract_tzoffset_from_date(the_date):
    """Input: NSDate object
    Output: NSDate object with same date and time as the UTC.
    In Los Angeles (PDT), '2011-06-20T12:00:00Z' becomes
    '2011-06-20 12:00:00 -0700'.
    In New York (EDT), it becomes '2011-06-20 12:00:00 -0400'.
    This allows a pkginfo item to reference a time in UTC that
    gets translated to the same relative local time.
    A force_install_after_date for '2011-06-20T12:00:00Z' will happen
    after 2011-06-20 12:00:00 local time.
    """
    # find our time zone offset in seconds
    timezone = NSTimeZone.defaultTimeZone()
    seconds_offset = timezone.secondsFromGMTForDate_(the_date)
    # return new NSDate minus local_offset
    return NSDate.alloc(
        ).initWithTimeInterval_sinceDate_(-seconds_offset, the_date)


def add_tzoffset_to_date(the_date):
    """Input: NSDate object
    Output: NSDate object with timezone difference added
    to the date. This allows conditional_item conditions to
    be written like so:

    <Key>condition</key>
    <string>date > CAST("2012-12-17T16:00:00Z", "NSDate")</string>

    with the intent being that the comparison is against local time.

    """
    # find our time zone offset in seconds
    timezone = NSTimeZone.defaultTimeZone()
    seconds_offset = timezone.secondsFromGMTForDate_(the_date)
    # return new NSDate minus local_offset
    return NSDate.alloc(
        ).initWithTimeInterval_sinceDate_(seconds_offset, the_date)


@utils.Memoize
def predicate_info_object():
    '''Returns our info object used for predicate comparisons'''
    info_object = {}
    machine = getMachineFacts()
    info_object.update(machine)
    info_object.update(get_conditions())
    # use our start time for "current" date (if we have it)
    # and add the timezone offset to it so we can compare
    # UTC dates as though they were local dates.
    info_object['date'] = add_tzoffset_to_date(
        NSDate.dateWithString_(
            reports.report.get('StartTime', reports.format_time())))
    # split os version into components for easier predicate comparison
    os_vers = machine['os_vers']
    os_vers = os_vers + '.0.0'
    info_object['os_vers_major'] = int(os_vers.split('.')[0])
    info_object['os_vers_minor'] = int(os_vers.split('.')[1])
    info_object['os_vers_patch'] = int(os_vers.split('.')[2])
    # get last build number component for easier predicate comparison
    build = machine['os_build_number']
    info_object['os_build_last_component'] = pkgutils.MunkiLooseVersion(
        build).version[-1]
    if powermgr.hasInternalBattery():
        info_object['machine_type'] = 'laptop'
    else:
        info_object['machine_type'] = 'desktop'
    return info_object


def predicate_evaluates_as_true(predicate_string, additional_info=None):
    '''Evaluates predicate against our info object'''
    display.display_debug1('Evaluating predicate: %s', predicate_string)
    info_object = predicate_info_object()
    if isinstance(additional_info, dict):
        info_object.update(additional_info)
    try:
        predicate = NSPredicate.predicateWithFormat_(predicate_string)
    except BaseException as err:
        display.display_warning('%s', err)
        # can't parse predicate, so return False
        return False

    result = predicate.evaluateWithObject_(info_object)
    display.display_debug1('Predicate %s is %s', predicate_string, result)
    return result


if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
