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


import os
import stat
import subprocess
from xml.dom import minidom

from Foundation import NSDate

import FoundationPlist
import munkicommon
import munkistatus
import installer


def softwareUpdatePrefs():
    """Returns a dictionary of prefs from
    /Library/Preferences/com.apple.SoftwareUpdate.plist"""
    try:
        return FoundationPlist.readPlist(
                   '/Library/Preferences/com.apple.SoftwareUpdate.plist')
    except FoundationPlist.NSPropertyListSerializationException:
        return {}


def getCurrentSoftwareUpdateServer():
    '''Returns the current Apple SUS CatalogURL'''
    return softwareUpdatePrefs().get('CatalogURL','')


def selectSoftwareUpdateServer():
    '''Switch to our preferred Software Update Server if supplied'''
    if munkicommon.pref('SoftwareUpdateServerURL'):
        cmd = ['/usr/bin/defaults', 'write',
               '/Library/Preferences/com.apple.SoftwareUpdate',
               'CatalogURL', munkicommon.pref('SoftwareUpdateServerURL')]
        unused_retcode = subprocess.call(cmd)


def restoreSoftwareUpdateServer(theurl):
    '''Switch back to original Software Update server (if there was one)'''
    if munkicommon.pref('SoftwareUpdateServerURL'):
        if theurl:
            cmd = ['/usr/bin/defaults', 'write',
                   '/Library/Preferences/com.apple.SoftwareUpdate',
                   'CatalogURL', theurl]
        else:
            cmd = ['/usr/bin/defaults', 'delete',
                   '/Library/Preferences/com.apple.SoftwareUpdate', 
                   'CatalogURL']
        unused_retcode = subprocess.call(cmd)
        
        
def setupSoftwareUpdateCheck():
    '''Set defaults for root user and current host.
    Needed for Leopard.'''
    cmd = ['/usr/bin/defaults', '-currentHost', 'write',
           'com.apple.SoftwareUpdate', 'AgreedToLicenseAgreement', 
           '-bool', 'YES']
    unused_retcode = subprocess.call(cmd)
    cmd = ['/usr/bin/defaults', '-currentHost', 'write',
           'com.apple.SoftwareUpdate', 'AutomaticDownload', 
           '-bool', 'YES']
    unused_retcode = subprocess.call(cmd)
    cmd = ['/usr/bin/defaults', '-currentHost', 'write',
           'com.apple.SoftwareUpdate', 'LaunchAppInBackground', 
           '-bool', 'YES']
    unused_retcode = subprocess.call(cmd)
    
    
def checkForSoftwareUpdates():
    '''Does our Apple Software Update check'''
    if munkicommon.munkistatusoutput:
        munkistatus.message("Checking for available "
                            "Apple Software Updates...")
        munkistatus.detail("")
        munkistatus.percent(-1)
    else:
        munkicommon.display_status("Checking for available "
                                   "Apple Software Updates...")
    # save the current SUS URL
    original_url = getCurrentSoftwareUpdateServer()
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
    proc = subprocess.Popen(cmd, shell=False, bufsize=1,
                            stdin=subprocess.PIPE, 
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                            
    while True: 
        output = proc.stdout.readline().decode('UTF-8')
        if munkicommon.munkistatusoutput:
            if munkistatus.getStopButtonState() == 1:
                os.kill(proc.pid, 15) #15 is SIGTERM
                break
        if not output and (proc.poll() != None):
            break
        # send the output to STDOUT or MunkiStatus as applicable
        # But first, filter out some noise...
        if "Missing bundle identifier" not in output:
            munkicommon.display_status(output.rstrip('\n'))
    
    retcode = proc.poll()
    if retcode:
        if osvers == 9:
            # there's always an error on Leopard
            # because we prevent the app from launching
            # so let's just ignore them
            retcode = 0
            
    if retcode == 0:      
        # get SoftwareUpdate's LastResultCode
        LastResultCode = softwareUpdatePrefs().get('LastResultCode', 0)
        if LastResultCode > 2:
            retcode = LastResultCode
            
    if retcode:
        # there was an error
        munkicommon.display_error("softwareupdate error: %s" % retcode)
            
    if osvers == 9:
        # put mode back for Software Update.app
        os.chmod(softwareupdateapp, oldmode)
    
    # switch back to the original SUS server
    restoreSoftwareUpdateServer(original_url)
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
                for node in strings.childNodes:
                    text += node.nodeValue
                    
                #if 'language' in strings.attributes.keys():
                #    if strings.attributes['language'
                #                             ].value.encode(
                #                                   'UTF-8') == "English":
                #        for node in strings.childNodes:
                #            text += node.nodeValue
                           
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
            description = ""
            keep = True
            # lop off "SU_DESCRIPTION"
            line = line[16:]
            # lop off everything up through '
            line = line[line.find("'")+1:]
        
        if keep:
            # replace escaped single quotes
            line = line.replace("\\'","'")
            if line == "';":
                # we're done
                break
            elif line.endswith("';"):
                # done
                description += line[0:-2]
                break
            else:
                # append the line to the description
                description += line + "\n"
            
    # now try to extract the size
    itemsize = 0
    if gui_scripts:
        pkgrefs = gui_scripts[0].getElementsByTagName("pkg-ref")
        if pkgrefs:
            for ref in pkgrefs:
                keys = ref.attributes.keys()
                if 'installKBytes' in keys:
                    itemsize = int(
                            ref.attributes[
                            'installKBytes'].value.encode('UTF-8'))
                    break
            
    if itemsize == 0:
        for (path, unused_dirs, files) in os.walk(os.path.dirname(filename)):
            for name in files:
                pathname = os.path.join(path, name)
                # use os.lstat so we don't follow symlinks
                itemsize += int(os.lstat(pathname).st_size)
        # convert to kbytes
        itemsize = int(itemsize/1024)   
                 
    return title, vers, description, itemsize


def getRestartInfo(installitemdir):
    '''Looks at all the RestartActions for all the items in the
     directory and returns the highest weighted of:
       RequireRestart
       RecommendRestart
       RequireLogout
       RecommendLogout
       None'''
    
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

            proc = subprocess.Popen(["/usr/sbin/installer",
                                    "-query", "RestartAction", 
                                    "-pkg", installeritem], 
                                    bufsize=1, 
                                    stdout=subprocess.PIPE, 
                                    stderr=subprocess.PIPE)
            (out, unused_err) = proc.communicate()
            if out:
                thisAction = str(out).rstrip('\n')
                if thisAction in weight.keys():
                    if weight[thisAction] > weight[restartAction]:
                        restartAction = thisAction
            
    return restartAction


def getSoftwareUpdateInfo():
    '''Parses the Software Update index.plist and the downloaded updates,
    extracting info in the format munki expects. Returns an array of
    installeritems like those found in munki's InstallInfo.plist'''
    
    updatesdir = "/Library/Updates"
    updatesindex = os.path.join(updatesdir, "index.plist")
    if not os.path.exists(updatesindex):
        # no updates index, so bail
        return []
    
    suLastResultCode = softwareUpdatePrefs().get('LastResultCode')
    if suLastResultCode == 0:
        # successful and updates found
        pass
    elif suLastResultCode == 2:
        # no updates found/needed on last run
        return []
    elif suLastResultCode == 100:
        # couldn't contact the SUS on the most recent attempt.
        # see if the index.plist corresponds to the
        # LastSuccessfulDate
        lastSuccessfulDateString = str(
            softwareUpdatePrefs().get('LastSuccessfulDate', ''))
        if not lastSuccessfulDateString:
            # was never successful
            return []
        try:
            lastSuccessfulDate = NSDate.dateWithString_(
                                                    lastSuccessfulDateString)
        except (ValueError, TypeError):
            # bad LastSuccessfulDate string, bail
            return []
        updatesIndexDate = NSDate.dateWithTimeIntervalSince1970_(
                                              os.stat(updatesindex).st_mtime)
        secondsDiff = updatesIndexDate.timeIntervalSinceDate_(
                                                          lastSuccessfulDate)
        if abs(secondsDiff) > 30:
            # index.plist mod time doesn't correspond with LastSuccessfulDate
            return []
    else:
        # unknown LastResultCode
        return []

    # if we get here, either the LastResultCode was 0 or
    # the index.plist mod time was within 30 seconds of the LastSuccessfulDate
    # so the index.plist is _probably_ valid...
    infoarray = []
    plist = FoundationPlist.readPlist(updatesindex)
    if 'ProductPaths' in plist:
        products = plist['ProductPaths']
        for product_key in products.keys():
            updatename = products[product_key]
            installitem = os.path.join(updatesdir, updatename)
            if os.path.exists(installitem) and os.path.isdir(installitem):
                for subitem in os.listdir(installitem):
                    if subitem.endswith('.dist'):
                        distfile = os.path.join(installitem, subitem)
                        (title, vers, 
                            description, 
                            installedsize) = parseDist(distfile)
                        iteminfo = {}
                        iteminfo["installer_item"] = updatename
                        iteminfo["name"] = title
                        iteminfo["description"] = description
                        if iteminfo["description"] == '':
                            iteminfo["description"] = \
                                            "Updated Apple software."
                        iteminfo["version_to_install"] = vers
                        iteminfo['display_name'] = title
                        iteminfo['installed_size'] = installedsize
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
        plist = {}
        plist['AppleUpdates'] = appleUpdates
        FoundationPlist.writePlist(plist, appleUpdatesFile)
        return True
    else:
        try:
            os.unlink(appleUpdatesFile)
        except (OSError, IOError):
            pass
        return False


def displayAppleUpdateInfo():
    '''Prints Apple update information'''
    try:
        updatelist = FoundationPlist.readPlist(appleUpdatesFile)
    except FoundationPlist.FoundationPlistException:
        return
    else:
        appleupdates = updatelist.get('AppleUpdates', [])
        if len(appleupdates):
            munkicommon.display_info(
            "The following Apple Software Updates are available to install:")
        for item in appleupdates:
            munkicommon.display_info("    + %s-%s" %
                                        (item.get('display_name',''),
                                         item.get('version_to_install','')))
            if item.get('RestartAction') == 'RequireRestart' or \
               item.get('RestartAction') == 'RecommendRestart':
                munkicommon.display_info("       *Restart required")
                munkicommon.report['RestartRequired'] = True
            if item.get('RestartAction') == 'RequireLogout':
                munkicommon.display_info("       *Logout required")
                munkicommon.report['LogoutRequired'] = True


def appleSoftwareUpdatesAvailable(forcecheck=False, suppresscheck=False):
    '''Checks for available Apple Software Updates, trying not to hit the SUS
    more than needed'''

    if suppresscheck:
        # typically because we're doing a logout install; if
        # there are no waiting Apple Updates we shouldn't 
        # trigger a check for them. 
        pass
    elif forcecheck:
        # typically because user initiated the check from
        # Managed Software Update.app
        unused_retcode = checkForSoftwareUpdates()
    else:
        # have we checked recently?  Don't want to check with
        # Apple Software Update server too frequently
        now = NSDate.new()
        nextSUcheck = now
        lastSUcheckString = str(
            softwareUpdatePrefs().get('LastSuccessfulDate', ''))
        if lastSUcheckString:
            try:
                lastSUcheck = NSDate.dateWithString_(lastSUcheckString)
                interval = 24 * 60 * 60
                nextSUcheck = lastSUcheck.dateByAddingTimeInterval_(interval)
            except (ValueError, TypeError):
                pass
        if now.timeIntervalSinceDate_(nextSUcheck) >= 0:
            unused_retcode = checkForSoftwareUpdates()
        else:
            munkicommon.log("Skipping Apple Software Update check because "
                            "we last checked on %s..." % lastSUcheck)

    if writeAppleUpdatesFile():
        displayAppleUpdateInfo()
        return True
    else:
        return False


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
    '''Placeholder'''
    pass


if __name__ == '__main__':
    main()

