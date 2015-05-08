#!/usr/bin/python
# encoding: utf-8
"""
gurl_redirects_test.py

Unit tests for munkicommon's display_* functions.

"""
# Copyright 2015 Andreas Fuchs.
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


from gurl import Gurl
import munkicommon
import sys
import unittest

def log(msg, logname=''):
    """Redefine munkicommon's logging function so our tests don't write
    a bunch of garbage to Munki's logs"""
    pass
munkicommon.log = log

class GurlUnitTest(unittest.TestCase):
    def gurl(self, must_follow_redirects=False, allow_redirects='none'):
        options = {'url': 'http://example.com',
                   'file': '/tmp/munki_test_tempfile',
                   'must_follow_redirects': must_follow_redirects,
                   'allow_redirects': allow_redirects,
                   'can_resume': False,
                   'additional_headers': dict(),
                   'download_only_if_changed': False,
                   'cache_data': None,
                   'logging_function': munkicommon.display_debug2}
        return Gurl.alloc().initWithOptions_(options)

class TestMustFollowRedirect(GurlUnitTest):
    """Test behavior on following redirects as requested by munki
    internals."""

    def test_with_allowed_redirects_none(self):
        gurl = self.gurl(must_follow_redirects = True, allow_redirects = 'none')
        self.assertEqual(True, gurl.redirect_allowed('http://something.com'))

    def test_with_allowed_redirects_https(self):
        gurl = self.gurl(must_follow_redirects = True, allow_redirects = 'https')
        self.assertEqual(True, gurl.redirect_allowed('http://something.com'))

    def test_with_allowed_redirects_all(self):
        gurl = self.gurl(must_follow_redirects = True, allow_redirects = 'all')
        self.assertEqual(True, gurl.redirect_allowed('http://something.com'))

class TestAllowRedirects(GurlUnitTest):
    """Test behavior on following redirects as given by the preference
    AllowHTTPRedirects."""

    def test_disallow_for_none(self):
        gurl = self.gurl(allow_redirects = 'none')
        self.assertEqual(False, gurl.redirect_allowed('http://unsafe.example.com'))
        self.assertEqual(False, gurl.redirect_allowed('https://ssl.example.com'))

    def test_allow_only_https(self):
        gurl = self.gurl(allow_redirects = 'https')
        self.assertEqual(False, gurl.redirect_allowed('http://unsafe.example.com'))
        self.assertEqual(True, gurl.redirect_allowed('https://ssl.example.com'))

    def test_allow_all(self):
        gurl = self.gurl(allow_redirects = 'all')
        self.assertEqual(True, gurl.redirect_allowed('http://unsafe.example.com'))
        self.assertEqual(True, gurl.redirect_allowed('https://ssl.example.com'))

    def test_treat_others_as_none(self):
        for value in ['oink', 1, True, dict()]:
            gurl = self.gurl(allow_redirects = value)
            self.assertEqual(False, gurl.redirect_allowed('http://unsafe.example.com'))
            self.assertEqual(False, gurl.redirect_allowed('https://ssl.example.com'))

def main():
    unittest.main(buffer=True)


if __name__ == '__main__':
    main()
