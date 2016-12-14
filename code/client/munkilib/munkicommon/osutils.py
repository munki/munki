#!/usr/bin/python
# encoding: utf-8
#
# Copyright 2009-2016 Greg Neagle.
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
osutils

Created by Greg Neagle on 2016-12-13.

Common functions and classes used by the munki tools.
"""


def getOsVersion(only_major_minor=True, as_tuple=False):
    """Returns an OS version.

    Args:
      only_major_minor: Boolean. If True, only include major/minor versions.
      as_tuple: Boolean. If True, return a tuple of ints, otherwise a string.
    """
    os_version_tuple = platform.mac_ver()[0].split('.')
    if only_major_minor:
        os_version_tuple = os_version_tuple[0:2]
    if as_tuple:
        return tuple(map(int, os_version_tuple))
    else:
        return '.'.join(os_version_tuple)


def main():
    """Placeholder"""
    print 'This is a library of support tools for the Munki Suite.'


if __name__ == '__main__':
    main()

