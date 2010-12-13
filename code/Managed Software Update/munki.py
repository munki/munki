# encoding: utf-8
#
#  munki.py
#  Managed Software Update
#
#  Created by Greg Neagle on 2/11/10.
#  Copyright 2010 Greg Neagle.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

'''munki-specific code for use with Managed Software Update'''

import os
import subprocess
import FoundationPlist
from Foundation import NSFileManager
from Foundation import CFPreferencesCopyAppValue


UPDATECHECKLAUNCHFILE = \
    "/private/tmp/.com.googlecode.munki.updatecheck.launchd"

def call(cmd):
    '''Convenience function; works around an issue with subprocess.call
    in PyObjC in Snow Leopard'''
    proc = subprocess.Popen(cmd, bufsize=1, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
    (output, err) = proc.communicate()
    return proc.returncode


BUNDLE_ID = 'ManagedInstalls'

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
        'ShowRemovalDetail': False,
        'InstallRequiresLogout': False
    }
    pref_value = CFPreferencesCopyAppValue(pref_name, BUNDLE_ID)
    if pref_value == None:
        pref_value = default_prefs.get(pref_name)
    if type(pref_value).__name__ == "__NSCFDate":
        # convert NSDate/CFDates to strings
        pref_value = str(pref_value)
    return pref_value


def readSelfServiceManifest():
    '''Read the SelfServeManifest if it exists'''
    # read our working copy if it exists
    SelfServeManifest = "/Users/Shared/.SelfServeManifest"
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
    so managedsoftwareupdate can use it'''
    usermanifest = "/Users/Shared/.SelfServeManifest"
    try:
        FoundationPlist.writePlist(optional_install_choices, usermanifest)
    except FoundationPlist.FoundationPlistException:
        pass


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


def startUpdateCheck():
    '''Does launchd magic to run managedsoftwareupdate as root.'''
    result = call(["/usr/bin/touch", UPDATECHECKLAUNCHFILE])
    return result


def getAppleUpdates():
    '''Returns any available Apple updates'''
    managedinstallbase = pref('ManagedInstallDir')
    plist = {}
    appleUpdatesFile = os.path.join(managedinstallbase, 'AppleUpdates.plist')
    if (os.path.exists(appleUpdatesFile) and
            pref('InstallAppleSoftwareUpdates')):
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
    if version_string == None or version_string == '':
        return ''
    version_parts = version_string.split('.')
    # strip off all trailing 0's in the version, while over 2 parts.
    while len(version_parts) > 2 and version_parts[-1] == '0':
        del(version_parts[-1])
    return '.'.join(version_parts)


def getconsoleuser():
    from SystemConfiguration import SCDynamicStoreCopyConsoleUser
    cfuser = SCDynamicStoreCopyConsoleUser( None, None, None )
    return cfuser[0]


def currentGUIusers():
    '''Gets a list of GUI users by parsing the output of /usr/bin/who'''
    gui_users = []
    proc = subprocess.Popen("/usr/bin/who", shell=False,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (output, err) = proc.communicate()
    lines = str(output).splitlines()
    for line in lines:
        if "console" in line:
            parts = line.split()
            gui_users.append(parts[0])

    return gui_users


def logoutNow():
    '''Uses oscascript to run an AppleScript
    to tell loginwindow to logout.
    Ugly, but it works.'''

    script = """
ignoring application responses
    tell application "loginwindow"
        «event aevtrlgo»
    end tell
end ignoring
"""
    cmd = ["/usr/bin/osascript"]
    for line in script.splitlines():
        line = line.rstrip().lstrip()
        if line:
            cmd.append("-e")
            cmd.append(line)
    result = call(cmd)


def logoutAndUpdate():
    '''Touch a flag so the process that runs after
    logout knows it's OK to install everything'''
    cmd = ["/usr/bin/touch",
           "/private/tmp/com.googlecode.munki.installatlogout"]
    result = call(cmd)
    if result == 0:
        logoutNow()
    else:
        return result


def justUpdate():
    '''Trigger managedinstaller via launchd KeepAlive path trigger
    We touch a file that launchd is is watching
    launchd, in turn,
    launches managedsoftwareupdate --installwithnologout as root'''
    cmd = ["/usr/bin/touch",
           "/private/tmp/.com.googlecode.munki.managedinstall.launchd"]
    return call(cmd)
    
    
def getRunningProcesses():
    """Returns a list of paths of running processes"""
    proc = subprocess.Popen(['/bin/ps', '-axo' 'comm='],
                            shell=False, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    (output, unused_err) = proc.communicate()
    if proc.returncode == 0:
        proc_list = [item for item in output.splitlines()
                     if item.startswith('/')]
        LaunchCFMApp = ('/System/Library/Frameworks/Carbon.framework'
                        '/Versions/A/Support/LaunchCFMApp')
        if LaunchCFMApp in proc_list:
            # we have a really old Carbon app
            proc = subprocess.Popen(['/bin/ps', '-axwwwo' 'args='],
                                    shell=False, stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)
            (output, unused_err) = proc.communicate()
            if proc.returncode == 0:
                carbon_apps = [item[len(LaunchCFMApp)+1:] 
                               for item in output.splitlines()
                               if item.startswith(LaunchCFMApp)]
                if carbon_apps:
                    proc_list.extend(carbon_apps)
        return proc_list
    else:
        return []


def getRunningBlockingApps(appnames):
    """Given a list of app names, return a list of friendly names
    for apps in the list that are running"""
    proc_list = getRunningProcesses()
    running_apps = []
    filemanager = NSFileManager.alloc().init()
    for appname in appnames:
        matching_items = []
        if appname.endswith('.app'):
            # search by filename
            matching_items = [item for item in proc_list
                              if '/'+ appname + '/' in item]
        else:
            # check executable name
            matching_items = [item for item in proc_list
                              if item.endswith('/' + appname)]

        if not matching_items:
            # try adding '.app' to the name and check again
            matching_items = [item for item in proc_list
                              if '/'+ appname + '.app/' in item]

        matching_items = set(matching_items)
        for path in matching_items:
            while '/Contents/' in path or path.endswith('/Contents'):
                path = os.path.dirname(path)
            # ask NSFileManager for localized name since end-users
            # will see this name
            running_apps.append(filemanager.displayNameAtPath_(path))

    return list(set(running_apps))




