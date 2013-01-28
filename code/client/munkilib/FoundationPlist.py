#!/usr/bin/python
# encoding: utf-8
#
# Copyright 2009-2013 Greg Neagle.
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
"""FoundationPlist.py -- a tool to generate and parse MacOSX .plist files.

This is intended as a drop-in replacement for Python's included plistlib,
with a few caveats:
    - readPlist() and writePlist() operate only on a filepath,
        not a file object.
    - there is no support for the deprecated functions:
        readPlistFromResource()
        writePlistToResource()
    - there is no support for the deprecated Plist class.

The Property List (.plist) file format is a simple XML pickle supporting
basic object types, like dictionaries, lists, numbers and strings.
Usually the top level object is a dictionary.

To write out a plist file, use the writePlist(rootObject, filepath)
function. 'rootObject' is the top level object, 'filepath' is a
filename.

To parse a plist from a file, use the readPlist(filepath) function,
with a file name. It returns the top level object (again, usually a
dictionary).

To work with plist data in strings, you can use readPlistFromString()
and writePlistToString().
"""

from Foundation import NSData, \
                       NSPropertyListSerialization, \
                       NSPropertyListMutableContainers, \
                       NSPropertyListXMLFormat_v1_0

class FoundationPlistException(Exception):
    pass

class NSPropertyListSerializationException(FoundationPlistException):
    pass

class NSPropertyListWriteException(FoundationPlistException):
    pass

def readPlist(filepath):
    """
    Read a .plist file from filepath.  Return the unpacked root object
    (which is usually a dictionary).
    """
    plistData = NSData.dataWithContentsOfFile_(filepath)
    dataObject, plistFormat, error = \
        NSPropertyListSerialization.propertyListFromData_mutabilityOption_format_errorDescription_(
                     plistData, NSPropertyListMutableContainers, None, None)
    if error:
        error = error.encode('ascii', 'ignore')
        errmsg = "%s in file %s" % (error, filepath)
        raise NSPropertyListSerializationException(errmsg)
    else:
        return dataObject


def readPlistFromString(data):
    '''Read a plist data from a string. Return the root object.'''
    plistData = buffer(data)
    dataObject, plistFormat, error = \
     NSPropertyListSerialization.propertyListFromData_mutabilityOption_format_errorDescription_(
                    plistData, NSPropertyListMutableContainers, None, None)
    if error:
        error = error.encode('ascii', 'ignore')
        raise NSPropertyListSerializationException(error)
    else:
        return dataObject


def writePlist(dataObject, filepath):
    '''
    Write 'rootObject' as a plist to filepath.
    '''
    plistData, error = \
     NSPropertyListSerialization.dataFromPropertyList_format_errorDescription_(
                            dataObject, NSPropertyListXMLFormat_v1_0, None)
    if error:
        error = error.encode('ascii', 'ignore')
        raise NSPropertyListSerializationException(error)
    else:
        if plistData.writeToFile_atomically_(filepath, True):
            return
        else:
            raise NSPropertyListWriteException(
                                "Failed to write plist data to %s" % filepath)


def writePlistToString(rootObject):
    '''Return 'rootObject' as a plist-formatted string.'''
    plistData, error = \
     NSPropertyListSerialization.dataFromPropertyList_format_errorDescription_(
                            rootObject, NSPropertyListXMLFormat_v1_0, None)
    if error:
        error = error.encode('ascii', 'ignore')
        raise NSPropertyListSerializationException(error)
    else:
        return str(plistData)


