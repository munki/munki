#!/usr/bin/env python
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
managedinstaller
Tool to automatically install pkgs, mpkgs, and dmgs
(containing pkgs and mpkgs) from a defined folder.
"""

import os
import subprocess
import sys
import time
import plistlib
import optparse
import munkilib
import munkistatus
from removepackages import removepackages

def stopRequested():
    if options.munkistatusoutput:
        if munkistatus.getStopButtonState() == 1:
            log("### User stopped session ###")
            return True
    return False


def cleanup():
    if options.munkistatusoutput:
        munkistatus.quit()


def createDirsIfNeeded(dirlist):
    for dir in dirlist:
        if not os.path.exists(dir):
            try:
                os.makedirs(dir, mode=0755)
            except:
                print >>sys.stderr, "Could not create %s" % dir
                return False
                
    return True


def log(message):
    logfile = os.path.join(logdir,'ManagedInstaller.log')
    try:
        f = open(logfile, mode='a', buffering=1)
        print >>f, time.ctime(), message
        f.close()
    except:
        pass


def install(pkgpath):
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
    packagename = output.splitlines()[0]
    
    if options.munkistatusoutput:
        munkistatus.message("Installing %s..." % packagename)
        munkistatus.detail("")
        # clear indeterminate progress bar 
        munkistatus.percent(0)
        
    log("Installing %s from %s" % (packagename, os.path.basename(pkgpath)))
    cmd = ['/usr/sbin/installer', '-query', 'RestartAction', '-pkg', pkgpath]
    p = subprocess.Popen(cmd, shell=False, bufsize=1, stdin=subprocess.PIPE, 
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (output, err) = p.communicate()
    restartaction = output.rstrip("\n")
    if restartaction == "RequireRestart":
        message = "%s requires a restart after installation." % packagename
        if options.munkistatusoutput:
            munkistatus.detail(message)
        else:
            print message
            sys.stdout.flush()
        log(message)
        restartneeded = True

    cmd = ['/usr/sbin/installer', '-verboseR', '-pkg', pkgpath, '-target', '/']
    p = subprocess.Popen(cmd, shell=False, bufsize=1, stdin=subprocess.PIPE, 
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    while (p.poll() == None): 
        installinfo =  p.stdout.readline()
        if installinfo.startswith("installer:"):
            # save all installer output in case there is
            # an error so we can dump it to the log
            installeroutput.append(installinfo)
            msg = installinfo[10:].rstrip("\n")
            if msg.startswith("PHASE:"):
                phase = msg[6:]
                if phase:
                    if options.munkistatusoutput:
                        munkistatus.detail(phase)
                    else:
                        print phase
                        sys.stdout.flush()
            elif msg.startswith("STATUS:"):
                status = msg[7:]
                if status:
                    if options.munkistatusoutput:
                        munkistatus.detail(status)
                    else:
                        print status 
                        sys.stdout.flush()
            elif msg.startswith("%"):
                if options.munkistatusoutput:
                    percent = float(msg[1:])
                    percent = int(percent * 100)
                    munkistatus.percent(percent)
            elif msg.startswith(" Error"):
                if options.munkistatusoutput:
                    munkistatus.detail(msg)
                else:
                    print >>sys.stderr, msg
                log(msg)
            elif msg.startswith(" Cannot install"):
                if options.munkistatusoutput:
                    munkistatus.detail(msg)
                else:
                    print >>sys.stderr, msg
                log(msg)
            else:
                log(msg)

    retcode = p.poll()
    if retcode:
        message = "Install of %s failed." % packagename
        if options.munkistatusoutput:
            munkistatus.detail(message)
        print >>sys.stderr, message
        log(message)
        message = "-------------------------------------------------"
        print >>sys.stderr, message
        log(message)
        for line in installeroutput:
            print >>sys.stderr, "     ", line.rstrip("\n")
            log(line.rstrip("\n"))
        message = "-------------------------------------------------"
        print >>sys.stderr, message
        log(message)
        restartneeded = False
    else:
        log("Install of %s was successful." % packagename)
        if options.munkistatusoutput:
            munkistatus.percent(100)
            
    return (retcode, restartneeded)


def installall(dirpath):
    """
    Attempts to install all pkgs and mpkgs in a given directory.
    Will mount dmg files and install pkgs and mpkgs found at the
    root of any mountpoints.
    """
    restartflag = False
    installitems = os.listdir(dirpath)
    for item in installitems:
        if stopRequested():
            return restartflag
        itempath = os.path.join(dirpath, item)
        if (item.endswith(".pkg") or item.endswith(".mpkg")):
            (retcode, needsrestart) = install(itempath)
            if needsrestart:
                restartflag = True
        if item.endswith(".dmg"):
            mountpoints = mountdmg(itempath)
            if stopRequested():
                for mountpoint in mountpoints:
                    unmountdmg(mountpoint)
                return restartflag
            for mountpoint in mountpoints:
                # install all the pkgs and mpkgs at the root
                # of the mountpoint -- call us recursively!
                needtorestart = installall(mountpoint)
                if needtorestart:
                    restartflag = True
                unmountdmg(mountpoint)
                
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
    for item in installlist:
        if stopRequested():
            return restartflag
        if "installer_item" in item:
            itempath = os.path.join(dirpath, item["installer_item"])
            if not os.path.exists(itempath):
                #can't install, so we should stop
                return restartflag
            if (itempath.endswith(".pkg") or itempath.endswith(".mpkg")):
                (retcode, needsrestart) = install(itempath)
                if needsrestart:
                    restartflag = True
            if itempath.endswith(".dmg"):
                mountpoints = mountdmg(itempath)
                if stopRequested():
                    for mountpoint in mountpoints:
                        unmountdmg(mountpoint)
                    return restartflag
                for mountpoint in mountpoints:
                    # install all the pkgs and mpkgs at the root
                    # of the mountpoint -- call us recursively!
                    needtorestart = installall(mountpoint)
                    if needtorestart:
                        restartflag = True
                    unmountdmg(mountpoint)
                
            # now remove the item from the install cache
            # (using rm -f in case it's a bundle pkg)
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
        if stopRequested():
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
                            if options.munkistatusoutput:
                                munkistatus.message("Removing %s..." % name)
                                munkistatus.detail("")
                                # clear indeterminate progress bar 
                                munkistatus.percent(0)                               
                            else:
                                print "Removing %s..." % name
                            
                            log("Removing %s..." % name)
                            retcode = removepackages(item['packages'], 
                                            munkistatusoutput=options.munkistatusoutput,
                                            forcedeletebundles=True,
                                            logfile=os.path.join(logdir,'ManagedInstaller.log'))
                            if retcode:
                                if retcode == -128:
                                    message = "Uninstall of %s was cancelled." % name
                                else:
                                    message = "Uninstall of %s failed." % name
                                print >>sys.stderr, message
                                log(message)
                            else:
                                log("Uninstall of %s was successful." % name)
                        
                    elif os.path.exists(uninstallmethod[0]) and os.access(uninstallmethod[0], os.X_OK):
                        # it's a script or program to uninstall
                        if options.munkistatusoutput:
                            munkistatus.message("Running uninstall script for %s..." % name)
                            munkistatus.detail("")
                            # set indeterminate progress bar 
                            munkistatus.percent(-1)
                        
                        if item.get('RestartAction') == "RequireRestart":
                            restartFlag = True
                        
                        cmd = uninstallmethod
                        uninstalleroutput = []
                        p = subprocess.Popen(cmd, shell=False, bufsize=1, stdin=subprocess.PIPE, 
                                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

                        while (p.poll() == None): 
                            msg =  p.stdout.readline()
                            # save all uninstaller output in case there is
                            # an error so we can dump it to the log
                            uninstalleroutput.append(msg)
                            msg = msg.rstrip("\n")
                            if options.munkistatusoutput:
                                # do nothing with the output
                                pass
                            else:
                                print msg
                    
                        retcode = p.poll()
                        if retcode:
                            message = "Uninstall of %s failed." % name
                            print >>sys.stderr, message
                            log(message)
                            message = "-------------------------------------------------"
                            print >>sys.stderr, message
                            log(message)
                            for line in uninstalleroutput:
                                print >>sys.stderr, "     ", line.rstrip("\n")
                                log(line.rstrip("\n"))
                            message = "-------------------------------------------------"
                            print >>sys.stderr, message
                            log(message)
                        else:
                            log("Uninstall of %s was successful." % name)
                            
                        if options.munkistatusoutput:
                            # clear indeterminate progress bar 
                            munkistatus.percent(0)
           
                    else:
                        log("Uninstall of %s failed because there was no valid uninstall method." % name)
                                    
    return restartFlag
                    
                    

def mountdmg(dmgpath):
    """
    Attempts to mount the dmg at dmgpath
    and returns a list of mountpoints
    """
    mountpoints = []
    dmgname = os.path.basename(dmgpath)
    if not options.munkistatusoutput:
        print "Mounting disk image %s" % dmgname
    log("Mounting disk image %s" % dmgname)
    p = subprocess.Popen(['/usr/bin/hdiutil', 'attach', dmgpath, '-mountRandom', '/tmp', '-nobrowse', '-plist'],
            bufsize=1, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (plist, err) = p.communicate()
    if plist:
        pl = plistlib.readPlistFromString(plist)
        for entity in pl['system-entities']:
            if 'mount-point' in entity:
                mountpoints.append(entity['mount-point'])

    return mountpoints


def unmountdmg(mountpoint):
    """
    Unmounts the dmg at mountpoint
    """
    p = subprocess.Popen(['/usr/bin/hdiutil', 'detach', mountpoint], 
        bufsize=1, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (output, err) = p.communicate()
    if err:
        print >>sys.stderr, err
        p = subprocess.Popen(['/usr/bin/hdiutil', 'detach', mountpoint, '-force'], 
            bufsize=1, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        (output, err) = p.communicate()
        
        
# module (global) variables
logdir = None
options = None


def main():
    global logdir, options
    managedinstallbase = munkilib.managed_install_dir()
    installdir = os.path.join(managedinstallbase , 'Cache')
    logdir = os.path.join(managedinstallbase, 'Logs')
    
    p = optparse.OptionParser()
    p.add_option('--munkistatusoutput', '-m', action='store_true')
    options, arguments = p.parse_args()
    
    needtorestart = False
    createDirsIfNeeded([logdir])
    log("### Beginning managed installer session ###")
    installinfo = os.path.join(managedinstallbase, 'InstallInfo.plist')
    if os.path.exists(installinfo):
        try:
            pl = plistlib.readPlist(installinfo)
        except:
            print >>sys.stderr, "Invalid %s" % installinfo
            exit(-1)
        
        # remove the install info file
        # it's no longer valid once we start running
        os.unlink(installinfo)
        
        if "removals" in pl:
            removalcount = getRemovalCount(pl['removals'])
            if removalcount:
                if options.munkistatusoutput:
                    if removalcount == 1:
                        munkistatus.message("Removing 1 item...")
                    else:
                        munkistatus.message("Removing %i items..." % removalcount)
                    # set indeterminate progress bar 
                    munkistatus.percent(-1)
                log("Processing removals")
                needtorestart = processRemovals(pl['removals'])
        if "managed_installs" in pl:
            if not stopRequested():
                installcount = getInstallCount(pl['managed_installs'])
                if installcount:
                    if options.munkistatusoutput:
                        if installcount == 1:
                            munkistatus.message("Installing 1 item...")
                        else:
                            munkistatus.message("Installing %i items..." % installcount)
                        # set indeterminate progress bar 
                        munkistatus.percent(-1)                        
                    log("Processing installs")
                    needtorestart = installWithInfo(installdir, pl['managed_installs'])
                                    
    else:
        log("No %s found." % installinfo)

    if needtorestart:
        log("Software installed or removed requires a restart.")
        if options.munkistatusoutput:
            munkistatus.hideStopButton()
            munkistatus.message("Software installed or removed requires a restart.")
            munkistatus.detail("")
            munkistatus.percent(-1)
        else:
            print "Software installed or removed requires a restart."
            sys.stdout.flush()
           
    log("###    End managed installer session    ###")
    
    if needtorestart:
        if munkilib.getconsoleuser() == None:
            time.sleep(5)
            cleanup()
            retcode = subprocess.call(["/sbin/shutdown", "-r", "now"])
        else:
            if options.munkistatusoutput:
                # someone is logged in and we're using MunkiStatus
                munkistatus.activate()
                munkistatus.osascript('tell application "MunkiStatus" to display alert "Restart Required" message "Software installed requires a restart. You will have a chance to save open documents." as critical default button "Restart"')
                cleanup()
                munkistatus.osascript('tell application "System Events" to restart')
            else:
                print "Please restart immediately."
    else:
        cleanup()


if __name__ == '__main__':
    main()
