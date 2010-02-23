# encoding: utf-8
#
#  munki.py
#  Managed Software Update
#
#  Created by Greg Neagle on 2/11/10.
#  Copyright 2009-2010 Greg Neagle.
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
import time

from Foundation import NSDate
from ScriptingBridge import SBApplication

_updatechecklaunchfile = "/private/tmp/.com.googlecode.munki.updatecheck.launchd"
_MunkiStatusIdentifier = "com.googlecode.munki.MunkiStatus"

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
    cmd = ["/usr/bin/touch", _updatechecklaunchfile]
    if subprocess.call(cmd):
        return -1
    else:
        for i in range(7):
            time.sleep(1)
            # check to see if we were successful in starting the update
            result = updateInProgress()
            if result == 1:
                return 1
            else:
                # try again
                pass
        if result == -1:
            try:
                # this might fail if we don't own it
                os.unlink(_updatechecklaunchfile)
            except:
                pass
        return result
       

def updateInProgress():
    # if MunkiStatus is running, we're doing an update right now
    MunkiStatus = SBApplication.applicationWithBundleIdentifier_(_MunkiStatusIdentifier)
    if MunkiStatus and MunkiStatus.isRunning():
        # bring it back to the front
        MunkiStatus.activate()
        return 1
    elif os.path.exists(_updatechecklaunchfile):
        # we tried to trigger the update, but it failed?
        return -1
    else:
        return 0
    
    
def checkForUpdates():
    # returns 1 if we've kicked off an update check (or one is in progress),
    # returns 0 if we're not going to check (because we just did)
    # returns -1 if the munki server is unavailable
    # returns -2 if there's an unexpected problem
    
    # are we checking right now (MunkiStatus.app is running)?
    update = updateInProgress()
    if update == 1:
        return 1
    elif update == -1:
        return -2
    
    # when did we last check?
    now = NSDate.new()
    prefs = getManagedInstallsPrefs()
    lastCheckedDateString = prefs.get("LastCheckDate")
    if lastCheckedDateString:
        lastCheckedDate = NSDate.dateWithString_(lastCheckedDateString)
    if (not lastCheckedDateString) or now.timeIntervalSinceDate_(lastCheckedDate) > 10:
        # we haven't checked in more than 10 seconds
        result = startUpdateCheck()
        if result == 1:
            return 1
        else:
            return -2
    else:
        # we just finished checking
        lastCheckResult = prefs.get("LastCheckResult")
        if lastCheckResult == -1:
            # check failed
            return -1
        else:
            return 0

    

def getAppleUpdates():
    prefs = getManagedInstallsPrefs()
    managedinstallbase = prefs['ManagedInstallDir']
    pl = {}
    appleUpdatesFile = os.path.join(managedinstallbase, 'AppleUpdates.plist')
    if os.path.exists(appleUpdatesFile):
        try:
            pl = FoundationPlist.readPlist(appleUpdatesFile)
        except FoundationPlist.NSPropertyListSerializationException:
            pass
    return pl
    
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
        
    p = subprocess.Popen(cmd, bufsize=1, stdout=subprocess.PIPE, 
                                stderr=subprocess.PIPE)
    (output, err) = p.communicate()

    

def logoutAndUpdate():
    # touch a flag so the process that runs after
	# logout knows it's OK to install everything
    cmd = ["/usr/bin/touch",  "/private/tmp/com.googlecode.munki.installatlogout"]
    result = subprocess.call(cmd)
    if result == 0:
        logoutNow()
    else:
        return result


def justUpdate():
    # trigger managedinstaller via launchd KeepAlive path trigger
    # we touch a file that launchd is is watching
    # launchd, in turn, launches managedsoftwareupdate --installwithnologout as root
    cmd = ["/usr/bin/touch",  "/private/tmp/.com.googlecode.munki.managedinstall.launchd"]
    return subprocess.call(cmd)
        



