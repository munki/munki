# encoding: utf-8
#
#  munki.py
#  MunkiStatus
#
#  Created by Greg Neagle on 2/11/10.
#  Copyright 2010-2019 Greg Neagle.
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

'''munki-specific code for use with MunkiStatus'''

import os
import stat
import subprocess

from Foundation import CFPreferencesCopyAppValue
from SystemConfiguration import SCDynamicStoreCopyConsoleUser

INSTALLATLOGOUTFILE = "/private/tmp/com.googlecode.munki.installatlogout"

BUNDLE_ID = u'ManagedInstalls'

def pref(pref_name):
    """Return a preference. Since this uses CFPreferencesCopyAppValue,
        Preferences can be defined several places. Precedence is:
        - MCX
        - ~/Library/Preferences/ManagedInstalls.plist
        - /Library/Preferences/ManagedInstalls.plist
        - default_prefs defined here.
        """
    default_prefs = {
        'LogFile': '/Library/Managed Installs/Logs/ManagedSoftwareUpdate.log'
    }
    pref_value = CFPreferencesCopyAppValue(pref_name, BUNDLE_ID)
    if pref_value == None:
        pref_value = default_prefs.get(pref_name)
    return pref_value

def call(cmd):
    '''Convenience function; works around an issue with subprocess.call
    in PyObjC in Snow Leopard'''
    proc = subprocess.Popen(cmd, bufsize=1, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
    (output, err) = proc.communicate()
    return proc.returncode


def getconsoleuser():
    cfuser = SCDynamicStoreCopyConsoleUser( None, None, None )
    return cfuser[0]


def osascript(osastring):
    """Wrapper to run AppleScript commands"""
    cmd = ['/usr/bin/osascript', '-e', osastring]
    proc = subprocess.Popen(cmd, shell=False, bufsize=1,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out, err) = proc.communicate()
    if proc.returncode != 0:
        print >> sys.stderr, 'Error: ', err
    if out:
        return str(out).decode('UTF-8').rstrip('\n')


def restartNow():
    '''Trigger a restart'''
    osascript('tell application "System Events" to restart')


def clearLaunchTrigger():
    '''Clear the trigger file that fast-launches us at loginwindow.
    typically because we have been launched in statusmode at the
    loginwindow to perform a logout-install.'''
    try:
        if os.path.exists(INSTALLATLOGOUTFILE):
            os.unlink(INSTALLATLOGOUTFILE)
    except (OSError, IOError):
        return 1


def pythonScriptRunning(scriptname):
    """Returns Process ID for a running python script"""
    cmd = ['/bin/ps', '-eo', 'pid=,command=']
    proc = subprocess.Popen(cmd, shell=False, bufsize=1,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out, dummy_err) = proc.communicate()
    mypid = os.getpid()
    lines = str(out).splitlines()
    for line in lines:
        try:
            (pid, process) = line.split(None, 1)
        except ValueError:
            # funky process line, so we'll skip it
            pass
        else:
            args = process.split()
            try:
                # first look for Python processes
                if (args[0].find('MacOS/Python') != -1 or
                    args[0].find('python') != -1):
                    # look for first argument being scriptname
                    if args[1].find(scriptname) != -1:
                        try:
                            if int(pid) != int(mypid):
                                return pid
                        except ValueError:
                            # pid must have some funky characters
                            pass
            except IndexError:
                pass
    # if we get here we didn't find a Python script with scriptname
    # (other than ourselves)
    return 0