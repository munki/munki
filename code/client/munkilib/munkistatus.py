# encoding: utf-8
#
# Copyright 2009-2023 Greg Neagle.
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
munkistatus.py

Created by Greg Neagle on 2009-09-24.

Utility functions for using MunkiStatus.app
to display status and progress.
"""
from __future__ import absolute_import, print_function

import os
import time

# PyLint cannot properly find names inside Cocoa libraries, so issues bogus
# No name 'Foo' in module 'Bar' warnings. Disable them.
# pylint: disable=E0611
from Foundation import NSDistributedNotificationCenter
from Foundation import NSNotificationDeliverImmediately
from Foundation import NSNotificationPostToAllSessions
# pylint: enable=E0611

# we use lots of camelCase-style names. Deal with it.
# pylint: disable=C0103

# our NSDistributedNotification identifier
NOTIFICATION_ID = 'com.googlecode.munki.managedsoftwareupdate.statusUpdate'

# keep our current status. We keep this so that notification clients
# that come "online" late can get current state
_currentStatus = {}

def initStatusDict():
    '''Initialize our status dictionary'''
    global _currentStatus
    _currentStatus = {
        'message': '',
        'detail': '',
        'percent': -1,
        'stop_button_visible': True,
        'stop_button_enabled': True,
        'command': '',
        'pid': os.getpid()
    }

def launchMunkiStatus():
    '''Uses launchd KeepAlive path so it launches from a launchd agent
    in the correct context.
    This is more complicated to set up, but makes Apple (and launchservices)
    happier.
    There needs to be a launch agent that is triggered when the launchfile
    is created; and that launch agent then runs MunkiStatus.app.'''
    initStatusDict()

    launchfile = "/var/run/com.googlecode.munki.MunkiStatus"
    try:
        open(launchfile, 'w').close()
    except (OSError, IOError):
        pass
    time.sleep(0.1)
    if os.path.exists(launchfile):
        os.unlink(launchfile)


def postStatusNotification():
    '''Post a status notification'''
    dnc = NSDistributedNotificationCenter.defaultCenter()
    dnc.postNotificationName_object_userInfo_options_(
        NOTIFICATION_ID,
        None,
        _currentStatus,
        NSNotificationDeliverImmediately + NSNotificationPostToAllSessions)


def message(messageText):
    '''Sets the status message.'''
    _currentStatus['message'] = messageText
    postStatusNotification()


def detail(detailsText):
    '''Sets the detail text.'''
    _currentStatus['detail'] = detailsText
    postStatusNotification()


def percent(percentage):
    '''Sets the progress indicator to 0-100 percent done.
    If you pass a negative number, the progress indicator
    is shown as an indeterminate indicator (barber pole).'''
    _currentStatus['percent'] = percentage
    postStatusNotification()


def hideStopButton():
    '''Hides the stop button.'''
    _currentStatus['stop_button_visible'] = False
    postStatusNotification()


def showStopButton():
    '''Shows the stop button.'''
    _currentStatus['stop_button_visible'] = True
    postStatusNotification()


def disableStopButton():
    '''Disables (grays out) the stop button.'''
    _currentStatus['stop_button_enabled'] = False
    postStatusNotification()


def enableStopButton():
    '''Enables the stop button.'''
    _currentStatus['stop_button_enabled'] = True
    postStatusNotification()


def activate():
    '''Brings MunkiStatus window to the front.'''
    _currentStatus['command'] = 'activate'
    postStatusNotification()
    # now clear the command; unlike the other fields, this
    # should not persist between notifications
    _currentStatus['command'] = ''


def quit_app():
    '''Tells the status app that we're done.'''
    _currentStatus['command'] = 'quit'
    postStatusNotification()
    # now clear the command; unlike the other fields, this
    # should not persist between notifications
    _currentStatus['command'] = ''


def restartAlert():
    '''Tells MunkiStatus to display a restart alert.'''
    _currentStatus['command'] = 'showRestartAlert'
    postStatusNotification()
    # now clear the command; unlike the other fields, this
    # should not persist between notifications
    _currentStatus['command'] = ''


if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
