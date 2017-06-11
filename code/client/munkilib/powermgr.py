# encoding: utf-8
#
# Copyright 2009-2017 Greg Neagle.
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

import objc

# PyLint cannot properly find names inside Cocoa libraries, so issues bogus
# No name 'Foo' in module 'Bar' warnings. Disable them.
# pylint: disable=E0611
from Foundation import NSBundle
# pylint:enable=E0611

# lots of camelCase names
# pylint: disable=C0103

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
# pylint: disable=E1101
objc.loadBundleFunctions(IOKit, globals(), functions)
# pylint: enable=E1101

def onACPower():
    """Returns a boolean to indicate if the machine is on AC power"""
    # pylint: disable=E0602
    power_source = IOPSGetProvidingPowerSourceType(IOPSCopyPowerSourcesInfo())
    # pylint: enable=E0602
    return power_source == 'AC Power'


def onBatteryPower():
    """Returns a boolean to indicate if the machine is on battery power"""
    # pylint: disable=E0602
    power_source = IOPSGetProvidingPowerSourceType(IOPSCopyPowerSourcesInfo())
    # pylint: enable=E0602
    return power_source == 'Battery Power'


def getBatteryPercentage():
    """Returns battery charge percentage"""
    # pylint: disable=E0602
    ps_blob = IOPSCopyPowerSourcesInfo()
    power_sources = IOPSCopyPowerSourcesList(ps_blob)
    for source in power_sources:
        description = IOPSGetPowerSourceDescription(ps_blob, source)
        if description.get('Type') == 'InternalBattery':
            return description.get('Current Capacity', 0)
    return 0


def assertNoIdleSleep(reason='Munki is installing software'):
    """Uses IOKit functions to prevent idle sleep."""
    kIOPMAssertionTypeNoIdleSleep = "NoIdleSleepAssertion"
    kIOPMAssertionLevelOn = 255
    # pylint: disable=E0602
    errcode, assertID = IOPMAssertionCreateWithName(
        kIOPMAssertionTypeNoIdleSleep,
        kIOPMAssertionLevelOn,
        reason, None)
    # pylint: enable=E0602
    if errcode:
        return None
    return assertID


def removeNoIdleSleepAssertion(assertion_id):
    """Uses IOKit functions to remove a "no idle sleep" assertion."""
    if assertion_id:
        # pylint: disable=E0602
        IOPMAssertionRelease(assertion_id)


if __name__ == '__main__':
    print 'This is a library of support tools for the Munki Suite.'
