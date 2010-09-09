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

UPDATECHECKLAUNCHFILE = \
    "/private/tmp/.com.googlecode.munki.updatecheck.launchd"

def call(cmd):
    '''Convenience function; works around an issue with subprocess.call
    in PyObjC in Snow Leopard'''
    proc = subprocess.Popen(cmd, bufsize=1, stdout=subprocess.PIPE, 
                                stderr=subprocess.PIPE)
    (output, err) = proc.communicate()
    return proc.returncode


def getManagedInstallsPrefs():
    '''Define default preference values; 
    Read preference values from ManagedInstalls.plist if it exists.'''
    
    prefs = {}
    prefs['ManagedInstallDir'] = "/Library/Managed Installs"
    prefs['InstallAppleSoftwareUpdates'] = False
    prefs['ShowRemovalDetail'] = False
    prefs['InstallRequiresLogout'] = False
        
    prefsfile = "/Library/Preferences/ManagedInstalls.plist"
    if os.path.exists(prefsfile):
        try:
            plist = FoundationPlist.readPlist(prefsfile)
        except FoundationPlist.NSPropertyListSerializationException:
            return prefs
        try:
            for key in plist.keys():
                if type(plist[key]).__name__ == "__NSCFDate":
                    # convert NSDate/CFDates to strings
                    prefs[key] = str(plist[key])
                else:
                    prefs[key] = plist[key]
        except AttributeError:
            pass
                        
    return prefs
    
    
def readSelfServiceManifest():
    '''Read the SelfServeManifest if it exists'''
    # read our working copy if it exists
    SelfServeManifest = "/Users/Shared/.SelfServeManifest"
    if not os.path.exists(SelfServeManifest):
        # no working copy, look for system copy
        prefs = getManagedInstallsPrefs()
        managedinstallbase = prefs['ManagedInstallDir']
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
    return getManagedInstallsPrefs().get('ShowRemovalDetail', False)
    
def installRequiresLogout():
    '''Returns preference to force logout for all installs'''
    return getManagedInstallsPrefs().get('InstallRequiresLogout', False)


def getInstallInfo():
    '''Returns the dictionary describing the managed installs and removals'''
    prefs = getManagedInstallsPrefs()
    managedinstallbase = prefs['ManagedInstallDir']
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
    prefs = getManagedInstallsPrefs()
    managedinstallbase = prefs['ManagedInstallDir']
    plist = {}
    appleUpdatesFile = os.path.join(managedinstallbase, 'AppleUpdates.plist')
    if (os.path.exists(appleUpdatesFile) and 
            prefs['InstallAppleSoftwareUpdates']):
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
    
def trimVersionString(versString, tupleCount):
    '''Trims the version string to no more than tupleCount parts'''
    if versString == None or versString == "":
        return ""
    components = str(versString).split(".")
    if len(components) > tupleCount:
        components = components[0:tupleCount]
    return ".".join(components)

    
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
        



