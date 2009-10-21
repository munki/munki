#!/usr/bin/env python
# encoding: utf-8
"""
adobeutils.py

Utilities to enable munki to install/uninstall Adobe CS4 products using their
CS4 Deployment Toolkit.

"""
# Copyright 2009 Greg Neagle.
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
import subprocess
import time
from xml.dom import minidom

import FoundationPlist
import munkicommon
import munkistatus

# dmg helper
# we need this instead of the one in munkicommon because the Adobe stuff
# needs the dmgs mounted under /Volumes.  We can merge this later.
def mountdmg(dmgpath):
    """
    Attempts to mount the dmg at dmgpath
    and returns a list of mountpoints
    """
    mountpoints = []
    dmgname = os.path.basename(dmgpath)
    p = subprocess.Popen(['/usr/bin/hdiutil', 'attach', dmgpath, '-nobrowse', '-plist'],
            bufsize=1, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (plist, err) = p.communicate()
    if err:
        print >>sys.stderr, "Error %s mounting %s." % (err, dmgpath)
    if plist:
        pl = FoundationPlist.readPlistFromString(plist)
        for entity in pl['system-entities']:
            if 'mount-point' in entity:
                mountpoints.append(entity['mount-point'])

    return mountpoints
    
    
def getAdobeUpdateInfo(installroot):
    # given the root of mounted Adobe Updater DMG, look for info about the update
    info = {}
    # look for an extensions folder
    for (path, dirs, files) in os.walk(installroot):
        if path.endswith("/extensions"):
            # hopefully, there's a single directory in here:
            extensions = []
            for item in os.listdir(path):
                itempath = os.path.join(path, item)
                if os.path.isdir(itempath):
                    extensions.append(itempath)
            
            if len(extensions) > 1:
                # right now, I have no idea how to deal with multiple updates
                # in a single DMG, so bail
                return info
            else:
                extensionpath = extensions[0]
                # look for .proxy.xml file in the extension dir
                for item in os.listdir(extensionpath):
                    if item.endswith('.proxy.xml'):
                        xmlpath = os.path.join(extensionpath, item)
                        dom = minidom.parse(xmlpath)
                        payload_info = dom.getElementsByTagName("PayloadInfo")
                        if payload_info:
                            installer_properties = payload_info[0].getElementsByTagName("InstallerProperties")
                            if installer_properties:
                                properties = installer_properties[0].getElementsByTagName("Property")
                                for prop in properties:
                                    if 'name' in prop.attributes.keys():
                                        propname = prop.attributes['name'].value.encode('UTF-8')
                                        propvalue = ''
                                        for node in prop.childNodes:
                                            propvalue += node.nodeValue
                                        if propname == 'ProductName':
                                            info['display_name'] = propvalue
                                        if propname == 'ProductVersion':
                                            info['version'] = munkicommon.padVersionString(propvalue,5)    
                            
                            installmetadata = payload_info[0].getElementsByTagName("InstallDestinationMetadata")
                            if installmetadata:
                                totalsizes = installmetadata[0].getElementsByTagName("TotalSize")
                                if totalsizes:
                                    installsize = ''
                                    for node in totalsizes[0].childNodes:
                                        installsize += node.nodeValue
                                    info['installed_size'] = str(int(installsize)/1024)
                        
    return info


def getAdobePackageInfo(installroot):
    # gets the package name from the AdobeUberInstaller.xml file
    info = {}
    info['description'] = ""
    installerxml = os.path.join(installroot, "AdobeUberInstaller.xml")
    if os.path.exists(installerxml):
        description = ''
        dom = minidom.parse(installerxml)
        installinfo = dom.getElementsByTagName("InstallInfo")
        if installinfo:
            packagedescriptions = installinfo[0].getElementsByTagName("PackageDescription")
            if packagedescriptions:
                prop = packagedescriptions[0]
                for node in prop.childNodes:
                    description += node.nodeValue

        if description:
            description_parts = description.split(' : ', 1)
            info['display_name'] = description_parts[0]
            if len(description_parts) > 1:
                info['description'] = description_parts[1]
            else:
                info['description'] = ""
            return info
    
    info['display_name'] = os.path.basename(installroot)      
    return info
    

lastlogline = ''
def getAdobeInstallerLogInfo():
    # Adobe Setup.app and AdobeUberInstaller don't provide progress output,
    # so we're forced to do fancy log tailing...
    global lastlogline
    logpath = "/Library/Logs/Adobe/Installers"
    # find the most recently-modified log file
    p = subprocess.Popen(['/bin/ls', '-t1', logpath], 
        bufsize=1, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (output, err) = p.communicate()
    if output:
        firstitem = output.splitlines()[0]
        if firstitem.endswith(".log"):
            # get the last line of the most recently modified log
            logfile = os.path.join(logpath, firstitem)
            p = subprocess.Popen(['/usr/bin/tail', '-1', logfile], 
                bufsize=1, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            (output, err) = p.communicate()
            logline = output.rstrip('\n')
            # is it different than the last time we checked?
            if logline != lastlogline:
                lastlogline = logline
                return logline
    return ''


def countPayloads(dirpath):
    # attempts to count the payloads in the package
    for item in os.listdir(dirpath):
        itempath = os.path.join(dirpath, item)
        if os.path.isdir(itempath):
            if item == "payloads":
                count = 0
                for subitem in os.listdir(itempath):
                    subitempath = os.path.join(itempath, subitem)
                    if os.path.isdir(subitempath):
                        count = count + 1
                return count
            else:
                payloadcount = countPayloads(itempath)
                if payloadcount:
                    return payloadcount
    return 0


def getPercent(current, maximum):
    # returns a value useful with MunkiStatus
    if current < 0:
        percentdone = -1
    elif current > maximum:
        percentdone = -1
    elif current == maximum:
        percentdone = 100
    else:
        percentdone = int(float(current)/float(maximum)*100)
    return percentdone
    
    
def findSetupApp(dirpath):
    # search dirpath and enclosed directories for Setup.app
    for (path, dirs, files) in os.walk(dirpath):
        if path.endswith("Setup.app"):
            setup_path = os.path.join(path, "Contents", "MacOS", "Setup")
            if os.path.exists(setup_path):
                return setup_path
    return ''


def runAdobeSetup(dmgpath):
    # runs the Adobe setup tool in silent mode from
    # an Adobe CS4 update DMG
    munkicommon.display_status("Mounting disk image %s" % os.path.basename(dmgpath))
    mountpoints = mountdmg(dmgpath)
    if mountpoints:
        setup_path = findSetupApp(mountpoints[0])
        if setup_path:
            munkicommon.display_status("Running Adobe Update Installer")
            adobe_setup = [ setup_path, '--mode=silent', '--skipProcessCheck=1' ]
            p = subprocess.Popen(adobe_setup, shell=False, bufsize=1, stdin=subprocess.PIPE, 
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            while (p.poll() == None): 
                time.sleep(1)
                loginfo = getAdobeInstallerLogInfo()
                if loginfo.startswith("Mounting payload image at "):
                    try:
                        payloadpath = loginfo[26:]
                        payloadfilename = os.path.basename(payloadpath)
                        payloadname = os.path.splitext(payloadfilename)[0]
                        munkicommon.display_status("Installing payload: %s" % payloadname)
                    except:
                        pass
                      
            retcode = p.poll()
            if retcode:
                munkicommon.display_error("***Adobe Setup error: %s: %s***" % (retcode, adobeSetupError(retcode)))
        else:
            munkicommon.display_error("%s doesn't appear to contain an Adobe CS4 update." % os.path.basename(dmgpath))
            retcode = -1
        munkicommon.unmountdmg(mountpoints[0])
    else:
        munkicommon.display_error("No mountable filesystems on %s" % dmgpath)
        retcode = -1
    
    return retcode
    
    
def runAdobeUberTool(dmgpath, pkgname='', uninstalling=False):
    # runs either AdobeUberInstaller or AdobeUberUninstaller
    # from a disk image and provides progress feedback
    # pkgname is the name of a directory at the top level of the dmg
    # containing the AdobeUber tools and their XML files
    munkicommon.display_status("Mounting disk image %s" % os.path.basename(dmgpath))
    mountpoints = mountdmg(dmgpath)
    if mountpoints:
        installroot = mountpoints[0]
        if uninstalling:
            ubertool = os.path.join(installroot, pkgname, "AdobeUberUninstaller")
        else:
            ubertool = os.path.join(installroot, pkgname, "AdobeUberInstaller")
            
        if os.path.exists(ubertool):
            info = getAdobePackageInfo(installroot)
            packagename = info['display_name']
            action = "Installing"
            if uninstalling:
                action = "Uninstalling"
            if munkicommon.munkistatusoutput:
                munkistatus.message("%s %s..." % (action, packagename))
                munkistatus.detail("Starting %s" % os.path.basename(ubertool))
                munkistatus.percent(-1)
            else:
                munkicommon.display_status("%s %s" % (action, packagename))
            
            # try to find and count the number of payloads 
            # so we can give a rough progress indicator
            number_of_payloads = countPayloads(installroot)
            payload_completed_count = 0
            
            p = subprocess.Popen([ubertool], shell=False, bufsize=1, stdin=subprocess.PIPE, 
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            while (p.poll() == None): 
                time.sleep(1)
                loginfo = getAdobeInstallerLogInfo()
                # installing
                if loginfo.startswith("Mounting payload image at "):
                    # increment payload_completed_count
                    payload_completed_count = payload_completed_count + 1
                    if munkicommon.munkistatusoutput:
                        munkistatus.percent(getPercent(payload_completed_count, number_of_payloads))
                    try:
                        payloadpath = loginfo[26:]
                        payloadfilename = os.path.basename(payloadpath)
                        payloadname = os.path.splitext(payloadfilename)[0]
                        munkicommon.display_status("Installing payload: %s" % payloadname)
                    except:
                        pass
                # uninstalling
                if loginfo.startswith("Physical payload uninstall result"):
                    # increment payload_completed_count
                    payload_completed_count = payload_completed_count + 1
                    munkicommon.display_status("Removed Adobe payload %s" % payload_completed_count)
                    if munkicommon.munkistatusoutput:
                        munkistatus.percent(getPercent(payload_completed_count, number_of_payloads))
            
            # ubertool completed  
            retcode = p.poll()
            if retcode:
                munkicommon.display_error("***Adobe Setup error: %s: %s***" % (retcode, adobeSetupError(retcode)))
        else:
            munkicommon.display_error("No %s found" % ubertool)
            retcode = -1
        
        if munkicommon.munkistatusoutput:
            munkistatus.percent(100)
        munkicommon.display_status("Done.")
        munkicommon.unmountdmg(installroot)
        return retcode
    else:
        munkicommon.display_error("No mountable filesystems on %s" % dmgpath)
        return -1
        

def adobeSetupError(errorcode):
    # returns text description for numeric error code
    # Reference: http://www.adobe.com/devnet/creativesuite/pdfs/DeployGuide.pdf
    errormessage = { 0 : "Application installed successfully",
                     1 : "Unable to parse command line",
                     2 : "Unknoen user interface mode specified",
                     3 : "Unable to initialize ExtendScript",
                     4 : "User interface workflow failed",
                     5 : "Unable to initialize user interface workflow",
                     6 : "Slient workflow completed with errors",
                     7 : "Unable to complete the silent workflow",
                     8 : "Exit and restart",
                     9 : "Unsupported operating system version",
                     10 : "Unsuppoerted file system",
                     11 : "Another instance running",
                     12 : "CAPS integrity error",
                     13 : "Media opitmization failed",
                     14 : "Failed due to insuffcient privileges",
                     9999 : "Catastrophic error",
                     -1 : "The AdobeUberInstaller failed before launching the installer" }
    return errormessage.get(errorcode, "Unknown error")


def install(dmgpath, pkgname=''):
    return runAdobeUberTool(dmgpath, pkgname)


def uninstall(dmgpath, pkgname=''):
    return runAdobeUberTool(dmgpath, pkgname, uninstalling=True)


def main():
	pass


if __name__ == '__main__':
	main()

