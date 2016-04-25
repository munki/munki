#!/usr/bin/python
# encoding: utf-8
#
# Copyright 2009-2016 Greg Neagle.
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
munki module to toggle IOKit/PowerManager idle sleep assertions.
"""

# pylint: disable=E0611
# stuff for IOKit/PowerManager, courtesy Michael Lynn, pudquick@github
from ctypes import c_uint32, cdll, c_void_p, POINTER, byref
from CoreFoundation import CFStringCreateWithCString
from CoreFoundation import kCFStringEncodingASCII
from objc import pyobjc_id
# pylint: enable=E0611

# lots of camelCase names
# pylint: disable=C0103

libIOKit = cdll.LoadLibrary('/System/Library/Frameworks/IOKit.framework/IOKit')
libIOKit.IOPMAssertionCreateWithName.argtypes = [
    c_void_p, c_uint32, c_void_p, POINTER(c_uint32)]
libIOKit.IOPMAssertionRelease.argtypes = [c_uint32]


def _CFSTR(py_string):
    """Returns a CFString given a Python string."""
    return CFStringCreateWithCString(None, py_string, kCFStringEncodingASCII)


def _rawPointer(pyobjc_string):
    """Returns a pointer to a CFString."""
    return pyobjc_id(pyobjc_string.nsstring())


def _IOPMAssertionCreateWithName(assert_name, assert_level, assert_msg):
    """Creaes a PowerManager assertion."""
    assertID = c_uint32(0)
    p_assert_name = _rawPointer(_CFSTR(assert_name))
    p_assert_msg = _rawPointer(_CFSTR(assert_msg))
    errcode = libIOKit.IOPMAssertionCreateWithName(
        p_assert_name, assert_level, p_assert_msg, byref(assertID))
    return (errcode, assertID)


def assertNoIdleSleep():
    """Uses IOKit functions to prevent idle sleep."""
    # based on code by Michael Lynn, pudquick@github
    kIOPMAssertionTypeNoIdleSleep = "NoIdleSleepAssertion"
    kIOPMAssertionLevelOn = 255
    reason = "Munki is installing software"

    dummy_errcode, assertID = _IOPMAssertionCreateWithName(
        kIOPMAssertionTypeNoIdleSleep,
        kIOPMAssertionLevelOn,
        reason)
    return assertID


def removeNoIdleSleepAssertion(assertion_id):
    """Uses IOKit functions to remove a "no idle sleep" assertion."""
    return libIOKit.IOPMAssertionRelease(assertion_id)
