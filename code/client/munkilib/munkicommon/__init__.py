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
munkicommon

Created by Greg Neagle on 2008-11-18.

Common functions used by the munki tools.
"""

import os

# We wildcard-import from submodules for backwards compatibility; functions
# that were previously available from this module
# pylint: disable=wildcard-import
from .authrestart import *
from .constants import *
from .display import *
from .dmgutils import *
from .hash import *
from .info import *
from .munkilog import *
from .osutils import *
from .pkgutils import *
from .prefs import *
from .processes import *
from .reports import *
from .scriptutils import *
# pylint: enable=wildcard-import

# we use camelCase-style names. Deal with it.
# pylint: disable=C0103


# misc functions

_stop_requested = False
def stopRequested():
    """Allows user to cancel operations when GUI status is being used"""
    global _stop_requested
    if _stop_requested:
        return True
    stop_request_flag = (
        '/private/tmp/'
        'com.googlecode.munki.managedsoftwareupdate.stop_requested')
    if munkistatusoutput:
        if os.path.exists(stop_request_flag):
            # store this so it's persistent until this session is over
            _stop_requested = True
            log('### User stopped session ###')
            try:
                os.unlink(stop_request_flag)
            except OSError, err:
                display_error(
                    'Could not remove %s: %s', stop_request_flag, err)
            return True
    return False


if __name__ == '__main__':
    print 'This is a library of support tools for the Munki Suite.'
