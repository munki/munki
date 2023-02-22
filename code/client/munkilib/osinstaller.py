# encoding: utf-8
#
# Copyright 2017-2023 Greg Neagle.
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
August 2022: added support for launching the Install macOS app
"""
# This code is largely still compatible with Python 2, so for now, turn off
# Python 3 style warnings
# pylint: disable=consider-using-f-string
# pylint: disable=redundant-u-string-prefix
# pylint: disable=useless-object-inheritance

from __future__ import absolute_import, print_function

# stdlib imports
import os
import signal
import subprocess
import time

# PyLint cannot properly find names inside Cocoa libraries, so issues bogus
# No name 'Foo' in module 'Bar' warnings. Disable them.
# pylint: disable=E0611,E0401
from Foundation import CFPreferencesSetValue
from Foundation import kCFPreferencesAnyUser
from Foundation import kCFPreferencesCurrentHost
# pylint: enable=E0611,E0401

# our imports
import munkilib.authrestart.client as authrestartd

from . import FoundationPlist
from . import authrestart
from . import bootstrapping
from . import display
from . import dmgutils
from . import info
from . import launchd
from . import munkilog
from . import munkistatus
from . import osutils
from . import pkgutils
from . import prefs
from . import processes
from . import reports
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
    missing the InstallESD.dmg and missing SharedSupport.dmg (new in Big Sur)'''
    installesd_dmg = os.path.join(
        app_path, 'Contents/SharedSupport/InstallESD.dmg')
    sharedsupport_dmg = os.path.join(
        app_path, 'Contents/SharedSupport/SharedSupport.dmg')
    return not (os.path.exists(installesd_dmg) or
                os.path.exists(sharedsupport_dmg))


def get_os_version(app_path):
    '''Returns the os version from the OS Installer app'''
    installinfo_plist = os.path.join(
        app_path, 'Contents/SharedSupport/InstallInfo.plist')
    if os.path.isfile(installinfo_plist):
        try:
            install_info = FoundationPlist.readPlist(installinfo_plist)
            return install_info['System Image Info']['version']
        except (FoundationPlist.FoundationPlistException,
                IOError, KeyError, AttributeError, TypeError):
            return ''
    sharedsupport_dmg = os.path.join(
        app_path, 'Contents/SharedSupport/SharedSupport.dmg')
    if os.path.isfile(sharedsupport_dmg):
        # starting with macOS Big Sur
        mountpoints = dmgutils.mountdmg(sharedsupport_dmg)
        if mountpoints:
            plist_path = os.path.join(
                mountpoints[0],
                "com_apple_MobileAsset_MacSoftwareUpdate",
                "com_apple_MobileAsset_MacSoftwareUpdate.xml"
            )
            try:
                plist = FoundationPlist.readPlist(plist_path)
                return plist['Assets'][0]['OSVersion']
            except FoundationPlist.FoundationPlistException:
                return ''
            finally:
                dmgutils.unmountdmg(mountpoints[0])
    return ''


def setup_authrestart_if_applicable():
    '''Sets up the ability to do an authrestart if applicable'''
    # ask authrestartd if we can do an auth restart, or look for a recovery
    # key (via munkilib.authrestart methods)
    if (authrestartd.verify_can_attempt_auth_restart() or
            authrestart.can_attempt_auth_restart()):
        display.display_info(
            'FileVault is active and we can do an authrestart')
        # set an undocumented  preference to tell the osinstaller
        # process to exit instead of restart
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
        # (but it's still there in the macOS 13 installer!)
        display.display_info(
            'Configuring startosinstall to quit instead of restart...')
        CFPreferencesSetValue(
            'IAQuitInsteadOfReboot', True, '.GlobalPreferences',
            kCFPreferencesAnyUser, kCFPreferencesCurrentHost)


class StartOSInstallError(Exception):
    '''Exception to raise if starting the macOS install fails'''


class StartOSInstallRunner(object):
    '''Handles running startosinstall to set up and kick off an upgrade install
    of macOS'''
    def __init__(self, installer, finishing_tasks=None, installinfo=None):
        self.installer = installer
        self.installinfo = installinfo
        self.finishing_tasks = finishing_tasks
        self.dmg_mountpoint = None
        self.got_sigusr1 = False

    def sigusr1_handler(self, _signum, _frame):
        '''Signal handler for SIGUSR1 from startosinstall, which tells us it's
        done setting up the macOS install and is ready and waiting to reboot'''
        display.display_debug1('Got SIGUSR1 from startosinstall')
        self.got_sigusr1 = True

        setup_authrestart_if_applicable()

        # set Munki to run at boot after the OS upgrade is complete
        try:
            bootstrapping.set_bootstrap_mode()
        except bootstrapping.SetupError as err:
            display.display_error(
                'Could not set up Munki to run after OS upgrade is complete: '
                '%s', err)

        # do cleanup, record-keeping, notifications
        if self.installinfo and 'postinstall_script' in self.installinfo:
            # run the postinstall_script
            dummy_retcode = scriptutils.run_embedded_script(
                'postinstall_script', self.installinfo)
        if self.finishing_tasks:
            self.finishing_tasks()

        if pkgutils.hasValidDiskImageExt(self.installer):
            # remove the diskimage to free up more space for the actual install
            try:
                os.unlink(self.installer)
            except (IOError, OSError):
                pass

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
            #else:
            raise StartOSInstallError(
                u'No filesystems mounted from %s' % itempath)
        #else:
        raise StartOSInstallError(
            u'%s doesn\'t appear to be an application or disk image'
            % itempath)

    def start(self):
        '''Starts a macOS install from an Install macOS.app stored at the root
        of a disk image, or from a locally installed Install macOS.app.
        Will always reboot after if the setup is successful.
        Therefore this must be done at the end of all other actions that Munki
        performs during a managedsoftwareupdate run.'''

        if info.is_apple_silicon():
            raise StartOSInstallError(
                'Skipping macOS upgrade because this is not currently '
                'supported on Apple silicon.')

        if boot_volume_is_cs_converting():
            raise StartOSInstallError(
                'Skipping macOS upgrade because the boot volume is in the '
                'middle of a CoreStorage conversion.')

        if self.installinfo and 'preinstall_script' in self.installinfo:
            # run the preinstall_script
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
        if not os_vers_to_install:
            display.display_warning(
                'Could not get OS version to install from application bundle.')

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

        if os_vers_to_install and pkgutils.MunkiLooseVersion(
                os_vers_to_install) < pkgutils.MunkiLooseVersion('10.14'):
            # --applicationpath option is _required_ in Sierra and early
            # releases of High Sierra. It became optional (or is ignored?) in
            # later releases of High Sierra and causes warnings in Mojave
            # so don't add this option when installing Mojave
            cmd.extend(['--applicationpath', app_path])

        if os_vers_to_install and pkgutils.MunkiLooseVersion(
                os_vers_to_install) < pkgutils.MunkiLooseVersion('10.12.4'):
            # --volume option is _required_ prior to 10.12.4 installer
            # and must _not_ be included in 10.12.4+ installer's startosinstall
            cmd.extend(['--volume', '/'])

        if os_vers_to_install and pkgutils.MunkiLooseVersion(
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
            raise StartOSInstallError(err) from err

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
                #else:
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
            msg = info_output.strip()
            if msg.startswith('Preparing to '):
                display.display_status_minor(msg)
            elif msg.startswith(('Preparing ', 'Preparing: ')):
                # percent-complete messages
                percent_str = msg.split()[-1].rstrip('%.')
                try:
                    percent = int(float(percent_str))
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

        if self.got_sigusr1:
            # startosinstall got far enough along to signal us it was ready
            # to finish and reboot, so we can believe it was successful
            munkilog.log('macOS install successfully set up.')
            munkilog.log(
                'Starting macOS install of %s: SUCCESSFUL' % os_vers_to_install,
                'Install.log')
            if retcode:
                # some logging for possible investigation in the future
                munkilog.log('startosinstall exited %s' % retcode)
            munkilog.log('startosinstall quit instead of rebooted; we will '
                         'do restart.')
            # clear our special secret InstallAssistant preference
            CFPreferencesSetValue(
                'IAQuitInsteadOfReboot', None, '.GlobalPreferences',
                kCFPreferencesAnyUser, kCFPreferencesCurrentHost)
            # attempt to do an auth restart, or regular restart, or shutdown
            if not authrestartd.restart():
                authrestart.do_authorized_or_normal_restart(
                    shutdown=osutils.bridgeos_update_staged())
        elif retcode:
            # did not get SIGUR1 and exited non-zero
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
                'startosinstall failed with return code %s. '
                'See /var/log/install.log for details.' % retcode)
        else:
            # retcode == 0 but we got no SIGUSR1
            raise StartOSInstallError(
                'startosinstall did not complete successfully. '
                'See /var/log/install.log for details.')


def get_startosinstall_catalog_info(mounted_dmgpath):
    '''Returns catalog info (pkginfo) for a macOS installer on a disk
    image, using the startosinstall installation method'''
    app_path = find_install_macos_app(mounted_dmgpath)
    if app_path:
        vers = get_os_version(app_path)
        minimum_munki_version = '3.0.0.3211'
        minimum_os_version = '10.8'
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
            elif vers.startswith('10.14'):
                # Mojave:
                # https://support.apple.com/en-us/HT210190
                installed_size = int(18.5 * 1024 * 1024)
            elif vers.startswith('10.15'):
                # Catalina:
                # https://support.apple.com/en-us/HT201475
                installed_size = int(18.5 * 1024 * 1024)
                minimum_munki_version = '3.6.3'
                minimum_os_version = '10.9'
            elif vers.startswith('11.'):
                # Big Sur
                # https://support.apple.com/en-us/HT211238
                installed_size = int(35.5 * 1024 * 1024)
                # but we really need Munki 5.1 in place before we install
                minimum_munki_version = '5.1.0'
                minimum_os_version = '10.9'
            elif vers.startswith('12.'):
                # Monterey
                # https://support.apple.com/en-us/HT212551
                installed_size = int(26 * 1024 * 1024)
                minimum_munki_version = '5.1.0'
                minimum_os_version = '10.9'
            else:
                # will need to modify for future macOS releases, but should
                # never be less than the highest version we know about
                installed_size = int(26 * 1024 * 1024)
                minimum_munki_version = '5.1.0'
                minimum_os_version = '10.9'

            return {'RestartAction': 'RequireRestart',
                    'apple_item': True,
                    'description': description,
                    'display_name': display_name,
                    'installed_size': installed_size,
                    'installer_type': 'startosinstall',
                    'minimum_munki_version': minimum_munki_version,
                    'minimum_os_version': minimum_os_version,
                    'name': name,
                    'supported_architectures': ["x86_64"],
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
    except StartOSInstallError as err:
        display.display_error(
            u'Error starting macOS install: %s', err)
        munkilog.log(
            u'Starting macOS install: FAILED: %s' % err, 'Install.log')
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


#### support for launching Install macOS app ####

##### functions for working with info about a staged macOS installer #####

def get_stage_os_installer_catalog_info(app_path):
    '''Returns additional catalog info from macOS installer at app_path,
    describing a stage_os_installer item'''

    # calculate the size of the installer app
    appsize = 0
    for (path, _, files) in os.walk(app_path):
        for name in files:
            filename = os.path.join(path, name)
            # use os.lstat so we don't follow symlinks
            appsize += int(os.lstat(filename).st_size)
    # convert to kbytes
    appsize = int(appsize/1024)

    vers = get_os_version(app_path)
    minimum_munki_version = '6.0.0'
    minimum_os_version = '10.9'
    if vers:
        display_name_staged = os.path.splitext(os.path.basename(app_path))[0]
        macos_name = display_name_staged.replace('Install ', '')
        display_name = '%s Installer' % macos_name
        description = 'Downloads %s installer' % macos_name
        description_staged = 'Installs %s, version %s' % (macos_name, vers)
        if vers.startswith('11.'):
            # Big Sur requires 35.5GB of available storage to upgrade.
            # https://support.apple.com/en-us/HT211238
            installed_size = int(35.5 * 1024 * 1024) - appsize
        elif vers.startswith('12.'):
            # Monterey requires 26GB of available storage to upgrade.
            # https://support.apple.com/en-us/HT212551
            installed_size = int(26 * 1024 * 1024) - appsize
        else:
            # will need to modify for future macOS releases, but should
            # never be less than the highest version we know about
            installed_size = int(26 * 1024 * 1024) - appsize

        return {'description': description,
                'description_staged': description_staged,
                'display_name': display_name,
                'display_name_staged': display_name_staged,
                'installed_size_staged': installed_size,
                'installer_type': 'stage_os_installer',
                'minimum_munki_version': minimum_munki_version,
                'minimum_os_version': minimum_os_version,
                'name': display_name_staged.replace(' ', '_'),
                'uninstallable': True,
                'version': vers}
    return {}


def verify_staged_os_installer(app_path):
    '''Attempts to trigger a "verification" process against the staged macOS
    installer. This improves the launch time.'''
    display.display_status_minor("Verifying macOS installer...")
    display.display_percent_done(-1, 100)
    startosinstall_path = os.path.join(
        app_path, 'Contents/Resources/startosinstall')
    try:
        proc = subprocess.Popen([startosinstall_path, "--usage"],
                                shell=False,
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
    except (OSError, IOError) as err:
        display.display_warning(u'Error verifying macOS installer: %s', err)
    else:
        stderr = proc.communicate()[1]
        if proc.returncode:
            display.display_warning(u'Error verifying macOS installer: %s', stderr)


def staged_os_installer_info_path():
    '''returns the path to the StagedOSInstaller.plist (which may or may not
    actually exist)'''
    managedinstallbase = prefs.pref('ManagedInstallDir')
    return os.path.join(managedinstallbase, 'StagedOSInstaller.plist')


def get_osinstaller_path(iteminfo):
    '''Returns the expected path to the locally staged macOS installer'''
    try:
        copied_item = iteminfo["items_to_copy"][0]
    except (KeyError, IndexError):
        return None
    source_itemname = copied_item.get("source_item")
    destpath = copied_item.get('destination_path')
    dest_itemname = copied_item.get("destination_item")
    if not destpath:
        destpath = copied_item.get('destination_item')
        if destpath:
            # split it into path and name
            dest_itemname = os.path.basename(destpath)
            destpath = os.path.dirname(destpath)
    if not destpath:
        return None
    return os.path.join(
        destpath, os.path.basename(dest_itemname or source_itemname))


def create_osinstaller_info(iteminfo):
    '''Creates a dict describing a staged OS installer'''
    osinstaller_info = {}
    osinstaller_path = get_osinstaller_path(iteminfo)
    if osinstaller_path:
        osinstaller_info['osinstaller_path'] = osinstaller_path
        osinstaller_info['name'] = iteminfo.get('name', '')
        osinstaller_info['display_name'] = iteminfo.get(
            'display_name_staged',
            iteminfo.get('display_name', iteminfo['name'])
        )
        osinstaller_info['description'] = iteminfo.get(
            'description_staged',
            iteminfo.get('description', '')
        )
        osinstaller_info['installed_size'] = iteminfo.get(
            'installed_size_staged',
            iteminfo.get('installed_size',
                         iteminfo.get('installer_item_size', 0))
        )
        osinstaller_info['installed'] = False
        osinstaller_info['version_to_install'] = iteminfo.get(
            'version_to_install',
            iteminfo.get('version', 'UNKNOWN')
        )
        osinstaller_info['developer'] = iteminfo.get('developer', 'Apple')
        # optional keys to copy if they exist
        optional_keys = ['category', 'icon_name', 'localized_strings']
        for key in optional_keys:
            if key in iteminfo:
                osinstaller_info[key] = iteminfo[key]
    return osinstaller_info


def record_staged_os_installer(iteminfo):
    '''Records info on a staged macOS installer. This includes info for
    managedsoftwareupdate and Managed Software Center to display, and the
    path to the staged installer.'''
    infopath = staged_os_installer_info_path()
    staged_os_installer_info = create_osinstaller_info(iteminfo)
    if staged_os_installer_info:
        try:
            FoundationPlist.writePlist(staged_os_installer_info, infopath)
        except FoundationPlist.FoundationPlistException as err:
            display.display_error(
                "Error recording staged macOS installer: %s" % err)
        # finally, trigger a verification
        verify_staged_os_installer(staged_os_installer_info["osinstaller_path"])
    else:
        display.display_error("Error recording staged macOS installer: "
            "could not get osinstaller_path")


def get_staged_os_installer_info():
    '''Returns any info we may have on a staged OS installer'''
    infopath = staged_os_installer_info_path()
    if not os.path.exists(infopath):
        return None
    try:
        osinstaller_info = FoundationPlist.readPlist(infopath)
    except FoundationPlist.NSPropertyListSerializationException:
        display.display_error("Invalid %s" % infopath)
        return None
    app_path = osinstaller_info.get("osinstaller_path")
    if not app_path or not os.path.exists(app_path):
        try:
            os.unlink(infopath)
        except (OSError, IOError):
            pass
        return None
    return osinstaller_info


def remove_staged_os_installer_info():
    '''Removes any staged OS installer we may have'''
    infopath = staged_os_installer_info_path()
    try:
        os.unlink(infopath)
    except (OSError, IOError):
        pass


def display_staged_os_installer_info():
    """Prints staged macOS installer info and updates ManagedInstallReport."""
    item = get_staged_os_installer_info()
    if not item:
        return
    display.display_info('')
    reports.report['StagedOSInstaller'] = item
    display.display_info(
        'The following macOS upgrade is available to install:')
    display.display_info(
        '    + %s-%s' % (
        item.get('display_name', item.get('name', '')),
        item.get('version_to_install', '')))
    display.display_info('       *Must be manually installed')


##### functions for determining if a user is a volume owner #####

def volume_owner_uuids():
    '''Returns a list of local accounts that are volume owners for /'''
    cryptousers = {}
    try:
        output = subprocess.check_output(
            ["/usr/sbin/diskutil", "apfs", "listUsers", "/", "-plist"])
        cryptousers = FoundationPlist.readPlistFromString(output)
    except subprocess.CalledProcessError:
        pass

    users = cryptousers.get("Users", [])

    return [
        user.get("APFSCryptoUserUUID")
        for user in users
        if "APFSCryptoUserUUID" in user
        and user.get("VolumeOwner")
        and user.get("APFSCryptoUserType") == "LocalOpenDirectory"
    ]


def generateduid(username):
    '''Returns the GeneratedUID for username, or None'''
    record = {}
    try:
        output = subprocess.check_output(
            ["dscl", "-plist", ".", "read", "/Users/" + username,
             "GeneratedUID"])
        record = FoundationPlist.readPlistFromString(output)
    except subprocess.CalledProcessError:
        pass
    uuid_list = record.get("dsAttrTypeStandard:GeneratedUID", [])
    if uuid_list:
        return uuid_list[0]
    return None


def user_is_volume_owner(username):
    '''Returns a boolean to indicate if the user is a volume owner of /'''
    return generateduid(username) in volume_owner_uuids()


##### functions for launching staged macOS installer #####

def get_adminopen_path():
    '''Writes out adminopen script to a temp file. Returns the path'''
    script = """#!/bin/bash

# This script is designed to be run as root.
# It takes one argument, a path to an app to be launched.
# 
# If the current console user is not a member of the admin group, the user will
# be added to to the group.
# The app will then be launched in the console user's context.
# When the app exits (or this script is killed via SIGINT or SIGTERM),
# if we had promoted the user to admin, we demote that user once again.

export PATH=/usr/bin:/bin:/usr/sbin:/sbin

function fail {
    echo "$@" 1>&2
    exit 1
}

function demote_user {
    # demote CONSOLEUSER from admin
    dseditgroup -o edit -d ${CONSOLEUSER} -t user admin
}

if [ $EUID -ne 0 ]; then
   fail "This script must be run as root." 
fi


CONSOLEUSER=$(stat -f %Su /dev/console)
if [ "${CONSOLEUSER}" == "root" ] ; then
    fail "The console user may not be root!"
fi

USER_UID=$(id -u ${CONSOLEUSER})
if [ $? -ne 0 ] ; then
    # failed to get UID, bail
    fail "Could not get UID for ${CONSOLEUSER}"
fi

APP=$1
if [ "${APP}" == "" ] ; then
    # no application specified
    fail "Need to specify an application!"
fi

# check if CONSOLEUSER is admin
dseditgroup -o checkmember -m ${CONSOLEUSER} admin > /dev/null
if [ $? -ne 0 ] ; then
    # not currently admin, so promote to admin
    dseditgroup -o edit -a ${CONSOLEUSER} -t user admin
    # make sure we demote the user at the end or if we are interrupted
    trap demote_user EXIT SIGINT SIGTERM
fi

# launch $APP as $USER_UID and wait until it exits
launchctl asuser ${USER_UID} open -W "${APP}"
"""
    scriptpath = os.path.join(osutils.tmpdir(), "adminopen")
    try:
        with open(scriptpath, mode='wb') as fileobject:
            fileobject.write(script.encode('UTF-8'))
        os.chown(scriptpath, 0, 0)
        os.chmod(scriptpath, int('744', 8))
    except (OSError, IOError) as err:
        display.display_error("Couldn't create adminopen tool: %s" % err)
        return ""
    return scriptpath


def launch_installer_app(app_path):
    '''Runs our adminopen tool to launch the Install macOS app. adminopen is run
    via launchd so we can exit after the app is launched (and the user may or
    may not actually complete running it.) Returns True if we run adminopen,
    False otherwise (some reasons: can't find Install app, no GUI user)
    '''
    # do we have a GUI user?
    username = osutils.getconsoleuser()
    if not username or username == u"loginwindow":
        # we're at the loginwindow. Bail.
        display.display_error(
            u'Could not launch macOS installer: No current GUI user.')
        return False

    # if we're on Apple silicon -- is the user a volume owner?
    if info.is_apple_silicon() and not user_is_volume_owner(username):
        display.display_error(
            u"Could not launch macOS installer: "
             "Current GUI user is not a volume owner.")
        return False

    # create the adminopen tool and get its path
    adminopen_path = get_adminopen_path()
    if not adminopen_path:
        display.display_error(
            u'Error launching macOS installer: Can\'t create adminopen tool.')
        return False

    # make sure the Install macOS app is present
    if not os.path.exists(app_path):
        display.display_error(
            u'Error launching macOS installer: Can\'t find %s.' % app_path)
        return False

    # OK, we have everything we need, let's go
    display.display_status_major("Launching macOS installer...")
    cmd = [adminopen_path, app_path]
    try:
        job = launchd.Job(cmd, cleanup_at_exit=False)
        job.start()
    except launchd.LaunchdJobException as err:
        display.display_error(
            'Error with launchd job (%s): %s', cmd, err)
        display.display_error(
            'Failed to launch macOS installer due to launchd error.')
        return False

    # sleep a bit, then check to see if our launchd job has exited with an error
    time.sleep(1)
    if job.returncode():
        error_msg = ""
        if job.stderr:
            error_msg = job.stderr.read()
        display.display_error('Unexpected error: %s', error_msg)

    # set Munki to run at boot after the OS upgrade is complete
    try:
        bootstrapping.set_bootstrap_mode()
    except bootstrapping.SetupError as err:
        display.display_error(
            'Could not set up Munki to run after OS upgrade is complete: '
            '%s', err)
    # return True to indicate we launched the Install macOS app
    return True


def launch():
    '''Attempt to launch a staged OS installer'''
    osinstaller_info = get_staged_os_installer_info()

    osinstaller_path = osinstaller_info.get("osinstaller_path")
    if not osinstaller_path:
        display.display_error(
            'stagedinstaller item is missing macOS installer path.')
        return False

    if prefs.pref('SuppressStopButtonOnInstall'):
        munkistatus.hideStopButton()

    munkilog.log("### Beginning GUI launch of macOS installer ###")
    success = launch_installer_app(osinstaller_path)
    return success


if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
