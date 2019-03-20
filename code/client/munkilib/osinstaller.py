# encoding: utf-8
#
# Copyright 2017-2019 Greg Neagle.
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
osinstaller.py

Created by Greg Neagle on 2017-03-29.

Support for using startosinstall to install macOS.
"""

# stdlib imports
import os
import signal
import subprocess
import time

# PyLint cannot properly find names inside Cocoa libraries, so issues bogus
# No name 'Foo' in module 'Bar' warnings. Disable them.
# pylint: disable=E0611
from Foundation import CFPreferencesSetValue
from Foundation import kCFPreferencesAnyUser
from Foundation import kCFPreferencesCurrentHost
# pylint: enable=E0611

# our imports
import munkilib.authrestart.client as authrestartd

from . import FoundationPlist
from . import authrestart
from . import bootstrapping
from . import display
from . import dmgutils
from . import launchd
from . import munkilog
from . import munkistatus
from . import osutils
from . import pkgutils
from . import prefs
from . import processes
from . import scriptutils


def boot_volume_is_cs_converting():
    '''Returns True if the boot volume is in the middle of a CoreStorage
    conversion from encrypted to decrypted or vice-versa. macOS installs fail
    in this state.'''
    try:
        output = subprocess.check_output(
            ['/usr/sbin/diskutil', 'cs', 'info', '-plist', '/'])
    except subprocess.CalledProcessError:
        # diskutil cs info returns error if volume is not CoreStorage
        return False
    try:
        csinfo_plist = FoundationPlist.readPlistFromString(output)
    except FoundationPlist.FoundationPlistException:
        return False
    conversion_state = csinfo_plist.get(
        'CoreStorageLogicalVolumeConversionState')
    return conversion_state == 'Converting'


def find_install_macos_app(dir_path):
    '''Returns the path to the first Install macOS.app found the top level of
    dir_path, or None'''
    for item in osutils.listdir(dir_path):
        item_path = os.path.join(dir_path, item)
        startosinstall_path = os.path.join(
            item_path, 'Contents/Resources/startosinstall')
        if os.path.exists(startosinstall_path):
            return item_path
    # if we get here we didn't find one
    return None


def install_macos_app_is_stub(app_path):
    '''High Sierra downloaded installer is sometimes a "stub" application that
    does not contain the InstallESD.dmg. Return True if the given app path is
    missing the InstallESD.dmg'''
    installesd_dmg = os.path.join(
        app_path, 'Contents/SharedSupport/InstallESD.dmg')
    return not os.path.exists(installesd_dmg)


def get_os_version(app_path):
    '''Returns the os version from the OS Installer app'''
    installinfo_plist = os.path.join(
        app_path, 'Contents/SharedSupport/InstallInfo.plist')
    if not os.path.isfile(installinfo_plist):
        # no Contents/SharedSupport/InstallInfo.plist
        return ''
    try:
        info = FoundationPlist.readPlist(installinfo_plist)
        return info['System Image Info']['version']
    except (FoundationPlist.FoundationPlistException,
            IOError, KeyError, AttributeError, TypeError):
        return ''


class StartOSInstallError(Exception):
    '''Exception to raise if starting the macOS install fails'''
    pass


class StartOSInstallRunner(object):
    '''Handles running startosinstall to set up and kick off an upgrade install
    of macOS'''
    def __init__(self, installer, finishing_tasks=None, installinfo=None):
        self.installer = installer
        self.installinfo = installinfo
        self.finishing_tasks = finishing_tasks
        self.dmg_mountpoint = None
        self.got_sigusr1 = False

    def sigusr1_handler(self, dummy_signum, dummy_frame):
        '''Signal handler for SIGUSR1 from startosinstall, which tells us it's
        done setting up the macOS install and is ready and waiting to reboot'''
        display.display_debug1('Got SIGUSR1 from startosinstall')
        self.got_sigusr1 = True
        # do cleanup, record-keeping, notifications
        if self.installinfo and 'postinstall_script' in self.installinfo:
            # run the postinstall_script
            dummy_retcode = scriptutils.run_embedded_script(
                'postinstall_script', self.installinfo)
        if self.finishing_tasks:
            self.finishing_tasks()
        # set Munki to run at boot after the OS upgrade is complete
        try:
            bootstrapping.set_bootstrap_mode()
        except bootstrapping.SetupError, err:
            display.display_error(
                'Could not set up Munki to run after OS upgrade is complete: '
                '%s', err)
        if pkgutils.hasValidDiskImageExt(self.installer):
            # remove the diskimage to free up more space for the actual install
            try:
                os.unlink(self.installer)
            except (IOError, OSError):
                pass
        # ask authrestartd if we can do an auth restart, or look for a recovery
        # key (via munkilib.authrestart methods)
        if (authrestartd.verify_can_attempt_auth_restart() or
                authrestart.can_attempt_auth_restart()):
            #
            # set a secret preference to tell the osinstaller process to exit
            # instead of restart
            # this is the equivalent of:
            # `defaults write /Library/Preferences/.GlobalPreferences
            #                 IAQuitInsteadOfReboot -bool YES`
            #
            # This preference is referred to in a framework inside the
            # Install macOS.app:
            # Contents/Frameworks/OSInstallerSetup.framework/Versions/A/
            #     Frameworks/OSInstallerSetupInternal.framework/Versions/A/
            #     OSInstallerSetupInternal
            #
            # It might go away in future versions of the macOS installer.
            #
            CFPreferencesSetValue(
                'IAQuitInsteadOfReboot', True, '.GlobalPreferences',
                kCFPreferencesAnyUser, kCFPreferencesCurrentHost)
        # now tell startosinstall it's OK to proceed
        subprocess.call(['/usr/bin/killall', '-SIGUSR1', 'startosinstall'])

    def get_app_path(self, itempath):
        '''Mounts dmgpath and returns path to the Install macOS.app'''
        if itempath.endswith('.app'):
            return itempath
        if pkgutils.hasValidDiskImageExt(itempath):
            display.display_status_minor(
                'Mounting disk image %s' % os.path.basename(itempath))
            mountpoints = dmgutils.mountdmg(itempath, random_mountpoint=False)
            if mountpoints:
                # look in the first mountpoint for apps
                self.dmg_mountpoint = mountpoints[0]
                app_path = find_install_macos_app(self.dmg_mountpoint)
                if app_path:
                    # leave dmg mounted
                    return app_path
                # if we get here we didn't find an Install macOS.app with the
                # expected contents
                dmgutils.unmountdmg(self.dmg_mountpoint)
                self.dmg_mountpoint = None
                raise StartOSInstallError(
                    'Valid Install macOS.app not found on %s' % itempath)
            else:
                raise StartOSInstallError(
                    u'No filesystems mounted from %s' % itempath)
        else:
            raise StartOSInstallError(
                u'%s doesn\'t appear to be an application or disk image'
                % itempath)

    def start(self):
        '''Starts a macOS install from an Install macOS.app stored at the root
        of a disk image, or from a locally installed Install macOS.app.
        Will always reboot after if the setup is successful.
        Therefore this must be done at the end of all other actions that Munki
        performs during a managedsoftwareupdate run.'''

        if boot_volume_is_cs_converting():
            raise StartOSInstallError(
                'Skipping macOS upgrade because the boot volume is in the '
                'middle of a CoreStorage conversion.')

        if self.installinfo and 'preinstall_script' in self.installinfo:
            # run the postinstall_script
            retcode = scriptutils.run_embedded_script(
                'preinstall_script', self.installinfo)
            if retcode:
                # don't install macOS, return failure
                raise StartOSInstallError(
                    'Skipping macOS upgrade due to preinstall_script error.')

        # set up our signal handler
        signal.signal(signal.SIGUSR1, self.sigusr1_handler)

        # get our tool paths
        app_path = self.get_app_path(self.installer)
        startosinstall_path = os.path.join(
            app_path, 'Contents/Resources/startosinstall')

        os_vers_to_install = get_os_version(app_path)

        # run startosinstall via subprocess

        # we need to wrap our call to startosinstall with a utility
        # that makes startosinstall think it is connected to a tty-like
        # device so its output is unbuffered so we can get progress info
        # otherwise we get nothing until the process exits.
        #
        # Try to find our ptyexec tool
        # first look in the parent directory of this file's directory
        # (../)
        parent_dir = (
            os.path.dirname(
                os.path.dirname(
                    os.path.abspath(__file__))))
        ptyexec_path = os.path.join(parent_dir, 'ptyexec')
        if not os.path.exists(ptyexec_path):
            # try absolute path in munki's normal install dir
            ptyexec_path = '/usr/local/munki/ptyexec'
        if os.path.exists(ptyexec_path):
            cmd = [ptyexec_path]
        else:
            # fall back to /usr/bin/script
            # this is not preferred because it uses way too much CPU
            # checking stdin for input that will never come...
            cmd = ['/usr/bin/script', '-q', '-t', '1', '/dev/null']

        cmd.extend([startosinstall_path,
                    '--agreetolicense',
                    '--rebootdelay', '300',
                    '--pidtosignal', str(os.getpid())])

        if pkgutils.MunkiLooseVersion(
                os_vers_to_install) < pkgutils.MunkiLooseVersion('10.14'):
            # --applicationpath option is _required_ in Sierra and early
            # releases of High Sierra. It became optional (or is ignored?) in
            # later releases of High Sierra and causes warnings in Mojave
            # so don't add this option when installing Mojave
            cmd.extend(['--applicationpath', app_path])

        if pkgutils.MunkiLooseVersion(
                os_vers_to_install) < pkgutils.MunkiLooseVersion('10.12.4'):
            # --volume option is _required_ prior to 10.12.4 installer
            # and must _not_ be included in 10.12.4+ installer's startosinstall
            cmd.extend(['--volume', '/'])

        if pkgutils.MunkiLooseVersion(
                os_vers_to_install) < pkgutils.MunkiLooseVersion('10.13.5'):
            # --nointeraction is an undocumented option that appears to be
            # not only no longer needed/useful but seems to trigger some issues
            # in more recent releases
            cmd.extend(['--nointeraction'])

        if (self.installinfo and
                'additional_startosinstall_options' in self.installinfo):
            cmd.extend(self.installinfo['additional_startosinstall_options'])

        # more magic to get startosinstall to not buffer its output for
        # percent complete
        env = {'NSUnbufferedIO': 'YES'}

        try:
            job = launchd.Job(cmd, environment_vars=env, cleanup_at_exit=False)
            job.start()
        except launchd.LaunchdJobException as err:
            display.display_error(
                'Error with launchd job (%s): %s', cmd, err)
            display.display_error('Aborting startosinstall run.')
            raise StartOSInstallError(err)

        startosinstall_output = []
        timeout = 2 * 60 * 60
        inactive = 0
        while True:
            if processes.stop_requested():
                job.stop()
                break

            info_output = job.stdout.readline()
            if not info_output:
                if job.returncode() is not None:
                    break
                else:
                    # no data, but we're still running
                    inactive += 1
                    if inactive >= timeout:
                        # no output for too long, kill the job
                        display.display_error(
                            "startosinstall timeout after %d seconds"
                            % timeout)
                        job.stop()
                        break
                    # sleep a bit before checking for more output
                    time.sleep(1)
                    continue

            # we got non-empty output, reset inactive timer
            inactive = 0

            info_output = info_output.decode('UTF-8')
            # save all startosinstall output in case there is
            # an error so we can dump it to the log
            startosinstall_output.append(info_output)

            # parse output for useful progress info
            msg = info_output.rstrip('\n')
            if msg.startswith('Preparing to '):
                display.display_status_minor(msg)
            elif msg.startswith('Preparing '):
                # percent-complete messages
                try:
                    percent = int(float(msg[10:].rstrip().rstrip('.')))
                except ValueError:
                    percent = -1
                display.display_percent_done(percent, 100)
            elif msg.startswith(('By using the agreetolicense option',
                                 'If you do not agree,')):
                # annoying legalese
                pass
            elif msg.startswith('Helper tool cr'):
                # no need to print that stupid message to screen!
                # 10.12: 'Helper tool creashed'
                # 10.13: 'Helper tool crashed'
                munkilog.log(msg)
            elif msg.startswith(
                    ('Signaling PID:', 'Waiting to reboot',
                     'Process signaled okay')):
                # messages around the SIGUSR1 signalling
                display.display_debug1('startosinstall: %s', msg)
            elif msg.startswith('System going down for install'):
                display.display_status_minor(
                    'System will restart and begin upgrade of macOS.')
            else:
                # none of the above, just display
                display.display_status_minor(msg)

        # startosinstall exited
        munkistatus.percent(100)
        retcode = job.returncode()
        # previously we unmounted the disk image, but since we're going to
        # restart very very soon, don't bother
        #if self.dmg_mountpoint:
        #    dmgutils.unmountdmg(self.dmg_mountpoint)

        if retcode and not (retcode == 255 and self.got_sigusr1):
            # append stderr to our startosinstall_output
            if job.stderr:
                startosinstall_output.extend(job.stderr.read().splitlines())
            display.display_status_minor(
                "Starting macOS install failed with return code %s" % retcode)
            display.display_error("-"*78)
            for line in startosinstall_output:
                display.display_error(line.rstrip("\n"))
            display.display_error("-"*78)
            raise StartOSInstallError(
                'startosinstall failed with return code %s' % retcode)
        elif self.got_sigusr1:
            # startosinstall got far enough along to signal us it was ready
            # to finish and reboot, so we can believe it was successful
            munkilog.log('macOS install successfully set up.')
            munkilog.log(
                'Starting macOS install of %s: SUCCESSFUL' % os_vers_to_install,
                'Install.log')
            # previously we checked if retcode == 255:
            # that may have been something specific to 10.12's startosinstall
            # if startosinstall exited after sending us sigusr1 we should
            # handle the restart.
            if retcode not in (0, 255):
                # some logging for possible investigation in the future
                munkilog.log('startosinstall exited %s' % retcode)
            munkilog.log('startosinstall quit instead of rebooted; we will '
                         'do restart.')
            # clear our special secret InstallAssistant preference
            CFPreferencesSetValue(
                'IAQuitInsteadOfReboot', None, '.GlobalPreferences',
                kCFPreferencesAnyUser, kCFPreferencesCurrentHost)
            # attempt to do an auth restart, or regular restart
            if not authrestartd.restart():
                authrestart.do_authorized_or_normal_restart()
        else:
            raise StartOSInstallError(
                'startosinstall did not complete successfully. '
                'See /var/log/install.log for details.')


def get_catalog_info(mounted_dmgpath):
    '''Returns catalog info (pkginfo) for a macOS Sierra installer on a disk
    image'''
    app_path = find_install_macos_app(mounted_dmgpath)
    if app_path:
        vers = get_os_version(app_path)
        if vers:
            display_name = os.path.splitext(os.path.basename(app_path))[0]
            name = display_name.replace(' ', '_')
            description = 'Installs macOS version %s' % vers
            if vers.startswith('10.12'):
                # Sierra was 8.8GB at http://www.apple.com/macos/how-to-upgrade/
                # (http://web.archive.org/web/20160910163424/
                #      https://www.apple.com/macos/how-to-upgrade/)
                installed_size = int(8.8 * 1024 * 1024)
            elif vers.startswith('10.13'):
                # High Sierra:
                # "14.3GB of available storage to perform upgrade"
                # http://www.apple.com/macos/how-to-upgrade/
                installed_size = int(14.3 * 1024 * 1024)
            else:
                # will need to modify for future macOS releases
                installed_size = int(14.3 * 1024 * 1024)
            return {'RestartAction': 'RequireRestart',
                    'apple_item': True,
                    'description': description,
                    'display_name': display_name,
                    'installed_size': installed_size,
                    'installer_type': 'startosinstall',
                    'minimum_munki_version': '3.0.0.3211',
                    'minimum_os_version': '10.8',
                    'name': name,
                    'uninstallable': False,
                    'version': vers}
    return None


def startosinstall(installer, finishing_tasks=None, installinfo=None):
    '''Run startosinstall to set up an install of macOS, using a Install app
    installed locally or located on a given disk image. Returns True if
    startosinstall completes successfully, False otherwise.'''
    try:
        StartOSInstallRunner(
            installer,
            finishing_tasks=finishing_tasks, installinfo=installinfo).start()
        return True
    except StartOSInstallError, err:
        display.display_error(
            u'Error starting macOS install: %s', unicode(err))
        munkilog.log(
            'Starting macOS install: FAILED: %s' % unicode(err), 'Install.log')
        return False


def run(finishing_tasks=None):
    '''Runs the first startosinstall item in InstallInfo.plist's
    managed_installs. Returns True if successful, False otherwise'''
    managedinstallbase = prefs.pref('ManagedInstallDir')
    cachedir = os.path.join(managedinstallbase, 'Cache')
    installinfopath = os.path.join(managedinstallbase, 'InstallInfo.plist')
    try:
        installinfo = FoundationPlist.readPlist(installinfopath)
    except FoundationPlist.NSPropertyListSerializationException:
        display.display_error("Invalid %s" % installinfopath)
        return False

    if prefs.pref('SuppressStopButtonOnInstall'):
        munkistatus.hideStopButton()

    success = False
    if "managed_installs" in installinfo:
        if not processes.stop_requested():
            # filter list to items that need to be installed
            installlist = [
                item for item in installinfo['managed_installs']
                if item.get('installer_type') == 'startosinstall']
            if installlist:
                munkilog.log("### Beginning os installer session ###")
                item = installlist[0]
                if not 'installer_item' in item:
                    display.display_error(
                        'startosinstall item is missing installer_item.')
                    return False
                display.display_status_major('Starting macOS upgrade...')
                # set indeterminate progress bar
                munkistatus.percent(-1)
                # remove the InstallInfo.plist since it won't be valid
                # after the upgrade
                try:
                    os.unlink(installinfopath)
                except (OSError, IOError):
                    pass
                itempath = os.path.join(cachedir, item["installer_item"])
                success = startosinstall(
                    itempath,
                    finishing_tasks=finishing_tasks, installinfo=item)
    munkilog.log("### Ending os installer session ###")
    return success


if __name__ == '__main__':
    print 'This is a library of support tools for the Munki Suite.'
