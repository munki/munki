#!/usr/bin/python
# encoding: utf-8
#
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
"""
installer.py
munki module to automatically install pkgs, mpkgs, and dmgs
(containing pkgs and mpkgs) from a defined folder.
"""

import os
import subprocess
import sys
import time
import tempfile
import munkicommon
import munkistatus
import FoundationPlist
from removepackages import removepackages


def cleanup():
    if munkicommon.munkistatusoutput:
        munkistatus.quit()


def install(pkgpath, choicesXMLpath=''):
    """
    Uses the apple installer to install the package or metapackage
    at pkgpath. Prints status messages to STDOUT.
    Returns the installer return code and true if a restart is needed.
    """
    
    restartneeded = False
    installeroutput = []

    cmd = ['/usr/sbin/installer', '-pkginfo', '-pkg', pkgpath]
    p = subprocess.Popen(cmd, shell=False, bufsize=1, stdin=subprocess.PIPE, 
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (output, err) = p.communicate()
    packagename = output.decode('UTF-8').splitlines()[0]
    
    if munkicommon.munkistatusoutput:
        munkistatus.message("Installing %s..." % packagename)
        # clear indeterminate progress bar 
        munkistatus.percent(0)
        
    munkicommon.log("Installing %s from %s" % (packagename, os.path.basename(pkgpath)))
    cmd = ['/usr/sbin/installer', '-query', 'RestartAction', '-pkg', pkgpath]
    if choicesXMLpath:
        cmd.extend(['-applyChoiceChangesXML', choicesXMLpath])
    p = subprocess.Popen(cmd, shell=False, bufsize=1, stdin=subprocess.PIPE, 
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (output, err) = p.communicate()
    restartaction = output.decode('UTF-8').rstrip("\n")
    if restartaction == "RequireRestart":
        munkicommon.display_status("%s requires a restart after installation." % packagename)
        restartneeded = True
        
    # get the OS version; we need it later when processing installer's output, 
    # which varies depnding on OS version.    
    osvers = int(os.uname()[2].split('.')[0])
    cmd = ['/usr/sbin/installer', '-verboseR', '-pkg', pkgpath, '-target', '/']
    if choicesXMLpath:
        cmd.extend(['-applyChoiceChangesXML', choicesXMLpath])
    p = subprocess.Popen(cmd, shell=False, bufsize=1, stdin=subprocess.PIPE, 
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    while True: 
        installinfo =  p.stdout.readline().decode('UTF-8')
        if not installinfo and (p.poll() != None):
            break
        if installinfo.startswith("installer:"):
            # save all installer output in case there is
            # an error so we can dump it to the log
            installeroutput.append(installinfo)
            msg = installinfo[10:].rstrip("\n")
            if msg.startswith("PHASE:"):
                phase = msg[6:]
                if phase:
                    if munkicommon.munkistatusoutput:
                        munkistatus.detail(phase)
                    else:
                        print phase.encode('UTF-8')
                        sys.stdout.flush()
            elif msg.startswith("STATUS:"):
                status = msg[7:]
                if status:
                    if munkicommon.munkistatusoutput:
                        munkistatus.detail(status)
                    else:
                        print status.encode('UTF-8')
                        sys.stdout.flush()
            elif msg.startswith("%"):
                if munkicommon.munkistatusoutput:
                    percent = float(msg[1:])
                    if osvers < 10:
                        # Leopard uses a float from 0 to 1
                        percent = int(percent * 100)
                    munkistatus.percent(percent)
            elif msg.startswith(" Error"):
                if munkicommon.munkistatusoutput:
                    munkistatus.detail(msg)
                else:
                    print >>sys.stderr, msg.encode('UTF-8')
                munkicommon.log(msg)
            elif msg.startswith(" Cannot install"):
                if munkicommon.munkistatusoutput:
                    munkistatus.detail(msg)
                else:
                    print >>sys.stderr, msg.encode('UTF-8')
                munkicommon.log(msg)
            else:
                munkicommon.log(msg)

    retcode = p.poll()
    if retcode:
        munkicommon.display_status("Install of %s failed." % packagename)
        munkicommon.display_error("-------------------------------------------------")
        for line in installeroutput:
            munkicommon.display_error(line.rstrip("\n"))
            
        munkicommon.display_error("-------------------------------------------------")
        restartneeded = False
    else:
        munkicommon.log("Install of %s was successful." % packagename)
        if munkicommon.munkistatusoutput:
            munkistatus.percent(100)
            
    return (retcode, restartneeded)


def installall(dirpath, choicesXMLpath=''):
    """
    Attempts to install all pkgs and mpkgs in a given directory.
    Will mount dmg files and install pkgs and mpkgs found at the
    root of any mountpoints.
    """
    restartflag = False
    installitems = os.listdir(dirpath)
    for item in installitems:
        if munkicommon.stopRequested():
            return restartflag
        itempath = os.path.join(dirpath, item)
        if item.endswith(".dmg"):
            munkicommon.display_info("Mounting disk image %s" % item)
            mountpoints = munkicommon.mountdmg(itempath)
            if mountpoints == []:
                munkicommon.display_error("ERROR: No filesystems mounted from %s" % item)
                return restartflag
            if munkicommon.stopRequested():
                for mountpoint in mountpoints:
                    munkicommon.unmountdmg(mountpoint)
                return restartflag
            for mountpoint in mountpoints:
                # install all the pkgs and mpkgs at the root
                # of the mountpoint -- call us recursively!
                needtorestart = installall(mountpoint, choicesXMLpath)
                if needtorestart:
                    restartflag = True
                munkicommon.unmountdmg(mountpoint)
        
        if (item.endswith(".pkg") or item.endswith(".mpkg")):
            (retcode, needsrestart) = install(itempath, choicesXMLpath)
            if needsrestart:
                restartflag = True
    return restartflag
    

def getInstallCount(installList):
    count = 0
    for item in installList:
        if 'installed' in item:
            if not item['installed']:
                count +=1
    return count

    
def installWithInfo(dirpath, installlist):
    """
    Uses the installlist to install items in the
    correct order.
    """
    restartflag = False
    itemindex = -1
    for item in installlist:
        itemindex = itemindex + 1
        if munkicommon.stopRequested():
            return restartflag
        if "installer_item" in item:
            itempath = os.path.join(dirpath, item["installer_item"])
            if not os.path.exists(itempath):
                #can't install, so we should stop
                munkicommon.display_error("Installer item %s was not found." % item["installer_item"])
                return restartflag
            if 'installer_choices_xml' in item:
                choicesXMLfile = os.path.join(munkicommon.tmpdir, "choices.xml")
                FoundationPlist.writePlist(item['installer_choices_xml'], choicesXMLfile)
            else:
                choicesXMLfile = ''
            if itempath.endswith(".dmg"):
                munkicommon.display_status("Mounting disk image %s" % item["installer_item"])
                mountpoints = munkicommon.mountdmg(itempath)
                if mountpoints == []:
                    munkicommon.display_error("ERROR: No filesystems mounted from %s" % item["installer_item"])
                    return restartflag
                if munkicommon.stopRequested():
                    for mountpoint in mountpoints:
                        munkicommon.unmountdmg(mountpoint)
                    return restartflag
                for mountpoint in mountpoints:
                    # install all the pkgs and mpkgs at the root
                    # of the mountpoint -- call us recursively!
                    needtorestart = installall(mountpoint, choicesXMLfile)
                    if needtorestart:
                        restartflag = True
                    munkicommon.unmountdmg(mountpoint)
            else:
                itempath = munkicommon.findInstallerItem(itempath)
                if (itempath.endswith(".pkg") or itempath.endswith(".mpkg") or itempath.endswith(".dist")):
                    (retcode, needsrestart) = install(itempath, choicesXMLfile)
                    if needsrestart:
                        restartflag = True
            
            # check to see if this installer item is needed by any additional items in installinfo
            # this might happen if there are mulitple things being installed with choicesXML files
            # applied to a metapackage
            foundagain = False
            current_installer_item = item['installer_item']
            # are we at the end of the installlist?
            if itemindex+1 != len(installlist):
                # nope, let's check the remaining items
                for lateritem in installlist[itemindex+1:]:
                    if 'installer_item' in lateritem:
                        if lateritem['installer_item'] == current_installer_item:
                            foundagain = True
                            break
                        
            if not foundagain:
                # now remove the item from the install cache
                # (using rm -rf in case it's a bundle pkg)
                itempath = os.path.join(dirpath, current_installer_item)
                retcode = subprocess.call(["/bin/rm", "-rf", itempath])

    return restartflag


def getRemovalCount(removalList):
    count = 0
    for item in removalList:
        if 'installed' in item:
            if item['installed']:
                count +=1
    return count


def processRemovals(removalList):
    restartFlag = False
    for item in removalList:
        if munkicommon.stopRequested():
            return restartFlag
        if 'installed' in item:
            if item['installed']:
                name = item.get('name','')
                if 'uninstall_method' in item:
                    uninstallmethod = item['uninstall_method'].split(' ')
                    if uninstallmethod[0] == "removepackages":
                        if 'packages' in item:
                            if item.get('RestartAction') == "RequireRestart":
                                restartFlag = True
                            if munkicommon.munkistatusoutput:
                                # clear indeterminate progress bar 
                                munkistatus.percent(0)                               
                            
                            munkicommon.display_status("Removing %s..." % name)
                            retcode = removepackages(item['packages'], forcedeletebundles=True)
                            if retcode:
                                if retcode == -128:
                                    message = "Uninstall of %s was cancelled." % name
                                else:
                                    message = "Uninstall of %s failed." % name
                                munkicommon.display_error(message)
                            else:
                                munkicommon.log("Uninstall of %s was successful." % name)
                        
                    elif os.path.exists(uninstallmethod[0]) and os.access(uninstallmethod[0], os.X_OK):
                        # it's a script or program to uninstall
                        if munkicommon.munkistatusoutput:
                            munkistatus.message("Running uninstall script for %s..." % name)
                            # set indeterminate progress bar 
                            munkistatus.percent(-1)
                        
                        if item.get('RestartAction') == "RequireRestart":
                            restartFlag = True
                        
                        cmd = uninstallmethod
                        uninstalleroutput = []
                        p = subprocess.Popen(cmd, shell=False, bufsize=1, stdin=subprocess.PIPE, 
                                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

                        while (p.poll() == None): 
                            msg =  p.stdout.readline().decode('UTF-8')
                            # save all uninstaller output in case there is
                            # an error so we can dump it to the log
                            uninstalleroutput.append(msg)
                            msg = msg.rstrip("\n")
                            if munkicommon.munkistatusoutput:
                                # do nothing with the output
                                pass
                            else:
                                print msg
                    
                        retcode = p.poll()
                        if retcode:
                            message = "Uninstall of %s failed." % name
                            print >>sys.stderr, message
                            munkicommon.log(message)
                            message = "-------------------------------------------------"
                            print >>sys.stderr, message
                            munkicommon.log(message)
                            for line in uninstalleroutput:
                                print >>sys.stderr, "     ", line.rstrip("\n")
                                munkicommon.log(line.rstrip("\n"))
                            message = "-------------------------------------------------"
                            print >>sys.stderr, message
                            munkicommon.log(message)
                        else:
                            munkicommon.log("Uninstall of %s was successful." % name)
                            
                        if munkicommon.munkistatusoutput:
                            # clear indeterminate progress bar 
                            munkistatus.percent(0)
           
                    else:
                        munkicommon.log("Uninstall of %s failed because there was no valid uninstall method." % name)
                                    
    return restartFlag



def run():
    
    managedinstallbase = munkicommon.ManagedInstallDir()
    installdir = os.path.join(managedinstallbase , 'Cache')
    
    needtorestart = removals_need_restart = installs_need_restart = False
    munkicommon.log("### Beginning managed installer session ###")
    
    installinfo = os.path.join(managedinstallbase, 'InstallInfo.plist')
    if os.path.exists(installinfo):
        try:
            pl = FoundationPlist.readPlist(installinfo)
        except:
            print >>sys.stderr, "Invalid %s" % installinfo
            return -1
        
        # remove the install info file
        # it's no longer valid once we start running
        os.unlink(installinfo)
        
        if "removals" in pl:
            removalcount = getRemovalCount(pl['removals'])
            if removalcount:
                if munkicommon.munkistatusoutput:
                    if removalcount == 1:
                        munkistatus.message("Removing 1 item...")
                    else:
                        munkistatus.message("Removing %i items..." % removalcount)
                    # set indeterminate progress bar 
                    munkistatus.percent(-1)
                munkicommon.log("Processing removals")
                removals_need_restart = processRemovals(pl['removals'])
        if "managed_installs" in pl:
            if not munkicommon.stopRequested():
                installcount = getInstallCount(pl['managed_installs'])
                if installcount:
                    if munkicommon.munkistatusoutput:
                        if installcount == 1:
                            munkistatus.message("Installing 1 item...")
                        else:
                            munkistatus.message("Installing %i items..." % installcount)
                        # set indeterminate progress bar 
                        munkistatus.percent(-1)                        
                    munkicommon.log("Processing installs")
                    installs_need_restart = installWithInfo(installdir, pl['managed_installs'])
                                    
    else:
        munkicommon.log("No %s found." % installinfo)
        
    needtorestart = removals_need_restart or installs_need_restart
    if needtorestart:
        munkicommon.log("Software installed or removed requires a restart.")
        if munkicommon.munkistatusoutput:
            munkistatus.hideStopButton()
            munkistatus.message("Software installed or removed requires a restart.")
            munkistatus.percent(-1)
        else:
            print "Software installed or removed requires a restart."
            sys.stdout.flush()
           
    munkicommon.log("###    End managed installer session    ###")
    
    if needtorestart:
        if munkicommon.getconsoleuser() == None:
            time.sleep(5)
            cleanup()
            retcode = subprocess.call(["/sbin/shutdown", "-r", "now"])
        else:
            if munkicommon.munkistatusoutput:
                # someone is logged in and we're using munkistatus
                print "Notifying currently logged-in user to restart."
                munkistatus.activate()
                munkistatus.restartAlert()
                cleanup()
                munkicommon.osascript('tell application "System Events" to restart')
            else:
                print "Please restart immediately."
    else:
        cleanup()