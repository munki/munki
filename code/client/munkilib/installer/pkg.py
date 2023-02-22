# encoding: utf-8
#
# Copyright 2009-2023 Greg Neagle.
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

# This code is largely still compatible with Python 2, so for now, turn off
# Python 3 style warnings
# pylint: disable=consider-using-f-string
# pylint: disable=redundant-u-string-prefix

from __future__ import absolute_import, print_function

import os
import pwd
import signal
import subprocess
import time

from .. import display
from .. import dmgutils
from .. import info
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


def pkg_needs_restart(pkgpath, options):
    '''Query a package for its RestartAction. Returns True if a restart is
    needed, False otherwise'''
    cmd = ['/usr/sbin/installer', '-query', 'RestartAction', '-pkg', pkgpath]
    if options.get('installer_choices_xml'):
        choices_xml_file = os.path.join(osutils.tmpdir(), 'choices.xml')
        FoundationPlist.writePlist(
            options.get('installer_choices_xml'), choices_xml_file)
        cmd.extend(['-applyChoiceChangesXML', choices_xml_file])
    else:
        choices_xml_file = None
    if options.get('allow_untrusted'):
        cmd.append('-allowUntrusted')
    proc = subprocess.Popen(cmd, shell=False, bufsize=-1,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output = proc.communicate()[0].decode('UTF-8')
    restartaction = output.rstrip('\n')
    return restartaction in ['RequireRestart', 'RecommendRestart']


def get_installer_env(custom_env):
    '''Sets up environment for installer'''
    env_vars = os.environ.copy()
    # get info for root
    userinfo = pwd.getpwuid(0)
    env_vars['USER'] = userinfo.pw_name
    env_vars['HOME'] = userinfo.pw_dir
    if custom_env:
        # Munki admin has specified custom installer environment
        for key in custom_env.keys():
            if key == 'USER' and custom_env[key] == 'CURRENT_CONSOLE_USER':
                # current console user (if there is one) 'owns' /dev/console
                userinfo = pwd.getpwuid(os.stat('/dev/console').st_uid)
                env_vars['USER'] = userinfo.pw_name
                env_vars['HOME'] = userinfo.pw_dir
            else:
                env_vars[key] = custom_env[key]
        display.display_debug1(
            'Using custom installer environment variables: %s', env_vars)
    return env_vars


def _display_installer_output(installinfo):
    '''Parses a line of output from installer, displays it as progress output
    and logs it'''
    # output we're dealing with always starts with 'installer:'
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


def _run_installer(cmd, env_vars, packagename):
    '''Runs /usr/sbin/installer, parses and displays the output, and returns
    the process exit code'''
    installeroutput = []

    job = subprocess.Popen(
        cmd,
        env=env_vars,
        shell=False,
        bufsize=-1,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    timeout = 2 * 60 * 60
    last_output = None
    while True:
        installinfo = job.stdout.readline()
        if not installinfo and job.poll() is not None:
            break

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
            _display_installer_output(installinfo)

    # installer exited or was killed
    # try for a little bit to catch return code from exiting process...
    retcode = job.poll()
    i = 0
    while retcode is None and i < 5:
        time.sleep(1)
        i += 1
        retcode = job.poll()

    if retcode != 0:
        # append stdout to our installer output
        installeroutput.extend(job.stderr.read().decode("UTF-8").splitlines())
        display.display_status_minor(
            "Install of %s failed with return code %s" % (packagename, retcode))
        display.display_error("-"*78)
        for line in installeroutput:
            display.display_error(line.rstrip("\n"))
        display.display_error("-"*78)
    elif retcode == 0:
        munkilog.log("Install of %s was successful." % packagename)
        munkistatus.percent(100)
    return retcode


def install(pkgpath, options=None):
    """
    Uses the apple installer to install the package or metapackage
    at pkgpath.
    Returns a tuple:
    the installer return code and restart needed as a boolean.
    """

    restartneeded = False

    if not options:
        options = {}
    display_name = options.get('display_name') or options.get('name')

    if os.path.islink(pkgpath):
        # resolve links before passing them to /usr/bin/installer
        pkgpath = os.path.realpath(pkgpath)

    if options.get('suppress_bundle_relocation'):
        remove_bundle_relocation_info(pkgpath)

    packagename = os.path.basename(pkgpath)
    if not display_name:
        display_name = packagename

    munkilog.log("Installing %s from %s" % (display_name, packagename))
    if pkg_needs_restart(pkgpath, options):
        display.display_status_minor(
            '%s requires a restart after installation.' % display_name)
        restartneeded = True

    # set up installer cmd
    cmd = ['/usr/sbin/installer', '-verboseR', '-pkg', pkgpath, '-target', '/']
    if options.get('installer_choices_xml'):
        # choices_xml_file was already built by pkg_needs_restart(),
        # just re-use it
        choices_xml_file = os.path.join(osutils.tmpdir(), 'choices.xml')
        cmd.extend(['-applyChoiceChangesXML', choices_xml_file])
    if options.get('allow_untrusted'):
        cmd.append('-allowUntrusted')

    # get env for installer
    env_vars = get_installer_env(options.get('installer_environment'))

    # run it!
    retcode = _run_installer(cmd, env_vars, packagename)
    if retcode:
        restartneeded = False
    return (retcode, restartneeded)


def installall(dirpath, options=None):
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
            mountpoints = dmgutils.mountdmg(
                itempath, use_shadow=True, skip_verification=True)
            if not mountpoints:
                display.display_error("No filesystems mounted from %s", item)
                return (retcode, restartflag)
            if processes.stop_requested():
                dmgutils.unmountdmg(mountpoints[0])
                return (retcode, restartflag)
            for mountpoint in mountpoints:
                # install all the pkgs and mpkgs at the root
                # of the mountpoint -- call us recursively!
                (retcode, needsrestart) = installall(
                    mountpoint, options=options)
                if needsrestart:
                    restartflag = True
                if retcode:
                    # ran into error; should unmount and stop.
                    dmgutils.unmountdmg(mountpoints[0])
                    return (retcode, restartflag)

            dmgutils.unmountdmg(mountpoints[0])

        if pkgutils.hasValidInstallerItemExt(item):
            (retcode, needsrestart) = install(
                itempath, options=options)
            if needsrestart:
                restartflag = True
            if retcode:
                # ran into error; should stop.
                return (retcode, restartflag)

    return (retcode, restartflag)


if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
