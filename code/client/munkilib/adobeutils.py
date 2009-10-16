#!/usr/bin/env python
# encoding: utf-8
"""
adobeutils.py

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


def getAdobePackageName(installroot):
    # gets the package name from the AdobeUberInstaller.xml file
    installerxml = os.path.join(installroot, "AdobeUberInstaller.xml")
    if os.path.exists(installerxml):
        description = ''
        dom = minidom.parse(xmlfile)
        installinfo = dom.getElementsByTagName("InstallInfo")
        if installinfo:
            packagedescriptions = installinfo[0].getElementsByTagName("PackageDescription")
            if packagedescriptions:
                prop = packagedescriptions[0]
                for node in prop.childNodes:
                    description += node.nodeValue

        if description:
            name = description.split(' : ')[0]
            if name:
                return name
                
    return os.path.basename(installroot)
    

lastlogline = ''
def getAdobeInstallerInfo():
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
    elif current > maximum
        percentdone = -1
    elif current == maximum:
        percentdone = 100
    else:
        percentdone = int(float(current)/float(maximum)*100)
    return percentdone
    

def runAdobeUberTool(dmgpath, uninstalling=False):
    # runs either AdobeUberInstaller or AdobeUberUninstaller
    # from a disk image and provides progress feedback
    munkicommon.display_status("Mounting disk image %s" % os.path.basename(dmgpath))
    mountpoints = mountdmg(dmgpath)
    if mountpoints:
        installroot = mountpoints[0]
        if uninstalling:
            ubertool = os.path.join(installroot, "AdobeUberUninstaller")
        else:
            ubertool = os.path.join(installroot, "AdobeUberInstaller")
            
        if os.path.exists(ubertool):
            packagename = getAdobePackageName(installroot)
            action = "Installing"
            if uninstalling:
                action = "Uninstalling"
            if munkicommon.munkistatusoutput:
                munkistatus.message("%s %s..." % (action, packagename))
                # clear indeterminate progress bar 
                munkistatus.percent(0)
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
                loginfo = getAdobeInstallerInfo()
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
                munkicommon.display_error("***Adobe Setup error: %s***" % retcode)
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
        

def install(dmgpath):
    runAdobeUberTool(dmgpath)


def uninstall(dmgpath):
    runAdobeUberTool(dmgpath, uninstalling=True)


def main():
	pass


if __name__ == '__main__':
	main()

