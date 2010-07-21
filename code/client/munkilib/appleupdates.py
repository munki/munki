#!/usr/bin/env python
# encoding: utf-8
"""
appleupdates.py

Utilities for dealing with Apple Software Update.

"""
# Copyright 2009-2010 Greg Neagle.
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


import sys
import os
import stat
#import re
import subprocess
from xml.dom import minidom

from Foundation import NSDate

import FoundationPlist
import munkicommon
import munkistatus
import installer


oldsuserver = ''
def selectSoftwareUpdateServer():
    # switch to our preferred Software Update Server if supplied
    global oldsuserver
    if munkicommon.pref('SoftwareUpdateServerURL'):
        cmd = ['/usr/bin/defaults', 'read',
               '/Library/Preferences/com.apple.SoftwareUpdate', 'CatalogURL']
        p = subprocess.Popen(cmd, shell=False, bufsize=1,
                             stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, 
                             stderr=subprocess.PIPE)
        (out, err) = p.communicate()
        if p.returncode == 0:
            oldsusserver = out.rstrip('\n')
            
        cmd = ['/usr/bin/defaults', 'write',
               '/Library/Preferences/com.apple.SoftwareUpdate',
               'CatalogURL', munkicommon.pref('SoftwareUpdateServerURL')]
        retcode = subprocess.call(cmd)


def restoreSoftwareUpdateServer():
    # switch back to original Software Update server
    if munkicommon.pref('SoftwareUpdateServerURL'):
        if oldsuserver:
            cmd = ['/usr/bin/defaults', 'write',
                   '/Library/Preferences/com.apple.SoftwareUpdate',
                   'CatalogURL', oldsuserver]
        else:
            cmd = ['/usr/bin/defaults', 'delete',
                   '/Library/Preferences/com.apple.SoftwareUpdate', 
                   'CatalogURL']
        retcode = subprocess.call(cmd)
        
        
def setupSoftwareUpdateCheck():
    # set defaults for root user and current host
    cmd = ['/usr/bin/defaults', '-currentHost', 'write',
           'com.apple.SoftwareUpdate', 'AgreedToLicenseAgreement', 
           '-bool', 'YES']
    p = subprocess.Popen(cmd, bufsize=1, 
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out, err) = p.communicate()
    cmd = ['/usr/bin/defaults', '-currentHost', 'write',
           'com.apple.SoftwareUpdate', 'AutomaticDownload', 
           '-bool', 'YES']
    p = subprocess.Popen(cmd, bufsize=1, 
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out, err) = p.communicate()
    cmd = ['/usr/bin/defaults', '-currentHost', 'write',
           'com.apple.SoftwareUpdate', 'LaunchAppInBackground', 
           '-bool', 'YES']
    p = subprocess.Popen(cmd, bufsize=1, 
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out, err) = p.communicate()
    
    
def checkForSoftwareUpdates():
    # switch to a different SUS server if specified
    selectSoftwareUpdateServer()
    # get the OS version 
    osvers = int(os.uname()[2].split('.')[0])
    if osvers == 9:
        setupSoftwareUpdateCheck()
        softwareupdateapp = "/System/Library/CoreServices/Software Update.app"
        softwareupdatecheck = os.path.join(softwareupdateapp, 
                                "Contents/Resources/SoftwareUpdateCheck")
        
        # record mode of Software Update.app
        rawmode = os.stat(softwareupdateapp).st_mode
        oldmode = stat.S_IMODE(rawmode)
        
        # set mode of Software Update.app so it won't launch
        # yes, this is a hack.  So sue me.
        newmode = stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR
        os.chmod(softwareupdateapp, newmode)
        
        cmd = [ softwareupdatecheck ]
    elif osvers == 10:
        # in Snow Leopard we can just use /usr/sbin/softwareupdate, since it
        # now downloads updates the same way as SoftwareUpdateCheck
        cmd = ['/usr/sbin/softwareupdate', '-d', '-a']
    else:
        # unsupported os version
        return -1
       
    # now check for updates
    p = subprocess.Popen(cmd, shell=False, bufsize=1, stdin=subprocess.PIPE, 
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                         
    while True: 
        output = p.stdout.readline().decode('UTF-8')
        if munkicommon.munkistatusoutput:
            if munkistatus.getStopButtonState() == 1:
                os.kill(p.pid, 15) #15 is SIGTERM
                break
        if not output and (p.poll() != None):
            break
        # send the output to STDOUT or MunkiStatus as applicable
        munkicommon.display_status(output.rstrip('\n'))
    
    retcode = p.poll()
    if retcode:
        if osvers == 9:
            # there's always an error on Leopard
            # because we prevent the app from launching
            # so let's just ignore them
            retcode = 0
            
    if retcode == 0:      
        # get last result code
        cmd = ['/usr/bin/defaults', 'read',
               '/Library/Preferences/com.apple.SoftwareUpdate', 
               'LastResultCode']
        p = subprocess.Popen(cmd, shell=False, bufsize=1,
                             stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, 
                             stderr=subprocess.PIPE)
        (out, err) = p.communicate()
        if p.returncode == 0:
            try:
                LastResultCode = int(out.rstrip('\n'))
                if LastResultCode > 2:
                    retcode = LastResultCode
            except:
                retcode = 0
            
    if retcode:
        # there was an error
        munkicommon.display_error("softwareupdate error: %s" % retcode)
            
    if osvers == 9:
        # put mode back for Software Update.app
        os.chmod(softwareupdateapp, oldmode)
    
    # switch back to the original SUS server
    restoreSoftwareUpdateServer()
    return retcode
    
    
def parseDist(filename):
    '''Attempts to extract:
    SU_TITLE, SU_VERS, and SU_DESCRIPTION
    from a .dist file in a Software Update download.'''
    text = ""
    dom = minidom.parse(filename)
    gui_scripts = dom.getElementsByTagName("installer-gui-script")
    if gui_scripts:
        localizations = gui_scripts[0].getElementsByTagName("localization")
        if localizations:
            string_elements = localizations[0].getElementsByTagName("strings")
            if string_elements:
                strings = string_elements[0]
                if 'language' in strings.attributes.keys():
                    if strings.attributes['language'
                                             ].value.encode(
                                                        'UTF-8') == "English":
                        for node in strings.childNodes:
                            text += node.nodeValue
                            
    title = vers = description = ""
    keep = False
    for line in text.split('\n'):
        if line.startswith('"SU_TITLE"'):
            title = line[10:]
            title = title[title.find('"')+1:-2]
        if line.startswith('"SU_VERS"'):
            vers = line[9:]
            vers = vers[vers.find('"')+1:-2]
        if line.startswith('"SU_DESCRIPTION"'):
            keep = True
            # lop off "SU_DESCRIPTION"
            line = line[16:]
            # lop off everything up through '
            line = line[line.find("'")+1:]
            
        if keep:
            if line == "';":
                # we're done
                break
            else:
                # append the line to the description
                description += line + "\n"
                
    return title, vers, description
    

def getRestartInfo(installitemdir):
    # looks at all the RestartActions for all the items in the
    # directory and returns the highest weighted of:
    #   RequireRestart
    #   RecommendRestart
    #   RequireLogout
    #   RecommendLogout
    #   None
    
    weight = {}
    weight['RequireRestart'] = 4
    weight['RecommendRestart'] = 3
    weight['RequireLogout'] = 2
    weight['RecommendLogout'] = 1
    weight['None'] = 0
    
    restartAction = "None"
    for item in os.listdir(installitemdir):
        if item.endswith(".dist") or item.endswith(".pkg") or \
                item.endswith(".mpkg"):
            installeritem = os.path.join(installitemdir, item)

            p = subprocess.Popen(["/usr/sbin/installer",
                                  "-query", "RestartAction", 
                                  "-pkg", installeritem], 
                                  bufsize=1, 
                                  stdout=subprocess.PIPE, 
                                  stderr=subprocess.PIPE)
            (out, err) = p.communicate()
            if out:
                thisAction = out.rstrip('\n')
                if thisAction in weight.keys():
                    if weight[thisAction] > weight[restartAction]:
                        restartAction = thisAction
            
    return restartAction


def getSoftwareUpdateInfo():
    '''Parses the Software Update index.plist and the downloaded updates,
    extracting info in the format Munki expects. Returns an array of
    installeritems like those found in munki's InstallInfo.plist'''
    infoarray = []
    updatesdir = "/Library/Updates"
    updatesindex = os.path.join(updatesdir, "index.plist")
    if os.path.exists(updatesindex):
        pl = FoundationPlist.readPlist(updatesindex)
        if 'ProductPaths' in pl:
            products = pl['ProductPaths']
            for product_key in products.keys():
                updatename = products[product_key]
                installitem = os.path.join(updatesdir, updatename)
                if os.path.exists(installitem) and os.path.isdir(installitem):
                    for subitem in os.listdir(installitem):
                        if subitem.endswith('.dist'):
                            distfile = os.path.join(installitem, subitem)
                            (title, vers, description) = parseDist(distfile)
                            iteminfo = {}
                            iteminfo["installer_item"] = updatename
                            iteminfo["name"] = title
                            iteminfo["description"] = description
                            if iteminfo["description"] == '':
                                iteminfo["description"] = \
                                                "Updated Apple software."
                            iteminfo["version_to_install"] = vers
                            iteminfo['display_name'] = title
                            restartAction = getRestartInfo(installitem)
                            if restartAction != "None":
                                iteminfo['RestartAction'] = restartAction
                            
                            infoarray.append(iteminfo)
                            break

    return infoarray
    

def writeAppleUpdatesFile():
    '''Writes a file used by Managed Software Update.app to display
    available updates'''
    appleUpdates = getSoftwareUpdateInfo()
    if appleUpdates:
        pl = {}
        pl['AppleUpdates'] = appleUpdates
        FoundationPlist.writePlist(pl, appleUpdatesFile)
        return True
    else:
        try:
            os.unlink(appleUpdatesFile)
        except (OSError, IOError):
            pass
        return False


def appleSoftwareUpdatesAvailable(forcecheck=False, suppresscheck=False):
    '''Checks for available Apple Software Updates, trying not to hit the SUS
    more than needed'''
    # have we already processed the list of Apple Updates?
    updatesindexfile = '/Library/Updates/index.plist'
    if os.path.exists(appleUpdatesFile) and os.path.exists(updatesindexfile):
        appleUpdatesFile_modtime = os.stat(appleUpdatesFile).st_mtime
        updatesindexfile_modtime = os.stat(updatesindexfile).st_mtime
        if appleUpdatesFile_modtime > updatesindexfile_modtime:
            return True
        else:
            # updatesindexfile is newer, use it to generate a new
            # appleUpdatesFile
            return writeAppleUpdatesFile()
    
    if forcecheck:
        # typically because user initiated the check from
        # Managed Software Update.app
        retcode = checkForSoftwareUpdates()
    elif suppresscheck:
        # typically because we're doing a logout install; if
        # there are no waiting Apple Updates we shouldn't 
        # trigger a check for them
        return False
    else:
        # have we checked recently?  Don't want to check with
        # Apple Software Update server too frequently
        now = NSDate.new()
        nextSUcheck = now
        cmd = ['/usr/bin/defaults', 'read', 
               '/Library/Preferences/com.apple.softwareupdate',    
               'LastSuccessfulDate']
        p = subprocess.Popen(cmd, shell=False, bufsize=1, 
                             stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
        (out, err) = p.communicate()
        lastSUcheckString = out.rstrip('\n')
        if lastSUcheckString:
            try:
                lastSUcheck = NSDate.dateWithString_(lastSUcheckString)
                interval = 24 * 60 * 60
                nextSUcheck = lastSUcheck.dateByAddingTimeInterval_(interval)
            except ValueError:
                pass
        if now.timeIntervalSinceDate_(nextSUcheck) >= 0:
            retcode = checkForSoftwareUpdates()
        
    return writeAppleUpdatesFile()


def clearAppleUpdateInfo():
    '''Clears Apple update info. Called after performing munki updates
    because the Apple updates may no longer be relevant.'''
    updatesindexfile = '/Library/Updates/index.plist'
    try:
        os.unlink(updatesindexfile)
        os.unlink(appleUpdatesFile)
    except (OSError, IOError):
        pass


def installAppleUpdates():
    '''Uses /usr/sbin/installer to install updates previously
    downloaded. Some items downloaded by SoftwareUpdate are not
    installable by /usr/sbin/installer, so this approach may fail
    to install all downloaded updates'''

    restartneeded = False
    appleupdatelist = []
    # first check if appleUpdatesFile is current
    updatesindexfile = '/Library/Updates/index.plist'
    if os.path.exists(appleUpdatesFile) and os.path.exists(updatesindexfile):
        appleUpdatesFile_modtime = os.stat(appleUpdatesFile).st_mtime
        updatesindexfile_modtime = os.stat(updatesindexfile).st_mtime
        if appleUpdatesFile_modtime > updatesindexfile_modtime:
            try:
                pl = FoundationPlist.readPlist(appleUpdatesFile)
                appleupdatelist = pl['AppleUpdates']
            except FoundationPlist.NSPropertyListSerializationException:
                appleupdatelist = []
    if appleupdatelist == []:
        # we don't have any updates in appleUpdatesFile, 
        # or appleUpdatesFile is out-of-date, so check updatesindexfile
        appleupdatelist = getSoftwareUpdateInfo()
    
    # did we find some Apple updates?        
    if appleupdatelist:
        munkicommon.report['AppleUpdateList'] = appleupdatelist
        munkicommon.savereport()
        try:
            # once we start, we should remove /Library/Updates/index.plist
            # because it will point to items we've already installed
            os.unlink('/Library/Updates/index.plist')
            # remove the appleupdatesfile 
            # so Managed Software Update.app doesn't display these
            # updates again
            os.unlink(appleUpdatesFile)
        except (OSError, IOError):
            pass
        # now try to install the updates
        restartneeded = installer.installWithInfo("/Library/Updates",
                                                  appleupdatelist)
        if restartneeded:
            munkicommon.report['RestartRequired'] = True
        munkicommon.savereport()
    return restartneeded
    

# define this here so we can access it in multiple functions
appleUpdatesFile = os.path.join(munkicommon.pref('ManagedInstallDir'),
                                'AppleUpdates.plist')


def main():
    pass


if __name__ == '__main__':
	main()

