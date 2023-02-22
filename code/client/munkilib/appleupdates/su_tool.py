# encoding: utf-8
#
# Copyright 2019-2023 Greg Neagle.
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
su_tool.py

Created by Greg Neagle on 2019-03-20.

wrapper for running /usr/sbin/softwareupdate
"""
# This code is largely still compatible with Python 2, so for now, turn off
# Python 3 style warnings
# pylint: disable=consider-using-f-string
# pylint: disable=redundant-u-string-prefix

from __future__ import absolute_import

import os
import time

from . import su_prefs

from ..constants import POSTACTION_NONE, POSTACTION_RESTART, POSTACTION_SHUTDOWN

from .. import display
from .. import launchd
from .. import osutils
from .. import processes


def find_ptty_tool():
    """Returns a command-and-arguments list for a psuedo-tty tool we can use
    to wrap our run of softwareupdate"""
    # we need to wrap our call to /usr/sbin/softwareupdate with a utility
    # that makes softwareupdate think it is connected to a tty-like
    # device so its output is unbuffered so we can get progress info
    #
    # Try to find our ptyexec tool
    # first look in the parent directory of the parent directory of this
    # file's directory
    # (../)
    parent_dir = (
        os.path.dirname(
            os.path.dirname(
                os.path.dirname(
                    os.path.abspath(__file__)))))
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
        display.display_warning(
            'Using /usr/bin/script as a ptty; CPU load may suffer')
    return cmd


def parse_su_update_line_new_style(line):
    '''Parses a new-style software update line'''
    info = {}
    line = line.strip().rstrip(',')
    for subitem in line.split(', '):
        key, _, value = subitem.partition(": ")
        if key:
            info[key] = value
    return info


def parse_su_update_line_old_style(line):
    '''Parses an old-style (pre-10.15) softwareupdate -l output line
    into a dict'''
    info = {}
    # strip leading and trailing whitespace
    line = line.strip()
    title, seperator, line = line.partition("(")
    if not seperator == "(":
        # no idea of the format, just return an empty dict
        return {}
    info['Title'] = title.rstrip()
    version, seperator, line = line.partition(")")
    if not seperator == ")":
        # no idea of the format, just return an empty dict
        return {}
    info['Version'] = version
    line = line.lstrip(', ')
    size, seperator, line = line.partition('K')
    if seperator == 'K':
        info['Size'] = '%sK' % size
    # now start from the end
    if line.endswith(" [restart]"):
        line = line[0:-len(" [restart]")]
        info['Action'] = 'restart'
    if line.endswith(" [recommended]"):
        line = line[0:-len(" [recommended]")]
        info['Recommended'] = 'YES'
    else:
        info['Recommended'] = 'NO'
    return info


def parse_su_identifier(line):
    '''parses first line of softwareupdate -l item output'''
    if line.startswith('   * '):
        label = line[5:]
    elif line.startswith('* Label: '):
        label = line[9:]
    else:
        return {}
    update_parts = label.split('-')
    # version is the bit after the last hyphen
    # (let's hope there are no hyphens in the versions!)
    vers = update_parts[-1]
    # identifier is everything before the last hyphen
    identifier = '-'.join(update_parts[0:-1])
    return {'Label': label,
            'identifier': identifier,
            'version': vers}


def parse_su_update_lines(line1, line2):
    '''Parses two lines from softwareupdate -l output and returns a dict'''
    info = parse_su_identifier(line1)
    if line1.startswith('   * '):
        info.update(parse_su_update_line_old_style(line2))
    elif line1.startswith('* Label: '):
        info.update(parse_su_update_line_new_style(line2))
    return info


def run(options_list, catalog_url=None, stop_allowed=False, timeout=0):
    """Runs /usr/sbin/softwareupdate with options.

    Provides user feedback via command line or MunkiStatus.

    Args:
      options_list: sequence of options to send to softwareupdate.
      stopped_allowed: boolean
      mode: a hint as to the softwareupdate mode. Supported values are
            "list", "download", and "install"

    Returns:
      Dictionary of results
    """
    results = {}
    # some things to track to work around a softwareupdate bug
    seems_to_be_finished = False
    countdown_timer = timeout or 60

    cmd = find_ptty_tool()
    cmd.extend(['/usr/sbin/softwareupdate', '--verbose'])

    os_version_tuple = osutils.getOsVersion(as_tuple=True)
    if catalog_url and os_version_tuple == (10, 10):
        # OS version-specific stuff to use a specific CatalogURL
        su_prefs.set_custom_catalogurl(catalog_url)

    cmd.extend(options_list)
    # figure out the softwareupdate 'mode'
    mode = None
    if '-l' in options_list or '--list' in options_list:
        mode = 'list'
    elif '-d' in options_list or '--download' in options_list:
        mode = 'download'
    elif '-i' in options_list or '--install' in options_list:
        mode = 'install'

    display.display_debug1('softwareupdate cmd: %s', cmd)

    results['installed'] = []
    results['download'] = []
    results['failures'] = []
    results['updates'] = []
    results['exit_code'] = 0
    results['post_action'] = POSTACTION_NONE

    try:
        job = launchd.Job(cmd)
        job.start()
    except launchd.LaunchdJobException as err:
        message = 'Error with launchd job (%s): %s' % (cmd, err)
        display.display_warning(message)
        display.display_warning('Skipping softwareupdate run.')
        results['exit_code'] = -3
        results['failures'].append(message)
        return results

    last_output = None
    while True:
        if stop_allowed and processes.stop_requested():
            job.stop()
            break

        output = job.stdout.readline()
        if not output:
            if job.returncode() is not None:
                break
            #else:
            # no data, but we're still running
            if seems_to_be_finished or timeout:
                # softwareupdate provided output that it was finished
                countdown_timer -= 1
                if countdown_timer == 0:
                    # yet it's been at least a minute and it hasn't exited
                    # just stop the job and move on.
                    # Works around yet another softwareupdate bug.
                    display.display_warning(
                        'softwareupdate failed to exit: killing it')
                    job.stop()
                    break
            # sleep a bit before checking for more output
            time.sleep(1)
            continue

        # got output; reset countdown_timer
        countdown_timer = timeout or 60
        # Don't bother parsing the stdout output if it hasn't changed since
        # the last loop iteration.
        if last_output == output:
            continue
        last_output = output

        # do NOT strip leading or trailing spaces yet; we need them when
        # parsing -l/--list output
        output = output.decode('UTF-8').rstrip('\n\r')

        # parse and record info, or send the output to STDOUT or MunkiStatus
        # as applicable

        # --list-specific output
        if mode == 'list':
            if output.startswith(('   * ', '* Label: ')):
                # collect list of items available for install
                first_line = output
                second_line = job.stdout.readline()
                if second_line:
                    second_line = second_line.decode('UTF-8').rstrip('\n\r')
                    item = parse_su_update_lines(first_line, second_line)
                    results['updates'].append(item)
            # we don't want any output from calling `softwareupdate -l`
            continue

        output = output.strip()
        # --download-specific output
        if mode == 'download':
            if output.startswith('Installed '):
                # 10.6/10.7/10.8(+?). Successful download of package name.
                # don't display.
                # softwareupdate logging "Installed" at the end of a
                # successful download-only session is odd.
                continue

        # --install-specific output
        if mode == 'install':
            if output.startswith('Installing '):
                item = output[11:]
                if item:
                    display.display_status_major(output)
                continue
            if output.startswith('Downloaded '):
                # don't display this
                continue
            if output.startswith('Done with '):
                # 10.9 successful install
                display.display_status_minor(output)
                results['installed'].append(output[10:])
                continue
            if output.startswith('Downloading '):
                # This is 10.5 & 10.7 behavior for a missing subpackage.
                display.display_warning(
                    'A necessary subpackage is not available on disk '
                    'during an Apple Software Update installation '
                    'run: %s' % output)
                results['download'].append(output[12:])
                continue
            if output.startswith('Installed '):
                # 10.6/10.7/10.8(+?) Successful install of package name.
                display.display_status_minor(output)
                results['installed'].append(output[10:])
                continue
            if output.startswith('Done '):
                # 10.5. Successful install of package name.
                display.display_status_minor(output)
                results['installed'].append(output[5:])
                continue
            if output.startswith('Package failed:'):
                # Doesn't tell us which package.
                display.display_error(
                    'Apple update failed to install: %s' % output)
                results['failures'].append(output)
                continue
            if (('Please call halt' in output
                 or 'your computer must shut down' in output)
                    and results['post_action'] != POSTACTION_SHUTDOWN):
                # This update requires we shutdown instead of a restart.
                display.display_status_minor(output)
                display.display_info('### This update requires a shutdown. ###')
                results['post_action'] = POSTACTION_SHUTDOWN
                seems_to_be_finished = True
                continue
            if ('requires that you restart your computer' in output
                    and results['post_action'] == POSTACTION_NONE):
                # a restart is required
                display.display_status_minor(output)
                results['post_action'] = POSTACTION_RESTART
                seems_to_be_finished = True
                continue
            if output == "Done.":
                # done installing items
                seems_to_be_finished = True
                continue

        # other output
        if output.lower().startswith(
                ('progress: ', 'downloading: ', 'preparing: ')):
            # Snow Leopard/Lion progress info with '-v' flag
            # Big Sur has 'downloading/Downloading' percent-done
            try:
                percent = int(float(output.partition(": ")[2].rstrip('%')))
            except ValueError:
                percent = -1
            display.display_percent_done(percent, 100)
            if output.startswith('downloading: '):
                display.display_status_minor('Downloading...')
            if output.startswith('downloading: '):
                display.display_status_minor('Preparing...')
            continue
        if output.startswith('Software Update Tool'):
            # don't display this
            continue
        if output.startswith('Copyright 2'):
            # don't display this
            continue
        if output.startswith('x '):
            # don't display this, it's just confusing
            continue
        if 'Missing bundle identifier' in output:
            # don't display this, it's noise
            continue
        if output == '':
            continue
        #else:
        display.display_status_minor(output)

    if catalog_url and os_version_tuple == (10, 10):
        # reset CatalogURL if needed
        su_prefs.reset_original_catalogurl()

    retcode = job.returncode()
    if retcode == 0:
        # get SoftwareUpdate's LastResultCode
        last_result_code = su_prefs.pref(
            'LastResultCode') or 0
        if last_result_code > 2:
            retcode = last_result_code

        if results['failures']:
            retcode = 1

    results['exit_code'] = retcode

    display.display_debug2('softwareupdate run results: %s', results)
    return results
