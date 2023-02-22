# encoding: utf-8
# Copyright 2009-2023 Greg Neagle.
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

Utilities to enable Munki to install/uninstall Adobe CS3/CS4/CS5 products
using the CS3/CS4/CS5 Deployment Toolkits.

"""
from __future__ import absolute_import, print_function


import os
import re
import subprocess
import time
import tempfile

from . import adobeinfo

from .. import display
from .. import dmgutils
from .. import info
from .. import munkistatus
from .. import munkilog
from .. import osutils
from .. import prefs
from .. import utils


def get_pdapp_log_path():
    '''Returns path to active PDApp.log'''
    # with CCP HD installs the useful info is recorded to the PDApp.log
    # in the current GUI user's ~/Library/Logs directory, or in root's
    # Library/Logs if we're at the loginwindow.
    user = osutils.getconsoleuser()
    if not user or user == u'loginwindow':
        user = 'root'
    return os.path.expanduser('~%s/Library/Logs/PDApp.log' % user)


def rotate_pdapp_log():
    '''Since CCP HD installers now dump all the interesting progress info into
    the PDApp.log, before we start installing or uninstalling, we need to rotate
    out any existing PDApp.log so we can more easily find the stuff relevant to
    the current install/uninstall session.'''
    timestamp_string = time.strftime('%Y-%m-%d %H-%M-%S', time.localtime())
    pdapplog_path = get_pdapp_log_path()
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
        except OSError as err:
            munkilog.log(u'Could not rotate PDApp.log: %s' % err)


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
        pdapp_log_path = get_pdapp_log_path()

        logpath = '/Library/Logs/Adobe/Installers'
        # find the most recently-modified log file
        recent_adobe_log = None
        proc = subprocess.Popen(['/bin/ls', '-t1', logpath],
                                bufsize=-1, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        output = proc.communicate()[0].decode('UTF-8')
        if output:
            firstitem = output.splitlines()[0]
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
            output = proc.communicate()[0].decode('UTF-8')
            if output:
                lines = output.splitlines()
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
                            match = regex.search(line)
                        else:
                            match = regex.match(line)
                        try:
                            if logfile.endswith('PDApp.log'):
                                last_adobecode = (
                                    match.group(1) + '-' + match.group(2))
                            else:
                                last_adobecode = match.group(1)
                            break
                        except (IndexError, AttributeError):
                            pass

        total_completed_payloads = 0
        for key in self.payload_count:
            total_completed_payloads += self.payload_count[key]

        return (total_completed_payloads, last_adobecode)


# dmg helper
def mount_adobe_dmg(dmgpath):
    """
    Attempts to mount the dmg at dmgpath
    and returns a list of mountpoints
    """
    return dmgutils.mountdmg(dmgpath, random_mountpoint=False)


def get_percent(current, maximum):
    '''Returns a value useful with MunkiStatus to use when
    displaying percent-done status'''
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


SECONDSTOLIVE = {}
def kill_stupid_processes():
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
            if not pid in SECONDSTOLIVE:
                SECONDSTOLIVE[pid] = 30
            else:
                SECONDSTOLIVE[pid] = SECONDSTOLIVE[pid] - 1
                if SECONDSTOLIVE[pid] == 0:
                    # it's been running too long; kill it
                    munkilog.log("Killing PID %s: %s" % (pid, procname))
                    try:
                        os.kill(int(pid), 9)
                    except OSError:
                        pass
                    # remove this PID from our list
                    del SECONDSTOLIVE[pid]
                    # only kill one process per invocation
                    return


def run_adobe_install_tool(
        cmd, number_of_payloads=0, kill_adobeair=False, payloads=None,
        kind="CS5", operation="install"):
    '''An abstraction of the tasks for running Adobe Setup,
    AdobeUberInstaller, AdobeUberUninstaller, AdobeDeploymentManager, etc'''

    # initialize an AdobeInstallProgressMonitor object.
    progress_monitor = AdobeInstallProgressMonitor(
        kind=kind, operation=operation)

    if display.munkistatusoutput and not number_of_payloads:
        # indeterminate progress bar
        munkistatus.percent(-1)

    proc = subprocess.Popen(cmd, shell=False,
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
                display.display_status_minor(
                    'Completed payload %s of %s%s' %
                    (payload_completed_count, number_of_payloads,
                     payloadinfo))
            else:
                display.display_status_minor(
                    'Completed payload %s%s',
                    payload_completed_count, payloadinfo)
            if display.munkistatusoutput:
                munkistatus.percent(
                    get_percent(payload_completed_count, number_of_payloads))

        # Adobe AIR Installer workaround/hack
        # CSx installs at the loginwindow hang when Adobe AIR is installed.
        # So we check for this and kill the process. Ugly.
        # Hopefully we can disable this in the future.
        if kill_adobeair:
            if (not osutils.getconsoleuser() or
                    osutils.getconsoleuser() == u"loginwindow"):
                # we're at the loginwindow.
                kill_stupid_processes()

    # run of tool completed
    retcode = proc.poll()

    #check output for errors
    output = proc.stdout.readlines()
    for line in output:
        line = line.decode("UTF-8").rstrip("\n")
        if line.startswith("Error"):
            display.display_error(line)
        if line.startswith("Exit Code:"):
            if retcode == 0:
                try:
                    retcode = int(line[11:])
                except (ValueError, TypeError):
                    retcode = -1

    if retcode != 0 and retcode != 8:
        display.display_error(
            'Adobe Setup error: %s: %s', retcode, adobe_setup_error(retcode))
    else:
        if display.munkistatusoutput:
            munkistatus.percent(100)
        display.display_status_minor('Done.')

    return retcode


def run_adobe_setup(dmgpath, uninstalling=False, payloads=None):
    '''Runs the Adobe setup tool in silent mode from
    an Adobe update DMG or an Adobe CS3 install DMG'''
    display.display_status_minor(
        'Mounting disk image %s' % os.path.basename(dmgpath))
    mountpoints = mount_adobe_dmg(dmgpath)
    if mountpoints:
        setup_path = adobeinfo.find_setup_app(mountpoints[0])
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
                    dmgutils.unmountdmg(mountpoints[0])
                    display.display_error(
                        '%s doesn\'t appear to contain uninstall adobeinfo.',
                        os.path.basename(dmgpath))
                    return -1
            else:
                operation = 'install'
                if os.path.exists(installxml):
                    deploymentfile = installxml

            # try to find and count the number of payloads
            # so we can give a rough progress indicator
            number_of_payloads = adobeinfo.count_payloads(mountpoints[0])
            display.display_status_minor('Running Adobe Setup')
            adobe_setup = [setup_path, '--mode=silent', '--skipProcessCheck=1']
            if deploymentfile:
                adobe_setup.append('--deploymentFile=%s' % deploymentfile)

            retcode = run_adobe_install_tool(
                adobe_setup, number_of_payloads, payloads=payloads,
                kind='CS3', operation=operation)

        else:
            display.display_error(
                '%s doesn\'t appear to contain Adobe Setup.' %
                os.path.basename(dmgpath))
            retcode = -1

        dmgutils.unmountdmg(mountpoints[0])
        return retcode
    else:
        display.display_error('No mountable filesystems on %s' % dmgpath)
        return -1


def writefile(stringdata, path):
    '''Writes string data to path.
    Returns the path on success, empty string on failure.'''
    try:
        fileobject = open(path, mode='wb')
        fileobject.write(stringdata.encode('UTF-8'))
        fileobject.close()
        return path
    except (OSError, IOError):
        display.display_error("Couldn't write %s" % stringdata)
        return ""


def do_adobe_cs5_uninstall(adobe_install_info, payloads=None):
    '''Runs the locally-installed Adobe CS5 tools to remove CS5 products.
    We need the uninstallxml and the CS5 Setup.app.'''
    uninstallxml = adobe_install_info.get('uninstallxml')
    if not uninstallxml:
        display.display_error("No uninstall.xml in adobe_install_info")
        return -1
    payloadcount = adobe_install_info.get('payload_count', 0)
    path = os.path.join(osutils.tmpdir(), "uninstall.xml")
    deployment_file = writefile(uninstallxml, path)
    if not deployment_file:
        return -1
    setupapp = "/Library/Application Support/Adobe/OOBE/PDApp/DWA/Setup.app"
    setup = os.path.join(setupapp, "Contents/MacOS/Setup")
    if not os.path.exists(setup):
        display.display_error("%s is not installed." % setupapp)
        return -1
    uninstall_cmd = [setup,
                     '--mode=silent',
                     '--action=uninstall',
                     '--skipProcessCheck=1',
                     '--deploymentFile=%s' % deployment_file]
    display.display_status_minor('Running Adobe Uninstall')
    return run_adobe_install_tool(
        uninstall_cmd, payloadcount, payloads=payloads, kind='CS5',
        operation='uninstall')


def run_adobe_cpp_pkg_script(dmgpath, payloads=None, operation='install'):
    '''Installs or removes an Adobe product packaged via
    Creative Cloud Packager'''
    display.display_status_minor(
        'Mounting disk image %s' % os.path.basename(dmgpath))
    mountpoints = mount_adobe_dmg(dmgpath)
    if not mountpoints:
        display.display_error("No mountable filesystems on %s" % dmgpath)
        return -1

    deploymentmanager = adobeinfo.find_adobe_deployment_manager(mountpoints[0])
    if not deploymentmanager:
        display.display_error(
            '%s doesn\'t appear to contain AdobeDeploymentManager',
            os.path.basename(dmgpath))
        dmgutils.unmountdmg(mountpoints[0])
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
            display.display_error(
                "No Adobe install script found on %s" % dmgpath)
        else:
            display.display_error(
                "No Adobe uninstall script found on %s" % dmgpath)
        dmgutils.unmountdmg(mountpoints[0])
        return -1
    number_of_payloads = adobeinfo.count_payloads(basepath)
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
            for item in osutils.listdir(realdir):
                os.symlink(os.path.join(realdir, item),
                           os.path.join(tmpsubdir, item))

    os_version_tuple = osutils.getOsVersion(as_tuple=True)
    if (os_version_tuple < (10, 11) and
            (not osutils.getconsoleuser() or
             osutils.getconsoleuser() == u"loginwindow")):
        # we're at the loginwindow, so we need to run the deployment
        # manager in the loginwindow context using launchctl bsexec
        # launchctl bsexec doesn't work for this in El Cap, so do it
        # only if we're running Yosemite or earlier
        loginwindow_pid = utils.getPIDforProcessName("loginwindow")
        cmd = ['/bin/launchctl', 'bsexec', loginwindow_pid]
    else:
        cmd = []

    # preinstall script is in pkg/Contents/Resources, so calculate
    # path to pkg
    pkg_dir = os.path.dirname(os.path.dirname(basepath))
    cmd.extend([preinstall_script, pkg_dir, '/', '/'])

    rotate_pdapp_log()
    if operation == 'install':
        display.display_status_minor('Starting Adobe installer...')
    elif operation == 'uninstall':
        display.display_status_minor('Starting Adobe uninstaller...')
    retcode = run_adobe_install_tool(
        cmd, number_of_payloads, kill_adobeair=True, payloads=payloads,
        kind='CS6', operation=operation)

    # now clean up and return
    dummy_result = subprocess.call(["/bin/rm", "-rf", tmpdir])
    dmgutils.unmountdmg(mountpoints[0])
    return retcode


def run_adobe_cs5_aamee_install(dmgpath, payloads=None):
    '''Installs a CS5 product using an AAMEE-generated package on a
    disk image.'''
    display.display_status_minor(
        'Mounting disk image %s' % os.path.basename(dmgpath))
    mountpoints = mount_adobe_dmg(dmgpath)
    if not mountpoints:
        display.display_error("No mountable filesystems on %s" % dmgpath)
        return -1

    deploymentmanager = adobeinfo.find_adobe_deployment_manager(mountpoints[0])
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
        number_of_payloads = adobeinfo.count_payloads(basepath)
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
                for item in osutils.listdir(realdir):
                    os.symlink(
                        os.path.join(realdir, item),
                        os.path.join(tmpsubdir, item))

        option_xml_file = os.path.join(basepath, "optionXML.xml")
        os_version_tuple = osutils.getOsVersion(as_tuple=True)
        if (os_version_tuple < (10, 11) and
                (not osutils.getconsoleuser() or
                 osutils.getconsoleuser() == u"loginwindow")):
            # we're at the loginwindow, so we need to run the deployment
            # manager in the loginwindow context using launchctl bsexec
            # launchctl bsexec doesn't work for this in El Cap, so do it
            # only if we're running Yosemite or earlier
            loginwindow_pid = utils.getPIDforProcessName("loginwindow")
            cmd = ['/bin/launchctl', 'bsexec', loginwindow_pid]
        else:
            cmd = []

        cmd.extend([deploymentmanager, '--optXMLPath=%s' % option_xml_file,
                    '--setupBasePath=%s' % basepath, '--installDirPath=/',
                    '--mode=install'])

        display.display_status_minor('Starting Adobe installer...')
        retcode = run_adobe_install_tool(
            cmd, number_of_payloads, kill_adobeair=True, payloads=payloads,
            kind='CS5', operation='install')
        # now clean up our symlink hackfest
        dummy_result = subprocess.call(["/bin/rm", "-rf", tmpdir])
    else:
        display.display_error(
            '%s doesn\'t appear to contain AdobeDeploymentManager',
            os.path.basename(dmgpath))
        retcode = -1

    dmgutils.unmountdmg(mountpoints[0])
    return retcode


def run_adobe_cs5_patch_installer(dmgpath, copylocal=False, payloads=None):
    '''Runs the AdobePatchInstaller for CS5.
    Optionally can copy the DMG contents to the local disk
    to work around issues with the patcher.'''
    display.display_status_minor(
        'Mounting disk image %s' % os.path.basename(dmgpath))
    mountpoints = mount_adobe_dmg(dmgpath)
    if mountpoints:
        if copylocal:
            # copy the update to the local disk before installing
            updatedir = tempfile.mkdtemp(prefix='munki-', dir='/tmp')
            retcode = subprocess.call(
                ["/bin/cp", "-r", mountpoints[0], updatedir])
            # unmount diskimage
            dmgutils.unmountdmg(mountpoints[0])
            if retcode:
                display.display_error(
                    'Error copying items from %s' % dmgpath)
                return -1
            # remove the dmg file to free up space, since we don't need it
            # any longer
            dummy_result = subprocess.call(["/bin/rm", dmgpath])
        else:
            updatedir = mountpoints[0]

        patchinstaller = adobeinfo.find_adobepatchinstaller_app(updatedir)
        if patchinstaller:
            # try to find and count the number of payloads
            # so we can give a rough progress indicator
            number_of_payloads = adobeinfo.count_payloads(updatedir)
            display.display_status_minor('Running Adobe Patch Installer')
            install_cmd = [patchinstaller,
                           '--mode=silent',
                           '--skipProcessCheck=1']
            retcode = run_adobe_install_tool(
                install_cmd, number_of_payloads, payloads=payloads, kind='CS5',
                operation='install')
        else:
            display.display_error(
                "%s doesn't appear to contain AdobePatchInstaller.app.",
                os.path.basename(dmgpath))
            retcode = -1
        if copylocal:
            # clean up our mess
            dummy_result = subprocess.call(["/bin/rm", "-rf", updatedir])
        else:
            dmgutils.unmountdmg(mountpoints[0])
        return retcode
    else:
        display.display_error('No mountable filesystems on %s' % dmgpath)
        return -1


def run_adobe_uber_tool(dmgpath, pkgname='', uninstalling=False, payloads=None):
    '''Runs either AdobeUberInstaller or AdobeUberUninstaller
    from a disk image and provides progress feedback.
    pkgname is the name of a directory at the top level of the dmg
    containing the AdobeUber tools and their XML files.'''

    display.display_status_minor(
        'Mounting disk image %s' % os.path.basename(dmgpath))
    mountpoints = mount_adobe_dmg(dmgpath)
    if mountpoints:
        installroot = mountpoints[0]
        if uninstalling:
            ubertool = os.path.join(installroot, pkgname,
                                    "AdobeUberUninstaller")
        else:
            ubertool = os.path.join(installroot, pkgname,
                                    "AdobeUberInstaller")

        if os.path.exists(ubertool):
            packagename = adobeinfo.get_adobe_package_info(
                installroot)['display_name']
            action = "Installing"
            operation = "install"
            if uninstalling:
                action = "Uninstalling"
                operation = "uninstall"
            display.display_status_major('%s %s' % (action, packagename))
            if display.munkistatusoutput:
                munkistatus.detail('Starting %s' % os.path.basename(ubertool))

            # try to find and count the number of payloads
            # so we can give a rough progress indicator
            number_of_payloads = adobeinfo.count_payloads(installroot)

            retcode = run_adobe_install_tool(
                [ubertool], number_of_payloads, kill_adobeair=True,
                payloads=payloads, kind='CS4', operation=operation)

        else:
            display.display_error("No %s found" % ubertool)
            retcode = -1

        dmgutils.unmountdmg(installroot)
        return retcode
    else:
        display.display_error("No mountable filesystems on %s" % dmgpath)
        return -1


def update_acrobatpro(dmgpath):
    """Uses the scripts and Resources inside the Acrobat Patch application
    bundle to silently update Acrobat Pro and related apps
    Why oh why does this use a different mechanism than the other Adobe
    apps?"""

    if display.munkistatusoutput:
        munkistatus.percent(-1)

    #first mount the dmg
    display.display_status_minor(
        'Mounting disk image %s' % os.path.basename(dmgpath))
    mountpoints = mount_adobe_dmg(dmgpath)
    if mountpoints:
        installroot = mountpoints[0]
        acrobatpatchapp_path = adobeinfo.find_acrobat_patch_app(installroot)
    else:
        display.display_error("No mountable filesystems on %s" % dmgpath)
        return -1

    if not acrobatpatchapp_path:
        display.display_error(
            'No Acrobat Patch app at %s', acrobatpatchapp_path)
        dmgutils.unmountdmg(installroot)
        return -1

    # some values needed by the patching script
    resources_dir = os.path.join(
        acrobatpatchapp_path, 'Contents', 'Resources')
    apply_operation = os.path.join(resources_dir, 'ApplyOperation.py')
    calling_script_path = os.path.join(resources_dir, 'InstallUpdates.sh')

    app_list = []
    app_list_file = os.path.join(resources_dir, 'app_list.txt')
    if os.path.exists(app_list_file):
        fileobj = open(app_list_file, mode='r')
        if fileobj:
            for line in fileobj.readlines():
                app_list.append(line)
            fileobj.close()

    if not app_list:
        display.display_error('Did not find a list of apps to update.')
        dmgutils.unmountdmg(installroot)
        return -1

    payload_num = -1
    for line in app_list:
        payload_num = payload_num + 1
        if display.munkistatusoutput:
            munkistatus.percent(get_percent(payload_num + 1, len(app_list) + 1))

        (appname, status) = line.split("\t")
        display.display_status_minor('Searching for %s' % appname)
        # first look in the obvious place
        pathname = os.path.join("/Applications/Adobe Acrobat 9 Pro", appname)
        if os.path.exists(pathname):
            item = {}
            item['path'] = pathname
            candidates = [item]
        else:
            # use system_profiler to search for the app
            candidates = [item for item in info.app_data()
                          if item['path'].endswith('/' + appname)]

        # hope there's only one!
        if not candidates:
            # there are no candidates!
            if status == "optional":
                continue
            else:
                display.display_error(
                    "Cannot patch %s because it was not found on the startup "
                    "disk." % appname)
                dmgutils.unmountdmg(installroot)
                return -1

        if len(candidates) > 1:
            display.display_error(
                "Cannot patch %s because we found more than one copy on the "
                "startup disk." % appname)
            dmgutils.unmountdmg(installroot)
            return -1

        display.display_status_minor('Updating %s' % appname)
        apppath = os.path.dirname(candidates[0]["path"])
        cmd = [apply_operation, apppath, appname, resources_dir,
               calling_script_path, str(payload_num)]

        proc = subprocess.Popen(cmd, shell=False, bufsize=-1,
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT)
        while proc.poll() is None:
            time.sleep(1)

        # run of patch tool completed
        retcode = proc.poll()
        if retcode != 0:
            display.display_error(
                'Error patching %s: %s', appname, retcode)
            break
        else:
            display.display_status_minor('Patching %s complete.', appname)

    display.display_status_minor('Done.')
    if display.munkistatusoutput:
        munkistatus.percent(100)

    dmgutils.unmountdmg(installroot)
    return retcode


def adobe_setup_error(errorcode):
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
        16: "Failed to load the Deployment file",
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


def do_adobe_removal(item):
    '''Wrapper for all the Adobe removal methods'''
    uninstallmethod = item['uninstall_method']
    payloads = item.get("payloads")
    itempath = ""
    if "uninstaller_item" in item:
        managedinstallbase = prefs.pref('ManagedInstallDir')
        itempath = os.path.join(managedinstallbase, 'Cache',
                                item["uninstaller_item"])
        if not os.path.exists(itempath):
            display.display_error(
                "%s package for %s was missing from the cache."
                % (uninstallmethod, item['name']))
            return -1

    if uninstallmethod == "AdobeSetup":
        # CS3 uninstall
        retcode = run_adobe_setup(
            itempath, uninstalling=True, payloads=payloads)

    elif uninstallmethod == "AdobeUberUninstaller":
        # CS4 uninstall
        pkgname = item.get("adobe_package_name") or item.get("package_path", "")
        retcode = run_adobe_uber_tool(
            itempath, pkgname, uninstalling=True, payloads=payloads)

    elif uninstallmethod == "AdobeCS5AAMEEPackage":
        # CS5 uninstall. Sheesh. Three releases, three methods.
        adobe_install_info = item.get('adobe_install_info')
        retcode = do_adobe_cs5_uninstall(adobe_install_info, payloads=payloads)

    elif uninstallmethod == "AdobeCCPUninstaller":
        # Adobe Creative Cloud Packager packages
        retcode = run_adobe_cpp_pkg_script(
            itempath, payloads=payloads, operation="uninstall")

    if retcode:
        display.display_error("Uninstall of %s failed.", item['name'])
    return retcode


def do_adobe_install(item):
    '''Wrapper to handle all the Adobe installer methods.
    First get the path to the installer dmg. We know
    it exists because installer.py already checked.'''

    managedinstallbase = prefs.pref('ManagedInstallDir')
    itempath = os.path.join(
        managedinstallbase, 'Cache', item['installer_item'])
    installer_type = item.get("installer_type", "")
    payloads = item.get("payloads")
    if installer_type == "AdobeSetup":
        # Adobe CS3/CS4 updater or Adobe CS3 installer
        retcode = run_adobe_setup(itempath, payloads=payloads)
    elif installer_type == "AdobeUberInstaller":
        # Adobe CS4 installer
        pkgname = item.get("adobe_package_name") or item.get("package_path", "")
        retcode = run_adobe_uber_tool(itempath, pkgname, payloads=payloads)
    elif installer_type == "AdobeAcrobatUpdater":
        # Acrobat Pro 9 updater
        retcode = update_acrobatpro(itempath)
    elif installer_type == "AdobeCS5AAMEEPackage":
        # Adobe CS5 AAMEE package
        retcode = run_adobe_cs5_aamee_install(itempath, payloads=payloads)
    elif installer_type == "AdobeCS5PatchInstaller":
        # Adobe CS5 updater
        retcode = run_adobe_cs5_patch_installer(
            itempath, copylocal=item.get("copy_local"), payloads=payloads)
    elif installer_type == "AdobeCCPInstaller":
        # Adobe Creative Cloud Packager packages
        retcode = run_adobe_cpp_pkg_script(itempath, payloads=payloads)
    return retcode


if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
