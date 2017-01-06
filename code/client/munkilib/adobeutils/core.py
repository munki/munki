#!/usr/bin/python
# encoding: utf-8
# Copyright 2009-2016 Greg Neagle.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
adobeutils.core

Utilities to enable munki to install/uninstall Adobe CS3/CS4/CS5 products
using the CS3/CS4/CS5 Deployment Toolkits.

"""


import os
import re
import subprocess
import time
import tempfile

from . import adobeinfo

from .. import FoundationPlist
from .. import munkicommon
from .. import munkistatus
from .. import utils

# we use lots of camelCase-style names. Deal with it.
# pylint: disable=C0103


def getPDAppLogPath():
    '''Returns path to active PDApp.log'''
    # with CCP HD installs the useful info is recorded to the PDApp.log
    # in the current GUI user's ~/Library/Logs directory, or in root's
    # Library/Logs if we're at the loginwindow.
    user = munkicommon.getconsoleuser()
    if not user or user == u'loginwindow':
        user = 'root'
    return os.path.expanduser('~%s/Library/Logs/PDApp.log' % user)


def rotatePDAppLog():
    '''Since CCP HD installers now dump all the interesting progress info into
    the PDApp.log, before we start installing or uninstalling, we need to rotate
    out any existing PDApp.log so we can more easily find the stuff relevant to
    the current install/uninstall session.'''
    timestamp_string = time.strftime('%Y-%m-%d %H-%M-%S', time.localtime())
    pdapplog_path = getPDAppLogPath()
    if os.path.exists(pdapplog_path):
        logdir = os.path.dirname(pdapplog_path)
        newlogname = os.path.join(logdir, 'PDApp %s.log' % timestamp_string)
        index = 1
        while os.path.exists(newlogname):
            alternate_string = '%s_%s' % (timestamp_string, str(index))
            index += 1
            newlogname = os.path.join(logdir, 'PDApp %s.log' % alternate_string)
        try:
            os.rename(pdapplog_path, newlogname)
        except OSError, err:
            munkicommon.log('Could not rotate PDApp.log: %s', unicode(err))


class AdobeInstallProgressMonitor(object):
    """A class to monitor installs/removals of Adobe products.
    Finds the currently active installation log and scrapes data out of it.
    Installations that install a product and updates may actually create
    multiple logs."""

    def __init__(self, kind='CS5', operation='install'):
        '''Provide some hints as to what type of installer is running and
        whether we are installing or removing'''
        self.kind = kind
        self.operation = operation
        self.payload_count = {}

    def get_current_log(self):
        '''Returns the current Adobe install log'''

        # with CCP HD installs the useful info is recorded to the PDApp.log
        pdapp_log_path = getPDAppLogPath()

        logpath = '/Library/Logs/Adobe/Installers'
        # find the most recently-modified log file
        recent_adobe_log = None
        proc = subprocess.Popen(['/bin/ls', '-t1', logpath],
                                bufsize=-1, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        (output, dummy_err) = proc.communicate()
        if output:
            firstitem = str(output).splitlines()[0]
            if firstitem.endswith(".log"):
                # store path of most recently modified log file
                recent_adobe_log = os.path.join(logpath, firstitem)
        # if PDApp.log is newer, return that, otherwise, return newest
        # log file in /Library/Logs/Adobe/Installers
        if recent_adobe_log and os.path.exists(recent_adobe_log):
            if (not os.path.exists(pdapp_log_path) or
                    (os.path.getmtime(pdapp_log_path) <
                     os.path.getmtime(recent_adobe_log))):
                return recent_adobe_log
        if os.path.exists(pdapp_log_path):
            return pdapp_log_path
        return None

    def info(self):
        '''Returns the number of completed Adobe payloads/packages,
        and the AdobeCode or package name of the most recently completed
        payload/package.'''
        last_adobecode = ""

        logfile = self.get_current_log()
        if logfile:
            if logfile.endswith('PDApp.log'):
                if self.operation == 'install':
                    regex = r'Completed \'INSTALL\' task for Package '
                else:
                    regex = r'Completed \'UN-INSTALL\' task for Package '
            elif self.kind in ['CS6', 'CS5']:
                regex = r'END TIMER :: \[Payload Operation :\{'
            elif self.kind in ['CS3', 'CS4']:
                if self.operation == 'install':
                    regex = r'Closed PCD cache session payload with ID'
                else:
                    regex = r'Closed CAPS session for removal of payload'
            else:
                if self.operation == 'install':
                    regex = r'Completing installation for payload at '
                else:
                    regex = r'Physical payload uninstall result '

            cmd = ['/usr/bin/grep', '-E', regex, logfile]
            proc = subprocess.Popen(cmd, bufsize=-1,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)
            (output, dummy_err) = proc.communicate()
            if output:
                lines = str(output).splitlines()
                completed_payloads = len(lines)

                if (logfile not in self.payload_count
                        or completed_payloads > self.payload_count[logfile]):
                    # record number of completed payloads
                    self.payload_count[logfile] = completed_payloads

                    # now try to get the AdobeCode of the most recently
                    # completed payload.
                    # this isn't 100% accurate, but it's mostly for show
                    # anyway...
                    if logfile.endswith('PDApp.log'):
                        regex = re.compile(r'\(Name: (.+) Version: (.+)\)')
                    else:
                        regex = re.compile(r'[^{]*(\{[A-Fa-f0-9-]+\})')
                    lines.reverse()
                    for line in lines:
                        if logfile.endswith('PDApp.log'):
                            m = regex.search(line)
                        else:
                            m = regex.match(line)
                        try:
                            if logfile.endswith('PDApp.log'):
                                last_adobecode = m.group(1) + '-' + m.group(2)
                            else:
                                last_adobecode = m.group(1)
                            break
                        except (IndexError, AttributeError):
                            pass

        total_completed_payloads = 0
        for key in self.payload_count.keys():
            total_completed_payloads += self.payload_count[key]

        return (total_completed_payloads, last_adobecode)


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
                            bufsize=-1,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (pliststr, err) = proc.communicate()
    if err:
        munkicommon.display_error('Error %s mounting %s.' % (err, dmgname))
    if pliststr:
        plist = FoundationPlist.readPlistFromString(pliststr)
        for entity in plist['system-entities']:
            if 'mount-point' in entity:
                mountpoints.append(entity['mount-point'])

    return mountpoints


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


secondsToLive = {}
def killStupidProcesses():
    '''A nasty bit of hackery to get Adobe CS5 AAMEE packages to install
    when at the loginwindow.'''
    stupid_processes = ["Adobe AIR Installer",
                        "Adobe AIR Application Installer",
                        "InstallAdobeHelp",
                        "open -a /Library/Application Support/Adobe/"
                        "SwitchBoard/SwitchBoard.app",
                        "/bin/bash /Library/Application Support/Adobe/"
                        "SwitchBoard/SwitchBoard.app/Contents/MacOS/"
                        "switchboard.sh"]

    for procname in stupid_processes:
        pid = utils.getPIDforProcessName(procname)
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


def runAdobeInstallTool(
        cmd, number_of_payloads=0, killAdobeAIR=False, payloads=None,
        kind="CS5", operation="install"):
    '''An abstraction of the tasks for running Adobe Setup,
    AdobeUberInstaller, AdobeUberUninstaller, AdobeDeploymentManager, etc'''

    # initialize an AdobeInstallProgressMonitor object.
    progress_monitor = AdobeInstallProgressMonitor(
        kind=kind, operation=operation)

    if munkicommon.munkistatusoutput and not number_of_payloads:
        # indeterminate progress bar
        munkistatus.percent(-1)

    proc = subprocess.Popen(cmd, shell=False, bufsize=1,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    old_payload_completed_count = 0
    payloadname = ""
    while proc.poll() is None:
        time.sleep(1)
        (payload_completed_count, adobe_code) = progress_monitor.info()
        if payload_completed_count > old_payload_completed_count:
            old_payload_completed_count = payload_completed_count
            payloadname = adobe_code
            if adobe_code and payloads:
                # look up a payload name from the AdobeCode
                matched_payloads = [payload for payload in payloads
                                    if payload.get('AdobeCode') == adobe_code]
                if matched_payloads:
                    payloadname = matched_payloads[0].get('display_name')
            payloadinfo = " - %s" % payloadname
            if number_of_payloads:
                munkicommon.display_status_minor(
                    'Completed payload %s of %s%s' %
                    (payload_completed_count, number_of_payloads,
                     payloadinfo))
            else:
                munkicommon.display_status_minor(
                    'Completed payload %s%s',
                    payload_completed_count, payloadinfo)
            if munkicommon.munkistatusoutput:
                munkistatus.percent(
                    getPercent(payload_completed_count, number_of_payloads))

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
        munkicommon.display_error(
            'Adobe Setup error: %s: %s', retcode, adobeSetupError(retcode))
    else:
        if munkicommon.munkistatusoutput:
            munkistatus.percent(100)
        munkicommon.display_status_minor('Done.')

    return retcode


def runAdobeSetup(dmgpath, uninstalling=False, payloads=None):
    '''Runs the Adobe setup tool in silent mode from
    an Adobe update DMG or an Adobe CS3 install DMG'''
    munkicommon.display_status_minor(
        'Mounting disk image %s' % os.path.basename(dmgpath))
    mountpoints = mountAdobeDmg(dmgpath)
    if mountpoints:
        setup_path = adobeinfo.findSetupApp(mountpoints[0])
        if setup_path:
            # look for install.xml or uninstall.xml at root
            deploymentfile = None
            installxml = os.path.join(mountpoints[0], "install.xml")
            uninstallxml = os.path.join(mountpoints[0], "uninstall.xml")
            if uninstalling:
                operation = 'uninstall'
                if os.path.exists(uninstallxml):
                    deploymentfile = uninstallxml
                else:
                    # we've been asked to uninstall,
                    # but found no uninstall.xml
                    # so we need to bail
                    munkicommon.unmountdmg(mountpoints[0])
                    munkicommon.display_error(
                        '%s doesn\'t appear to contain uninstall adobeinfo.',
                        os.path.basename(dmgpath))
                    return -1
            else:
                operation = 'install'
                if os.path.exists(installxml):
                    deploymentfile = installxml

            # try to find and count the number of payloads
            # so we can give a rough progress indicator
            number_of_payloads = adobeinfo.countPayloads(mountpoints[0])
            munkicommon.display_status_minor('Running Adobe Setup')
            adobe_setup = [setup_path, '--mode=silent', '--skipProcessCheck=1']
            if deploymentfile:
                adobe_setup.append('--deploymentFile=%s' % deploymentfile)

            retcode = runAdobeInstallTool(
                adobe_setup, number_of_payloads, payloads=payloads,
                kind='CS3', operation=operation)

        else:
            munkicommon.display_error(
                '%s doesn\'t appear to contain Adobe Setup.' %
                os.path.basename(dmgpath))
            retcode = -1

        munkicommon.unmountdmg(mountpoints[0])
        return retcode
    else:
        munkicommon.display_error('No mountable filesystems on %s' % dmgpath)
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


def doAdobeCS5Uninstall(adobeInstallInfo, payloads=None):
    '''Runs the locally-installed Adobe CS5 tools to remove CS5 products.
    We need the uninstallxml and the CS5 Setup.app.'''
    uninstallxml = adobeInstallInfo.get('uninstallxml')
    if not uninstallxml:
        munkicommon.display_error("No uninstall.xml in adobe_install_info")
        return -1
    payloadcount = adobeInstallInfo.get('payload_count', 0)
    path = os.path.join(munkicommon.tmpdir(), "uninstall.xml")
    deploymentFile = writefile(uninstallxml, path)
    if not deploymentFile:
        return -1
    setupapp = "/Library/Application Support/Adobe/OOBE/PDApp/DWA/Setup.app"
    setup = os.path.join(setupapp, "Contents/MacOS/Setup")
    if not os.path.exists(setup):
        munkicommon.display_error("%s is not installed." % setupapp)
        return -1
    uninstall_cmd = [setup,
                     '--mode=silent',
                     '--action=uninstall',
                     '--skipProcessCheck=1',
                     '--deploymentFile=%s' % deploymentFile]
    munkicommon.display_status_minor('Running Adobe Uninstall')
    return runAdobeInstallTool(uninstall_cmd, payloadcount, payloads=payloads,
                               kind='CS5', operation='uninstall')


def runAdobeCCPpkgScript(dmgpath, payloads=None, operation='install'):
    '''Installs or removes an Adobe product packaged via
    Creative Cloud Packager'''
    munkicommon.display_status_minor(
        'Mounting disk image %s' % os.path.basename(dmgpath))
    mountpoints = mountAdobeDmg(dmgpath)
    if not mountpoints:
        munkicommon.display_error("No mountable filesystems on %s" % dmgpath)
        return -1

    deploymentmanager = adobeinfo.findAdobeDeploymentManager(mountpoints[0])
    if not deploymentmanager:
        munkicommon.display_error(
            '%s doesn\'t appear to contain AdobeDeploymentManager',
            os.path.basename(dmgpath))
        munkicommon.unmountdmg(mountpoints[0])
        return -1

    # big hack to convince the Adobe tools to install off a mounted
    # disk image.
    #
    # For some reason, some versions of the Adobe install tools refuse to
    # install when the payloads are on a "removable" disk,
    # which includes mounted disk images.
    #
    # we create a temporary directory on the local disk and then symlink
    # some resources from the mounted disk image to the temporary
    # directory. When we pass this temporary directory to the Adobe
    # installation tools, they are now happy.

    basepath = os.path.dirname(deploymentmanager)
    preinstall_script = os.path.join(basepath, "preinstall")
    if not os.path.exists(preinstall_script):
        if operation == 'install':
            munkicommon.display_error(
                "No Adobe install script found on %s" % dmgpath)
        else:
            munkicommon.display_error(
                "No Adobe uninstall script found on %s" % dmgpath)
        munkicommon.unmountdmg(mountpoints[0])
        return -1
    number_of_payloads = adobeinfo.countPayloads(basepath)
    tmpdir = tempfile.mkdtemp(prefix='munki-', dir='/tmp')

    # make our symlinks
    for dir_name in ['ASU' 'ASU2', 'ProvisioningTool', 'uninstallinfo']:
        if os.path.isdir(os.path.join(basepath, dir_name)):
            os.symlink(os.path.join(basepath, dir_name),
                       os.path.join(tmpdir, dir_name))

    for dir_name in ['Patches', 'Setup']:
        realdir = os.path.join(basepath, dir_name)
        if os.path.isdir(realdir):
            tmpsubdir = os.path.join(tmpdir, dir_name)
            os.mkdir(tmpsubdir)
            for item in munkicommon.listdir(realdir):
                os.symlink(os.path.join(realdir, item),
                           os.path.join(tmpsubdir, item))

    os_version_tuple = munkicommon.getOsVersion(as_tuple=True)
    if (os_version_tuple < (10, 11) and
            (not munkicommon.getconsoleuser() or
             munkicommon.getconsoleuser() == u"loginwindow")):
        # we're at the loginwindow, so we need to run the deployment
        # manager in the loginwindow context using launchctl bsexec
        # launchctl bsexec doesn't work for this in El Cap, so do it
        # only if we're running Yosemite or earlier
        loginwindowPID = utils.getPIDforProcessName("loginwindow")
        cmd = ['/bin/launchctl', 'bsexec', loginwindowPID]
    else:
        cmd = []

    # preinstall script is in pkg/Contents/Resources, so calculate
    # path to pkg
    pkg_dir = os.path.dirname(os.path.dirname(basepath))
    cmd.extend([preinstall_script, pkg_dir, '/', '/'])

    rotatePDAppLog()
    if operation == 'install':
        munkicommon.display_status_minor('Starting Adobe installer...')
    elif operation == 'uninstall':
        munkicommon.display_status_minor('Starting Adobe uninstaller...')
    retcode = runAdobeInstallTool(
        cmd, number_of_payloads, killAdobeAIR=True, payloads=payloads,
        kind='CS6', operation=operation)

    # now clean up and return
    dummy_result = subprocess.call(["/bin/rm", "-rf", tmpdir])
    munkicommon.unmountdmg(mountpoints[0])
    return retcode


def runAdobeCS5AAMEEInstall(dmgpath, payloads=None):
    '''Installs a CS5 product using an AAMEE-generated package on a
    disk image.'''
    munkicommon.display_status_minor(
        'Mounting disk image %s' % os.path.basename(dmgpath))
    mountpoints = mountAdobeDmg(dmgpath)
    if not mountpoints:
        munkicommon.display_error("No mountable filesystems on %s" % dmgpath)
        return -1

    deploymentmanager = adobeinfo.findAdobeDeploymentManager(mountpoints[0])
    if deploymentmanager:
        # big hack to convince the Adobe tools to install off a mounted
        # disk image.
        #
        # For some reason, some versions of the Adobe install tools refuse to
        # install when the payloads are on a "removable" disk,
        # which includes mounted disk images.
        #
        # we create a temporary directory on the local disk and then symlink
        # some resources from the mounted disk image to the temporary
        # directory. When we pass this temporary directory to the Adobe
        # installation tools, they are now happy.

        basepath = os.path.dirname(deploymentmanager)
        number_of_payloads = adobeinfo.countPayloads(basepath)
        tmpdir = tempfile.mkdtemp(prefix='munki-', dir='/tmp')

        # make our symlinks
        os.symlink(os.path.join(basepath, "ASU"), os.path.join(tmpdir, "ASU"))
        os.symlink(os.path.join(basepath, "ProvisioningTool"),
                   os.path.join(tmpdir, "ProvisioningTool"))

        for dir_name in ['Patches', 'Setup']:
            realdir = os.path.join(basepath, dir_name)
            if os.path.isdir(realdir):
                tmpsubdir = os.path.join(tmpdir, dir_name)
                os.mkdir(tmpsubdir)
                for item in munkicommon.listdir(realdir):
                    os.symlink(
                        os.path.join(realdir, item),
                        os.path.join(tmpsubdir, item))

        optionXMLfile = os.path.join(basepath, "optionXML.xml")
        os_version_tuple = munkicommon.getOsVersion(as_tuple=True)
        if (os_version_tuple < (10, 11) and
                (not munkicommon.getconsoleuser() or
                 munkicommon.getconsoleuser() == u"loginwindow")):
            # we're at the loginwindow, so we need to run the deployment
            # manager in the loginwindow context using launchctl bsexec
            # launchctl bsexec doesn't work for this in El Cap, so do it
            # only if we're running Yosemite or earlier
            loginwindowPID = utils.getPIDforProcessName("loginwindow")
            cmd = ['/bin/launchctl', 'bsexec', loginwindowPID]
        else:
            cmd = []

        cmd.extend([deploymentmanager, '--optXMLPath=%s' % optionXMLfile,
                    '--setupBasePath=%s' % basepath, '--installDirPath=/',
                    '--mode=install'])

        munkicommon.display_status_minor('Starting Adobe installer...')
        retcode = runAdobeInstallTool(
            cmd, number_of_payloads, killAdobeAIR=True, payloads=payloads,
            kind='CS5', operation='install')
        # now clean up our symlink hackfest
        dummy_result = subprocess.call(["/bin/rm", "-rf", tmpdir])
    else:
        munkicommon.display_error(
            '%s doesn\'t appear to contain AdobeDeploymentManager',
            os.path.basename(dmgpath))
        retcode = -1

    munkicommon.unmountdmg(mountpoints[0])
    return retcode


def runAdobeCS5PatchInstaller(dmgpath, copylocal=False, payloads=None):
    '''Runs the AdobePatchInstaller for CS5.
    Optionally can copy the DMG contents to the local disk
    to work around issues with the patcher.'''
    munkicommon.display_status_minor(
        'Mounting disk image %s' % os.path.basename(dmgpath))
    mountpoints = mountAdobeDmg(dmgpath)
    if mountpoints:
        if copylocal:
            # copy the update to the local disk before installing
            updatedir = tempfile.mkdtemp(prefix='munki-', dir='/tmp')
            retcode = subprocess.call(
                ["/bin/cp", "-r", mountpoints[0], updatedir])
            # unmount diskimage
            munkicommon.unmountdmg(mountpoints[0])
            if retcode:
                munkicommon.display_error(
                    'Error copying items from %s' % dmgpath)
                return -1
            # remove the dmg file to free up space, since we don't need it
            # any longer
            dummy_result = subprocess.call(["/bin/rm", dmgpath])
        else:
            updatedir = mountpoints[0]

        patchinstaller = adobeinfo.findAdobePatchInstallerApp(updatedir)
        if patchinstaller:
            # try to find and count the number of payloads
            # so we can give a rough progress indicator
            number_of_payloads = adobeinfo.countPayloads(updatedir)
            munkicommon.display_status_minor('Running Adobe Patch Installer')
            install_cmd = [patchinstaller,
                           '--mode=silent',
                           '--skipProcessCheck=1']
            retcode = runAdobeInstallTool(install_cmd,
                                          number_of_payloads, payloads=payloads,
                                          kind='CS5', operation='install')
        else:
            munkicommon.display_error(
                "%s doesn't appear to contain AdobePatchInstaller.app.",
                os.path.basename(dmgpath))
            retcode = -1
        if copylocal:
            # clean up our mess
            dummy_result = subprocess.call(["/bin/rm", "-rf", updatedir])
        else:
            munkicommon.unmountdmg(mountpoints[0])
        return retcode
    else:
        munkicommon.display_error('No mountable filesystems on %s' % dmgpath)
        return -1


def runAdobeUberTool(dmgpath, pkgname='', uninstalling=False, payloads=None):
    '''Runs either AdobeUberInstaller or AdobeUberUninstaller
    from a disk image and provides progress feedback.
    pkgname is the name of a directory at the top level of the dmg
    containing the AdobeUber tools and their XML files.'''

    munkicommon.display_status_minor(
        'Mounting disk image %s' % os.path.basename(dmgpath))
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
            info = adobeinfo.getAdobePackageInfo(installroot)
            packagename = info['display_name']
            action = "Installing"
            operation = "install"
            if uninstalling:
                action = "Uninstalling"
                operation = "uninstall"
            munkicommon.display_status_major('%s %s' % (action, packagename))
            if munkicommon.munkistatusoutput:
                munkistatus.detail('Starting %s' % os.path.basename(ubertool))

            # try to find and count the number of payloads
            # so we can give a rough progress indicator
            number_of_payloads = adobeinfo.countPayloads(installroot)

            retcode = runAdobeInstallTool(
                [ubertool], number_of_payloads, killAdobeAIR=True,
                payloads=payloads, kind='CS4', operation=operation)

        else:
            munkicommon.display_error("No %s found" % ubertool)
            retcode = -1

        munkicommon.unmountdmg(installroot)
        return retcode
    else:
        munkicommon.display_error("No mountable filesystems on %s" % dmgpath)
        return -1


def updateAcrobatPro(dmgpath):
    """Uses the scripts and Resources inside the Acrobat Patch application
    bundle to silently update Acrobat Pro and related apps
    Why oh why does this use a different mechanism than the other Adobe
    apps?"""

    if munkicommon.munkistatusoutput:
        munkistatus.percent(-1)

    #first mount the dmg
    munkicommon.display_status_minor(
        'Mounting disk image %s' % os.path.basename(dmgpath))
    mountpoints = mountAdobeDmg(dmgpath)
    if mountpoints:
        installroot = mountpoints[0]
        pathToAcrobatPatchApp = adobeinfo.findAcrobatPatchApp(installroot)
    else:
        munkicommon.display_error("No mountable filesystems on %s" % dmgpath)
        return -1

    if not pathToAcrobatPatchApp:
        munkicommon.display_error(
            'No Acrobat Patch app at %s', pathToAcrobatPatchApp)
        munkicommon.unmountdmg(installroot)
        return -1

    # some values needed by the patching script
    resourcesDir = os.path.join(
        pathToAcrobatPatchApp, 'Contents', 'Resources')
    ApplyOperation = os.path.join(resourcesDir, 'ApplyOperation.py')
    callingScriptPath = os.path.join(resourcesDir, 'InstallUpdates.sh')

    appList = []
    appListFile = os.path.join(resourcesDir, 'app_list.txt')
    if os.path.exists(appListFile):
        fileobj = open(appListFile, mode='r', buffering=-1)
        if fileobj:
            for line in fileobj.readlines():
                appList.append(line)
            fileobj.close()

    if not appList:
        munkicommon.display_error('Did not find a list of apps to update.')
        munkicommon.unmountdmg(installroot)
        return -1

    payloadNum = -1
    for line in appList:
        payloadNum = payloadNum + 1
        if munkicommon.munkistatusoutput:
            munkistatus.percent(getPercent(payloadNum + 1, len(appList) + 1))

        (appname, status) = line.split("\t")
        munkicommon.display_status_minor('Searching for %s' % appname)
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

        munkicommon.display_status_minor('Updating %s' % appname)
        apppath = os.path.dirname(candidates[0]["path"])
        cmd = [ApplyOperation, apppath, appname, resourcesDir,
               callingScriptPath, str(payloadNum)]

        proc = subprocess.Popen(cmd, shell=False, bufsize=-1,
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT)
        while proc.poll() is None:
            time.sleep(1)

        # run of patch tool completed
        retcode = proc.poll()
        if retcode != 0:
            munkicommon.display_error(
                'Error patching %s: %s', appname, retcode)
            break
        else:
            munkicommon.display_status_minor('Patching %s complete.', appname)

    munkicommon.display_status_minor('Done.')
    if munkicommon.munkistatusoutput:
        munkistatus.percent(100)

    munkicommon.unmountdmg(installroot)
    return retcode


def adobeSetupError(errorcode):
    '''Returns text description for numeric error code
    Reference:
    http://www.adobe.com/devnet/creativesuite/pdfs/DeployGuide.pdf'''

    errormessage = {
        0: "Application installed successfully",
        1: "Unable to parse command line",
        2: "Unknown user interface mode specified",
        3: "Unable to initialize ExtendScript",
        4: "User interface workflow failed",
        5: "Unable to initialize user interface workflow",
        6: "Silent workflow completed with errors",
        7: "Unable to complete the silent workflow",
        8: "Exit and restart",
        9: "Unsupported operating system version",
        10: "Unsupported file system",
        11: "Another instance of Adobe Setup is running",
        12: "CAPS integrity error",
        13: "Media optimization failed",
        14: "Failed due to insufficient privileges",
        15: "Media DB Sync Failed",
        16: "Failed to laod the Deployment file",
        17: "EULA Acceptance Failed",
        18: "C3PO Bootstrap Failed",
        19: "Conflicting processes running",
        20: "Install source path not specified or does not exist",
        21: "Version of payloads is not supported by this version of RIB",
        22: "Install Directory check failed",
        23: "System Requirements Check failed",
        24: "Exit User Canceled Workflow",
        25: "A binary path Name exceeded Operating System's MAX PATH limit",
        26: "Media Swap Required in Silent Mode",
        27: "Keyed files detected in target",
        28: "Base product is not installed",
        29: "Base product has been moved",
        30: "Insufficient disk space to install the payload + Done with errors",
        31: "Insufficient disk space to install the payload + Failed",
        32: "The patch is already applied",
        9999: "Catastrophic error",
        -1: "AdobeUberInstaller failed before launching Setup"}
    return errormessage.get(errorcode, "Unknown error")


def doAdobeRemoval(item):
    '''Wrapper for all the Adobe removal methods'''
    uninstallmethod = item['uninstall_method']
    payloads = item.get("payloads")
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
        retcode = runAdobeSetup(itempath, uninstalling=True, payloads=payloads)

    elif uninstallmethod == "AdobeUberUninstaller":
        # CS4 uninstall
        pkgname = item.get("adobe_package_name") or item.get("package_path", "")
        retcode = runAdobeUberTool(
            itempath, pkgname, uninstalling=True, payloads=payloads)

    elif uninstallmethod == "AdobeCS5AAMEEPackage":
        # CS5 uninstall. Sheesh. Three releases, three methods.
        adobeInstallInfo = item.get('adobe_install_info')
        retcode = doAdobeCS5Uninstall(adobeInstallInfo, payloads=payloads)

    elif uninstallmethod == "AdobeCCPUninstaller":
        # Adobe Creative Cloud Packager packages
        retcode = runAdobeCCPpkgScript(
            itempath, payloads=payloads, operation="uninstall")

    if retcode:
        munkicommon.display_error("Uninstall of %s failed.", item['name'])
    return retcode


def doAdobeInstall(item):
    '''Wrapper to handle all the Adobe installer methods.
    First get the path to the installer dmg. We know
    it exists because installer.py already checked.'''

    managedinstallbase = munkicommon.pref('ManagedInstallDir')
    itempath = os.path.join(
        managedinstallbase, 'Cache', item['installer_item'])
    installer_type = item.get("installer_type", "")
    payloads = item.get("payloads")
    if installer_type == "AdobeSetup":
        # Adobe CS3/CS4 updater or Adobe CS3 installer
        retcode = runAdobeSetup(itempath, payloads=payloads)
    elif installer_type == "AdobeUberInstaller":
        # Adobe CS4 installer
        pkgname = item.get("adobe_package_name") or item.get("package_path", "")
        retcode = runAdobeUberTool(itempath, pkgname, payloads=payloads)
    elif installer_type == "AdobeAcrobatUpdater":
        # Acrobat Pro 9 updater
        retcode = updateAcrobatPro(itempath)
    elif installer_type == "AdobeCS5AAMEEPackage":
        # Adobe CS5 AAMEE package
        retcode = runAdobeCS5AAMEEInstall(itempath, payloads=payloads)
    elif installer_type == "AdobeCS5PatchInstaller":
        # Adobe CS5 updater
        retcode = runAdobeCS5PatchInstaller(
            itempath, copylocal=item.get("copy_local"), payloads=payloads)
    elif installer_type == "AdobeCCPInstaller":
        # Adobe Creative Cloud Packager packages
        retcode = runAdobeCCPpkgScript(itempath, payloads=payloads)
    return retcode


if __name__ == '__main__':
    print 'This is a library of support tools for the Munki Suite.'
