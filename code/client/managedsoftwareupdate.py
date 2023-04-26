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
managedsoftwareupdate
"""
# This code is largely still compatible with Python 2, so for now, turn off
# Python 3 style warnings
# pylint: disable=consider-using-f-string
# pylint: disable=redundant-u-string-prefix

from __future__ import absolute_import, print_function

import optparse
import os
import re
import signal
import subprocess
import sys
import time
import traceback

# Disable PyLint complaining about 'invalid' camelCase names
# pylint: disable=C0103

# Do not place any imports with ObjC bindings above this!
try:
    # PyLint cannot properly find names inside Cocoa libraries, so issues bogus
    # No name 'Foo' in module 'Bar' warnings. Disable them.
    # pylint: disable=E0611,E0401
    from Foundation import NSDate
    from Foundation import NSDistributedNotificationCenter
    from Foundation import NSNotificationDeliverImmediately
    from Foundation import NSNotificationPostToAllSessions
    # pylint: enable=E0611,E0401
except ImportError:
    # Python is missing ObjC bindings. Run external report script.
    from munkilib import utils
    print('Python is missing ObjC bindings.', file=sys.stderr)
    _scriptdir = os.path.realpath(os.path.dirname(sys.argv[0]))
    _script = os.path.join(_scriptdir, 'report_broken_client')
    try:
        _result, _stdout, _stderr = utils.runExternalScript(_script)
        print(_result, _stdout, _stderr, file=sys.stderr)
    except utils.ScriptNotFoundError:
        pass  # script is not required, so pass
    except utils.RunExternalScriptError as utils_err:
        print(str(utils_err), file=sys.stderr)
    sys.exit(200)
else:
    from munkilib import appleupdates
    from munkilib import authrestart
    from munkilib import bootstrapping
    from munkilib import constants
    from munkilib import display
    from munkilib import info
    from munkilib import installer
    from munkilib import installinfo
    from munkilib import munkilog
    from munkilib import munkistatus
    from munkilib import osinstaller
    from munkilib import osutils
    from munkilib import prefs
    from munkilib import processes
    from munkilib import reports
    from munkilib import updatecheck
    from munkilib import utils
    from munkilib import FoundationPlist
    from munkilib.wrappers import unicode_or_str

    import munkilib.authrestart.client as authrestartd


def signal_handler(signum, _frame):
    """Handle any signals we've been told to.
    Right now just handle SIGTERM so clean up can happen, like
    garbage collection, which will trigger object destructors and
    kill any launchd processes we've started."""
    if signum == signal.SIGTERM:
        sys.exit()


def getIdleSeconds():
    """Returns the number of seconds since the last mouse
    or keyboard event."""
    cmd = ['/usr/sbin/ioreg', '-c', 'IOHIDSystem']
    proc = subprocess.Popen(cmd, shell=False, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (output, dummy_err) = proc.communicate()
    ioreglines = output.decode("UTF-8").splitlines()
    idle_time = 0
    regex = re.compile(r'"?HIDIdleTime"?\s+=\s+(\d+)')
    for line in ioreglines:
        idle_re = regex.search(line)
        if idle_re:
            idle_time = idle_re.group(1)
            break
    return int(int(idle_time)/1000000000) # pylint: disable=old-division


def networkUp():
    """Determine if the network is up by looking for any non-loopback
       internet network interfaces.

    Returns:
      Boolean. True if loopback is found (network is up), False otherwise.
    """
    cmd = ['/sbin/ifconfig', '-a', 'inet']
    proc = subprocess.Popen(cmd, shell=False, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (output, dummy_err) = proc.communicate()
    lines = output.decode('UTF-8').splitlines()
    for line in lines:
        if 'inet' in line:
            parts = line.split()
            addr = parts[1]
            if not addr in ['127.0.0.1', '0.0.0.0']:
                return True
    return False


def detectNetworkHardware():
    """Trigger the detection of new network hardware,
       like a USB-to-Ethernet adapter"""
    cmd = ["/usr/sbin/networksetup", "-detectnewhardware"]
    subprocess.call(cmd)


def clearLastNotifiedDate():
    """Clear the last date the user was notified of updates."""
    prefs.set_pref('LastNotifiedDate', None)


def createDirsIfNeeded(dirlist):
    """Create any missing directories needed by the munki tools.

    Args:
      dirlist: a sequence of directories.
    Returns:
      Boolean. True if all directories existed or were created,
      False otherwise.
    """
    for directory in dirlist:
        if not os.path.exists(directory):
            try:
                os.mkdir(directory)
            except (OSError, IOError):
                print('ERROR: Could not create %s' % directory, file=sys.stderr)
                return False

    return True


def initMunkiDirs():
    """Figure out where data directories should be and create them if needed.

    Returns:
      Boolean. True if all data dirs existed or were created, False otherwise.
    """
    ManagedInstallDir = prefs.pref('ManagedInstallDir')
    manifestsdir = os.path.join(ManagedInstallDir, 'manifests')
    catalogsdir = os.path.join(ManagedInstallDir, 'catalogs')
    iconsdir = os.path.join(ManagedInstallDir, 'icons')
    cachedir = os.path.join(ManagedInstallDir, 'Cache')
    logdir = os.path.join(ManagedInstallDir, 'Logs')

    if not createDirsIfNeeded([ManagedInstallDir, manifestsdir, catalogsdir,
                               iconsdir, cachedir, logdir]):
        display.display_error('Could not create needed directories '
                              'in %s' % ManagedInstallDir)
        return False
    return True


def runScript(script, display_name, runtype):
    """Run an external script. Do not run if the permissions on the external
    script file are weaker than the current executable."""
    result = 0
    if os.path.exists(script):
        display.display_status_minor('Performing %s tasks...' % display_name)
    else:
        return result

    try:
        utils.verifyFileOnlyWritableByMunkiAndRoot(script)
    except utils.VerifyFilePermissionsError as err:
        # preflight/postflight is insecure, but if the currently executing
        # file is insecure too we are no worse off.
        try:
            utils.verifyFileOnlyWritableByMunkiAndRoot(__file__)
        except utils.VerifyFilePermissionsError as inner_err:
            # OK, managedsoftwareupdate is insecure anyway - warn & execute.
            display.display_warning(
                'Multiple munki executable scripts have insecure file '
                'permissions. Executing %s anyway. Error: %s'
                % (display_name, inner_err))
        else:
            # Just the preflight/postflight is insecure. Do not execute.
            display.display_warning(
                'Skipping execution of %s due to insecure file permissions. '
                'Error: %s' % (display_name, err))
            return result

    try:
        result, stdout, stderr = utils.runExternalScript(
            script, allow_insecure=True, script_args=[runtype])
        if result:
            display.display_info(
                '%s return code: %d' % (display_name, result))
        if stdout:
            display.display_info('%s stdout: %s' % (display_name, stdout))
        if stderr:
            display.display_info('%s stderr: %s' % (display_name, stderr))
    except utils.ScriptNotFoundError:
        pass  # script is not required, so pass
    except utils.RunExternalScriptError as err:
        display.display_warning(unicode_or_str(err))
    return result


def cleanup(runtype):
    """
    If there are executables inside the cleanup directory,
    run them and remove them if successful
    """
    cleanupdir = os.path.join(os.path.realpath(
        os.path.dirname(sys.argv[0])), 'cleanup')
    if not os.path.isdir(cleanupdir):
        # path doesn't exist or isn't a directory
        return

    # get only filenames (and not directory names) from cleanupdir
    (_, _, filenames) = next(os.walk(cleanupdir))
    for filename in filenames:
        script_path = os.path.join(cleanupdir, filename)
        result = runScript(script_path, 'cleanup', runtype)
        if not result:
            # no output is a good thing
            os.remove(script_path)


def doInstallTasks(do_apple_updates, only_unattended=False):
    """Perform our installation/removal tasks.

    Args:
      do_apple_updates: Boolean. If True, install Apple updates
      only_unattended:  Boolean. If True, only do unattended_(un)install items.

    Returns:
      Boolean. True if a restart is required, False otherwise.
    """
    if not only_unattended:
        # first, clear the last notified date so we can get notified of new
        # changes after this round of installs
        clearLastNotifiedDate()

    munki_items_restart_action = constants.POSTACTION_NONE
    apple_items_restart_action = constants.POSTACTION_NONE

    if munkiUpdatesAvailable():
        # install munki updates
        try:
            munki_items_restart_action = installer.run(
                only_unattended=only_unattended)
        except:
            display.display_error('Unexpected error in munkilib.installer:')
            munkilog.log(traceback.format_exc())
            reports.savereport()
            raise
        if not only_unattended:
            if munkiUpdatesContainItemWithInstallerType("startosinstall"):
                reports.savereport()
                # install macOS
                try:
                    success = osinstaller.run(finishing_tasks=doFinishingTasks)
                except SystemExit:
                    # we _expect_ this since startosinstall or osinstaller will
                    # initiate a restart after successfully setting up a macOS
                    # install.
                    pass
                except Exception:
                    # some other non-system-exiting exception occurred
                    display.display_error(
                        'Unexpected error in munkilib.osinstaller:')
                    munkilog.log(traceback.format_exc())
                    reports.savereport()
                    raise
                if success:
                    # we really should not get here. If successful, either
                    # startosinstall or osinstaller.run should have initiated a
                    # restart.
                    # Print a warning, and restart anyway.
                    display.display_warning(
                        'Restart not initiated by startosinstall; will initiate '
                        'restart ourselves')
                    if not authrestartd.restart():
                        authrestart.do_authorized_or_normal_restart(
                            shutdown=osutils.bridgeos_update_staged()
                        )
            elif munkiUpdatesContainItemWithInstallerType("launchosinstaller"):
                do_apple_updates = False
                try:
                    success = osinstaller.launch()
                except Exception:
                    # some other non-system-exiting exception occurred
                    display.display_error(
                        'Unexpected error in munkilib.osinstaller:')
                    munkilog.log(traceback.format_exc())
                    reports.savereport()
                    raise

    if do_apple_updates:
        # install Apple updates
        try:
            apple_items_restart_action = appleupdates.installAppleUpdates(
                only_unattended=only_unattended)
        except:
            display.display_error(
                'Unexpected error in appleupdates.installAppleUpdates:')
            munkilog.log(traceback.format_exc())
            reports.savereport()
            raise

    reports.savereport()
    return max(apple_items_restart_action, munki_items_restart_action)


def doFinishingTasks(runtype=None):
    '''A collection of tasks to do as we finish up'''
    # finish our report
    reports.report['EndTime'] = reports.format_time()
    reports.report['ManagedInstallVersion'] = info.get_version()
    reports.report['AvailableDiskSpace'] = info.available_disk_space()
    reports.report['ConsoleUser'] = osutils.getconsoleuser() or '<None>'
    reports.savereport()

    # store the current pending update count and other data for munki-notifier
    installinfo.save_pending_update_times()
    update_info = installinfo.get_pending_update_info()
    prefs.set_pref('PendingUpdateCount', update_info['PendingUpdateCount'])
    prefs.set_pref('OldestUpdateDays', update_info['OldestUpdateDays'])
    prefs.set_pref('ForcedUpdateDueDate', update_info['ForcedUpdateDueDate'])

    # save application inventory data
    info.saveappdata()

    # run the postflight script if it exists
    scriptdir = os.path.realpath(os.path.dirname(sys.argv[0]))
    postflightscript = os.path.join(scriptdir, 'postflight')
    # if runtype is not defined -- we're being called by osinstall
    runScript(postflightscript, 'postflight', runtype or 'osinstall')
    # we ignore the result of the postflight


def startLogoutHelper():
    """Handle the need for a forced logout. Start our logouthelper"""
    cmd = ['/bin/launchctl', 'start', 'com.googlecode.munki.logouthelper']
    result = subprocess.call(cmd)
    if result:
        # some problem with the launchd job
        display.display_error(
            'Could not start com.googlecode.munki.logouthelper')


def doRestart(shutdown=False):
    """Handle the need for a restart or a possbile shutdown."""
    restartMessage = 'Software installed or removed requires a restart.'
    if shutdown:
        munkilog.log('Software installed or removed requires a shut down.')
    else:
        munkilog.log(restartMessage)
    if display.munkistatusoutput:
        munkistatus.hideStopButton()
        munkistatus.message(restartMessage)
        munkistatus.detail('')
        munkistatus.percent(-1)
    else:
        display.display_info(restartMessage)

    # check current console user
    consoleuser = osutils.getconsoleuser()
    if not consoleuser or consoleuser == u'loginwindow':
        # no-one is logged in or we're at the loginwindow
        time.sleep(5)
        # try to use authrestartd to do an auth restart; if that fails
        # do it directly
        if shutdown:
            authrestart.do_authorized_or_normal_restart(shutdown=shutdown)
        elif not authrestartd.restart():
            authrestart.do_authorized_or_normal_restart()
    else:
        if display.munkistatusoutput:
            # someone is logged in and we're using Managed Software Center.
            # We need to notify the active user that a restart is required.
            # We actually should almost never get here; generally Munki knows
            # a restart is needed before even starting the updates and forces
            # a logout before applying the updates
            display.display_info(
                'Notifying currently logged-in user to restart.')
            munkistatus.activate()
            munkistatus.restartAlert()
            # Managed Software Center will trigger a restart
            # when the alert is dismissed. If a user gets clever and subverts
            # this restart (perhaps by force-quitting the app),
            # that's their problem...
        else:
            print('Please restart immediately.')


def munkiUpdatesAvailable():
    """Return count of available updates."""
    updatesavailable = 0
    install_info = os.path.join(
        prefs.pref('ManagedInstallDir'), 'InstallInfo.plist')
    if os.path.exists(install_info):
        try:
            plist = FoundationPlist.readPlist(install_info)
            updatesavailable = (len(plist.get('removals', [])) +
                                len(plist.get('managed_installs', [])))
        except (AttributeError,
                FoundationPlist.NSPropertyListSerializationException):
            display.display_error(
                'Install info at %s is invalid.' % install_info)
    return updatesavailable


def munkiUpdatesContainItemWithInstallerType(installer_type):
    """Return True if there is a startosinstall item in the list of updates"""
    install_info = os.path.join(
        prefs.pref('ManagedInstallDir'), 'InstallInfo.plist')
    if os.path.exists(install_info):
        try:
            plist = FoundationPlist.readPlist(install_info)
        except FoundationPlist.NSPropertyListSerializationException:
            display.display_error(
                'Install info at %s is invalid.' % install_info)
        else:
            # check managed_installs for startosinstall items
            for item in plist.get('managed_installs', []):
                if item.get('installer_type') == installer_type:
                    return True
    return False


def munkiUpdatesContainAppleItems():
    """Return True if there are any Apple items in the list of updates"""
    install_info = os.path.join(
        prefs.pref('ManagedInstallDir'), 'InstallInfo.plist')
    if os.path.exists(install_info):
        try:
            plist = FoundationPlist.readPlist(install_info)
        except FoundationPlist.NSPropertyListSerializationException:
            display.display_error(
                'Install info at %s is invalid.' % install_info)
        else:
            # check managed_installs
            for item in plist.get('managed_installs', []):
                if item.get('apple_item'):
                    return True
            # check removals
            for item in plist.get('removals', []):
                if item.get('apple_item'):
                    return True
    return False


def recordUpdateCheckResult(result):
    """Record last check date and result"""
    now = NSDate.new()
    prefs.set_pref('LastCheckDate', now)
    prefs.set_pref('LastCheckResult', result)


def sendDistributedNotification(notification_name, userInfo=None):
    '''Sends a NSDistributedNotification'''
    dnc = NSDistributedNotificationCenter.defaultCenter()
    dnc.postNotificationName_object_userInfo_options_(
        notification_name,
        None,
        userInfo,
        NSNotificationDeliverImmediately + NSNotificationPostToAllSessions)


def sendUpdateNotification():
    '''Sends an update notification via NSDistributedNotificationCenter
    MSU.app registers to receive these events.'''
    userInfo = {'pid': os.getpid()}
    sendDistributedNotification(
        'com.googlecode.munki.managedsoftwareupdate.updateschanged',
        userInfo)


def sendDockUpdateNotification():
    '''Sends an update notification via NSDistributedNotificationCenter
    MSU.app's docktileplugin registers to receive these events.'''
    userInfo = {'pid': os.getpid()}
    sendDistributedNotification(
        'com.googlecode.munki.managedsoftwareupdate.dock.updateschanged',
        userInfo)


def sendStartNotification():
    '''Sends a start notification via NSDistributedNotificationCenter'''
    userInfo = {'pid': os.getpid()}
    sendDistributedNotification(
        'com.googlecode.munki.managedsoftwareupdate.started',
        userInfo)


def sendEndNotification():
    '''Sends an ended notification via NSDistributedNotificationCenter'''
    userInfo = {'pid': os.getpid()}
    sendDistributedNotification(
        'com.googlecode.munki.managedsoftwareupdate.ended',
        userInfo)


def notifyUserOfUpdates(force=False):
    """Notify the logged-in user of available updates.

    Args:
      force: bool, default False, forcefully notify user regardless
          of LastNotifiedDate.
    Returns:
      Boolean.  True if the user was notified, False otherwise.
    """
    # called when options.auto == True
    # someone is logged in, and we have updates.
    # if we haven't notified in a while, notify:
    user_was_notified = False
    lastNotifiedString = prefs.pref('LastNotifiedDate')
    try:
        daysBetweenNotifications = int(
            prefs.pref('DaysBetweenNotifications'))
    except ValueError:
        display.display_warning(
            'DaysBetweenNotifications is not an integer: %s'
            % prefs.pref('DaysBetweenNotifications'))
        # continue with the default DaysBetweenNotifications
        daysBetweenNotifications = 1
    now = NSDate.new()
    nextNotifyDate = now
    if lastNotifiedString:
        lastNotifiedDate = NSDate.dateWithString_(lastNotifiedString)
        interval = daysBetweenNotifications * (24 * 60 * 60)
        if daysBetweenNotifications > 0:
            # we make this adjustment so a 'daily' notification
            # doesn't require 24 hours to elapse
            # subtract 6 hours
            interval = interval - (6 * 60 * 60)
        nextNotifyDate = lastNotifiedDate.dateByAddingTimeInterval_(interval)
    if force or now.timeIntervalSinceDate_(nextNotifyDate) >= 0:
        # record current notification date
        prefs.set_pref('LastNotifiedDate', now)

        munkilog.log('Notifying user of available updates.')
        munkilog.log('LastNotifiedDate was %s' % lastNotifiedString)

        # notify user of available updates using LaunchAgent to launch
        # munki-notifier.app in the user context.
        launchfile = '/var/run/com.googlecode.munki.munki-notifier'
        f = open(launchfile, 'w')
        f.close()
        time.sleep(5)
        if os.path.exists(launchfile):
            os.unlink(launchfile)
        user_was_notified = True
    return user_was_notified


def warn_if_server_is_default(server):
    '''Munki defaults to using http://munki/repo as the base URL.
    This is useful as a bootstrapping default, but is insecure.
    Warn the admin if Munki is using an insecure default.'''
    # server can be either ManifestURL or SoftwareRepoURL
    if not server:
        # hasn't been defined yet; will be auto-detected later
        return
    if server.rstrip('/') in ['http://munki/repo',
                              'http://munki/repo/manifests']:
        display.display_warning(
            'Client is configured to use the default repo, which is insecure. '
            'Client could be trivially compromised when off your '
            'organization\'s network. '
            'Consider using a non-default URL, and preferably an https:// URL.')


def remove_launchd_logout_jobs_and_exit():
    """Removes the jobs that launch MunkiStatus and  managedsoftwareupdate at
    the loginwindow. We do this if we decide it's not applicable to run right
    now so we don't get relaunched repeatedly, but don't want to remove the
    trigger file because we do want to run again at the next logout/reboot.
    These jobs will be reloaded the next time we're in the loginwindow context.
    """
    munkistatus.quit_app()
    cmd = ["/bin/launchctl", "remove", "com.googlecode.munki.MunkiStatus"]
    subprocess.call(cmd)
    cmd = ["/bin/launchctl", "remove",
           "com.googlecode.munki.managedsoftwareupdate-loginwindow"]
    subprocess.call(cmd)
    sys.exit(0)


def main():
    """Main"""
    progname = "managedsoftwareupdate"
    
    # install handler for SIGTERM
    signal.signal(signal.SIGTERM, signal_handler)

    # save this for later
    scriptdir = os.path.realpath(os.path.dirname(sys.argv[0]))

    parser = optparse.OptionParser()
    parser.set_usage('Usage: %s [options]' % progname)
    parser.add_option('--version', '-V', action='store_true',
                      help='Print the version of the munki tools and exit.')

    # commonly-used options
    common_options = optparse.OptionGroup(
        parser, 'Common Options', 'Commonly used options')
    common_options.add_option(
        '--verbose', '-v', action='count', default=1,
        help='More verbose output. May be specified multiple times.')
    common_options.add_option(
        '--checkonly', action='store_true',
        help='Check for updates, but don\'t install them. This is the default '
        'behavior when no other options are specified.')
    common_options.add_option(
        '--installonly', action='store_true',
        help='Skip checking and install all pending updates. No safety checks.')
    common_options.add_option(
        '--applesuspkgsonly', action='store_true',
        help='Only check/install Apple SUS packages, skip Munki packages.')
    common_options.add_option(
        '--munkipkgsonly', action='store_true',
        help='Only check/install Munki packages, skip Apple SUS.')
    parser.add_option_group(common_options)

    # configuration options
    config_options = optparse.OptionGroup(
        parser, 'Configuration Options',
        'Options that show or control managedsoftwareupdate\'s configuration')
    config_options.add_option(
        '--show-config', action='store_true',
        help='Print the current configuration and exit.')
    config_options.add_option(
        '--id', default=u'',
        help='String to use as ClientIdentifier for this run only.')
    config_options.add_option(
        '--set-bootstrap-mode', action='store_true',
        help='Set up \'bootstrapping\' mode for  managedsoftwareupdate and '
        'exit. See the Munki wiki for details on \'bootstrapping\' mode.')
    config_options.add_option(
        '--clear-bootstrap-mode', action='store_true',
        help='Clear \'bootstrapping\' mode for managedsoftwareupdate and exit.')
    parser.add_option_group(config_options)

    # Other options
    other_options = optparse.OptionGroup(
        parser, 'Other Options',
        'Options intended for use by LaunchAgents and LaunchDaemons')
    other_options.add_option(
        '--auto', '-a', action='store_true',
        help='Used by launchd LaunchDaemon for scheduled/background runs. No '
        'user feedback or interaction. Not tested or supported with any other '
        'option. This is a safer option to use than --installonly when using '
        'managedsoftwareupdate to install pending updates, since only '
        'unattended updates are installed if there is an active user. There is '
        'no progress feedback at the command-line.')
    other_options.add_option(
        '--logoutinstall', '-l', action='store_true',
        help='Used by launchd LaunchAgent when running at the loginwindow. '
        'Not for general use.')
    other_options.add_option(
        '--installwithnologout', action='store_true',
        help='Used by Managed Software Center.app when user triggers an '
        'install without logging out. Not for general use.')
    other_options.add_option(
        '--launchosinstaller', action='store_true',
        help='Used interally. Not for general use.')
    other_options.add_option(
        '--manualcheck', action='store_true',
        help='Used by launchd LaunchAgent when checking manually. Not for '
        'general use.')
    other_options.add_option(
        '--munkistatusoutput', '-m', action='store_true',
        help='Uses MunkiStatus.app for progress feedback when installing. '
        'Not for general use.')
    other_options.add_option(
        '--quiet', '-q', action='store_true',
        help='Quiet mode. Logs messages, but nothing to stdout. --verbose is '
        'ignored if --quiet is used.')
    parser.add_option_group(other_options)

    options, dummy_arguments = parser.parse_args()

    if options.version:
        print(info.get_version())
        sys.exit(0)

    # check to see if we're root
    if os.geteuid() != 0:
        print('You must run this as root!', file=sys.stderr)
        sys.exit(constants.EXIT_STATUS_ROOT_REQUIRED)

    if options.show_config:
        prefs.print_config()
        sys.exit(0)

    if options.set_bootstrap_mode:
        try:
            bootstrapping.set_bootstrap_mode()
            print('Bootstrap mode is set.')
            sys.exit(0)
        except bootstrapping.SetupError as err:
            print(err, file=sys.stderr)
            sys.exit(-1)

    if options.clear_bootstrap_mode:
        try:
            bootstrapping.clear_bootstrap_mode()
            print('Bootstrap mode cleared.')
            sys.exit(0)
        except bootstrapping.SetupError as err:
            print(err, file=sys.stderr)
            sys.exit(-1)

    # check to see if another instance of this script is running
    myname = os.path.basename(sys.argv[0])
    other_managedsoftwareupdate_pid = osutils.pythonScriptRunning(myname)
    if other_managedsoftwareupdate_pid:
        # another instance of this script is running, so we should quit
        munkilog.log('*' * 60)
        munkilog.log('%s launched as pid %s' % (progname, os.getpid()))
        munkilog.log('Another instance of %s is running as pid %s.'
                     % (progname, other_managedsoftwareupdate_pid))
        munkilog.log('pid %s exiting.' % os.getpid())
        munkilog.log('*' * 60)
        print('Another instance of %s is running. Exiting.' % progname,
              file=sys.stderr)
        osutils.cleanUpTmpDir()
        sys.exit(0)

    runtype = 'custom'

    if options.auto:
        # typically invoked by a launch daemon periodically.
        # munkistatusoutput is false for checking, but true for installing
        runtype = 'auto'
        options.munkistatusoutput = False
        options.quiet = True
        options.checkonly = False
        options.installonly = False

    if options.logoutinstall:
        # typically invoked by launchd agent
        # running in the LoginWindow context
        runtype = 'logoutinstall'
        options.munkistatusoutput = True
        options.quiet = True
        options.checkonly = False
        options.installonly = True
        # if we're running at the loginwindow, let's make sure the user
        # triggered the update before logging out, or we triggered it before
        # restarting.
        user_triggered = False
        flagfiles = (constants.CHECKANDINSTALLATSTARTUPFLAG,
                     constants.INSTALLATSTARTUPFLAG,
                     constants.INSTALLATLOGOUTFLAG)
        for filename in flagfiles:
            if os.path.exists(filename):
                munkilog.log(
                    "managedsoftwareupdate run triggered by %s" % filename)
                user_triggered = True
                if filename == constants.CHECKANDINSTALLATSTARTUPFLAG:
                    runtype = 'checkandinstallatstartup'
                    options.installonly = False
                    options.auto = True
                    # HACK: sometimes this runs before the network is up.
                    # we'll attempt to wait up to 60 seconds for the network
                    # interfaces to come up before continuing
                    display.display_status_minor('Waiting for network...')
                    detectNetworkHardware()
                    for dummy_i in range(60):
                        if networkUp():
                            break
                        time.sleep(1)
                    break
                if filename == constants.INSTALLATSTARTUPFLAG:
                    runtype = 'installatstartup'
                    break

        # delete any triggerfile that isn't checkandinstallatstartup
        # so it's not hanging around at the next logout or restart
        for triggerfile in (constants.INSTALLATSTARTUPFLAG,
                            constants.INSTALLATLOGOUTFLAG):
            if os.path.exists(triggerfile):
                try:
                    os.unlink(triggerfile)
                except (OSError, IOError):
                    pass

        if not user_triggered:
            # no trigger file was found -- how'd we get launched?
            osutils.cleanUpTmpDir()
            sys.exit(0)

    if options.installwithnologout:
        # typically invoked by Managed Software Center.app
        # for installs that do not require a logout
        launchdtriggerfile = \
            '/private/tmp/.com.googlecode.munki.managedinstall.launchd'
        if os.path.exists(launchdtriggerfile):
            munkilog.log(
                "managedsoftwareupdate run triggered by %s"
                % launchdtriggerfile
            )
            try:
                launch_options = FoundationPlist.readPlist(launchdtriggerfile)
                options.launchosinstaller = launch_options.get(
                    'LaunchStagedOSInstaller')
            except FoundationPlist.FoundationPlistException:
                pass
            # remove it so we aren't automatically relaunched
            os.unlink(launchdtriggerfile)
        runtype = 'installwithnologout'
        options.munkistatusoutput = True
        options.quiet = True
        options.checkonly = False
        options.installonly = True

    if options.manualcheck:
        # triggered by Managed Software Center.app
        launchdtriggerfile = \
            '/private/tmp/.com.googlecode.munki.updatecheck.launchd'
        if os.path.exists(launchdtriggerfile):
            munkilog.log(
                "managedsoftwareupdate run triggered by %s"
                % launchdtriggerfile
            )
            try:
                launch_options = FoundationPlist.readPlist(launchdtriggerfile)
                options.munkipkgsonly = launch_options.get(
                    'SuppressAppleUpdateCheck')
            except FoundationPlist.FoundationPlistException:
                pass
            # remove it so we aren't automatically relaunched
            os.unlink(launchdtriggerfile)
        runtype = 'manualcheck'
        options.munkistatusoutput = True
        options.quiet = True
        options.checkonly = True
        options.installonly = False

    if options.quiet:
        options.verbose = 0

    if options.checkonly and options.installonly:
        print('--checkonly and --installonly options are mutually exclusive!',
              file=sys.stderr)
        sys.exit(constants.EXIT_STATUS_INVALID_PARAMETERS)

    # set munkicommon globals
    display.munkistatusoutput = True
    display.verbose = options.verbose

    # Set environment variable for verbosity
    os.environ['MUNKI_VERBOSITY_LEVEL'] = str(options.verbose)

    # Run cleanup scripts if required
    cleanup(runtype)

    if options.installonly:
        # we're only installing, not checking, so we should copy
        # some report values from the prior run
        reports.readreport()

    # start a new report
    reports.report['StartTime'] = reports.format_time()
    reports.report['RunType'] = runtype
    # Clearing arrays must be run before any call to display_warning/error.
    reports.report['Errors'] = []
    reports.report['Warnings'] = []

    if prefs.pref('LogToSyslog'):
        munkilog.configure_syslog()

    munkilog.log("### Starting managedsoftwareupdate run: %s ###" % runtype)
    if options.verbose:
        print('Managed Software Update Tool')
        print('Copyright 2010-2023 The Munki Project')
        print('https://github.com/munki/munki\n')

    display.display_status_major('Starting...')
    sendStartNotification()
    # run the preflight script if it exists
    preflightscript = os.path.join(scriptdir, 'preflight')
    result = runScript(preflightscript, 'preflight', runtype)

    if result:
        # non-zero return code means don't run
        display.display_info(
            'managedsoftwareupdate run aborted by preflight script: %s'
            % result)
        # record the check result for use by Managed Software Center.app
        # right now, we'll return the same code as if the munki server
        # was unavailable. We need to revisit this and define additional
        # update check results.
        recordUpdateCheckResult(-2)
        # tell status app we're done sending status
        munkistatus.quit_app()
        osutils.cleanUpTmpDir()
        sys.exit(result)
    # Force a prefs refresh, in case preflight modified the prefs file.
    prefs.reload_prefs()

    # create needed directories if necessary
    if not initMunkiDirs():
        sys.exit(constants.EXIT_STATUS_MUNKI_DIRS_FAILURE)

    applesoftwareupdatesonly = (prefs.pref('AppleSoftwareUpdatesOnly')
                                or options.applesuspkgsonly)

    skip_munki_check = (options.installonly or applesoftwareupdatesonly)
    if not skip_munki_check:
        # check to see if we are using an insecure default
        server = (prefs.pref('ManifestURL') or
                  prefs.pref('SoftwareRepoURL'))
        warn_if_server_is_default(server)

    # reset our errors and warnings files, rotate main log if needed
    munkilog.reset_errors()
    munkilog.reset_warnings()
    munkilog.rotate_main_log()

    # archive the previous session's report
    reports.archive_report()

    if applesoftwareupdatesonly and options.verbose:
        print ('NOTE: managedsoftwareupdate is configured to process Apple '
               'Software Updates only.')

    updatecheckresult = None
    if not skip_munki_check:
        try:
            updatecheckresult = updatecheck.check(
                client_id=unicode_or_str(options.id))
        except:
            display.display_error('Unexpected error in updatecheck:')
            munkilog.log(traceback.format_exc())
            reports.savereport()
            raise

    if updatecheckresult is not None:
        recordUpdateCheckResult(updatecheckresult)

    updatesavailable = munkiUpdatesAvailable()
    appleupdatesavailable = 0

    # should we do Apple Software updates this run?
    if applesoftwareupdatesonly:
        # admin told us to only do Apple updates this run
        should_do_apple_updates = True
    elif options.munkipkgsonly:
        # admin told us to skip Apple updates for this run
        should_do_apple_updates = False
    elif munkiUpdatesContainAppleItems():
        # shouldn't run Software Update if we're doing Apple items
        # with Munki items
        should_do_apple_updates = False
        munkilog.log('Skipping Apple Software Updates because items to be '
                     'installed from the Munki repo contain Apple items.')
        # if there are force_install_after_date items in a pre-existing
        # AppleUpdates.plist this means we are blocking those updates.
        # we need to delete AppleUpdates.plist so that other code doesn't
        # mistakenly alert for forced installs it isn't actually going to
        # install.
        appleupdates.clearAppleUpdateInfo()
    else:
        # check the normal preferences
        should_do_apple_updates = prefs.pref('InstallAppleSoftwareUpdates')

    if should_do_apple_updates:
        if not options.installonly and not processes.stop_requested():
            force_update_check = False
            force_catalog_refresh = False
            if options.manualcheck or runtype == 'checkandinstallatstartup':
                force_update_check = True
            if runtype == 'custom' and applesoftwareupdatesonly:
                force_update_check = True
                force_catalog_refresh = True
            try:
                appleupdatesavailable = \
                    appleupdates.appleSoftwareUpdatesAvailable(
                        forcecheck=force_update_check, client_id=options.id,
                        forcecatalogrefresh=force_catalog_refresh)
            except:
                display.display_error('Unexpected error in appleupdates:')
                munkilog.log(traceback.format_exc())
                reports.savereport()
                raise
            if applesoftwareupdatesonly:
                # normally we record the result of checking for Munki updates
                # but if we are only doing Apple updates, we should record the
                # result of the Apple updates check
                if appleupdatesavailable:
                    recordUpdateCheckResult(1)
                else:
                    recordUpdateCheckResult(0)

        if options.installonly:
            # just look and see if there are already downloaded Apple updates
            # to install; don't run softwareupdate to check with Apple
            try:
                appleupdatesavailable = \
                    appleupdates.appleSoftwareUpdatesAvailable(
                        suppresscheck=True, client_id=options.id)
            except:
                display.display_error('Unexpected error in appleupdates:')
                munkilog.log(traceback.format_exc())
                reports.savereport()
                raise

    # display any available update information
    if updatecheckresult:
        installinfo.display_update_info()
    if osinstaller.get_staged_os_installer_info():
        osinstaller.display_staged_os_installer_info()
    elif appleupdatesavailable:
        appleupdates.displayAppleUpdateInfo()

    # send a notification event so MSC can update its display if needed
    sendUpdateNotification()

    restart_action = constants.POSTACTION_NONE
    mustlogout = False
    notify_user = False
    force_action = None

    if runtype == 'installatstartup':
        # turn off options.installonly; we need options.auto behavior from here
        # on out because if FileVault is active we may actually be logged in
        # at this point!
        options.installonly = False
        options.auto = True

    if runtype == 'checkandinstallatstartup':
        # we're in bootstrap mode
        if not updatesavailable and appleupdatesavailable:
            # there are only Apple updates, but we might not be able to install
            # some
            if not appleupdates.installableUpdates():
                # there are no Apple updates we can actually install without
                # user assistance, so clear bootstrapping mode so we don't loop
                # endlessly
                try:
                    bootstrapping.clear_bootstrap_mode()
                except bootstrapping.SetupError as err:
                    display.display_error(err)

    if options.launchosinstaller:
        # user chose to update from Managed Software Center and there is
        # a cached macOS installer. We'll do that _only_.
        updatesavailable = False
        appleupdatesavailable = False
        if osinstaller.get_staged_os_installer_info():
            osinstaller.launch()
        else:
            # staged OS installer is missing
            display.display_error(
                'Requsted to launch staged OS installer, but no info on a '
                'staged installer was found.')

    if updatesavailable or appleupdatesavailable:
        if options.installonly or options.logoutinstall:
            # just install
            restart_action = doInstallTasks(appleupdatesavailable)
            # reset our count of available updates (it might not actually
            # be zero, but we want to clear the badge on the Dock icon;
            # it can be updated to the "real" count on the next Munki run)
            updatesavailable = 0
            appleupdatesavailable = 0
            # send a notification event so MSU can update its display
            # if needed
            sendUpdateNotification()

        elif options.auto:
            if not osutils.currentGUIusers():  # no GUI users
                if prefs.pref('SuppressAutoInstall'):
                    # admin says we can never install packages
                    # without user approval/initiation
                    munkilog.log('Skipping auto install because '
                                 'SuppressAutoInstall is true.')
                elif prefs.pref('SuppressLoginwindowInstall'):
                    # admin says we can't install pkgs at loginwindow
                    # unless they don't require a logout or restart
                    # (and are marked with unattended_install = True)
                    #
                    # check for packages that need to be force installed
                    # soon and convert them to unattended_installs if they
                    # don't require a logout
                    dummy_action = installinfo.force_install_package_check()
                    # now install anything that can be done unattended
                    munkilog.log('Installing only items marked unattended '
                                 'because SuppressLoginwindowInstall is true.')
                    dummy_restart = doInstallTasks(
                        appleupdatesavailable, only_unattended=True)
                elif getIdleSeconds() < 10:
                    munkilog.log(
                        'Skipping auto install at loginwindow because system '
                        'is not idle (keyboard or mouse activity).')
                elif processes.is_app_running(
                        '/System/Library/CoreServices/FileSyncAgent.app'):
                    munkilog.log(
                        'Skipping auto install at loginwindow because '
                        'FileSyncAgent.app is running '
                        '(HomeSyncing a mobile account on login?).')
                else:
                    # no GUI users, system is idle, so we can install
                    # but first, enable status output over login window
                    display.munkistatusoutput = True
                    munkilog.log('No GUI users, installing at login window.')
                    munkistatus.launchMunkiStatus()
                    restart_action = doInstallTasks(appleupdatesavailable)
                    # reset our count of available updates
                    updatesavailable = 0
                    appleupdatesavailable = 0
            else:  # there are GUI users
                if prefs.pref('SuppressAutoInstall'):
                    munkilog.log('Skipping unattended installs because '
                                 'SuppressAutoInstall is true.')
                else:
                    # check for packages that need to be force installed
                    # soon and convert them to unattended_installs if they
                    # don't require a logout
                    dummy_action = installinfo.force_install_package_check()
                    # install anything that can be done unattended
                    dummy_restart = doInstallTasks(
                        appleupdatesavailable, only_unattended=True)

                # send a notification event so MSC can update its display
                # if needed
                sendUpdateNotification()

                force_action = installinfo.force_install_package_check()
                # if any installs are still requiring force actions, just
                # initiate a logout to get started.  blocking apps might
                # have stopped even non-logout/reboot installs from
                # occurring.
                if force_action in ['now', 'logout', 'restart']:
                    mustlogout = True

                # it's possible that we no longer have any available updates
                # so we need to check InstallInfo.plist and
                # AppleUpdates.plist again
                updatesavailable = munkiUpdatesAvailable()
                if appleupdatesavailable:
                    # there were Apple updates available, but we might have
                    # installed some unattended
                    try:
                        appleupdatesavailable = (
                            appleupdates.appleSoftwareUpdatesAvailable(
                                suppresscheck=True, client_id=options.id))
                    except:
                        display.display_error(
                            'Unexpected error in appleupdates:')
                        munkilog.log(traceback.format_exc())
                        reports.savereport()
                        raise
                if appleupdatesavailable or updatesavailable:
                    # set a flag to notify the user of available updates
                    # after we conclude this run.
                    notify_user = True

        elif not options.quiet:
            print ('\nRun %s --installonly to install the downloaded '
                   'updates.' % progname)
    else:
        # no updates available
        if options.installonly and not options.quiet:
            print('Nothing to install or remove.')
        if runtype == 'checkandinstallatstartup':
            # we have nothing to do, clear the bootstrapping mode
            # so we'll stop running at startup/logout
            try:
                bootstrapping.clear_bootstrap_mode()
            except bootstrapping.SetupError as err:
                display.display_error(err)

    display.display_status_major('Finishing...')
    doFinishingTasks(runtype=runtype)
    sendDockUpdateNotification()
    sendEndNotification()

    munkilog.log("### Ending managedsoftwareupdate run ###")
    if options.verbose:
        print('Done.')

    osutils.cleanUpTmpDir()
    if mustlogout:
        # not handling this currently
        pass
    if restart_action == constants.POSTACTION_SHUTDOWN:
        doRestart(shutdown=True)
    elif restart_action == constants.POSTACTION_RESTART:
        doRestart()
    else:
        # tell status app we're done sending status
        munkistatus.quit_app()
        if notify_user:
            # it may have been more than a minute since we ran our original
            # updatecheck so tickle the updatecheck time so MSC.app knows to
            # display results immediately
            recordUpdateCheckResult(1)
            if force_action:
                notifyUserOfUpdates(force=True)
                time.sleep(2)
                startLogoutHelper()
            elif osutils.getconsoleuser() == u'loginwindow':
                # someone is logged in, but we're sitting at the loginwindow
                # due to to fast user switching so do nothing
                munkilog.log('Skipping user notification because we are at the'
                             'loginwindow.')
            elif prefs.pref('SuppressUserNotification'):
                munkilog.log('Skipping user notification because '
                             'SuppressUserNotification is true.')
            else:
                notifyUserOfUpdates()

    if (runtype == 'checkandinstallatstartup' and
            restart_action == constants.POSTACTION_NONE):
        if os.path.exists(constants.CHECKANDINSTALLATSTARTUPFLAG):
            # we installed things but did not need to restart; we need to run
            # again to check for more updates.
            if not osutils.currentGUIusers():
                # no-one is logged in
                idleseconds = getIdleSeconds()
                if idleseconds <= 10:
                    # system is not idle, but check again in case someone has
                    # simply briefly touched the mouse to see progress.
                    time.sleep(15)
                    idleseconds = getIdleSeconds()
                if idleseconds <= 10:
                    # we're still not idle.
                    # if the trigger file is present when we exit, we'll
                    # be relaunched by launchd, so we need to remove it
                    # to prevent automatic relaunch.
                    munkilog.log(
                        'System not idle -- '
                        'clearing bootstrap mode to prevent relaunch')
                    try:
                        bootstrapping.clear_bootstrap_mode()
                    except bootstrapping.SetupError as err:
                        display.display_error(err)


if __name__ == '__main__':
    main()
