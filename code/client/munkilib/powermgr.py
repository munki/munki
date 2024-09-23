# encoding: utf-8
#
# Copyright 2009-2024 Greg Neagle.
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
powermgr.py
Munki module to handle Power Manager tasks
"""
from __future__ import absolute_import, print_function

import objc
import os

# PyLint cannot properly find names inside Cocoa libraries, so issues bogus
# No name 'Foo' in module 'Bar' warnings. Disable them.
# pylint: disable=no-name-in-module
from Foundation import NSBundle
# pylint:enable=no-name-in-module

from . import display
from . import prefs
from . import constants
from . import osutils

# lots of camelCase names
# pylint: disable=invalid-name

# See http://michaellynn.github.io/2015/08/08/learn-you-a-better-pyobjc-bridgesupport-signature/
# for a primer on the bridging techniques used here
#

# https://developer.apple.com/documentation/iokit/iopowersources.h?language=objc
IOKit = NSBundle.bundleWithIdentifier_('com.apple.framework.IOKit')

functions = [("IOPMAssertionCreateWithName", b"i@i@o^i"),
             ("IOPMAssertionRelease", b"vi"),
             ("IOPSGetPowerSourceDescription", b"@@@"),
             ("IOPSCopyPowerSourcesInfo", b"@"),
             ("IOPSCopyPowerSourcesList", b"@@"),
             ("IOPSGetProvidingPowerSourceType", b"@@"),
            ]

# No idea why PyLint complains about objc.loadBundleFunctions
# pylint: disable=no-member
objc.loadBundleFunctions(IOKit, globals(), functions)
# pylint: enable=no-member

def onACPower():
    """Returns a boolean to indicate if the machine is on AC power"""
    # pylint: disable=undefined-variable
    power_source = IOPSGetProvidingPowerSourceType(IOPSCopyPowerSourcesInfo())
    # pylint: enable=undefined-variable
    return power_source == 'AC Power'


def onBatteryPower():
    """Returns a boolean to indicate if the machine is on battery power"""
    # pylint: disable=undefined-variable
    power_source = IOPSGetProvidingPowerSourceType(IOPSCopyPowerSourcesInfo())
    # pylint: enable=undefined-variable
    return power_source == 'Battery Power'


def getBatteryPercentage():
    """Returns battery charge percentage"""
    # pylint: disable=undefined-variable
    ps_blob = IOPSCopyPowerSourcesInfo()
    power_sources = IOPSCopyPowerSourcesList(ps_blob)
    for source in power_sources:
        description = IOPSGetPowerSourceDescription(ps_blob, source)
        if description.get('Type') == 'InternalBattery':
            return description.get('Current Capacity', 0)
    return 0

def hasInternalBattery():
    """Determine if this Mac has a power source of 'InternalBattery'"""
    ps_blob = IOPSCopyPowerSourcesInfo()
    power_sources = IOPSCopyPowerSourcesList(ps_blob)
    for source in power_sources:
        description = IOPSGetPowerSourceDescription(ps_blob, source)
        if description.get('Type') == 'InternalBattery':
            return True
    return False


def assertSleepPrevention(reason=None):
    """Uses IOKit functions to prevent either idle or display sleep."""
    prevent_display_sleep = (
           prefs.pref('SuspendDisplaySleepDuringBootstrap') and
           os.path.exists(constants.CHECKANDINSTALLATSTARTUPFLAG) and
           osutils.getconsoleuser() == u"loginwindow"
       )
    if prevent_display_sleep:
        display.display_info('Display sleep suspended due to SuspendDisplaySleepDuringBootstrap preference enabled, bootstrap flag set, and currently at loginwindow.')
        kIOPMAssertionType = "NoDisplaySleepAssertion"
    else:
        kIOPMAssertionType = "NoIdleSleepAssertion"
    kIOPMAssertionLevelOn = 255
    
    if not reason:
        reason = 'Munki is installing software'
    
    display.display_info(f'Preventing {"display" if prevent_display_sleep else "idle"} sleep due to: {reason}')
    
    # pylint: disable=undefined-variable
    errcode, assertID = IOPMAssertionCreateWithName(
        kIOPMAssertionType,
        kIOPMAssertionLevelOn,
        reason, None)
    # pylint: enable=undefined-variable
    
    if errcode:
        display.display_error('Failed to create sleep prevention assertion.')
        return None
    return assertID


def removeSleepPreventionAssertion(assertion_id):
    """Uses IOKit functions to remove a "no idle sleep" assertion."""
    if assertion_id:
        display.display_info('Allowing idle sleep')
        # pylint: disable=undefined-variable
        IOPMAssertionRelease(assertion_id)


class Caffeinator(object):
    """An object that prevents sleep and automatically removes the assertion when the object goes out of scope."""
    # pylint: disable=too-few-public-methods
    
    def __init__(self, reason=None):
        """Make a Power Manager assertion to prevent sleep and store the assertion ID."""
        self.assertion_id = assertSleepPrevention(reason)
    
    def __del__(self):
        """Remove our Power Manager assertion upon object deletion."""
        removeSleepPreventionAssertion(self.assertion_id)


if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
