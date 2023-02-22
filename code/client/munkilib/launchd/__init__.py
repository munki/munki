# encoding: utf-8
#
# Copyright 2011-2023 Greg Neagle.
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
launchd

Created by Greg Neagle on 2011-07-22.
get_socket_fd and refactoring by Greg Neagle on 2017-04-14.

Code for getting a socket file descriptor from launchd.
Returns a file descriptor for a socket defined in a launchd plist.
-and-
A wrapper for using launchd to run a process as root outside of Munki's
process space. Needed to properly run /usr/sbin/softwareupdate, for example.
"""
from __future__ import absolute_import, print_function

import os
import subprocess
import tempfile
import time
import uuid

from .. import osutils
from .. import FoundationPlist


def get_socket_fd(socket_name):
    '''Get socket file descriptors from launchd.'''
    os_version = osutils.getOsVersion(as_tuple=True)
    if os_version >= (10, 10):
        # use new launchd api
        from . import launch2
        try:
            sockets = launch2.launch_activate_socket(socket_name)
        except launch2.LaunchDError:
            # no sockets found
            return None
        return sockets[0]

    else:
        # use old launchd api
        from . import launch1
        try:
            socket_dict = launch1.get_launchd_socket_fds()
        except launch1.LaunchDCheckInError:
            # no sockets found
            return None

        if socket_name not in socket_dict:
            # no sockets found with the expected name
            return None

        return socket_dict[socket_name][0]


class LaunchdJobException(Exception):
    '''Exception for launchctl errors and other errors from
    this module.'''
    pass


def job_info(job_label):
    '''Get info about a launchd job. Returns a dictionary.'''
    info = {'state': 'unknown',
            'PID': None,
            'LastExitStatus': None}
    launchctl_cmd = ['/bin/launchctl', 'list']
    proc = subprocess.Popen(launchctl_cmd, shell=False, bufsize=-1,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    output = proc.communicate()[0].decode('UTF-8')
    if proc.returncode or not output:
        return info
    else:
        lines = output.splitlines()
        # search launchctl list output for our job label
        job_lines = [item for item in lines
                     if item.endswith('\t' + job_label)]
        if len(job_lines) != 1:
            # unexpected number of lines matched our label
            return info
        j_info = job_lines[0].split('\t')
        if len(j_info) != 3:
            # unexpected number of fields in the line
            return info
        if j_info[0] == '-':
            info['PID'] = None
            info['state'] = 'stopped'
        else:
            info['PID'] = int(j_info[0])
            info['state'] = 'running'
        if j_info[1] == '-':
            info['LastExitStatus'] = None
        else:
            info['LastExitStatus'] = int(j_info[1])
        return info


def stop_job(job_label):
    '''Stop the launchd job'''
    launchctl_cmd = ['/bin/launchctl', 'stop', job_label]
    proc = subprocess.Popen(launchctl_cmd, shell=False, bufsize=-1,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    err = proc.communicate()[1].decode('UTF-8')
    if proc.returncode:
        raise LaunchdJobException(err)


def remove_job(job_label):
    '''Remove a job from launchd by label'''
    launchctl_cmd = ['/bin/launchctl', 'remove', job_label]
    proc = subprocess.Popen(launchctl_cmd, shell=False, bufsize=-1,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    err = proc.communicate()[1].decode('UTF-8')
    if proc.returncode:
        raise LaunchdJobException(err)


class Job(object):
    '''launchd job object'''

    def __init__(self, cmd, environment_vars=None,
                 job_label=None, cleanup_at_exit=True):
        '''Initialize our launchd job'''
        if cleanup_at_exit:
            # safe to use the same tmpdir as the calling tool
            # (usually managedsoftwareupdate) so it will get cleaned up
            tmpdir = osutils.tmpdir()
        else:
            # need to create our own tmpdir; may not be cleaned up
            tmpdir = tempfile.mkdtemp(prefix='munki.launchd-', dir='/tmp')

        # label this job
        self.label = job_label or 'com.googlecode.munki.' + str(uuid.uuid1())

        self.cleanup_at_exit = cleanup_at_exit
        self.stdout_path = os.path.join(tmpdir, self.label + '.stdout')
        self.stderr_path = os.path.join(tmpdir, self.label + '.stderr')
        self.plist_path = os.path.join(tmpdir, self.label + '.plist')
        self.stdout = None
        self.stderr = None
        self.plist = {}
        self.plist['Label'] = self.label
        self.plist['ProgramArguments'] = cmd
        self.plist['StandardOutPath'] = self.stdout_path
        self.plist['StandardErrorPath'] = self.stderr_path
        if environment_vars:
            self.plist['EnvironmentVariables'] = environment_vars
        # create stdout and stderr files
        try:
            open(self.stdout_path, 'wb').close()
            open(self.stderr_path, 'wb').close()
        except (OSError, IOError) as err:
            raise LaunchdJobException(err)
        # write out launchd plist
        FoundationPlist.writePlist(self.plist, self.plist_path)
        # set owner, group and mode to those required
        # by launchd
        os.chown(self.plist_path, 0, 0)
        os.chmod(self.plist_path, int('644', 8))
        launchctl_cmd = ['/bin/launchctl', 'load', self.plist_path]
        proc = subprocess.Popen(launchctl_cmd, shell=False, bufsize=-1,
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)

        err = proc.communicate()[1].decode('UTF-8')
        if proc.returncode:
            raise LaunchdJobException(err)

    def __del__(self):
        '''Attempt to clean up'''
        if self.cleanup_at_exit:
            if self.plist:
                launchctl_cmd = ['/bin/launchctl', 'unload', self.plist_path]
                dummy_result = subprocess.call(launchctl_cmd)
            try:
                self.stdout.close()
                self.stderr.close()
            except AttributeError:
                pass
            try:
                os.unlink(self.plist_path)
                os.unlink(self.stdout_path)
                os.unlink(self.stderr_path)
            except (OSError, IOError):
                pass

    def start(self):
        '''Start the launchd job'''
        launchctl_cmd = ['/bin/launchctl', 'start', self.label]
        proc = subprocess.Popen(launchctl_cmd, shell=False, bufsize=-1,
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        err = proc.communicate()[1]
        if proc.returncode:
            raise LaunchdJobException(err)
        else:
            if (not os.path.exists(self.stdout_path) or
                    not os.path.exists(self.stderr_path)):
                # wait a second for the stdout/stderr files
                # to be created by launchd
                time.sleep(1)
            try:
                # open the stdout and stderr output files and
                # store their file descriptors for use
                self.stdout = open(self.stdout_path, 'rb')
                self.stderr = open(self.stderr_path, 'rb')
            except (OSError, IOError) as err:
                raise LaunchdJobException(err)

    def stop(self):
        '''Stop the launchd job'''
        stop_job(self.label)

    def info(self):
        '''Get info about the launchd job. Returns a dictionary.'''
        return job_info(self.label)

    def returncode(self):
        '''Returns the process exit code, if the job has exited; otherwise,
        returns None'''
        info = self.info()
        if info['state'] == 'stopped':
            return info['LastExitStatus']
        return None


if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
