# encoding: utf-8
#
# Copyright 2017-2023 Greg Neagle.
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
admin/common.py

Created by Greg Neagle on 2017-11-19.
Common code used by the admin libs
"""
from __future__ import absolute_import

import os

class AttributeDict(dict):
    '''Class that allow us to access foo['bar'] as foo.bar, and return None
    if foo.bar is not defined.'''
    def __getattr__(self, name):
        '''Allow access to dictionary keys as attribute names.'''
        try:
            return super(AttributeDict, self).__getattr__(name)
        except AttributeError:
            try:
                return self[name]
            except KeyError:
                return None


def list_items_of_kind(repo, kind):
    '''Returns a list of items of kind. Relative pathnames are prepended
    with kind. (example: ['icons/Bar.png', 'icons/Foo.png'])'''
    return [os.path.join(kind, item) for item in repo.itemlist(kind)]
