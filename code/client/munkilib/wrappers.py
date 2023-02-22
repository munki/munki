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
wrappers.py

Created by Greg Neagle on 2018-05-29.

Some wrappers to paper over the differences between Python 2 and Python 3
"""

import plistlib


# plistlib wrappers

class PlistError(Exception):
    """Base error for plists"""
    pass


class PlistReadError(PlistError):
    """Error when reading plists"""
    pass


class PlistWriteError(PlistError):
    """Error when writing plists"""
    pass


# Disable PyLint complaining about 'invalid' camelCase names
# pylint: disable=C0103

def readPlist(filepath):
    '''Wrapper for the differences between Python 2 and Python 3's plistlib'''
    try:
        with open(filepath, "rb") as fileobj:
            return plistlib.load(fileobj)
    except AttributeError:
        # plistlib module doesn't have a load function (as in Python 2)
        try:
            return plistlib.readPlist(filepath)
        except BaseException as err:
            raise PlistReadError(err)
    except Exception as err:
        raise PlistReadError(err)


def readPlistFromString(bytestring):
    '''Wrapper for the differences between Python 2 and Python 3's plistlib'''
    try:
        return plistlib.loads(bytestring)
    except AttributeError:
        # plistlib module doesn't have a loads function (as in Python 2)
        try:
            return plistlib.readPlistFromString(bytestring)
        except BaseException as err:
            raise PlistReadError(err)
    except Exception as err:
        raise PlistReadError(err)


def writePlist(data, filepath):
    '''Wrapper for the differences between Python 2 and Python 3's plistlib'''
    try:
        with open(filepath, "wb") as fileobj:
            plistlib.dump(data, fileobj)
    except AttributeError:
        # plistlib module doesn't have a dump function (as in Python 2)
        try:
            plistlib.writePlist(data, filepath)
        except BaseException as err:
            raise PlistWriteError(err)
    except Exception as err:
        raise PlistWriteError(err)


def writePlistToString(data):
    '''Wrapper for the differences between Python 2 and Python 3's plistlib'''
    try:
        return plistlib.dumps(data)
    except AttributeError:
        # plistlib module doesn't have a dumps function (as in Python 2)
        try:
            return plistlib.writePlistToString(data)
        except BaseException as err:
            raise PlistWriteError(err)
    except Exception as err:
        raise PlistWriteError(err)


# pylint: enable=C0103


# Python 2 and 3 wrapper for raw_input/input
try:
    # Python 2
    get_input = raw_input # pylint: disable=raw_input-builtin
except NameError:
    # Python 3
    get_input = input # pylint: disable=input-builtin


# remap basestring in Python 3
try:
    _ = basestring
except NameError:
    basestring = str

def is_a_string(something):
    '''Wrapper for basestring vs str'''
    return isinstance(something, basestring)


def unicode_or_str(something, encoding="UTF-8"):
    '''Wrapper for unicode vs str'''
    try:
        # Python 2
        if isinstance(something, str):
            return unicode(something, encoding)
        return unicode(something)
    except NameError:
        # Python 3
        if isinstance(something, bytes):
            return str(something, encoding)
        return str(something)
