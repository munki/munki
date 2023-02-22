#!/usr/bin/python
# encoding: utf-8
"""
test_display_unicode.py

Unit tests for display.display_* functions.

"""
# Copyright 2014-2023 Greg Neagle.
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
from __future__ import absolute_import

import unittest

from munkilib import display


MSG_UNI = u'Günther\'s favorite thing is %s'
MSG_STR = u'Günther\'s favorite thing is %s'.encode('UTF-8')

ARG_UNI = u'Günther'
ARG_STR = u'Günther'.encode('UTF-8')


def log(msg, logname=''):
    """Redefine the logging function so our tests don't write
    a bunch of garbage to Munki's logs"""
    pass
display.munkilog.log = log


class TestDisplayInfoUnicodeOutput(unittest.TestCase):
    """Test display_info with text that may or may not be proper
    Unicode."""

    def test_display_info_with_unicode_msg(self):
        display.display_info(MSG_UNI)

    def test_display_info_with_str_msg(self):
        display.display_info(MSG_STR)

    def test_display_info_with_unicode_msg_unicode_arg(self):
        display.display_info(MSG_UNI, ARG_UNI)

    def test_display_info_with_unicode_msg_str_arg(self):
        display.display_info(MSG_UNI, ARG_STR)

    def test_display_info_with_str_msg_unicode_arg(self):
        display.display_info(MSG_STR, ARG_UNI)

    def test_display_info_with_str_msg_str_arg(self):
        display.display_info(MSG_STR, ARG_STR)


class TestDisplayWarningUnicodeOutput(unittest.TestCase):
    """Test display_warning with text that may or may not be proper
    Unicode."""

    def test_display_warning_with_unicode_msg(self):
        display.display_warning(MSG_UNI)

    def test_display_warning_with_str_msg(self):
        display.display_warning(MSG_STR)

    def test_display_warning_with_unicode_msg_unicode_arg(self):
        display.display_warning(MSG_UNI, ARG_UNI)

    def test_display_warning_with_unicode_msg_str_arg(self):
        display.display_warning(MSG_UNI, ARG_STR)

    def test_display_warning_with_str_msg_unicode_arg(self):
        display.display_warning(MSG_STR, ARG_UNI)

    def test_display_warning_with_str_msg_str_arg(self):
        display.display_warning(MSG_STR, ARG_STR)


class TestDisplayErrorUnicodeOutput(unittest.TestCase):
    """Test display_error with text that may or may not be proper
    Unicode."""

    def test_display_error_with_unicode_msg(self):
        display.display_error(MSG_UNI)

    def test_display_error_with_str_msg(self):
        display.display_error(MSG_STR)

    def test_display_error_with_unicode_msg_unicode_arg(self):
        display.display_error(MSG_UNI, ARG_UNI)

    def test_display_error_with_unicode_msg_str_arg(self):
        display.display_error(MSG_UNI, ARG_STR)

    def test_display_error_with_str_msg_unicode_arg(self):
        display.display_error(MSG_STR, ARG_UNI)

    def test_display_error_with_str_msg_str_arg(self):
        display.display_error(MSG_STR, ARG_STR)


def main():
    unittest.main(buffer=True)


if __name__ == '__main__':
    main()
