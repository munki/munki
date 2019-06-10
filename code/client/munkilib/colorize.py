# encoding: utf-8
#
# Copyright 2019 Andy Duss
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

from collections import defaultdict

"""
colorize

Created by Andy Duss on 2019-06-03.

Color definitions for terminal output
"""

def colorize(boolean):
    if boolean:
        return {
            "ok_green": '\033[92m',
            "ok_blue": '\033[94m',
            "warning": '\033[93m',
            "fail": '\033[91m',
            "end": '\033[0m'
        }
    else:
        return defaultdict(lambda: '')