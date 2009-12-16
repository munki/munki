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
import tempfile

import adobeutils
import munkicommon
import munkistatus
import FoundationPlist
from removepackages import removepackages


# initialize our report fields
# we do this here because appleupdates.installAppleUpdates()
# calls installWithInfo()
munkicommon.report['InstallResults'] = []
munkicommon.report['RemovalResults'] = []


def install(pkgpath, choicesXMLpath=None):
    """
    Uses the apple installer to install the package or metapackage
    at pkgpath. Prints status messages to STDOUT.
    Returns the installer return code and true if a restart is needed.
    """
    
    restartneeded = False
    installeroutput = []
    
    if os.path.islink(pkgpath):
        # resolve links before passing them to /usr/bin/installer
        pkgpath = os.path.realpath(pkgpath)
    
    packagename = ''
    restartaction = 'None'
    pkginfo = munkicommon.getInstallerPkgInfo(pkgpath)
    if pkginfo:
        packagename = pkginfo.get('display_name')
        restartaction = pkginfo.get('RestartAction','None')
    if not packagename:
        packagename = os.path.basename(pkgpath)
    
    if munkicommon.munkistatusoutput:
        munkistatus.message("Installing %s..." % packagename)
        munkistatus.detail("")
        # clear indeterminate progress bar 
        munkistatus.percent(0)
        
    munkicommon.log("Installing %s from %s" % (packagename,
                                               os.path.basename(pkgpath)))
    cmd = ['/usr/sbin/installer', '-query', 'RestartAction', '-pkg', pkgpath]
    if choicesXMLpath:
        cmd.extend(['-applyChoiceChangesXML', choicesXMLpath])
    p = subprocess.Popen(cmd, shell=False, bufsize=1, stdin=subprocess.PIPE, 
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (output, err) = p.communicate()
    restartaction = output.decode('UTF-8').rstrip("\n")
    if restartaction == "RequireRestart" or \
       restartaction == "RecommendRestart":
        munkicommon.display_status("%s requires a restart after installation."
                                    % packagename)
        restartneeded = True
        
    # get the OS version; we need it later when processing installer's output, 
    # which varies depnding on OS version.    
    osvers = int(os.uname()[2].split('.')[0])
    cmd = ['/usr/sbin/installer', '-verboseR', '-pkg', pkgpath, 
                                  '-target', '/']
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
                percent = float(msg[1:])
                if osvers < 10:
                    # Leopard uses a float from 0 to 1
                    percent = int(percent * 100)
                if munkicommon.munkistatusoutput:
                   munkistatus.percent(percent)
                else:
                    print "%s percent complete" % percent
                    sys.stdout.flush()
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
        munkicommon.display_error("-"*78)
        for line in installeroutput:
            munkicommon.display_error(line.rstrip("\n"))
        munkicommon.display_error("-"*78)
        restartneeded = False
    else:
        munkicommon.log("Install of %s was successful." % packagename)
        if munkicommon.munkistatusoutput:
            munkistatus.percent(100)
            
    return (retcode, restartneeded)


def installall(dirpath, choicesXMLpath=None):
    """
    Attempts to install all pkgs and mpkgs in a given directory.
    Will mount dmg files and install pkgs and mpkgs found at the
    root of any mountpoints.
    """
    retcode = 0
    restartflag = False
    installitems = os.listdir(dirpath)
    for item in installitems:
        if munkicommon.stopRequested():
            return (retcode, restartflag)
        itempath = os.path.join(dirpath, item)
        if item.endswith(".dmg"):
            munkicommon.display_info("Mounting disk image %s" % item)
            mountpoints = munkicommon.mountdmg(itempath)
            if mountpoints == []:
                munkicommon.display_error("No filesystems mounted from %s" %
                                           item)
                return (retcode, restartflag)
            if munkicommon.stopRequested():
                munkicommon.unmountdmg(mountpoints[0])
                return (retcode, restartflag)
            for mountpoint in mountpoints:
                # install all the pkgs and mpkgs at the root
                # of the mountpoint -- call us recursively!
                (retcode, needsrestart) = installall(mountpoint,
                                                     choicesXMLpath)
                if needsrestart:
                    restartflag = True
                if retcode:
                    # ran into error; should unmount and stop.
                    munkicommon.unmountdmg(mountpoints[0])
                    return (retcode, restartflag)  
                                  
            munkicommon.unmountdmg(mountpoints[0])
        
        if (item.endswith(".pkg") or item.endswith(".mpkg")):
            (retcode, needsrestart) = install(itempath, choicesXMLpath)
            if needsrestart:
                restartflag = True
            if retcode:
                # ran into error; should stop.
                return (retcode, restartflag)
                
    return (retcode, restartflag)
    
    
def copyAppFromDMG(dmgpath):
    # copies application from DMG to /Applications
    munkicommon.display_status("Mounting disk image %s" %
                                os.path.basename(dmgpath))
    mountpoints = munkicommon.mountdmg(dmgpath)
    if mountpoints:
        retcode = 0
        appfound = False
        mountpoint = mountpoints[0]
        # find an app at the root level, copy it to /Applications
        for item in os.listdir(mountpoint):
            itempath = os.path.join(mountpoint,item)
            if munkicommon.isApplication(itempath):
                appfound = True
                break
                
        if appfound:        
            destpath = os.path.join("/Applications", item)
            if os.path.exists(destpath):
                retcode = subprocess.call(["/bin/rm", "-r", destpath])
                if retcode:
                    munkicommon.display_error("Error removing existing "
                                              "%s" % destpath)
            if retcode == 0:
                munkicommon.display_status(
                            "Copying %s to Applications folder" % item)
                retcode = subprocess.call(["/bin/cp", "-pR", 
                                            itempath, destpath])
                if retcode:
                    munkicommon.display_error("Error copying %s to %s" % 
                                                (itempath, destpath))
            if retcode == 0:
                # remove com.apple.quarantine attribute from copied app
                cmd = ["/usr/bin/xattr", destpath]
                p = subprocess.Popen(cmd, shell=False, bufsize=1, 
                                     stdin=subprocess.PIPE, 
                                     stdout=subprocess.PIPE, 
                                     stderr=subprocess.PIPE)
                (out, err) = p.communicate()
                if out:
                    xattrs = out.splitlines()
                    if "com.apple.quarantine" in xattrs:
                        err = subprocess.call(["/usr/bin/xattr", "-d", 
                                               "com.apple.quarantine", 
                                               destpath])
                    
        munkicommon.unmountdmg(mountpoint)
        if not appfound:
            munkicommon.display_error("No application found on %s" %        
                                        os.path.basename(dmgpath))
            retcode = -2
            
        return retcode
    else:
        munkicommon.display_error("No mountable filesystems on %s" % 
                                    os.path.basename(dmgpath))
        return -1
    
    
def installWithInfo(dirpath, installlist):
    """
    Uses the installlist to install items in the
    correct order.
    """
    restartflag = False
    itemindex = 0
    for item in installlist:
        if munkicommon.stopRequested():
            return restartflag
        if "installer_item" in item:
            itemindex = itemindex + 1
            display_name = item.get('display_name') or item.get('name') or \
                           item.get('manifestitem')
            version_to_install = item.get('version_to_install','')
            if munkicommon.munkistatusoutput:
                munkistatus.message("Installing %s (%s of %s)..." % 
                                    (display_name, itemindex, 
                                     len(installlist)))
                munkistatus.detail("")
                munkistatus.percent(-1)
            else:
                munkicommon.display_status("Installing %s (%s of %s)" % 
                                            (display_name, itemindex, 
                                            len(installlist)))
            itempath = os.path.join(dirpath, item["installer_item"])
            if not os.path.exists(itempath):
                # can't install, so we should stop. Since later items might
                # depend on this one, we shouldn't continue
                munkicommon.display_error("Installer item %s was not found." %
                                           item["installer_item"])
                return restartflag
            installer_type = item.get("installer_type","")
            if installer_type == "AdobeUberInstaller":
                # Adobe CS4 installer
                pkgname = item.get("adobe_package_name") or \
                          item.get("package_path","")
                retcode = adobeutils.install(itempath, pkgname)
                if retcode == 8:
                    # Adobe Setup says restart needed
                    restartflag = True
                    retcode = 0
            elif installer_type == "AdobeSetup":
                # Adobe updater or Adobe CS3 installer
                retcode = adobeutils.runAdobeSetup(itempath)
                if retcode == 8:
                    # Adobe Setup says restart needed
                    restartflag = True
                    retcode = 0
            elif installer_type == "appdmg":
                retcode = copyAppFromDMG(itempath)
            else:
                # must be Apple installer package
                if 'installer_choices_xml' in item:
                    choicesXMLfile = os.path.join(munkicommon.tmpdir, 
                                                  "choices.xml")
                    FoundationPlist.writePlist(item['installer_choices_xml'],
                                               choicesXMLfile)
                else:
                    choicesXMLfile = ''
                if itempath.endswith(".dmg"):
                    munkicommon.display_status("Mounting disk image %s" %
                                                item["installer_item"])
                    mountpoints = munkicommon.mountdmg(itempath)
                    if mountpoints == []:
                        munkicommon.display_error("No filesystems mounted "
                                                  "from %s" %
                                                  item["installer_item"])
                        return restartflag
                    if munkicommon.stopRequested():
                        munkicommon.unmountdmg(mountpoints[0])
                        return restartflag
                    needtorestart = False
                    if item.get('package_path','').endswith('.pkg') or \
                       item.get('package_path','').endswith('.mpkg'):
                        # admin has specified the relative path of the pkg 
                        # on the DMG
                        # this is useful if there is more than one pkg on 
                        # the DMG, or the actual pkg is not at the root
                        # of the DMG
                        fullpkgpath = os.path.join(mountpoints[0],
                                                    item['package_path'])
                        if os.path.exists(fullpkgpath):
                            (retcode, needtorestart) = install(fullpkgpath,
                                                               choicesXMLfile)
                    else:
                        # no relative path to pkg on dmg, so just install all
                        # pkgs found at the root of the first mountpoint
                        # (hopefully there's only one)
                        (retcode, needtorestart) = installall(mountpoints[0],
                                                              choicesXMLfile)
                    if needtorestart:
                        restartflag = True
                    munkicommon.unmountdmg(mountpoints[0])
                else:
                    itempath = munkicommon.findInstallerItem(itempath)
                    if (itempath.endswith(".pkg") or \
                            itempath.endswith(".mpkg")):
                        (retcode, needtorestart) = install(itempath,
                                                           choicesXMLfile)
                        if needtorestart:
                            restartflag = True
                    elif os.path.isdir(itempath):
                        # directory of packages, 
                        # like what we get from Software Update
                        (retcode, needtorestart) = installall(itempath,
                                                              choicesXMLfile)
                        if needtorestart:
                            restartflag = True
                            
            # record install success/failure
            if retcode == 0:
                success_msg = ("Install of %s-%s: SUCCESSFUL" % 
                               (display_name, version_to_install))
                munkicommon.log(success_msg, "Install.log")
                munkicommon.report['InstallResults'].append(success_msg)
            else:
                failure_msg = ("Install of %s-%s: "
                               "FAILED with return code: %s" %
                               (display_name, version_to_install, retcode))
                munkicommon.log(failure_msg, "Install.log")
                munkicommon.report['InstallResults'].append(failure_msg)
                
            # check to see if this installer item is needed by any additional 
            # items in installinfo
            # this might happen if there are multiple things being installed 
            # with choicesXML files applied to a metapackage or
            # multiple packages being installed from a single DMG
            foundagain = False
            current_installer_item = item['installer_item']
            # are we at the end of the installlist?
            # (we already incremented itemindex for display
            # so with zero-based arrays itemindex now points to the item
            # after the current item)
            if itemindex < len(installlist):
                # nope, let's check the remaining items
                for lateritem in installlist[itemindex:]:
                    if 'installer_item' in lateritem:
                        if lateritem['installer_item'] == \
                                    current_installer_item:
                            foundagain = True
                            break
                        
            if not foundagain:
                # now remove the item from the install cache
                # (using rm -rf in case it's a bundle pkg)
                itempath = os.path.join(dirpath, current_installer_item)
                retcode = subprocess.call(["/bin/rm", "-rf", itempath])
    
    return restartflag


def processRemovals(removallist):
    restartFlag = False
    index = 0
    for item in removallist:
        if munkicommon.stopRequested():
            return restartFlag
        if 'installed' in item:
            if item['installed']:
                index += 1
                name = item.get('display_name') or item.get('name') or \
                       item.get('manifestitem')
                if munkicommon.munkistatusoutput:
                    munkistatus.message("Removing %s (%s of %s)..." % 
                                        (name, index, len(removallist)))
                    munkistatus.detail("")
                    munkistatus.percent(-1)
                else:
                    munkicommon.display_status("Removing %s (%s of %s)..." %
                                              (name, index, len(removallist)))
                
                if 'uninstall_method' in item:
                    uninstallmethod = item['uninstall_method'].split(' ')
                    if uninstallmethod[0] == "removepackages":
                        if 'packages' in item:
                            if item.get('RestartAction') == "RequireRestart":
                                restartFlag = True
                            retcode = removepackages(item['packages'],
                                                     forcedeletebundles=True)
                            if retcode:
                                if retcode == -128:
                                    message = ("Uninstall of %s was "
                                               "cancelled." % name)
                                else:
                                    message = "Uninstall of %s failed." % name
                                munkicommon.display_error(message)
                            else:
                                munkicommon.log("Uninstall of %s was"
                                                "successful." % name)
                                
                    elif uninstallmethod[0] == "AdobeUberUninstaller":
                        if "uninstaller_item" in item:
                            managedinstallbase = \
                                         munkicommon.pref('ManagedInstallDir')
                            itempath = os.path.join(managedinstallbase,
                                                    'Cache', 
                                                    item["uninstaller_item"])
                            if os.path.exists(itempath):
                                pkgname = item.get("adobe_package_name") or \
                                          item.get("pacakge_path","")
                                retcode = adobeutils.uninstall(itempath,
                                                               pkgname)
                                if retcode:
                                    munkicommon.display_error("Uninstall of "
                                                              "%s failed." %
                                                               name)
                            else:
                                munkicommon.display_error("Adobe"
                                                          "UberUninstaller "
                                                          "package for %s "          
                                                          "was missing from " 
                                                          "the Cache." % name)
                                
                    elif uninstallmethod[0] == "AdobeSetup":
                        if "uninstaller_item" in item:
                            managedinstallbase = \
                                        munkicommon.pref('ManagedInstallDir')
                            itempath = os.path.join(managedinstallbase,
                                                    'Cache',
                                                     item["uninstaller_item"])
                            if os.path.exists(itempath):
                                retcode = adobeutils.runAdobeSetup(itempath,
                                                            uninstalling=True)
                                if retcode:
                                    munkicommon.display_error("Uninstall of "
                                                              "%s failed." %
                                                               name)
                            else:
                                munkicommon.display_error("Adobe Setup "
                                                          "package for %s " 
                                                          "was missing from " 
                                                          "the Cache." % name)
                                
                    elif uninstallmethod[0] == "remove_app":
                        remove_app_info = item.get('remove_app_info',None)
                        if remove_app_info:
                            path_to_remove = remove_app_info['path']
                            munkicommon.display_status("Removing %s" %
                                                        path_to_remove)
                            retcode = subprocess.call(["/bin/rm", "-rf",
                                                        path_to_remove])
                            if retcode:
                                munkicommon.display_error("Removal error "
                                                          "for %s" %
                                                           path_to_remove)
                        else:
                            munkicommon.display_error("Application removal "
                                                      "info missing from %s" % 
                                                      name)
                        
                    elif os.path.exists(uninstallmethod[0]) and \
                         os.access(uninstallmethod[0], os.X_OK):
                        # it's a script or program to uninstall
                        if munkicommon.munkistatusoutput:
                            munkistatus.message("Running uninstall script "
                                                "for %s..." % name)
                            munkistatus.detail("")
                            # set indeterminate progress bar 
                            munkistatus.percent(-1)
                        
                        if item.get('RestartAction') == "RequireRestart":
                            restartFlag = True
                        
                        cmd = uninstallmethod
                        uninstalleroutput = []
                        p = subprocess.Popen(cmd, shell=False, bufsize=1, 
                                             stdin=subprocess.PIPE, 
                                             stdout=subprocess.PIPE, 
                                             stderr=subprocess.STDOUT)

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
                            message = \
                           "-------------------------------------------------"
                            print >>sys.stderr, message
                            munkicommon.log(message)
                            for line in uninstalleroutput:
                                print >>sys.stderr, "     ", line.rstrip("\n")
                                munkicommon.log(line.rstrip("\n"))
                            message = \
                           "-------------------------------------------------"
                            print >>sys.stderr, message
                            munkicommon.log(message)
                        else:
                            munkicommon.log("Uninstall of %s was "
                                            "successful." % name)
                            
                        if munkicommon.munkistatusoutput:
                            # clear indeterminate progress bar 
                            munkistatus.percent(0)
           
                    else:
                        munkicommon.log("Uninstall of %s failed because "
                                        "there was no valid uninstall "    
                                        "method." % name)
                        retcode = -99
                    
                    # record removal success/failure
                    if retcode == 0:
                        success_msg = "Removal of %s: SUCCESSFUL" % name
                        munkicommon.log(success_msg, "Install.log")
                        munkicommon.report[
                                         'RemovalResults'].append(success_msg)
                    else:
                        failure_msg = "Removal of %s: " % name + \
                                      " FAILED with return code: %s" % retcode
                        munkicommon.log(failure_msg, "Install.log")
                        munkicommon.report[
                                         'RemovalResults'].append(failure_msg)
                        
    return restartFlag


def run():
    managedinstallbase = munkicommon.pref('ManagedInstallDir')
    installdir = os.path.join(managedinstallbase , 'Cache')
    
    needtorestart = removals_need_restart = installs_need_restart = False
    munkicommon.log("### Beginning managed installer session ###")
    
    installinfo = os.path.join(managedinstallbase, 'InstallInfo.plist')
    if os.path.exists(installinfo):
        try:
            pl = FoundationPlist.readPlist(installinfo)
        except FoundationPlist.NSPropertyListSerializationException:
            print >>sys.stderr, "Invalid %s" % installinfo
            return -1
        
        # remove the install info file
        # it's no longer valid once we start running
        try:
            os.unlink(installinfo)
        except (OSError, IOError):
            munkicommon.display_warning("Could not remove %s" % installinfo)
        
        if "removals" in pl:
            # filter list to items that need to be removed
            removallist = [item for item in pl['removals'] 
                                if item.get('installed')]
            munkicommon.report['ItemsToRemove'] = removallist
            if removallist:
                if munkicommon.munkistatusoutput:
                    if len(removallist) == 1:
                        munkistatus.message("Removing 1 item...")
                    else:
                        munkistatus.message("Removing %i items..." % 
                                            len(removallist))
                    munkistatus.detail("")
                    # set indeterminate progress bar 
                    munkistatus.percent(-1)
                munkicommon.log("Processing removals")
                removals_need_restart = processRemovals(removallist)
        if "managed_installs" in pl:
            if not munkicommon.stopRequested():
                # filter list to items that need to be installed
                installlist = [item for item in pl['managed_installs'] 
                                    if item.get('installed') == False]
                munkicommon.report['ItemsToInstall'] = installlist
                if installlist:
                    if munkicommon.munkistatusoutput:
                        if len(installlist) == 1:
                            munkistatus.message("Installing 1 item...")
                        else:
                            munkistatus.message("Installing %i items..." %
                                                len(installlist))
                        munkistatus.detail("")
                        # set indeterminate progress bar 
                        munkistatus.percent(-1)
                    munkicommon.log("Processing installs")
                    installs_need_restart = installWithInfo(installdir,
                                                            installlist)
                                    
    else:
        munkicommon.log("No %s found." % installinfo)
    
    munkicommon.log("###    End managed installer session    ###")
    munkicommon.savereport()
    
    return (removals_need_restart or installs_need_restart)
    