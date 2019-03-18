# encoding: utf-8
#
#  munki.py
#  Managed Software Center
#
#  Created by Greg Neagle on 2/11/10.
#  Copyright 2010-2019 Greg Neagle.
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

'''munki-specific code for use with Managed Software Center'''

import os
import subprocess
import FoundationPlist

import objc

# PyLint cannot properly find names inside Cocoa libraries, so issues bogus
# No name 'Foo' in module 'Bar' warnings. Disable them.
# pylint: disable=E0611
from Foundation import NSTimeZone
from Foundation import NSBundle
from Foundation import NSDate
from Foundation import NSFileManager
from Foundation import CFPreferencesCopyAppValue
from Foundation import CFPreferencesAppSynchronize
from Foundation import NSDateFormatter
from Foundation import NSDateFormatterBehavior10_4
from Foundation import kCFDateFormatterLongStyle
from Foundation import kCFDateFormatterShortStyle
from SystemConfiguration import SCDynamicStoreCopyConsoleUser
# pylint: enable=E0611

# See http://michaellynn.github.io/2015/08/08/learn-you-a-better-pyobjc-bridgesupport-signature/
# for a primer on the bridging techniques used here
#

# https://developer.apple.com/documentation/iokit/iopowersources.h?language=objc
IOKit = NSBundle.bundleWithIdentifier_('com.apple.framework.IOKit')

functions = [("IOPSGetPowerSourceDescription", b"@@@"),
             ("IOPSCopyPowerSourcesInfo", b"@"),
             ("IOPSCopyPowerSourcesList", b"@@"),
             ("IOPSGetProvidingPowerSourceType", b"@@"),
            ]

# No idea why PyLint complains about objc.loadBundleFunctions
# pylint: disable=no-member
objc.loadBundleFunctions(IOKit, globals(), functions)
# pylint: enable=no-member

# Disable PyLint complaining about 'invalid' camelCase names
# pylint: disable=C0103


INSTALLATLOGOUTFILE = "/private/tmp/com.googlecode.munki.installatlogout"
UPDATECHECKLAUNCHFILE = \
    "/private/tmp/.com.googlecode.munki.updatecheck.launchd"
INSTALLWITHOUTLOGOUTFILE = \
    "/private/tmp/.com.googlecode.munki.managedinstall.launchd"

def call(cmd):
    '''Convenience function; works around an issue with subprocess.call
    in PyObjC in Snow Leopard'''
    proc = subprocess.Popen(cmd, bufsize=-1, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    _ = proc.communicate()
    return proc.returncode


def osascript(osastring):
    """Wrapper to run AppleScript commands"""
    cmd = ['/usr/bin/osascript', '-e', osastring]
    proc = subprocess.Popen(cmd, shell=False, bufsize=-1,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out, _) = proc.communicate()
    if proc.returncode != 0:
        return ''
    if out:
        return str(out).decode('UTF-8').rstrip('\n')


def restartNow():
    '''Trigger a restart'''
    osascript('tell application "System Events" to restart')


BUNDLE_ID = u'ManagedInstalls'

def reload_prefs():
    """Uses CFPreferencesAppSynchronize(BUNDLE_ID)
    to make sure we have the latest prefs. Call this
    if another process may have modified ManagedInstalls.plist,
    this needs to be run after returning from MunkiStatus"""
    CFPreferencesAppSynchronize(BUNDLE_ID)

DEFAULT_GUI_CACHE_AGE_SECS = 600

def pref(pref_name):
    """Return a preference. Since this uses CFPreferencesCopyAppValue,
    Preferences can be defined several places. Precedence is:
        - MCX
        - ~/Library/Preferences/ManagedInstalls.plist
        - /Library/Preferences/ManagedInstalls.plist
        - default_prefs defined here.
    """
    default_prefs = {
        'ManagedInstallDir': '/Library/Managed Installs',
        'InstallAppleSoftwareUpdates': False,
        'AppleSoftwareUpdatesOnly': False,
        'ShowRemovalDetail': False,
        'InstallRequiresLogout': False,
        'CheckResultsCacheSeconds': DEFAULT_GUI_CACHE_AGE_SECS,
    }
    pref_value = CFPreferencesCopyAppValue(pref_name, BUNDLE_ID)
    if pref_value is None:
        pref_value = default_prefs.get(pref_name)
    #if type(pref_value).__name__ in ['__NSCFDate', '__NSDate', '__CFDate']:
        # convert NSDate/CFDates to strings
        #pref_value = str(pref_value)
    return pref_value


WRITEABLE_SELF_SERVICE_MANIFEST_PATH = "/Users/Shared/.SelfServeManifest"

def readSelfServiceManifest():
    '''Read the SelfServeManifest if it exists'''
    # read our working copy if it exists
    SelfServeManifest = WRITEABLE_SELF_SERVICE_MANIFEST_PATH
    if not os.path.exists(SelfServeManifest):
        # no working copy, look for system copy
        managedinstallbase = pref('ManagedInstallDir')
        SelfServeManifest = os.path.join(managedinstallbase, "manifests",
                                         "SelfServeManifest")
    if os.path.exists(SelfServeManifest):
        try:
            return FoundationPlist.readPlist(SelfServeManifest)
        except FoundationPlist.NSPropertyListSerializationException:
            return {}
    else:
        return {}


def writeSelfServiceManifest(optional_install_choices):
    '''Write out our self-serve manifest
    so managedsoftwareupdate can use it. Returns True on success,
    False otherwise.'''
    usermanifest = WRITEABLE_SELF_SERVICE_MANIFEST_PATH
    try:
        FoundationPlist.writePlist(optional_install_choices, usermanifest)
        return True
    except FoundationPlist.FoundationPlistException:
        return False


def userSelfServiceChoicesChanged():
    '''Is WRITEABLE_SELF_SERVICE_MANIFEST_PATH different from
    the 'system' version of this file?'''
    if not os.path.exists(WRITEABLE_SELF_SERVICE_MANIFEST_PATH):
        return False
    user_choices = FoundationPlist.readPlist(
        WRITEABLE_SELF_SERVICE_MANIFEST_PATH)
    managedinstallbase = pref('ManagedInstallDir')
    system_path = os.path.join(managedinstallbase, "manifests",
                               "SelfServeManifest")
    if not os.path.exists(system_path):
        return True
    system_choices = FoundationPlist.readPlist(system_path)
    return user_choices != system_choices


def getRemovalDetailPrefs():
    '''Returns preference to control display of removal detail'''
    return pref('ShowRemovalDetail')


def installRequiresLogout():
    '''Returns preference to force logout for all installs'''
    return pref('InstallRequiresLogout')


def getInstallInfo():
    '''Returns the dictionary describing the managed installs and removals'''
    managedinstallbase = pref('ManagedInstallDir')
    plist = {}
    installinfo = os.path.join(managedinstallbase, 'InstallInfo.plist')
    if os.path.exists(installinfo):
        try:
            plist = FoundationPlist.readPlist(installinfo)
        except FoundationPlist.NSPropertyListSerializationException:
            pass
    return plist


def munkiUpdatesContainAppleItems():
    """Return True if there are any Apple items in the list of updates"""
    installinfo = getInstallInfo()
    # check managed_installs
    for item in installinfo.get('managed_installs', []):
        if item.get('apple_item'):
            return True
    # check removals
    for item in installinfo.get('removals', []):
        if item.get('apple_item'):
            return True
    return False


def thereAreUpdatesToBeForcedSoon(hours=72):
    '''Return True if any updates need to be installed within the next
    X hours, false otherwise'''
    installinfo = getInstallInfo().get('managed_installs', [])
    installinfo.extend(getAppleUpdates().get('AppleUpdates', []))

    if installinfo:
        now_xhours = NSDate.dateWithTimeIntervalSinceNow_(hours * 3600)
        for item in installinfo:
            force_install_after_date = item.get('force_install_after_date')
            if force_install_after_date:
                try:
                    force_install_after_date = discardTimeZoneFromDate(
                        force_install_after_date)
                    if now_xhours >= force_install_after_date:
                        return True
                except BadDateError:
                    # some issue with the stored date
                    pass
    return False


def earliestForceInstallDate(installinfo=None):
    """Check installable packages for force_install_after_dates
    Returns None or earliest force_install_after_date converted to local time
    """
    earliest_date = None

    if not installinfo:
        installinfo = getInstallInfo().get('managed_installs', [])
        installinfo.extend(getAppleUpdates().get('AppleUpdates', []))

    for install in installinfo:
        this_force_install_date = install.get('force_install_after_date')

        if this_force_install_date:
            try:
                this_force_install_date = discardTimeZoneFromDate(
                    this_force_install_date)
                if not earliest_date or this_force_install_date < earliest_date:
                    earliest_date = this_force_install_date
            except BadDateError:
                # some issue with the stored date
                pass
    return earliest_date


class BadDateError(Exception):
    '''Exception when transforming dates'''
    pass

def discardTimeZoneFromDate(the_date):
    """Input: NSDate object
    Output: NSDate object with same date and time as the UTC.
    In Los Angeles (PDT), '2011-06-20T12:00:00Z' becomes
    '2011-06-20 12:00:00 -0700'.
    In New York (EDT), it becomes '2011-06-20 12:00:00 -0400'.
    """
    # get local offset
    offset = NSTimeZone.localTimeZone().secondsFromGMT()
    try:
        # return new NSDate minus local_offset
        return the_date.dateByAddingTimeInterval_(-offset)
    except:
        raise BadDateError()


def stringFromDate(nsdate):
    """Input: NSDate object
    Output: unicode object, date and time formatted per system locale.
    """
    df = NSDateFormatter.alloc().init()
    df.setFormatterBehavior_(NSDateFormatterBehavior10_4)
    df.setDateStyle_(kCFDateFormatterLongStyle)
    df.setTimeStyle_(kCFDateFormatterShortStyle)
    return unicode(df.stringForObjectValue_(nsdate))


def shortRelativeStringFromDate(nsdate):
    """Input: NSDate object
    Output: unicode object, date and time formatted per system locale.
    """
    df = NSDateFormatter.alloc().init()
    df.setDateStyle_(kCFDateFormatterShortStyle)
    df.setTimeStyle_(kCFDateFormatterShortStyle)
    df.setDoesRelativeDateFormatting_(True)
    return unicode(df.stringFromDate_(nsdate))


def getAppleUpdates():
    '''Returns any available Apple updates'''
    managedinstallbase = pref('ManagedInstallDir')
    plist = {}
    appleUpdatesFile = os.path.join(managedinstallbase, 'AppleUpdates.plist')
    if (os.path.exists(appleUpdatesFile) and
            (pref('InstallAppleSoftwareUpdates') or
             pref('AppleSoftwareUpdatesOnly'))):
        try:
            plist = FoundationPlist.readPlist(appleUpdatesFile)
        except FoundationPlist.NSPropertyListSerializationException:
            pass
    return plist


def humanReadable(kbytes):
    """Returns sizes in human-readable units."""
    units = [(" KB", 2**10), (" MB", 2**20), (" GB", 2**30), (" TB", 2**40)]
    for suffix, limit in units:
        if kbytes > limit:
            continue
        else:
            return str(round(kbytes/float(limit/2**10), 1)) + suffix


def trimVersionString(version_string):
    """Trims all lone trailing zeros in the version string after major/minor.

    Examples:
      10.0.0.0 -> 10.0
      10.0.0.1 -> 10.0.0.1
      10.0.0-abc1 -> 10.0.0-abc1
      10.0.0-abc1.0 -> 10.0.0-abc1
    """
    if version_string is None or version_string == '':
        return ''
    version_parts = version_string.split('.')
    # strip off all trailing 0's in the version, while over 2 parts.
    while len(version_parts) > 2 and version_parts[-1] == '0':
        del version_parts[-1]
    return '.'.join(version_parts)


def getconsoleuser():
    '''Get current GUI user'''
    cfuser = SCDynamicStoreCopyConsoleUser(None, None, None)
    return cfuser[0]


def currentGUIusers():
    '''Gets a list of GUI users by parsing the output of /usr/bin/who'''
    gui_users = []
    proc = subprocess.Popen("/usr/bin/who", shell=False,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (output, _) = proc.communicate()
    lines = str(output).splitlines()
    for line in lines:
        if "console" in line:
            parts = line.split()
            gui_users.append(parts[0])

    # 10.11 sometimes has a phantom '_mbsetupuser' user. Filter it out.
    users_to_ignore = ['_mbsetupuser']
    gui_users = [user for user in gui_users if user not in users_to_ignore]

    return gui_users


class ProcessStartError(Exception):
    '''An exception to raise when we can't start managedsoftwareupdate'''
    pass


def startUpdateCheck(suppress_apple_update_check=False):
    '''Does launchd magic to run managedsoftwareupdate as root.'''
    try:
        if not os.path.exists(UPDATECHECKLAUNCHFILE):
            plist = {}
            plist['SuppressAppleUpdateCheck'] = suppress_apple_update_check
            try:
                FoundationPlist.writePlist(plist, UPDATECHECKLAUNCHFILE)
            except FoundationPlist.FoundationPlistException, err:
                # problem creating the trigger file
                raise ProcessStartError(err)
    except (OSError, IOError), err:
        raise ProcessStartError(err)


def logoutNow():
    '''Uses osascript to run an AppleScript
    to tell loginwindow to logout.
    Ugly, but it works.'''

    script = """
ignoring application responses
    tell application "loginwindow"
        «event aevtrlgo»
    end tell
end ignoring
"""
    cmd = ['/usr/bin/osascript', '-e', script]
    _ = call(cmd)


def logoutAndUpdate():
    '''Touch a flag so the process that runs after
    logout knows it's OK to install everything'''
    try:
        if not os.path.exists(INSTALLATLOGOUTFILE):
            open(INSTALLATLOGOUTFILE, 'w').close()
        logoutNow()
    except (OSError, IOError), err:
        raise ProcessStartError(err)


def clearLaunchTrigger():
    '''Clear the trigger file that fast-launches us at loginwindow.
    typically because we have been launched in statusmode at the
    loginwindow to perform a logout-install.'''
    try:
        if os.path.exists(INSTALLATLOGOUTFILE):
            os.unlink(INSTALLATLOGOUTFILE)
    except (OSError, IOError), err:
        raise ProcessStartError(err)


def justUpdate():
    '''Trigger managedinstaller via launchd KeepAlive path trigger
    We touch a file that launchd is is watching
    launchd, in turn,
    launches managedsoftwareupdate --installwithnologout as root'''
    try:
        if not os.path.exists(INSTALLWITHOUTLOGOUTFILE):
            open(INSTALLWITHOUTLOGOUTFILE, 'w').close()
    except (OSError, IOError), err:
        raise ProcessStartError(err)


def pythonScriptRunning(scriptname):
    """Returns Process ID for a running python script"""
    cmd = ['/bin/ps', '-eo', 'pid=,command=']
    proc = subprocess.Popen(cmd, shell=False, bufsize=1,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out, dummy_err) = proc.communicate()
    mypid = os.getpid()
    lines = str(out).splitlines()
    for line in lines:
        try:
            (pid, process) = line.split(None, 1)
        except ValueError:
            # funky process line, so we'll skip it
            pass
        else:
            args = process.split()
            try:
                # first look for Python processes
                if (args[0].find('MacOS/Python') != -1 or
                        args[0].find('python') != -1):
                    # look for first argument being scriptname
                    if args[1].find(scriptname) != -1:
                        try:
                            if int(pid) != int(mypid):
                                return pid
                        except ValueError:
                            # pid must have some funky characters
                            pass
            except IndexError:
                pass
    # if we get here we didn't find a Python script with scriptname
    # (other than ourselves)
    return 0


def getRunningProcessesWithUsers():
    """Returns a list of usernames and paths of running processes"""
    proc_list = []
    proc = subprocess.Popen(['/bin/ps', '-axo' 'user=,comm='],
                            shell=False, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    (output, dummy_err) = proc.communicate()
    if proc.returncode == 0:
        proc_lines = [item for item in output.splitlines()]
        LaunchCFMApp = ('/System/Library/Frameworks/Carbon.framework'
                        '/Versions/A/Support/LaunchCFMApp')
        saw_launch_cfmapp = False
        for line in proc_lines:
            # split into max two parts on whitespace
            parts = line.split(None, 1)
            if len(parts) > 1 and parts[1] == LaunchCFMApp:
                saw_launch_cfmapp = True
            elif len(parts) > 1:
                info = {'user': parts[0],
                        'pathname': parts[1]}
                proc_list.append(info)
        if saw_launch_cfmapp:
            # look at the process table again with different options
            # and get the arguments for LaunchCFMApp instances
            proc = subprocess.Popen(['/bin/ps', '-axo' 'user=,command='],
                                    shell=False, stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)
            (output, dummy_err) = proc.communicate()
            if proc.returncode == 0:
                proc_lines = [item for item in output.splitlines()]
                for line in proc_lines:
                    # split into max three parts on whitespace
                    parts = line.split(None, 2)
                    if len(parts) > 2 and parts[1] == LaunchCFMApp:
                        info = {'user': parts[0],
                                'pathname': parts[2]}
                        proc_list.append(info)
        return proc_list
    else:
        return []


def getRunningBlockingApps(appnames):
    """Given a list of app names, return a list of dicts for apps in the list
    that are running. Each dict contains username, pathname, display_name"""
    proc_list = getRunningProcessesWithUsers()
    running_apps = []
    filemanager = NSFileManager.alloc().init()
    for appname in appnames:
        matching_items = []
        if appname.startswith('/'):
            # search by exact path
            matching_items = [item for item in proc_list
                              if item['pathname'] == appname]
        elif appname.endswith('.app'):
            # search by filename
            matching_items = [
                item for item in proc_list
                if '/'+ appname + '/Contents/MacOS/' in item['pathname']]
        else:
            # check executable name
            matching_items = [item for item in proc_list
                              if item['pathname'].endswith('/' + appname)]

        if not matching_items:
            # try adding '.app' to the name and check again
            matching_items = [
                item for item in proc_list
                if '/' + appname + '.app/Contents/MacOS/' in item['pathname']]

        #matching_items = set(matching_items)
        for item in matching_items:
            path = item['pathname']
            while '/Contents/' in path or path.endswith('/Contents'):
                path = os.path.dirname(path)
            # ask NSFileManager for localized name since end-users
            # will see this name
            item['display_name'] = filemanager.displayNameAtPath_(path)
            running_apps.append(item)

    return running_apps


def onACPower():
    """Returns a boolean to indicate if the machine is on AC power"""
    # pylint: disable=undefined-variable
    power_source = IOPSGetProvidingPowerSourceType(IOPSCopyPowerSourcesInfo())
    # pylint: enable=undefined-variable
    return power_source == 'AC Power'


def onBatteryPower():
    """Returns a boolean to indicate if the machine is on battery power"""
    # pylint: disable=undefined-variable
    power_source = IOPSGetProvidingPowerSourceType(IOPSCopyPowerSourcesInfo())
    # pylint: enable=undefined-variable
    return power_source == 'Battery Power'


def getBatteryPercentage():
    """Returns battery charge percentage"""
    # pylint: disable=undefined-variable
    ps_blob = IOPSCopyPowerSourcesInfo()
    power_sources = IOPSCopyPowerSourcesList(ps_blob)
    for source in power_sources:
        description = IOPSGetPowerSourceDescription(ps_blob, source)
        if description.get('Type') == 'InternalBattery':
            return description.get('Current Capacity', 0)
    return 0
