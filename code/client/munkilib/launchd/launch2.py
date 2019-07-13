#
# Copyright 2015 Per Olofsson
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
'''Python wrapper for updated launchd checkin API'''
from __future__ import absolute_import

import os
# pylint: disable=wildcard-import
# pylint: disable=unused-wildcard-import
from ctypes import *
# pylint: enable=unused-wildcard-import
# pylint: enable=wildcard-import
# pylint: disable=invalid-name
libc = CDLL("/usr/lib/libc.dylib")
# pylint: enable=invalid-name

try:
    _ = xrange # pylint: disable=xrange-builtin
except NameError:
    # no xrange in Python 3
    xrange = range

# int launch_activate_socket(const char *name, int **fds, size_t *cnt)
libc.launch_activate_socket.restype = c_int
libc.launch_activate_socket.argtypes = [c_char_p, POINTER(POINTER(c_int)),
                                        POINTER(c_size_t)]


class LaunchDError(Exception):
    '''Exception to raise if there is a checkin error'''
    pass

def launch_activate_socket(name):
    """Retrieve named socket file descriptors from launchd."""

    # Wrap in try/finally to free resources allocated during lookup.
    try:
        fds = POINTER(c_int)()
        cnt = c_size_t(0)
        err = libc.launch_activate_socket(name, byref(fds), byref(cnt))
        if err:
            raise LaunchDError("Failed to retrieve sockets from launchd: %s"
                               % os.strerror(err))

        # Return a list of file descriptors.
        return list(fds[x] for x in xrange(cnt.value))

    finally:
        if fds:
            libc.free(fds)
