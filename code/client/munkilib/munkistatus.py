#!/usr/bin/python
# encoding: utf-8
#
# Copyright 2009-2014 Greg Neagle.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
munkistatus.py

Created by Greg Neagle on 2009-09-24.

Utility functions for using MunkiStatus.app
to display status and progress.
"""

import os
import subprocess
import time

from Foundation import NSDistributedNotificationCenter
from Foundation import NSNotificationDeliverImmediately
from Foundation import NSNotificationPostToAllSessions


# our NSDistributedNotification identifier
NOTIFICATION_ID = 'com.googlecode.munki.managedsoftwareupdate.statusUpdate'


def launchMunkiStatus():
    '''Uses launchd KeepAlive path so it launches from a launchd agent
    in the correct context.
    This is more complicated to set up, but makes Apple (and launchservices)
    happier.
    There needs to be a launch agent that is triggered when the launchfile
    is created; and that launch agent then runs MunkiStatus.app.'''
    
    # TESTING, TESTING
    return
    
    launchfile = "/var/run/com.googlecode.munki.MunkiStatus"
    cmd = ['/usr/bin/touch', launchfile]
    unused_retcode = subprocess.call(cmd)
    time.sleep(0.1)
    if os.path.exists(launchfile):
        os.unlink(launchfile)


def postNotificationWithUserDict(userInfoDict):
    dnc = NSDistributedNotificationCenter.defaultCenter()
    dnc.postNotificationName_object_userInfo_options_(
        NOTIFICATION_ID,
        None, 
        userInfoDict,
        NSNotificationDeliverImmediately + NSNotificationPostToAllSessions)


def activate():
    '''Brings MunkiStatus window to the front.'''
    postNotificationWithUserDict({'command': 'activate'})


def message(messageText):
    '''Sets the status message.'''
    postNotificationWithUserDict({'message': messageText})


def detail(detailsText):
    '''Sets the detail text.'''
    postNotificationWithUserDict({'detail': detailsText})


def percent(percentage):
    '''Sets the progress indicator to 0-100 percent done.
    If you pass a negative number, the progress indicator
    is shown as an indeterminate indicator (barber pole).'''
    postNotificationWithUserDict({'percent': percentage})


def hideStopButton():
    '''Hides the stop button.'''
    postNotificationWithUserDict({'command': 'hideStopButton'})


def showStopButton():
    '''Shows the stop button.'''
    postNotificationWithUserDict({'command': 'showStopButton'})


def disableStopButton():
    '''Disables (grays out) the stop button.'''
    postNotificationWithUserDict({'command': 'disableStopButton'})


def enableStopButton():
    '''Enables the stop button.'''
    postNotificationWithUserDict({'command': 'enableStopButton'})


def quit():
    '''Tells the status app that we're done.'''
    postNotificationWithUserDict({'command': 'quit'})


def restartAlert():
    '''Tells MunkiStatus to display a restart alert.'''
    postNotificationWithUserDict({'command': 'showRestartAlert'})

