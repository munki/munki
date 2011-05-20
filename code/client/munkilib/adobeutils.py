#!/usr/bin/python
# encoding: utf-8
"""
adobeutils.py

Utilities to enable munki to install/uninstall Adobe CS3/CS4/CS5 products
using the CS3/CS4/CS5 Deployment Toolkits.

"""
# Copyright 2009-2011 Greg Neagle.
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

#import sys
import os
import subprocess
import time
from xml.dom import minidom
import tempfile

import FoundationPlist
import munkicommon
import munkistatus

# dmg helper
# we need this instead of the one in munkicommon because the Adobe stuff
# needs the dmgs mounted under /Volumes.  We can merge this later (or not).
def mountAdobeDmg(dmgpath):
    """
    Attempts to mount the dmg at dmgpath
    and returns a list of mountpoints
    """
    mountpoints = []
    dmgname = os.path.basename(dmgpath)
    proc = subprocess.Popen(['/usr/bin/hdiutil', 'attach', dmgpath,
                            '-nobrowse', '-noverify', '-plist'],
                            bufsize=1, 
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (pliststr, err) = proc.communicate()
    if err:
        munkicommon.display_error("Error %s mounting %s." % (err, dmgname))
    if pliststr:
        plist = FoundationPlist.readPlistFromString(pliststr)
        for entity in plist['system-entities']:
            if 'mount-point' in entity:
                mountpoints.append(entity['mount-point'])

    return mountpoints


def getCS5uninstallXML(optionXMLfile):
    '''Gets the uninstall deployment data from a CS5 installer'''
    dom = minidom.parse(optionXMLfile)
    DeploymentInfo = dom.getElementsByTagName("DeploymentInfo")
    if DeploymentInfo:
        DeploymentUninstall = DeploymentInfo[0].getElementsByTagName(
                                                        "DeploymentUninstall")
        if DeploymentUninstall:
            deploymentData = DeploymentUninstall[0].getElementsByTagName(
                                                                "Deployment")
            if deploymentData:
                Deployment = deploymentData[0]
                return Deployment.toxml('UTF-8')
    return ""


def getCS5mediaSignature(dirpath):
    '''Returns the CS5 mediaSignature for an AAMEE CS5 install.
    dirpath is typically the root of a mounted dmg'''
    
    deploymentmgr = findAdobeDeploymentManager(dirpath)
    if deploymentmgr:
        parentdir = os.path.join(os.path.dirname(deploymentmgr), "Setup")
    else:
        return ""
    # now look for setup.xml
    setupxml = os.path.join(parentdir, "payloads", "Setup.xml")
    if os.path.exists(setupxml) and os.path.isfile(setupxml):
        # parse the XML
        dom = minidom.parse(setupxml)
        setupElements = dom.getElementsByTagName("Setup")
        if setupElements:
            mediaSignatureElements = \
                setupElements[0].getElementsByTagName("mediaSignature")
            if mediaSignatureElements:
                element = mediaSignatureElements[0]
                elementvalue = ''
                for node in element.childNodes:
                    elementvalue += node.nodeValue
                return elementvalue
    
    return ""
    
    
def getPayloadInfo(dirpath):
    '''Parses Adobe payloads, pulling out info useful to munki'''
    payloadinfo = {}
    # look for .proxy.xml file dir
    if os.path.isdir(dirpath):
        for item in munkicommon.listdir(dirpath):
            if item.endswith('.proxy.xml'):
                xmlpath = os.path.join(dirpath, item)
                dom = minidom.parse(xmlpath)
                payload_info = dom.getElementsByTagName("PayloadInfo")
                if payload_info:
                    installer_properties = \
                      payload_info[0].getElementsByTagName(
                        "InstallerProperties")
                    if installer_properties:
                        properties = \
                          installer_properties[0].getElementsByTagName(
                                                                   "Property")
                        for prop in properties:
                            if 'name' in prop.attributes.keys():
                                propname = \
                                 prop.attributes['name'].value.encode('UTF-8')
                                propvalue = ''
                                for node in prop.childNodes:
                                    propvalue += node.nodeValue
                                if propname == 'AdobeCode':
                                    payloadinfo['AdobeCode'] = propvalue
                                if propname == 'ProductName':
                                    payloadinfo['display_name'] = propvalue
                                if propname == 'ProductVersion':
                                    payloadinfo['version'] = propvalue
                                     
                    installmetadata = \
                        payload_info[0].getElementsByTagName(
                                                 "InstallDestinationMetadata")
                    if installmetadata:
                        totalsizes = \
                          installmetadata[0].getElementsByTagName("TotalSize")
                        if totalsizes:
                            installsize = ''
                            for node in totalsizes[0].childNodes:
                                installsize += node.nodeValue
                            payloadinfo['installed_size'] = \
                                                         int(installsize)/1024
                                                         
    return payloadinfo
    
    
def getAdobeSetupInfo(installroot):
    '''Given the root of mounted Adobe DMG,
    look for info about the installer or updater'''
    
    info = {}
    payloads = []
    
    # look for a payloads folder
    for (path, unused_dirs, unused_files) in os.walk(installroot):
        if path.endswith("/payloads"):
            driverfolder = ''
            mediaSignature = ''
            setupxml = os.path.join(path, "setup.xml")
            if os.path.exists(setupxml):
                dom = minidom.parse(setupxml)
                drivers =  dom.getElementsByTagName("Driver")
                if drivers:
                    driver = drivers[0]
                    if 'folder' in driver.attributes.keys():
                        driverfolder = \
                             driver.attributes['folder'].value.encode('UTF-8')
                if driverfolder == '':
                    # look for mediaSignature (CS5 AAMEE install)
                    setupElements = dom.getElementsByTagName("Setup")
                    if setupElements:
                        mediaSignatureElements = \
                            setupElements[0].getElementsByTagName(
                                                            "mediaSignature")
                        if mediaSignatureElements:
                            element = mediaSignatureElements[0]
                            for node in element.childNodes:
                                mediaSignature += node.nodeValue
                            
            for item in munkicommon.listdir(path):
                payloadpath = os.path.join(path, item)
                payloadinfo = getPayloadInfo(payloadpath)
                if payloadinfo:
                    payloads.append(payloadinfo)
                    if (driverfolder and item == driverfolder) or \
                       (mediaSignature and 
                            payloadinfo['AdobeCode'] == mediaSignature):
                        info['display_name'] = payloadinfo['display_name']
                        info['version'] = payloadinfo['version']
                        info['AdobeSetupType'] = "ProductInstall"
                        
            # we found a payloads directory, 
            # so no need to keep walking the installroot
            break

    if not payloads:
        # look for an extensions folder; almost certainly this is an Updater
        for (path, unused_dirs, unused_files) in os.walk(installroot):
            if path.endswith("/extensions"):
                for item in munkicommon.listdir(path):
                    #skip LanguagePacks
                    if item.find("LanguagePack") == -1:
                        itempath = os.path.join(path, item)
                        payloadinfo = getPayloadInfo(itempath)
                        if payloadinfo:
                            payloads.append(payloadinfo)
                        
                # we found an extensions dir, 
                # so no need to keep walking the install root
                break
                   
    if payloads:
        if len(payloads) == 1:
            info['display_name'] = payloads[0]['display_name']
            info['version'] = payloads[0]['version']
        else:
            if not 'display_name' in info:
                info['display_name'] = "ADMIN: choose from payloads"
            if not 'version' in info:
                info['version'] = "ADMIN please set me"
        info['payloads'] = payloads
        installed_size = 0
        for payload in payloads:
            installed_size = installed_size + \
                             payload.get('installed_size',0)
        info['installed_size'] = installed_size
    return info


def getAdobePackageInfo(installroot):
    '''Gets the package name from the AdobeUberInstaller.xml file;
    other info from the payloads folder'''
    
    info = getAdobeSetupInfo(installroot)
    info['description'] = ""
    installerxml = os.path.join(installroot, "AdobeUberInstaller.xml")
    if os.path.exists(installerxml):
        description = ''
        dom = minidom.parse(installerxml)
        installinfo = dom.getElementsByTagName("InstallInfo")
        if installinfo:
            packagedescriptions = \
                installinfo[0].getElementsByTagName("PackageDescription")
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
        else:
            installerxml = os.path.join(installroot, "optionXML.xml")
            if os.path.exists(installerxml):
                dom = minidom.parse(installerxml)
                installinfo = dom.getElementsByTagName("InstallInfo")
                if installinfo:
                    pkgname_elems = installinfo[0].getElementsByTagName(
                                                                "PackageName")
                    if pkgname_elems:
                        prop = pkgname_elems[0]
                        pkgname = ""
                        for node in prop.childNodes:
                            pkgname += node.nodeValue
                        info['display_name'] = pkgname
                        
    if not info.get('display_name'):
        info['display_name'] = os.path.basename(installroot)      
    return info
    
    
def getAdobeInstallLog():
    '''Returns the current Adobe install log'''
    
    logpath = "/Library/Logs/Adobe/Installers"
    # find the most recently-modified log file
    proc = subprocess.Popen(['/bin/ls', '-t1', logpath], 
                            bufsize=1, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    (output, unused_err) = proc.communicate()
    if output:
        firstitem = str(output).splitlines()[0]
        if firstitem.endswith(".log"):
            # get the last line of the most recently modified log
            return os.path.join(logpath, firstitem)
            
    return None


def getAdobeInstallProgressInfo(previous_completedpayloads,
                                            previous_payloadname):
    '''Returns the number of completed Adobe payloads,
    and the name of the most recentlly completed payload.'''
    
    completedpayloads = previous_completedpayloads
    lastpayloadname = previous_payloadname
    
    logfile = getAdobeInstallLog()
    if logfile:
        # get number of completed payloads
        regex = "(Completing installation for payload at )"
        regex += "|"
        regex += "(Physical payload uninstall result)"
        cmd = ['/usr/bin/grep', '-c', "-E", regex, logfile]
        proc = subprocess.Popen(cmd, bufsize=1, 
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        (output, unused_err) = proc.communicate()
        if output:
            try:
                completedpayloads = int(str(output).rstrip("\n"))
            except (ValueError, TypeError):
                completedpayloads = previous_completedpayloads
                
        if completedpayloads > previous_completedpayloads:
            # now try to get the name of the most recently completed payload
            # this isn't 100% accurate, but it's mostly for show anyway...
            regex = " for payload \{.*\} "
            cmd = ['/usr/bin/grep', "-E", regex, logfile]
            proc = subprocess.Popen(cmd, bufsize=1, 
                                    stdout=subprocess.PIPE, 
                                    stderr=subprocess.PIPE)
            (output, unused_err) = proc.communicate()
            if output:
                # start with the last line of the output
                # and work backwards until we find a name
                lines = str(output).splitlines()
                lines.reverse()
                for line in lines:
                    parts = line.split("}", 1)
                    if len(parts) == 2:
                        if parts[1]:
                            name = parts[1].lstrip()
                            if not name.startswith("returned :"):
                                lastpayloadname = name
                                break
            
    return (completedpayloads, lastpayloadname)


def countPayloads(dirpath):
    '''Attempts to count the payloads in the Adobe installation item'''
    for item in munkicommon.listdir(dirpath):
        itempath = os.path.join(dirpath, item)
        if os.path.isdir(itempath):
            if item == "payloads":
                count = 0
                for subitem in munkicommon.listdir(itempath):
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
    '''Returns a value useful with MunkiStatus to use when 
    displaying precent-done stauts'''
    if maximum == 0:
        percentdone = -1
    elif current < 0:
        percentdone = -1
    elif current > maximum:
        percentdone = -1
    elif current == maximum:
        percentdone = 100
    else:
        percentdone = int(float(current)/float(maximum)*100)
    return percentdone
    
    
def findSetupApp(dirpath):
    '''Search dirpath and enclosed directories for Setup.app.
    Returns the path to the actual executable.'''
    for (path, unused_dirs, unused_files) in os.walk(dirpath):
        if path.endswith("Setup.app"):
            setup_path = os.path.join(path, "Contents", "MacOS", "Setup")
            if os.path.exists(setup_path):
                return setup_path
    return ''
    
    
def findInstallApp(dirpath):
    '''Searches dirpath and enclosed directories for Install.app.
    Returns the path to the actual executable.'''
    for (path, unused_dirs, unused_files) in os.walk(dirpath):
        if path.endswith("Install.app"):
            setup_path = os.path.join(path, "Contents", "MacOS", "Install")
            if os.path.exists(setup_path):
                return setup_path
    return ''


def findAdobePatchInstallerApp(dirpath):
    '''Searches dirpath and enclosed directories for AdobePatchInstaller.app. 
    Returns the path to the actual executable.'''
    for (path, unused_dirs, unused_files) in os.walk(dirpath):
        if path.endswith("AdobePatchInstaller.app"):
            setup_path = os.path.join(path, "Contents", "MacOS",
                                                    "AdobePatchInstaller")
            if os.path.exists(setup_path):
                return setup_path
    return ''


def findAdobeDeploymentManager(dirpath):
    '''Searches dirpath and enclosed directories for AdobeDeploymentManager.
    Returns path to the executable.'''
    for (path, unused_dirs, unused_files) in os.walk(dirpath):
        if path.endswith("pkg/Contents/Resources"):
            dm_path = os.path.join(path, "AdobeDeploymentManager")
            if os.path.exists(dm_path):
                return dm_path
    return ''
    
    
def getPID(processname):
    '''Returns process ID for a command string'''
    cmd = ['/bin/ps', '-eo', 'pid=,command=']
    proc = subprocess.Popen(cmd, shell=False, bufsize=1, 
                            stdin=subprocess.PIPE, 
                            stdout=subprocess.PIPE, 
                            stderr=subprocess.PIPE)
    (out, unused_err) = proc.communicate()
    lines = str(out).splitlines()
    for line in lines:
        (pid, process) = line.split(None, 1)
        if process.find(processname) != -1:
            return pid
            
    return 0
    

secondsToLive = {}
def killStupidProcesses():
    '''A nasty bit of hackery to get Adobe CS5 AAMEE packages to install
    when at the loginwindow.'''
    stupid_processes = ["Adobe AIR Installer",
                        "Adobe AIR Application Installer",
                        "InstallAdobeHelp",
                        "open -a /Library/Application Support/Adobe/SwitchBoard/SwitchBoard.app"]
                        
    for procname in stupid_processes:
        pid = getPID(procname)
        if pid:
            if not pid in secondsToLive:
                secondsToLive[pid] = 30
            else:
                secondsToLive[pid] = secondsToLive[pid] - 1
                if secondsToLive[pid] == 0:
                    # it's been running too long; kill it
                    munkicommon.log("Killing PID %s: %s" % (pid, procname))
                    try:
                        os.kill(int(pid), 9)
                    except OSError:
                        pass
                    # remove this PID from our list
                    del secondsToLive[pid]
                    # only kill one process per invocation
                    return


def runAdobeInstallTool(cmd, number_of_payloads=0, killAdobeAIR=False):
    '''An abstraction of the tasks for running Adobe Setup,
    AdobeUberInstaller, AdobeUberUninstaller, AdobeDeploymentManager, etc'''
    if munkicommon.munkistatusoutput and not number_of_payloads:
        # indeterminate progress bar
        munkistatus.percent(-1)
    
    proc = subprocess.Popen(cmd, shell=False, bufsize=1, 
                            stdin=subprocess.PIPE, 
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                         
    old_payload_completed_count = 0
    payloadname = ""
    while (proc.poll() == None): 
        time.sleep(1)
        (payload_completed_count, payloadname) = \
             getAdobeInstallProgressInfo(old_payload_completed_count,
                                                                payloadname)
        if payload_completed_count > old_payload_completed_count:
            old_payload_completed_count = payload_completed_count
            if payloadname:
                payloadinfo = " - " + payloadname
            else:
                payloadinfo = ""
            if number_of_payloads:
                
                munkicommon.display_status("Completed payload %s of %s%s" %
                   (payload_completed_count, number_of_payloads, payloadinfo))
            else:
                munkicommon.display_status("Completed payload %s%s" %
                                       (payload_completed_count, payloadinfo))
            if munkicommon.munkistatusoutput:
                munkistatus.percent(getPercent(payload_completed_count,
                                                          number_of_payloads))
        
        # Adobe AIR Installer workaround/hack
        # CSx installs at the loginwindow hang when Adobe AIR is installed.
        # So we check for this and kill the process. Ugly.
        # Hopefully we can disable this in the future.
        if killAdobeAIR:
            if (not munkicommon.getconsoleuser() or
                   munkicommon.getconsoleuser() == u"loginwindow"):
                # we're at the loginwindow.
                killStupidProcesses()
                
    # run of tool completed  
    retcode = proc.poll()
    
    #check output for errors
    output = proc.stdout.readlines()
    for line in output:
        line = line.rstrip("\n")
        if line.startswith("Error"):
            munkicommon.display_error(line)
        if line.startswith("Exit Code:"):
            if retcode == 0:
                try:
                    retcode = int(line[11:])
                except (ValueError, TypeError):
                    retcode = -1
        
    if retcode != 0 and retcode != 8:
        munkicommon.display_error("Adobe Setup error: %s: %s" % 
                                   (retcode, adobeSetupError(retcode)))
    else:
        if munkicommon.munkistatusoutput:
            munkistatus.percent(100)
        munkicommon.display_status("Done.")
        
    return retcode


def runAdobeSetup(dmgpath, uninstalling=False):
    '''Runs the Adobe setup tool in silent mode from
    an Adobe update DMG or an Adobe CS3 install DMG'''
    munkicommon.display_status("Mounting disk image %s" %
                                os.path.basename(dmgpath))
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
                    # we've been asked to uninstall, 
                    # but found no uninstall.xml
                    # so we need to bail
                    munkicommon.unmountdmg(mountpoints[0])
                    munkicommon.display_error(
                              "%s doesn't appear to contain uninstall info." %
                               os.path.basename(dmgpath))
                    return -1
            else:
                if os.path.exists(installxml):
                    deploymentfile = installxml
            
            # try to find and count the number of payloads 
            # so we can give a rough progress indicator
            number_of_payloads = countPayloads(mountpoints[0])
            munkicommon.display_status("Running Adobe Setup")
            adobe_setup = [ setup_path, '--mode=silent',  
                            '--skipProcessCheck=1' ]
            if deploymentfile:
                adobe_setup.append('--deploymentFile=%s' % deploymentfile)
                
            retcode = runAdobeInstallTool(adobe_setup, number_of_payloads)
            
        else:
            munkicommon.display_error(
                             "%s doesn't appear to contain Adobe Setup." % 
                             os.path.basename(dmgpath))
            retcode = -1
            
        munkicommon.unmountdmg(mountpoints[0])
        return retcode
    else:
        munkicommon.display_error("No mountable filesystems on %s" % dmgpath)
        return -1


def writefile(stringdata, path):
    '''Writes string data to path.
    Returns the path on success, empty string on failure.'''
    try:
        fileobject = open(path, mode='w', buffering=1)
        print >> fileobject, stringdata.encode('UTF-8')
        fileobject.close()
        return path
    except (OSError, IOError):
        munkicommon.display_error("Couldn't write %s" % stringdata)
        return ""


def doAdobeCS5Uninstall(adobeInstallInfo):
    '''Runs the locally-installed Adobe CS5 tools to remove CS5 products.
    We need the uninstallxml and the CS5 Setup.app.'''
    uninstallxml = adobeInstallInfo.get('uninstallxml')
    if not uninstallxml:
        munkicommon.display_error("No uninstall.xml in adobe_install_info")
        return -1
    payloadcount = adobeInstallInfo.get('payload_count', 0)
    path = os.path.join(munkicommon.tmpdir, "uninstall.xml")
    deploymentFile = writefile(uninstallxml, path)
    if not deploymentFile:
        return -1
    setupapp = "/Library/Application Support/Adobe/OOBE/PDApp/DWA/Setup.app"
    setup = os.path.join(setupapp, "Contents/MacOS/Setup")
    if not os.path.exists(setup):
        munkicommon.display_error("%s is not installed." % setupapp)
        return -1
    uninstall_cmd = [ setup, 
                    '--mode=silent', 
                    '--action=uninstall',
                    '--skipProcessCheck=1', 
                    '--deploymentFile=%s' % deploymentFile ]
    munkicommon.display_status("Running Adobe Uninstall")
    return runAdobeInstallTool(uninstall_cmd, payloadcount)
    
    
def runAdobeCS5AAMEEInstall(dmgpath):
    '''Installs a CS5 product using an AAMEE-generated package on a 
    disk image.'''
    munkicommon.display_status("Mounting disk image %s" %
                                os.path.basename(dmgpath))
    mountpoints = mountAdobeDmg(dmgpath)
    if not mountpoints:
        munkicommon.display_error("No mountable filesystems on %s" % dmgpath)
        return -1
        
    deploymentmanager = findAdobeDeploymentManager(mountpoints[0])
    if deploymentmanager:
        # big hack to convince the Adobe tools to install off a mounted
        # disk image.
        # For some reason, the Adobe install tools refuse to install when
        # the payloads are on a "removable" disk, which includes mounted disk
        # images.
        # we create a temporary directory on the local disk and then symlink
        # some resources from the mounted disk image to the temporary
        # directory. When we pass this temporary directory to the Adobe
        # installation tools, they are now happy.
        basepath = os.path.dirname(deploymentmanager)
        number_of_payloads = countPayloads(basepath)
        tmpdir = tempfile.mkdtemp()
        
        # make our symlinks
        os.symlink(os.path.join(basepath,"ASU"), os.path.join(tmpdir, "ASU"))
        os.symlink(os.path.join(basepath,"ProvisioningTool"), 
                                    os.path.join(tmpdir, "ProvisioningTool"))
        
        realsetupdir = os.path.join(basepath,"Setup")
        tmpsetupdir = os.path.join(tmpdir, "Setup")
        os.mkdir(tmpsetupdir)
        for item in munkicommon.listdir(realsetupdir):
            os.symlink(os.path.join(realsetupdir, item), 
                                            os.path.join(tmpsetupdir, item))
                                            
        optionXMLfile = os.path.join(basepath, "optionXML.xml")
        if (not munkicommon.getconsoleuser() or
               munkicommon.getconsoleuser() == u"loginwindow"):
            # we're at the loginwindow, so we need to run the deployment
            # manager in the loginwindow context using launchctl bsexec
            loginwindowPID = getPID("loginwindow")
            cmd = ['/bin/launchctl', 'bsexec', loginwindowPID]
        else:
            cmd = []
               
        cmd.extend([deploymentmanager, '--optXMLPath=%s' % optionXMLfile,
                '--setupBasePath=%s' % tmpdir, '--installDirPath=/',
                '--mode=install'])
                
        munkicommon.display_status("Starting Adobe CS5 installer...")
        retcode = runAdobeInstallTool(cmd, number_of_payloads,
                                                            killAdobeAIR=True)
        # now clean up our symlink hackfest
        unused_result = subprocess.call(["/bin/rm", "-rf", tmpdir])
    else:
        munkicommon.display_error(
                       "%s doesn't appear to contain AdobeDeploymentManager" %
                       os.path.basename(dmgpath))
        retcode = -1
        
    munkicommon.unmountdmg(mountpoints[0])
    return retcode
    

def runAdobeCS5PatchInstaller(dmgpath, copylocal=False):
    '''Runs the AdobePatchInstaller for CS5.
    Optionally can copy the DMG contents to the local disk
    to work around issues with the patcher.'''
    munkicommon.display_status("Mounting disk image %s" %
                                os.path.basename(dmgpath))
    mountpoints = mountAdobeDmg(dmgpath)
    if mountpoints:
        if copylocal:
            # copy the update to the local disk before installing
            updatedir = tempfile.mkdtemp()
            retcode = subprocess.call(["/bin/cp", "-r", 
                                            mountpoints[0], updatedir])
            # unmount diskimage
            munkicommon.unmountdmg(mountpoints[0])
            if retcode:
                munkicommon.display_error(
                                "Error copying items from %s" % dmgpath)
                return -1
            # remove the dmg file to free up space, since we don't need it
            # any longer
            unused_result = subprocess.call(["/bin/rm", dmgpath])
        else:
            updatedir = mountpoints[0]
            
        patchinstaller = findAdobePatchInstallerApp(updatedir)
        if patchinstaller:
            # try to find and count the number of payloads 
            # so we can give a rough progress indicator
            number_of_payloads = countPayloads(updatedir)
            munkicommon.display_status("Running Adobe Patch Installer")
            install_cmd = [ patchinstaller, 
                            '--mode=silent',  
                            '--skipProcessCheck=1' ]
            retcode = runAdobeInstallTool(install_cmd,
                                          number_of_payloads)
        else:
            munkicommon.display_error(
                    "%s doesn't appear to contain AdobePatchInstaller.app." % 
                    os.path.basename(dmgpath))
            retcode = -1
        if copylocal:
            # clean up our mess
            unused_result = subprocess.call(["/bin/rm", "-rf", updatedir])
        else:
            munkicommon.unmountdmg(mountpoints[0])
        return retcode
    else:
        munkicommon.display_error("No mountable filesystems on %s" % dmgpath)
        return -1


def runAdobeUberTool(dmgpath, pkgname='', uninstalling=False):
    '''Runs either AdobeUberInstaller or AdobeUberUninstaller
    from a disk image and provides progress feedback.
    pkgname is the name of a directory at the top level of the dmg
    containing the AdobeUber tools and their XML files.'''
    
    munkicommon.display_status("Mounting disk image %s" %
                                os.path.basename(dmgpath))
    mountpoints = mountAdobeDmg(dmgpath)
    if mountpoints:
        installroot = mountpoints[0]
        if uninstalling:
            ubertool = os.path.join(installroot, pkgname,
                                    "AdobeUberUninstaller")
        else:
            ubertool = os.path.join(installroot, pkgname,
                                    "AdobeUberInstaller")
            
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


#lastpatchlogline = ''
#def getAcrobatPatchLogInfo(logpath):
#    '''Gets info from the Adobe Acrobat patch log'''
#    global lastpatchlogline
#    if os.path.exists(logpath):
#        proc = subprocess.Popen(['/usr/bin/tail', '-1', logpath], 
#                                bufsize=1, stdout=subprocess.PIPE,
#                                stderr=subprocess.PIPE)
#        (output, err) = proc.communicate()
#        logline = output.rstrip('\n')
#        # is it different than the last time we checked?
#        if logline != lastpatchlogline:
#            lastpatchlogline = logline
#            return logline
#    return ''


def findAcrobatPatchApp(dirpath):
    '''Attempts to find an AcrobatPro patching application
    in dirpath. If found, returns the path to the bundled
    patching script.'''
    
    for (path, unused_dirs, unused_files) in os.walk(dirpath):
        if path.endswith(".app"):
            # look for Adobe's patching script
            patch_script_path = os.path.join(path, "Contents", "Resources",
                                        "ApplyOperation.py")
            if os.path.exists(patch_script_path):
                return path
    return ''


def updateAcrobatPro(dmgpath):
    """Uses the scripts and Resources inside the Acrobat Patch application 
    bundle to silently update Acrobat Pro and related apps
    Why oh why does this use a different mechanism than the other Adobe 
    apps?"""
    
    if munkicommon.munkistatusoutput:
        munkistatus.percent(-1)
    
    #first mount the dmg
    munkicommon.display_status("Mounting disk image %s" %
                                os.path.basename(dmgpath))
    mountpoints = mountAdobeDmg(dmgpath)
    if mountpoints:
        installroot = mountpoints[0]
        pathToAcrobatPatchApp = findAcrobatPatchApp(installroot)
    else:
        munkicommon.display_error("No mountable filesystems on %s" % dmgpath)
        return -1
        
    if not pathToAcrobatPatchApp:
        munkicommon.display_error("No Acrobat Patch app at %s" %
                                   pathToAcrobatPatchApp)
        munkicommon.unmountdmg(installroot)
        return -1
        
    # some values needed by the patching script
    resourcesDir = os.path.join(pathToAcrobatPatchApp, 
                                "Contents", "Resources")
    ApplyOperation = os.path.join(resourcesDir, "ApplyOperation.py")        
    callingScriptPath = os.path.join(resourcesDir, "InstallUpdates.sh")
    
    appList = []
    appListFile = os.path.join(resourcesDir, "app_list.txt")
    if os.path.exists(appListFile):
        fileobj = open(appListFile, mode='r', buffering=1)
        if fileobj:
            for line in fileobj.readlines():
                appList.append(line)
            fileobj.close()
            
    if not appList:
        munkicommon.display_error("Did not find a list of apps to update.")
        munkicommon.unmountdmg(installroot)
        return -1
        
    payloadNum = -1
    for line in appList:
        payloadNum = payloadNum + 1
        if munkicommon.munkistatusoutput:
            munkistatus.percent(getPercent(payloadNum+1, len(appList)+1))
        
        (appname, status) = line.split("\t")
        munkicommon.display_status("Searching for %s" % appname)
        # first look in the obvious place
        pathname = os.path.join("/Applications/Adobe Acrobat 9 Pro", appname)
        if os.path.exists(pathname):
            item = {}
            item['path'] = pathname
            candidates = [item]
        else:
            # use system_profiler to search for the app
            candidates = [item for item in munkicommon.getAppData()
                          if item['path'].endswith('/' + appname)]
                      
        # hope there's only one!
        if len(candidates) == 0:
            if status == "optional":
                continue
            else:
                munkicommon.display_error("Cannot patch %s because it "
                                          "was not found on the startup "
                                          "disk." % appname)
                munkicommon.unmountdmg(installroot)
                return -1
                
        if len(candidates) > 1:
            munkicommon.display_error("Cannot patch %s because we found "
                                      "more than one copy on the "
                                      "startup disk." % appname)
            munkicommon.unmountdmg(installroot)
            return -1
        
        munkicommon.display_status("Updating %s" % appname)
        apppath = os.path.dirname(candidates[0]["path"])
        cmd = [ApplyOperation, apppath, appname, resourcesDir,
               callingScriptPath, str(payloadNum)]
        
        # figure out the log file path
        #patchappname = os.path.basename(pathToAcrobatPatchApp)
        #logfile_name = patchappname.split('.')[0] + str(payloadNum) + '.log'
        #homePath = os.path.expanduser("~")
        #logfile_dir = os.path.join(homePath, "Library", "Logs", 
        #                                    "Adobe", "Acrobat")
        #logfile_path = os.path.join(logfile_dir, logfile_name)
        
        proc = subprocess.Popen(cmd, shell=False, bufsize=1,
                                stdin=subprocess.PIPE, 
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT)
        while (proc.poll() == None): 
            time.sleep(1)
            #loginfo = getAcrobatPatchLogInfo(logfile_path)
            #if loginfo:
            #    print loginfo
                
        # run of patch tool completed  
        retcode = proc.poll()
        if retcode != 0:
            munkicommon.display_error("Error patching %s: %s" % 
                                       (appname, retcode))
            break
        else:
            munkicommon.display_status("Patching %s complete." % appname)
    
    munkicommon.display_status("Done.")
    if munkicommon.munkistatusoutput:
        munkistatus.percent(100)
    
    munkicommon.unmountdmg(installroot)
    return retcode
    

def getBundleInfo(path):
    """
    Returns Info.plist data if available
    for bundle at path
    """
    infopath = os.path.join(path, "Contents", "Info.plist")
    if not os.path.exists(infopath):
        infopath = os.path.join(path, "Resources", "Info.plist")

    if os.path.exists(infopath):
        try:
            plist = FoundationPlist.readPlist(infopath)
            return plist
        except FoundationPlist.NSPropertyListSerializationException:
            pass

    return None
    
    
def getAdobeInstallInfo(installdir):
    '''Encapsulates info used by the Adobe Setup/Install app.'''
    adobeInstallInfo = {}
    if installdir:
        adobeInstallInfo['media_signature'] = getCS5mediaSignature(installdir)
        adobeInstallInfo['payload_count'] = countPayloads(installdir)
        optionXMLfile = os.path.join(installdir, "optionXML.xml")
        if os.path.exists(optionXMLfile):
            adobeInstallInfo['uninstallxml'] = \
                                            getCS5uninstallXML(optionXMLfile)
                                            
    return adobeInstallInfo
    

def getAdobeCatalogInfo(mountpoint, pkgname=""):
    '''Used by makepkginfo to build pkginfo data for Adobe
    installers/updaters'''
    
    # look for AdobeDeploymentManager (AAMEE installer)
    deploymentmanager = findAdobeDeploymentManager(mountpoint)
    if deploymentmanager:
        dirpath = os.path.dirname(deploymentmanager)
        cataloginfo = getAdobePackageInfo(dirpath)
        if cataloginfo:
            # add some more data
            cataloginfo['name'] = \
                cataloginfo['display_name'].replace(" ",'')
            cataloginfo['uninstallable'] = True
            cataloginfo['uninstall_method'] = "AdobeCS5AAMEEPackage"
            cataloginfo['installer_type'] = "AdobeCS5AAMEEPackage"
            cataloginfo['minimum_os_version'] = "10.5.0"
            cataloginfo['adobe_install_info'] = getAdobeInstallInfo(
                                                        installdir=dirpath)
            mediasignature = cataloginfo['adobe_install_info'].get(
                                                            "media_signature")
            if mediasignature:
                # make a default <key>installs</key> entry
                uninstalldir = "/Library/Application Support/Adobe/Uninstall"
                signaturefile = mediasignature + ".db"
                filepath = os.path.join(uninstalldir, signaturefile)
                installs = []
                installitem = {}
                installitem['path'] = filepath
                installitem['type'] = 'file'
                installs.append(installitem)
                cataloginfo['installs'] = installs
            
            return cataloginfo
            
    # Look for Install.app (Bare metal CS5 install)
    # we don't handle this type, but we'll report it
    # back so makepkginfo can provide an error message
    installapp = findInstallApp(mountpoint)
    if installapp:
        cataloginfo = {}
        cataloginfo['installer_type'] = "AdobeCS5Installer"
        return cataloginfo
        
    # Look for AdobePatchInstaller.app (CS5 updater)
    installapp = findAdobePatchInstallerApp(mountpoint)
    if os.path.exists(installapp):
        # this is a CS5 updater disk image
        cataloginfo = getAdobePackageInfo(mountpoint)
        if cataloginfo:
            # add some more data
            cataloginfo['name'] = \
                cataloginfo['display_name'].replace(" ",'')
            cataloginfo['uninstallable'] = False
            cataloginfo['installer_type'] = "AdobeCS5PatchInstaller"
            if pkgname:
                cataloginfo['package_path'] = pkgname
                
            # make some (hopfully functional) installs items from the payloads
            installs = []
            uninstalldir = "/Library/Application Support/Adobe/Uninstall"
            # first look for a payload with a display_name matching the
            # overall display_name
            for payload in cataloginfo.get('payloads', []):
                if (payload.get('display_name','') ==
                                           cataloginfo['display_name']):
                    if 'AdobeCode' in payload:
                        dbfile = payload['AdobeCode'] + ".db"
                        filepath = os.path.join(uninstalldir, dbfile)
                        installitem = {}
                        installitem['path'] = filepath
                        installitem['type'] = 'file'
                        installs.append(installitem)
                        break
                        
            if installs == []:
                # didn't find a payload with matching name
                # just add all of the non-LangPack payloads
                # to the installs list.
                for payload in cataloginfo.get('payloads', []):
                    if 'AdobeCode' in payload:
                        if ("LangPack" in payload.get("display_name") or
                            "Language Files" in payload.get("display_name")):
                            # skip Language Packs
                            continue
                        dbfile = payload['AdobeCode'] + ".db"
                        filepath = os.path.join(uninstalldir, dbfile)
                        installitem = {}
                        installitem['path'] = filepath
                        installitem['type'] = 'file'
                        installs.append(installitem)
                        
            cataloginfo['installs'] = installs 
            return cataloginfo
    
    # Look for AdobeUberInstaller items (CS4 install)
    pkgroot = os.path.join(mountpoint, pkgname)
    adobeinstallxml = os.path.join(pkgroot, "AdobeUberInstaller.xml")
    if os.path.exists(adobeinstallxml):
        # this is a CS4 Enterprise Deployment package
        cataloginfo = getAdobePackageInfo(pkgroot)
        if cataloginfo:
            # add some more data
            cataloginfo['name'] = \
                cataloginfo['display_name'].replace(" ",'')
            cataloginfo['uninstallable'] = True
            cataloginfo['uninstall_method'] = "AdobeUberUninstaller"
            cataloginfo['installer_type'] = "AdobeUberInstaller"
            if pkgname:
                cataloginfo['package_path'] = pkgname
            return cataloginfo
            
    # maybe this is an Adobe update DMG or CS3 installer
    # look for Adobe Setup.app
    setuppath = findSetupApp(mountpoint)
    if setuppath:
        cataloginfo = getAdobeSetupInfo(mountpoint)
        if cataloginfo:
            # add some more data
            cataloginfo['name'] = \
                cataloginfo['display_name'].replace(" ",'')
            cataloginfo['installer_type'] = "AdobeSetup"
            if cataloginfo.get('AdobeSetupType') == "ProductInstall":
                cataloginfo['uninstallable'] = True
                cataloginfo['uninstall_method'] = "AdobeSetup"
            else:
                cataloginfo['description'] = "Adobe updater"
                cataloginfo['uninstallable'] = False
                cataloginfo['update_for'] = ["PleaseEditMe-1.0.0.0.0"]
            return cataloginfo
            
    # maybe this is an Adobe Acrobat 9 Pro patcher?
    acrobatpatcherapp = findAcrobatPatchApp(mountpoint)
    if acrobatpatcherapp:
        cataloginfo = {}
        cataloginfo['installer_type'] = "AdobeAcrobatUpdater"
        cataloginfo['uninstallable'] = False
        plist = getBundleInfo(acrobatpatcherapp)
        cataloginfo['version'] = munkicommon.getVersionString(plist)
        cataloginfo['name'] = "AcrobatPro9Update"
        cataloginfo['display_name'] = "Adobe Acrobat Pro Update"
        cataloginfo['update_for'] = ["AcrobatPro9"]
        cataloginfo['RestartAction'] = 'RequireLogout'
        cataloginfo['requires'] = []
        cataloginfo['installs'] = \
            [{'CFBundleIdentifier': 'com.adobe.Acrobat.Pro',
             'CFBundleName': 'Acrobat',
             'CFBundleShortVersionString': cataloginfo['version'],
             'path': 
            '/Applications/Adobe Acrobat 9 Pro/Adobe Acrobat Pro.app',
              'type': 'application'}]
        return cataloginfo
    
    # didn't find any Adobe installers/updaters we understand
    return None


def adobeSetupError(errorcode):
    '''Returns text description for numeric error code
    Reference:  
    http://www.adobe.com/devnet/creativesuite/pdfs/DeployGuide.pdf'''
    
    errormessage = { 
        0 : "Application installed successfully",
        1 : "Unable to parse command line",
        2 : "Unknown user interface mode specified",
        3 : "Unable to initialize ExtendScript",
        4 : "User interface workflow failed",
        5 : "Unable to initialize user interface workflow",
        6 : "Silent workflow completed with errors",
        7 : "Unable to complete the silent workflow",
        8 : "Exit and restart",
        9 : "Unsupported operating system version",
        10 : "Unsupported file system",
        11 : "Another instance of Adobe Setup is running",
        12 : "CAPS integrity error",
        13 : "Media optimization failed",
        14 : "Failed due to insufficient privileges",
        15 : "Media DB Sync Failed",
        16 : "Failed to laod the Deployment file",
        17 : "EULA Acceptance Failed",
        18 : "C3PO Bootstrap Failed",
        19 : "Conflicting processes running",
        20 : "Install source path not specified or does not exist",
        21 : "Version of payloads is not supported by this version of RIB",
        22 : "Install Directory check failed",
        23 : "System Requirements Check failed",
        24 : "Exit User Canceled Workflow",
        25 : "A binary path Name exceeded Operating System's MAX PATH limit",
        26 : "Media Swap Required in Silent Mode",
        27 : "Keyed files detected in target",
        28 : "Base product is not installed",
        29 : "Base product has been moved",
        30 : "Insufficient disk space to install the payload + Done with errors",
        31 : "Insufficient disk space to install the payload + Failed",
        32 : "The patch is already applied",
        9999 : "Catastrophic error",
        -1 : "AdobeUberInstaller failed before launching Setup" }
    return errormessage.get(errorcode, "Unknown error")


def doAdobeRemoval(item):
    '''Wrapper for all the Adobe removal methods'''
    uninstallmethod = item['uninstall_method']
    itempath = ""
    if "uninstaller_item" in item:
        managedinstallbase = munkicommon.pref('ManagedInstallDir')
        itempath = os.path.join(managedinstallbase, 'Cache', 
                                item["uninstaller_item"])
        if not os.path.exists(itempath):
            munkicommon.display_error("%s package for %s was "
                                      "missing from the cache."
                                      % (uninstallmethod, item['name']))
            return -1
    
    if uninstallmethod == "AdobeSetup":
        # CS3 uninstall
        retcode = runAdobeSetup(itempath, uninstalling=True)
        
    elif uninstallmethod == "AdobeUberUninstaller":
        # CS4 uninstall
        pkgname = item.get("adobe_package_name") or \
                  item.get("package_path","")
        retcode = runAdobeUberTool(itempath, pkgname, uninstalling=True)
        
    elif uninstallmethod == "AdobeCS5AAMEEPackage":
        # CS5 uninstall. Sheesh. Three releases, three methods.
        adobeInstallInfo = item.get('adobe_install_info')
        retcode = doAdobeCS5Uninstall(adobeInstallInfo)
        
    if retcode:
        munkicommon.display_error("Uninstall of %s failed." % item['name'])
    return retcode
    
    
def doAdobeInstall(item):
    '''Wrapper to handle all the Adobe installer methods.
    First get the path to the installer dmg. We know
    it exists because installer.py already checked.'''
    
    managedinstallbase = \
                 munkicommon.pref('ManagedInstallDir')
    itempath = os.path.join(managedinstallbase,
                            'Cache', 
                            item["installer_item"])
    installer_type = item.get("installer_type","")
    if installer_type == "AdobeSetup":
        # Adobe CS3/CS4 updater or Adobe CS3 installer
        retcode = runAdobeSetup(itempath)
    elif installer_type == "AdobeUberInstaller":
        # Adobe CS4 installer
        pkgname = item.get("adobe_package_name") or \
                  item.get("package_path","")
        retcode = runAdobeUberTool(itempath, pkgname)
    elif installer_type == "AdobeAcrobatUpdater":
        # Acrobat Pro 9 updater
        retcode = updateAcrobatPro(itempath)
    elif installer_type == "AdobeCS5AAMEEPackage":
        # Adobe CS5 AAMEE package
        retcode = runAdobeCS5AAMEEInstall(itempath)
    elif installer_type == "AdobeCS5PatchInstaller":
        # Adobe CS5 updater
        retcode = runAdobeCS5PatchInstaller(itempath,
                                    copylocal=item.get("copy_local"))
    return retcode


def main():
    '''Placeholder'''
    pass


if __name__ == '__main__':
    main()

