#!/usr/bin/python
# encoding: utf-8
"""
test_isapprunning.py

Unit tests for processes.isAppRunning.

"""
from __future__ import absolute_import, print_function
# Copyright 2016-present Nate Walck.
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

from ..data_scaffolds import getRunningProcessesMock
from munkilib import processes


try:
    from mock import patch
except ImportError:
    import sys
    print("mock module is required. run: easy_install mock", file=sys.stderr)
    raise


class TestIsAppRunning(unittest.TestCase):
    """Test munkicommonisAppRunning for each match catch."""

    def setUp(self):
        return

    def tearDown(self):
        self.processes = []

    @patch('munkilib.processes.getRunningProcesses', return_value=getRunningProcessesMock())
    def test_app_with_exact_path_match(self, ps_mock):
        print("Testing isAppRunning with exact path match...")
        self.assertEqual(
            processes.is_app_running('/Applications/Firefox.app/Contents/MacOS/firefox'),
            True
        )

    @patch('munkilib.processes.getRunningProcesses', return_value=getRunningProcessesMock())
    def test_app_with_exact_path_no_match(self, ps_mock):
        print("Testing isAppRunning with exact path no matches...")
        self.assertEqual(
            processes.is_app_running('/usr/local/bin/bonzi'),
            False
        )

    @patch('munkilib.processes.getRunningProcesses', return_value=getRunningProcessesMock())
    def test_app_by_filename_match(self, ps_mock):
        print("Testing isAppRunning with file name match...")
        self.assertEqual(
            processes.is_app_running('Firefox.app'),
            True
        )

    @patch('munkilib.processes.getRunningProcesses', return_value=getRunningProcessesMock())
    def test_app_by_filename_no_match(self, ps_mock):
        print("Testing isAppRunning with file name no matches...")
        self.assertEqual(
            processes.is_app_running('BonziBUDDY.app'),
            False
        )

    @patch('munkilib.processes.getRunningProcesses', return_value=getRunningProcessesMock())
    def test_app_by_executable_name_match(self, ps_mock):
        print("Testing isAppRunning with executable name match...")
        self.assertEqual(
            processes.is_app_running('firefox'),
            True
        )

    @patch('munkilib.processes.getRunningProcesses', return_value=getRunningProcessesMock())
    def test_app_by_executable_name_no_match(self, ps_mock):
        print("Testing isAppRunning with executable name no matches...")
        self.assertEqual(
            processes.is_app_running('bonzi'),
            False
        )

    @patch('munkilib.processes.getRunningProcesses', return_value=getRunningProcessesMock())
    def test_app_name_with_dot_app_match(self, ps_mock):
        print("Testing isAppRunning with name plus .app match...")
        self.assertEqual(
            processes.is_app_running('Firefox'),
            True
        )

    @patch('munkilib.processes.getRunningProcesses', return_value=getRunningProcessesMock())
    def test_app_name_with_dot_app_no_match(self, ps_mock):
        print("Testing isAppRunning with name plus .app match...")
        self.assertEqual(
            processes.is_app_running('BonziBUDDY'),
            False
        )


def main():
    unittest.main(buffer=True)


if __name__ == '__main__':
    main()
