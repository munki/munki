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
def mountAdobeDmg(dmgpath):
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


def getPayloadInfo(dirpath):
    payloadinfo = {}
    # look for .proxy.xml file dir
    if os.path.isdir(dirpath):
        for item in os.listdir(dirpath):
            if item.endswith('.proxy.xml'):
                xmlpath = os.path.join(dirpath, item)
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
                                    payloadinfo['display_name'] = propvalue
                                if propname == 'ProductVersion':
                                    payloadinfo['version'] = munkicommon.padVersionString(propvalue,5)    
                
                    installmetadata = payload_info[0].getElementsByTagName("InstallDestinationMetadata")
                    if installmetadata:
                        totalsizes = installmetadata[0].getElementsByTagName("TotalSize")
                        if totalsizes:
                            installsize = ''
                            for node in totalsizes[0].childNodes:
                                installsize += node.nodeValue
                            payloadinfo['installed_size'] = int(installsize)/1024
    return payloadinfo
    
    
def getAdobeSetupInfo(installroot):
    # given the root of mounted Adobe DMG,
    # look for info about the installer or updater
    info = {}
    payloads = []
    
    # look for a payloads folder
    for (path, dirs, files) in os.walk(installroot):
        if path.endswith("/payloads"):
            driverfolder = ''
            setupxml = os.path.join(path, "setup.xml")
            if os.path.exists(setupxml):
                dom = minidom.parse(setupxml)
                drivers =  dom.getElementsByTagName("Driver")
                if drivers:
                    driver = drivers[0]
                    if 'folder' in driver.attributes.keys():
                        driverfolder = driver.attributes['folder'].value.encode('UTF-8')
            for item in os.listdir(path):
                payloadpath = os.path.join(path, item)
                payloadinfo = getPayloadInfo(payloadpath)
                if payloadinfo:
                    payloads.append(payloadinfo)
                    if driverfolder and item == driverfolder:
                        info['display_name'] = payloadinfo['display_name']
                        info['version'] = payloadinfo['version']
                        info['AdobeSetupType'] = "ProductInstall"
                        
            # we found a payloads directory, so no need to keep walking the installroot
            break

    if not payloads:
        # look for an extensions folder; almost certainly this is an Updater
        for (path, dirs, files) in os.walk(installroot):
            if path.endswith("/extensions"):
                for item in os.listdir(path):
                    #skip LanguagePacks
                    if item.find("LanguagePack") == -1:
                        itempath = os.path.join(path, item)
                        payloadinfo = getPayloadInfo(itempath)
                        if payloadinfo:
                            payloads.append(payloadinfo)
                        
                # we found an extensions dir, so no need to keep walking the install root
                break
                   
    if payloads:
        if len(payloads) == 1:
            info['display_name'] = payloads[0]['display_name']
            info['version'] = payloads[0]['version']
            info['installed_size'] = payloads[0]['installed_size']
        else:
            if not 'display_name' in info:
                info['display_name'] = "ADMIN: choose from payloads"
                info['payloads'] = payloads
            if not 'version' in info:
                info['version'] = "ADMIN please set me"
            installed_size = 0
            for payload in payloads:
                installed_size = installed_size + payload.get('installed_size',0)
            info['installed_size'] = installed_size
    return info


def getAdobePackageInfo(installroot):
    # gets the package name from the AdobeUberInstaller.xml file;
    # other info from the payloads folder
    info = getAdobeSetupInfo(installroot)
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
            
    if not info.get('display_name'):
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
    
    
def runAdobeInstallTool(cmd, number_of_payloads=0):
    '''An abstraction of the tasks for running Adobe Setup,
    AdobeUberInstaller ot AdobeUberUninstaller'''
    if not number_of_payloads:
        # indeterminate progress bar
        munkistatus.percent(-1)
    payload_completed_count = 0
    p = subprocess.Popen(cmd, shell=False, bufsize=1, stdin=subprocess.PIPE, 
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    while (p.poll() == None): 
        time.sleep(1)
        loginfo = getAdobeInstallerLogInfo()
        # installing
        if loginfo.startswith("Mounting payload image at "):
            # increment payload_completed_count
            payload_completed_count = payload_completed_count + 1
            if munkicommon.munkistatusoutput and number_of_payloads:
                munkistatus.percent(getPercent(payload_completed_count, number_of_payloads))
            try:
                payloadpath = loginfo[26:]
                payloadfilename = os.path.basename(payloadpath)
                payloadname = os.path.splitext(payloadfilename)[0]
                munkicommon.display_status("Installing payload: %s" % payloadname)
            except:
                munkicommon.display_status("Installing payload %s" % payload_completed_count)
        # uninstalling
        if loginfo.startswith("Physical payload uninstall result"):
            # increment payload_completed_count
            payload_completed_count = payload_completed_count + 1
            if munkicommon.munkistatusoutput and number_of_payloads:
                munkistatus.percent(getPercent(payload_completed_count, number_of_payloads))
            munkicommon.display_status("Removed Adobe payload %s" % payload_completed_count)
                
    # run of tool completed  
    retcode = p.poll()
    if retcode != 0 and retcode != 8:
        munkicommon.display_error("Adobe Setup error: %s: %s" % (retcode, adobeSetupError(retcode)))
    else:
        if munkicommon.munkistatusoutput:
            munkistatus.percent(100)
        munkicommon.display_status("Done.")
        
    return retcode


def runAdobeSetup(dmgpath, uninstalling=False):
    # runs the Adobe setup tool in silent mode from
    # an Adobe update DMG or an Adobe CS3 install DMG
    munkicommon.display_status("Mounting disk image %s" % os.path.basename(dmgpath))
    mountpoints = mountAdobeDmg(dmgpath)
    if mountpoints:
        setup_path = findSetupApp(mountpoints[0])
        if setup_path:
            # look for install.xml or uninstall.xml at root
            deploymentfile = None
            installxml = os.path.join(mountpoints[0], "install.xml")
            uninstallxml = os.path.join(mountpoints[0], "uninstall.xml")
            if uninstalling:
                if os.path.exists(uninstallxml):
                    deploymentfile = uninstallxml
                else:
                    # we've been asked to uninstall, but found no uninstall.xml
                    # so we need to bail
                    munkicommon.unmountdmg(mountpoints[0])
                    munkicommon.display_error("%s doesn't appear to contain uninstall info." % os.path.basename(dmgpath))
                    return -1
            else:
                if os.path.exists(installxml):
                    deploymentfile = installxml
            
            # try to find and count the number of payloads 
            # so we can give a rough progress indicator
            number_of_payloads = countPayloads(mountpoints[0])
            munkicommon.display_status("Running Adobe Setup")
            adobe_setup = [ setup_path, '--mode=silent', '--skipProcessCheck=1' ]
            if deploymentfile:
                adobe_setup.append('--deploymentFile=%s' % deploymentFile)
                
            retcode = runAdobeInstallTool(adobe_setup, number_of_payloads)
            
        else:
            munkicommon.display_error("%s doesn't appear to contain Adobe Setup." % os.path.basename(dmgpath))
            retcode = -1
            
        munkicommon.unmountdmg(mountpoints[0])
        return retcode
    else:
        munkicommon.display_error("No mountable filesystems on %s" % dmgpath)
        return -1
    
    
def runAdobeUberTool(dmgpath, pkgname='', uninstalling=False):
    # runs either AdobeUberInstaller or AdobeUberUninstaller
    # from a disk image and provides progress feedback
    # pkgname is the name of a directory at the top level of the dmg
    # containing the AdobeUber tools and their XML files
    munkicommon.display_status("Mounting disk image %s" % os.path.basename(dmgpath))
    mountpoints = mountAdobeDmg(dmgpath)
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
            
            retcode = runAdobeInstallTool([ubertool], number_of_payloads)
            
        else:
            munkicommon.display_error("No %s found" % ubertool)
            retcode = -1
        
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
                     2 : "Unknown user interface mode specified",
                     3 : "Unable to initialize ExtendScript",
                     4 : "User interface workflow failed",
                     5 : "Unable to initialize user interface workflow",
                     6 : "Slient workflow completed with errors",
                     7 : "Unable to complete the silent workflow",
                     8 : "Exit and restart",
                     9 : "Unsupported operating system version",
                     10 : "Unsupported file system",
                     11 : "Another instance of Adobe Setup is running",
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

