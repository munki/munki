# encoding: utf-8
#
# Copyright 2009-2023 Greg Neagle.
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
from __future__ import absolute_import, print_function

# this module currently exists purely for backwards compatibility so that
# anything calling munkicommon functions will still work (for now)

# We wildcard-import from submodules for backwards compatibility; functions
# that were previously available from this module
# pylint: disable=wildcard-import
from .constants import *
from .display import *
from .dmgutils import *
from .munkihash import *
from .info import *
from .munkilog import *
from .osutils import *
from .pkgutils import *
from .prefs import *
from .processes import *
from .reports import *
from .scriptutils import *
# pylint: enable=wildcard-import

if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
