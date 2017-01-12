# encoding: utf-8
#
# Copyright 2009-2017 Greg Neagle.
#
# Licensed under the Apache License, Version 2.0 (the 'License');
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an 'AS IS' BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
installer.pkg

Created by Greg Neagle on 2017-01-03.

Routines for installing Apple pkgs
"""

import os
import pwd
import subprocess
import time

from .. import display
from .. import dmgutils
from .. import launchd
from .. import munkilog
from .. import munkistatus
from .. import osutils
from .. import processes
from .. import pkgutils
from .. import FoundationPlist


def remove_bundle_relocation_info(pkgpath):
    '''Attempts to remove any info in the package that would cause
    bundle relocation behavior. This makes bundles install or update in their
    default location.'''
    display.display_debug1("Looking for bundle relocation info...")
    if os.path.isdir(pkgpath):
        # remove relocatable stuff
        tokendefinitions = os.path.join(
            pkgpath, "Contents/Resources/TokenDefinitions.plist")
        if os.path.exists(tokendefinitions):
            try:
                os.remove(tokendefinitions)
                display.display_debug1(
                    "Removed Contents/Resources/TokenDefinitions.plist")
            except OSError:
                pass

        plist = {}
        infoplist = os.path.join(pkgpath, "Contents/Info.plist")
        if os.path.exists(infoplist):
            try:
                plist = FoundationPlist.readPlist(infoplist)
            except FoundationPlist.NSPropertyListSerializationException:
                pass

        if 'IFPkgPathMappings' in plist:
            del plist['IFPkgPathMappings']
            try:
                FoundationPlist.writePlist(plist, infoplist)
                display.display_debug1("Removed IFPkgPathMappings")
            except FoundationPlist.NSPropertyListWriteException:
                pass


def install(pkgpath, display_name=None, choicesXMLpath=None,
            suppressBundleRelocation=False, environment=None):
    """
    Uses the apple installer to install the package or metapackage
    at pkgpath. Prints status messages to STDOUT.
    Returns a tuple:
    the installer return code and restart needed as a boolean.
    """

    restartneeded = False
    installeroutput = []

    if os.path.islink(pkgpath):
        # resolve links before passing them to /usr/bin/installer
        pkgpath = os.path.realpath(pkgpath)

    if suppressBundleRelocation:
        remove_bundle_relocation_info(pkgpath)

    packagename = os.path.basename(pkgpath)
    if not display_name:
        display_name = packagename
    munkilog.log("Installing %s from %s" % (display_name, packagename))
    cmd = ['/usr/sbin/installer', '-query', 'RestartAction', '-pkg', pkgpath]
    if choicesXMLpath:
        cmd.extend(['-applyChoiceChangesXML', choicesXMLpath])
    proc = subprocess.Popen(cmd, shell=False, bufsize=-1,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (output, dummy_err) = proc.communicate()
    restartaction = str(output).decode('UTF-8').rstrip("\n")
    if restartaction == "RequireRestart" or \
       restartaction == "RecommendRestart":
        display.display_status_minor(
            '%s requires a restart after installation.' % display_name)
        restartneeded = True

    # get the OS version; we need it later when processing installer's output,
    # which varies depending on OS version.
    os_version = osutils.getOsVersion()
    cmd = ['/usr/sbin/installer', '-verboseR', '-pkg', pkgpath, '-target', '/']
    if choicesXMLpath:
        cmd.extend(['-applyChoiceChangesXML', choicesXMLpath])

    # set up environment for installer
    env_vars = os.environ.copy()
    # get info for root
    userinfo = pwd.getpwuid(0)
    env_vars['USER'] = userinfo.pw_name
    env_vars['HOME'] = userinfo.pw_dir
    if environment:
        # Munki admin has specified custom installer environment
        for key in environment.keys():
            if key == 'USER' and environment[key] == 'CURRENT_CONSOLE_USER':
                # current console user (if there is one) 'owns' /dev/console
                userinfo = pwd.getpwuid(os.stat('/dev/console').st_uid)
                env_vars['USER'] = userinfo.pw_name
                env_vars['HOME'] = userinfo.pw_dir
            else:
                env_vars[key] = environment[key]
        display.display_debug1(
            'Using custom installer environment variables: %s', env_vars)

    # run installer as a launchd job
    try:
        job = launchd.Job(cmd, environment_vars=env_vars)
        job.start()
    except launchd.LaunchdJobException, err:
        display.display_error(
            'Error with launchd job (%s): %s', cmd, str(err))
        display.display_error('Can\'t run installer.')
        return (-3, False)

    timeout = 2 * 60 * 60
    inactive = 0
    last_output = None
    while True:
        installinfo = job.stdout.readline()
        if not installinfo:
            if job.returncode() is not None:
                break
            else:
                # no data, but we're still running
                inactive += 1
                if inactive >= timeout:
                    # no output for too long, kill this installer session
                    display.display_error(
                        "/usr/sbin/installer timeout after %d seconds"
                        % timeout)
                    job.stop()
                    break
                # sleep a bit before checking for more output
                time.sleep(1)
                continue

        # we got non-empty output, reset inactive timer
        inactive = 0

        # Don't bother parsing the stdout output if it hasn't changed since
        # the last loop iteration.
        if last_output == installinfo:
            continue
        last_output = installinfo

        installinfo = installinfo.decode('UTF-8')
        if installinfo.startswith("installer:"):
            # save all installer output in case there is
            # an error so we can dump it to the log
            installeroutput.append(installinfo)
            msg = installinfo[10:].rstrip("\n")
            if msg.startswith("PHASE:"):
                phase = msg[6:]
                if phase:
                    display.display_status_minor(phase)
            elif msg.startswith("STATUS:"):
                status = msg[7:]
                if status:
                    display.display_status_minor(status)
            elif msg.startswith("%"):
                percent = float(msg[1:])
                if os_version == '10.5':
                    # Leopard uses a float from 0 to 1
                    percent = percent * 100
                munkistatus.percent(percent)
                display.display_status_minor("%s percent complete" % percent)
            elif msg.startswith(" Error"):
                display.display_error(msg)
                munkistatus.detail(msg)
            elif msg.startswith(" Cannot install"):
                display.display_error(msg)
                munkistatus.detail(msg)
            else:
                munkilog.log(msg)

    # installer exited
    retcode = job.returncode()
    if retcode != 0:
        # append stdout to our installer output
        installeroutput.extend(job.stderr.read().splitlines())
        display.display_status_minor(
            "Install of %s failed with return code %s" % (packagename, retcode))
        display.display_error("-"*78)
        for line in installeroutput:
            display.display_error(line.rstrip("\n"))
        display.display_error("-"*78)
        restartneeded = False
    elif retcode == 0:
        munkilog.log("Install of %s was successful." % packagename)
        munkistatus.percent(100)

    return (retcode, restartneeded)


def installall(dirpath, display_name=None, choicesXMLpath=None,
               suppressBundleRelocation=False, environment=None):
    """
    Attempts to install all pkgs and mpkgs in a given directory.
    Will mount dmg files and install pkgs and mpkgs found at the
    root of any mountpoints.
    """
    retcode = 0
    restartflag = False
    installitems = osutils.listdir(dirpath)
    for item in installitems:
        if processes.stop_requested():
            return (retcode, restartflag)
        itempath = os.path.join(dirpath, item)
        if pkgutils.hasValidDiskImageExt(item):
            display.display_info("Mounting disk image %s" % item)
            mountpoints = dmgutils.mountdmg(itempath, use_shadow=True)
            if mountpoints == []:
                display.display_error("No filesystems mounted from %s", item)
                return (retcode, restartflag)
            if processes.stop_requested():
                dmgutils.unmountdmg(mountpoints[0])
                return (retcode, restartflag)
            for mountpoint in mountpoints:
                # install all the pkgs and mpkgs at the root
                # of the mountpoint -- call us recursively!
                (retcode, needsrestart) = installall(mountpoint, display_name,
                                                     choicesXMLpath,
                                                     suppressBundleRelocation,
                                                     environment)
                if needsrestart:
                    restartflag = True
                if retcode:
                    # ran into error; should unmount and stop.
                    dmgutils.unmountdmg(mountpoints[0])
                    return (retcode, restartflag)

            dmgutils.unmountdmg(mountpoints[0])

        if pkgutils.hasValidInstallerItemExt(item):
            (retcode, needsrestart) = install(
                itempath, display_name,
                choicesXMLpath, suppressBundleRelocation, environment)
            if needsrestart:
                restartflag = True
            if retcode:
                # ran into error; should stop.
                return (retcode, restartflag)

    return (retcode, restartflag)


if __name__ == '__main__':
    print 'This is a library of support tools for the Munki Suite.'
