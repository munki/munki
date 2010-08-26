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

import os
import subprocess
import FoundationPlist

_updatechecklaunchfile = "/private/tmp/.com.googlecode.munki.updatecheck.launchd"

def call(cmd):
    # convenience function; works around an issue with subprocess.call
    # in PyObjC in Snow Leopard
    p = subprocess.Popen(cmd, bufsize=1, stdout=subprocess.PIPE, 
                                stderr=subprocess.PIPE)
    (output, err) = p.communicate()
    return p.returncode


def getManagedInstallsPrefs():
    # define default values
    prefs = {}
    prefs['ManagedInstallDir'] = "/Library/Managed Installs"
    prefs['InstallAppleSoftwareUpdates'] = False
    prefs['ShowRemovalDetail'] = False
    prefs['InstallRequiresLogout'] = False
        
    prefsfile = "/Library/Preferences/ManagedInstalls.plist"
    pl = {}
    if os.path.exists(prefsfile):
        try:
            pl = FoundationPlist.readPlist(prefsfile)
        except FoundationPlist.NSPropertyListSerializationException:
            pass
        try:
            for key in pl.keys():
                if type(pl[key]).__name__ == "__NSCFDate":
                    # convert NSDate/CFDates to strings
                    prefs[key] = str(pl[key])
                else:
                    prefs[key] = pl[key]
        except AttributeError:
            pass
                        
    return prefs
    
def writeSelfServiceManifest(optional_install_choices):
    usermanifest = "/Users/Shared/.SelfServeManifest"
    try:
        FoundationPlist.writePlist(optional_install_choices, usermanifest)
    except:
        pass
    
def getRemovalDetailPrefs():
    return getManagedInstallsPrefs().get('ShowRemovalDetail', False)
    
def installRequiresLogout():
    return getManagedInstallsPrefs().get('InstallRequiresLogout', False)


def getInstallInfo():
    prefs = getManagedInstallsPrefs()
    managedinstallbase = prefs['ManagedInstallDir']
    pl = {}
    installinfo = os.path.join(managedinstallbase, 'InstallInfo.plist')
    if os.path.exists(installinfo):
        try:
            pl = FoundationPlist.readPlist(installinfo)
        except FoundationPlist.NSPropertyListSerializationException:
            pass
    return pl
    

def startUpdateCheck():
    # does launchd magic to run managedsoftwareupdate as root
    result = call(["/usr/bin/touch", _updatechecklaunchfile])
    return result
    

def getAppleUpdates():
    prefs = getManagedInstallsPrefs()
    managedinstallbase = prefs['ManagedInstallDir']
    pl = {}
    appleUpdatesFile = os.path.join(managedinstallbase, 'AppleUpdates.plist')
    if os.path.exists(appleUpdatesFile) and prefs['InstallAppleSoftwareUpdates']:
        try:
            pl = FoundationPlist.readPlist(appleUpdatesFile)
        except FoundationPlist.NSPropertyListSerializationException:
            pass
    return pl
    
def humanReadable(kbytes):
    """Returns sizes in human-readable units."""
    units = [(" KB",2**10), (" MB",2**20), (" GB",2**30), (" TB",2**40)] 
    for suffix, limit in units:
        if kbytes > limit:
            continue
        else:
            return str(round(kbytes/float(limit/2**10),1))+suffix
    
def trimVersionString(versString,tupleCount):
    if versString == None or versString == "":
        return ""
    components = str(versString).split(".")
    if len(components) > tupleCount:
        components = components[0:tupleCount]
    return ".".join(components)

def currentGUIusers():
    '''Gets a list of GUI users by parsing the output of /usr/bin/who'''
    gui_users = []
    p = subprocess.Popen("/usr/bin/who", shell=False, stdin=subprocess.PIPE, 
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (output, err) = p.communicate()
    lines = output.splitlines()
    for line in lines:
        if "console" in line:
            parts = line.split()
            gui_users.append(parts[0])

    return gui_users
    
def logoutNow():
    # uses oscascript to run an AppleScript
    # to tell loginwindow to logout
    # ugly, but it works.
    
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
    # touch a flag so the process that runs after
	# logout knows it's OK to install everything
    cmd = ["/usr/bin/touch",  "/private/tmp/com.googlecode.munki.installatlogout"]
    result = call(cmd)
    if result == 0:
        logoutNow()
    else:
        return result


def justUpdate():
    # trigger managedinstaller via launchd KeepAlive path trigger
    # we touch a file that launchd is is watching
    # launchd, in turn, launches managedsoftwareupdate --installwithnologout as root
    cmd = ["/usr/bin/touch",  "/private/tmp/.com.googlecode.munki.managedinstall.launchd"]
    return call(cmd)
        



