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
powermgr.py
Munki module to handle Power Manager tasks
"""
from __future__ import absolute_import, print_function

import objc

# PyLint cannot properly find names inside Cocoa libraries, so issues bogus
# No name 'Foo' in module 'Bar' warnings. Disable them.
# pylint: disable=no-name-in-module
from Foundation import NSBundle
# pylint:enable=no-name-in-module

from . import display

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

def assertNoIdleSleep(reason=None):
    """Uses IOKit functions to prevent idle sleep."""
    kIOPMAssertionTypeNoIdleSleep = "NoIdleSleepAssertion"
    kIOPMAssertionLevelOn = 255
    display.display_info('Preventing idle sleep')
    if not reason:
        reason = 'Munki is installing software'
    # pylint: disable=undefined-variable
    errcode, assertID = IOPMAssertionCreateWithName(
        kIOPMAssertionTypeNoIdleSleep,
        kIOPMAssertionLevelOn,
        reason, None)
    # pylint: enable=undefined-variable
    if errcode:
        return None
    return assertID


def removeNoIdleSleepAssertion(assertion_id):
    """Uses IOKit functions to remove a "no idle sleep" assertion."""
    if assertion_id:
        display.display_info('Allowing idle sleep')
        # pylint: disable=undefined-variable
        IOPMAssertionRelease(assertion_id)


class Caffeinator(object):
    """A simple object that prevents idle sleep and automagically
    removes the assertion when the object goes out of scope"""
    # pylint: disable=too-few-public-methods

    def __init__(self, reason=None):
        """Make Power Manager assertion and store the assertion_id"""
        self.assertion_id = assertNoIdleSleep(reason=reason)

    def __del__(self):
        """Remove our Power Manager assertion"""
        removeNoIdleSleepAssertion(self.assertion_id)


if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
