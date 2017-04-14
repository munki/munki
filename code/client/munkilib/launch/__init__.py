# encoding: utf-8
#
# Copyright 2017 Greg Neagle.
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
launch.__init__.py

Created by Greg Neagle on 2017-04-14.

Code for getting socket file descriptor from launchd.
Returns a file descriptor for our socket.
"""

from .. import osutils

SOCKET_NAME = 'managedsoftwareupdated'


def get_socket_fd():
    '''Get socket file descriptors from launchd.'''
    os_version = osutils.getOsVersion(as_tuple=True)
    if os_version >= (10, 10):
        # use new launchd api
        from . import launch2
        try:
            sockets = launch2.launch_activate_socket(SOCKET_NAME)
        except launch2.LaunchDError:
            # no sockets found
            return None
        return sockets[0]

    else:
        # use old launchd api
        from . import launch1
        try:
            socket_dict = launch1.get_launchd_socket_fds()
        except launch1.LaunchDCheckInError:
            # no sockets found
            return None

        if SOCKET_NAME not in socket_dict:
            # no sockets found with the expected name
            return None

        return socket_dict[SOCKET_NAME][0]
