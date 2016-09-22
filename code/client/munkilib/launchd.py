#!/usr/bin/python
# encoding: utf-8
#
# Copyright 2011-2016 Greg Neagle.
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
launchd.py

Created by Greg Neagle on 2011-07-22.

A wrapper for using launchd to run a process as root outside of munki's
process space. Needed to properly run /usr/sbin/softwareupdate, for example.
"""

import os
import subprocess
import time
import uuid

import munkicommon
import FoundationPlist


class LaunchdJobException(Exception):
    '''Exception for launchctl errors and other errors from
    this module.'''
    pass


class Job(object):
    '''launchd job object'''

    def __init__(self, cmd, environment_vars=None):
        tmpdir = munkicommon.tmpdir()
        labelprefix = 'com.googlecode.munki.'
        # create a unique id for this job
        jobid = str(uuid.uuid1())

        self.label = labelprefix + jobid
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
        err = proc.communicate()[1]
        if proc.returncode:
            raise LaunchdJobException(err)

    def __del__(self):
        '''Attempt to clean up'''
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
                self.stdout = open(self.stdout_path, 'r')
                self.stderr = open(self.stderr_path, 'r')
            except (OSError, IOError), err:
                raise LaunchdJobException(err)

    def stop(self):
        '''Stop the launchd job'''
        launchctl_cmd = ['/bin/launchctl', 'stop', self.label]
        proc = subprocess.Popen(launchctl_cmd, shell=False, bufsize=-1,
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        err = proc.communicate()[1]
        if proc.returncode:
            raise LaunchdJobException(err)

    def info(self):
        '''Get info about the launchd job. Returns a dictionary.'''
        info = {'state': 'unknown',
                'PID': None,
                'LastExitStatus': None}
        launchctl_cmd = ['/bin/launchctl', 'list']
        proc = subprocess.Popen(launchctl_cmd, shell=False, bufsize=-1,
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        output = proc.communicate()[0]
        if proc.returncode or not output:
            return info
        else:
            lines = str(output).splitlines()
            # search launchctl list output for our job label
            job_lines = [item for item in lines
                         if item.endswith('\t' + self.label)]
            if len(job_lines) != 1:
                # unexpected number of lines matched our label
                return info
            job_info = job_lines[0].split('\t')
            if len(job_info) != 3:
                # unexpected number of fields in the line
                return info
            if job_info[0] == '-':
                info['PID'] = None
                info['state'] = 'stopped'
            else:
                info['PID'] = int(job_info[0])
                info['state'] = 'running'
            if job_info[1] == '-':
                info['LastExitStatus'] = None
            else:
                info['LastExitStatus'] = int(job_info[1])
            return info

    def returncode(self):
        '''Returns the process exit code, if the job has exited; otherwise,
        returns None'''
        info = self.info()
        if info['state'] == 'stopped':
            return info['LastExitStatus']
        else:
            return None


def main():
    '''placeholder'''
    pass


if __name__ == '__main__':
    main()

