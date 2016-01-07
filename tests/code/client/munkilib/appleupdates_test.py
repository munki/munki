#!/usr/bin/python
# encoding: utf-8
"""
appleupdates_test.py

Unit tests for appleupdates.

"""
# Copyright 2011 Google.
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

import appleupdates
try:
    import mox
except ImportError:
    import sys
    print >>sys.stderr, "mox module is required. run: easy_install mox"
    raise
from Foundation import NSDate
import os
import unittest
import stubout


class TestAppleUpdates(mox.MoxTestBase):
    """Test AppleUpdates class."""

    def setUp(self):
        mox.MoxTestBase.setUp(self)
        self.stubs = stubout.StubOutForTesting()
        self.au = appleupdates.AppleUpdates()
        self.encoded_cache_dir = appleupdates.urllib2.quote(self.au.cache_dir)

    def tearDown(self):
        self.mox.UnsetStubs()
        self.stubs.UnsetAll()

    def _MockMunkiDisplay(self):
        """Mock out all munkicommon.display_* methods."""
        for display in [
            'percent_done', 'status_major', 'status_minor',
            'info', 'detail', 'debug1', 'debug2', 'warning', 'error']:
            self.mox.StubOutWithMock(
                appleupdates.munkicommon, 'display_%s' % display)

    def _MockMunkiStatus(self):
        """Mock out munkistatus.message/detail/percent methods."""
        for method in ['message', 'detail', 'percent']:
            self.mox.StubOutWithMock(appleupdates.munkistatus, method)

    def _MockFoundationPlist(self):
        """Mock out all FoundationPlist functions."""
        for func_name in [
            'readPlist', 'readPlistFromString', 'writePlist',
            'writePlistToString']:
            self.mox.StubOutWithMock(appleupdates.FoundationPlist, func_name)
            
    def _MockUpdateCheck(self):
        """Mock out all updatecheck functions."""
        for func_name in [
            'getPrimaryManifestCatalogs', 'getItemDetail']:
            self.mox.StubOutWithMock(appleupdates.updatecheck, func_name)

    def testResetMunkiStatusAndDisplayMessageMunkiStatusOutputTrue(self):
        """Tests _ResetMunkiStatusAndDisplayMessage(), GUI is present."""
        self._MockMunkiStatus()
        self._MockMunkiDisplay()
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'log')

        msg = 'foo + bar == foobar'

        appleupdates.munkicommon.munkistatusoutput = True
        appleupdates.munkicommon.display_status_major(msg)

        self.mox.ReplayAll()
        self.au._ResetMunkiStatusAndDisplayMessage(msg)
        self.mox.VerifyAll()

    def testResetMunkiStatusAndDisplayMessageMunkiStatusOutputFalse(self):
        """Tests _ResetMunkiStatusAndDisplayMessage(), GUI not present."""
        self._MockMunkiDisplay()

        msg = 'asdf'

        appleupdates.munkicommon.munkistatusoutput = False
        appleupdates.munkicommon.display_status_major(msg)

        self.mox.ReplayAll()
        self.au._ResetMunkiStatusAndDisplayMessage(msg)
        self.mox.VerifyAll()

    def testGetURLPath(self):
        """Tests _GetURLPath()."""
        path = '/foo/bar/index.html'
        url = 'https://www.example.com' + path
        output_path = self.au._GetURLPath(url)
        self.assertEqual(output_path, path)

        path = '/foo/bar/'
        url = 'https://www.example.com' + path
        output_path = self.au._GetURLPath(url)
        self.assertEqual(output_path, path)

    def testRewriteURL(self):
        """Tests RewriteURL()."""
        self.mox.StubOutWithMock(self.au, '_GetURLPath')
        managed_installs = appleupdates.urllib2.quote(self.au.cache_dir)
        path = '/foo/bar/'
        url = 'https://www.example.com' + path
        self.au._GetURLPath(url).AndReturn(path)
        expected_output_url = 'file://localhost' + self.encoded_cache_dir + path
        self.mox.ReplayAll()
        output_url = self.au.RewriteURL(url)
        self.assertEqual(output_url, expected_output_url)
        self.mox.VerifyAll()

    def testRewriteURLWithFileURL(self):
        """Tests RewriteURL() with a file://localhost/Managed*... URL."""
        url = 'file://localhost' + self.encoded_cache_dir + 'foo/bar'
        self.mox.ReplayAll()
        output_url = self.au.RewriteURL(url)
        self.assertEqual(output_url, url)
        self.mox.VerifyAll()

    def testRewriteProductURLs(self):
        """Test RewriteProductURLs()."""
        self.mox.StubOutWithMock(self.au, 'RewriteURL')

        product = {
            'ServerMetadataURL': 'urlin0',
            'Packages': [
                {
                    'URL': 'urlin1',
                    'MetadataURL': 'urlin2',
                },
            ],
            'Distributions': {'lang': 'urlin3'},
        }

        self.au.RewriteURL('urlin0').AndReturn('urlout0')
        self.au.RewriteURL('urlin2').AndReturn('urlout2')
        self.au.RewriteURL('urlin3').AndReturn('urlout3')

        self.mox.ReplayAll()
        self.au.RewriteProductURLs(product)
        self.assertEqual(product['ServerMetadataURL'], 'urlout0')
        self.assertEqual(product['Packages'][0]['MetadataURL'], 'urlout2')
        self.assertEqual(product['Distributions']['lang'], 'urlout3')
        self.mox.VerifyAll()

    def testRewriteProductURLsWhenNoServerMetadataURL(self):
        """Test RewriteProductURLs() when no ServerMetadataURL in product."""
        self.mox.StubOutWithMock(self.au, 'RewriteURL')

        product = {
            'Packages': [
                {
                    'URL': 'urlin1',
                    'MetadataURL': 'urlin2',
                },
            ],
            'Distributions': {'lang': 'urlin3'},
        }

        self.au.RewriteURL('urlin2').AndReturn('urlout2')
        self.au.RewriteURL('urlin3').AndReturn('urlout3')

        self.mox.ReplayAll()
        self.au.RewriteProductURLs(product)
        self.assertFalse('ServerMetadataURL' in product)
        self.assertEqual(product['Packages'][0]['MetadataURL'], 'urlout2')
        self.assertEqual(product['Distributions']['lang'], 'urlout3')
        self.mox.VerifyAll()

    def testRewriteProductURLsWhenRewritePkgUrls(self):
        """Test RewriteProductURLs() when rewrite_pkg_urls=True."""
        self.mox.StubOutWithMock(self.au, 'RewriteURL')

        product = {
            'ServerMetadataURL': 'urlin0',
            'Packages': [
                {
                    'URL': 'urlin1',
                    'MetadataURL': 'urlin2',
                },
            ],
            'Distributions': {'lang': 'urlin3'},
        }

        self.au.RewriteURL('urlin0').AndReturn('urlout0')
        self.au.RewriteURL('urlin1').AndReturn('urlout1')
        self.au.RewriteURL('urlin2').AndReturn('urlout2')
        self.au.RewriteURL('urlin3').AndReturn('urlout3')

        self.mox.ReplayAll()
        self.au.RewriteProductURLs(product, rewrite_pkg_urls=True)
        self.assertEqual(product['ServerMetadataURL'], 'urlout0')
        self.assertEqual(product['Packages'][0]['URL'], 'urlout1')
        self.assertEqual(product['Packages'][0]['MetadataURL'], 'urlout2')
        self.assertEqual(product['Distributions']['lang'], 'urlout3')
        self.mox.VerifyAll()

    def testRewriteCatalogURLs(self):
        """Test RewriteCatalogURLs()."""
        self.mox.StubOutWithMock(self.au, 'RewriteProductURLs')
        catalog = {
            'Products': {
                'key0': 'data',
            },
        }

        self.au.RewriteProductURLs(
            catalog['Products']['key0'], rewrite_pkg_urls=1).AndReturn(None)

        self.mox.ReplayAll()
        self.au.RewriteCatalogURLs(catalog, rewrite_pkg_urls=1)
        self.mox.VerifyAll()

    def testRewriteCatalogURLsWhenNoProducts(self):
        """Test RewriteCatalogURLs() when no products in catalog."""
        self.mox.StubOutWithMock(self.au, 'RewriteProductURLs')
        catalog = {
            'not Products': {
                'key0': 'data',
            },
        }

        self.mox.ReplayAll()
        self.au.RewriteCatalogURLs(catalog)
        self.mox.VerifyAll()

    def testCacheUpdateMetadata(self):
        """Test CacheUpdateMetadata()."""
        self._MockMunkiDisplay()
        self._MockFoundationPlist()
        self.mox.StubOutWithMock(self.au, 'RetrieveURLToCacheDir')
        self.mox.StubOutWithMock(self.au, 'RewriteCatalogURLs')
        self.mox.StubOutWithMock(appleupdates.os.path, 'exists')
        self.mox.StubOutWithMock(appleupdates.os, 'makedirs')
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'stopRequested')


        catalog = {
            'Products': {
                'key0': {
                    'ServerMetadataURL': 'url0',
                    'Packages': [
                        {'MetadataURL': 'url1'},
                    ],
                    'Distributions': {
                        'lang': 'url2',
                    },
                },
            },
        }

        appleupdates.FoundationPlist.readPlist(
            self.au.filtered_catalog_path).AndReturn(catalog)

        appleupdates.munkicommon.stopRequested().AndReturn(False)
        appleupdates.munkicommon.display_status_minor(
            'Caching metadata for product ID %s', 'key0')
        self.au.RetrieveURLToCacheDir(
            'url0', copy_only_if_missing=True).AndReturn(None)

        appleupdates.munkicommon.stopRequested().AndReturn(False)
        appleupdates.munkicommon.display_status_minor(
            'Caching package metadata for product ID %s', 'key0')
        self.au.RetrieveURLToCacheDir(
            'url1', copy_only_if_missing=True).AndReturn(None)

        appleupdates.munkicommon.stopRequested().AndReturn(False)
        appleupdates.munkicommon.display_status_minor(
            'Caching %s distribution for product ID %s', 'lang',
            'key0').AndReturn(None)
        self.au.RetrieveURLToCacheDir(
            'url2', copy_only_if_missing=True).AndReturn(None)

        appleupdates.munkicommon.stopRequested().AndReturn(False)

        self.au.RewriteCatalogURLs(
            catalog, rewrite_pkg_urls=False).AndReturn(None)
        appleupdates.os.path.exists(
            self.au.local_catalog_dir).AndReturn(False)
        appleupdates.os.makedirs(self.au.local_catalog_dir).AndReturn(None)

        appleupdates.FoundationPlist.writePlist(
            catalog, self.au.local_download_catalog_path)

        self.au.RewriteCatalogURLs(catalog, rewrite_pkg_urls=True).AndReturn(
            None)

        appleupdates.FoundationPlist.writePlist(
            catalog, self.au.local_catalog_path)

        self.mox.ReplayAll()
        self.assertEqual(None, self.au.CacheUpdateMetadata())
        self.mox.VerifyAll()

    def testCacheUpdateMetadataWhenMakedirsError(self):
        """Test CacheUpdateMetadata() when os.makedirs() errors."""
        self._MockMunkiDisplay()
        self._MockFoundationPlist()
        self.mox.StubOutWithMock(self.au, 'RetrieveURLToCacheDir')
        self.mox.StubOutWithMock(appleupdates.os.path, 'exists')
        self.mox.StubOutWithMock(appleupdates.os, 'makedirs')
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'stopRequested')

        catalog = {
            'Products': {
                'key0': {
                    'ServerMetadataURL': 'url0',
                    'Packages': [
                        {'MetadataURL': 'url1'},
                    ],
                    'Distributions': {
                        'lang': 'url2',
                    },
                },
            },
        }

        appleupdates.FoundationPlist.readPlist(
            self.au.filtered_catalog_path).AndReturn(catalog)

        appleupdates.munkicommon.stopRequested().AndReturn(False)
        appleupdates.munkicommon.display_status_minor(
            'Caching metadata for product ID %s', 'key0')
        self.au.RetrieveURLToCacheDir(
            'url0', copy_only_if_missing=True).AndReturn(None)

        appleupdates.munkicommon.stopRequested().AndReturn(False)
        appleupdates.munkicommon.display_status_minor(
            'Caching package metadata for product ID %s', 'key0')
        self.au.RetrieveURLToCacheDir(
            'url1', copy_only_if_missing=True).AndReturn(None)

        appleupdates.munkicommon.stopRequested().AndReturn(False)
        appleupdates.munkicommon.display_status_minor(
            'Caching %s distribution for product ID %s', 'lang',
            'key0').AndReturn(None)
        self.au.RetrieveURLToCacheDir(
            'url2', copy_only_if_missing=True).AndReturn(None)

        appleupdates.munkicommon.stopRequested().AndReturn(False)

        appleupdates.os.path.exists(
            self.au.local_catalog_dir).AndReturn(False)
        appleupdates.os.makedirs(self.au.local_catalog_dir).AndRaise(OSError)

        self.mox.ReplayAll()
        self.assertRaises(
                appleupdates.ReplicationError, self.au.CacheUpdateMetadata)
        self.mox.VerifyAll()

    def testCacheUpdateMetadataWhenNoProducts(self):
        """Test CacheUpdateMetadata() when no products in catalog."""
        self._MockMunkiDisplay()
        self._MockFoundationPlist()

        catalog = {}
        
        appleupdates.munkicommon.display_warning(
            '"Products" not found in %s', self.au.filtered_catalog_path)

        appleupdates.FoundationPlist.readPlist(
            self.au.filtered_catalog_path).AndReturn(catalog)

        self.mox.ReplayAll()
        self.assertEqual(None, self.au.CacheUpdateMetadata())
        self.mox.VerifyAll()

    def testRetrieveURLToCacheDir(self):
        """Tests RetrieveURLToCacheDir()."""
        self.mox.StubOutWithMock(self.au, '_GetURLPath')
        self.mox.StubOutWithMock(appleupdates.os, 'makedirs')
        self.mox.StubOutWithMock(appleupdates.os.path, 'exists')
        self.mox.StubOutWithMock(self.au, 'GetSoftwareUpdateResource')

        path = '/foo/bar'
        url = 'https://www.example.com' + path
        local_file_path = os.path.join(self.au.cache_dir, path.lstrip('/'))
        local_dir_path = os.path.dirname(local_file_path)

        self.au._GetURLPath(url).AndReturn(path)

        appleupdates.os.path.exists(local_dir_path).AndReturn(False)
        appleupdates.os.makedirs(local_dir_path).AndReturn(None)
        self.au.GetSoftwareUpdateResource(
            url, local_file_path, resume=True).AndReturn(None)

        self.mox.ReplayAll()
        output = self.au.RetrieveURLToCacheDir(url)
        self.assertEqual(output, local_file_path)
        self.mox.VerifyAll()

    def testRetrieveURLToCacheDirWithMunkiDownloadError(self):
        """Tests RetrieveURLToCacheDir() with MunkiDownloadError."""
        self.mox.StubOutWithMock(self.au, '_GetURLPath')
        self.mox.StubOutWithMock(appleupdates.os, 'makedirs')
        self.mox.StubOutWithMock(appleupdates.os.path, 'exists')
        self.mox.StubOutWithMock(self.au, 'GetSoftwareUpdateResource')

        path = '/foo/bar'
        url = 'https://www.example.com' + path
        local_file_path = os.path.join(self.au.cache_dir, path.lstrip('/'))
        local_dir_path = os.path.dirname(local_file_path)

        self.au._GetURLPath(url).AndReturn(path)

        appleupdates.os.path.exists(local_dir_path).AndReturn(False)
        appleupdates.os.makedirs(local_dir_path).AndReturn(None)
        self.au.GetSoftwareUpdateResource(
            url, local_file_path, resume=True).AndRaise(
                appleupdates.fetch.MunkiDownloadError)

        self.mox.ReplayAll()
        self.assertRaises(
            appleupdates.Error, self.au.RetrieveURLToCacheDir, url)
        self.mox.VerifyAll()

    def testRetrieveURLToCacheDirMakedirsError(self):
        """Tests RetrieveURLToCacheDir() with os.makedirs() error."""
        self.mox.StubOutWithMock(self.au, '_GetURLPath')
        self.mox.StubOutWithMock(appleupdates.os, 'makedirs')
        self.mox.StubOutWithMock(appleupdates.os.path, 'exists')

        path = '/foo/bar'
        url = 'https://www.example.com' + path
        local_file_path = os.path.join(self.au.cache_dir, path.lstrip('/'))
        local_dir_path = os.path.dirname(local_file_path)

        self.au._GetURLPath(url).AndReturn(path)

        appleupdates.os.path.exists(local_dir_path).AndReturn(False)
        appleupdates.os.makedirs(local_dir_path).AndRaise(OSError)

        self.mox.ReplayAll()
        self.assertRaises(
            appleupdates.Error, self.au.RetrieveURLToCacheDir, url)
        self.mox.VerifyAll()

    def testRetrieveURLToCacheDirCopyOnlyIfMissing(self):
        """Tests RetrieveURLToCacheDir() with copy_only_if_missing=True."""
        self.mox.StubOutWithMock(self.au, '_GetURLPath')
        self.mox.StubOutWithMock(appleupdates.os.path, 'exists')

        path = '/foo/bar'
        url = 'https://www.example.com' + path
        local_file_path = os.path.join(self.au.cache_dir, path.lstrip('/'))

        self.au._GetURLPath(url).AndReturn(path)

        appleupdates.os.path.exists(local_file_path).AndReturn(True)

        self.mox.ReplayAll()
        output = self.au.RetrieveURLToCacheDir(url, copy_only_if_missing=True)
        self.assertEqual(output, local_file_path)
        self.mox.VerifyAll()

    def testWriteFilteredCatalog(self):
        """Tests _WriteFilteredCatalog()."""
        self._MockFoundationPlist()

        catalog_path = 'foo/catalog.sucatalog'
        product_ids = ['1', '3']
        catalog = {'Products': {'1': 'foo', '2': 'bar', '3': None}}
        # output catalog will be missing 2, since it's not in product_ids
        output_catalog = {'Products': {'1': 'foo', '3': None}}

        appleupdates.FoundationPlist.readPlist(
            self.au.extracted_catalog_path).AndReturn(catalog)
        appleupdates.FoundationPlist.writePlist(
            output_catalog, catalog_path).AndReturn(None)

        self.mox.ReplayAll()
        self.au._WriteFilteredCatalog(product_ids, catalog_path)
        self.mox.VerifyAll()

    def testIsRestartNeededFalse(self):
        """Tests IsRestartNeeded() when restart is not needed."""
        self._MockFoundationPlist()

        apple_updates = {
            'AppleUpdates': [
                {'RestartAction': 'None'},
                {'RestartAction': 'Nope'},
            ]
        }
        appleupdates.FoundationPlist.readPlist(
            self.au.apple_updates_plist).AndReturn(apple_updates)
        self.mox.ReplayAll()
        self.assertFalse(self.au.IsRestartNeeded())
        self.mox.VerifyAll()

    def testIsRestartNeededTrue(self):
        """Tests IsRestartNeeded() when restart is needed."""
        self._MockFoundationPlist()

        apple_updates = {
            'AppleUpdates': [
                {'RestartAction': 'None'},
                {'RestartAction': self.au.RESTART_ACTIONS[0]},
            ]
        }
        appleupdates.FoundationPlist.readPlist(
            self.au.apple_updates_plist).AndReturn(apple_updates)
        self.mox.ReplayAll()
        self.assertTrue(self.au.IsRestartNeeded())
        self.mox.VerifyAll()

    def testIsRestartNeededFoundationPlistError(self):
        """Tests IsRestartNeeded() when FoundationPlist has a read error."""
        self._MockFoundationPlist()

        exc = appleupdates.FoundationPlist.NSPropertyListSerializationException
        appleupdates.FoundationPlist.readPlist(
            self.au.apple_updates_plist).AndRaise(exc)

        self.mox.ReplayAll()
        self.assertTrue(self.au.IsRestartNeeded())
        self.mox.VerifyAll()

    def testClearAppleUpdateInfo(self):
        """Tests ClearAppleUpdateInfo()."""
        self.mox.StubOutWithMock(appleupdates.os, 'unlink')

        appleupdates.os.unlink(self.au.apple_updates_plist).AndReturn(None)
        appleupdates.os.unlink(self.au.applicable_updates_plist).AndReturn(None)
        appleupdates.os.unlink(self.au.apple_updates_plist).AndReturn(None)
        appleupdates.os.unlink(
            self.au.applicable_updates_plist).AndRaise(OSError)
        appleupdates.os.unlink(self.au.apple_updates_plist).AndReturn(None)
        appleupdates.os.unlink(
            self.au.applicable_updates_plist).AndRaise(IOError)
        appleupdates.os.unlink(self.au.apple_updates_plist).AndRaise(OSError)
        appleupdates.os.unlink(self.au.apple_updates_plist).AndRaise(IOError)

        self.mox.ReplayAll()
        self.au.ClearAppleUpdateInfo()
        self.au.ClearAppleUpdateInfo()
        self.au.ClearAppleUpdateInfo()
        self.au.ClearAppleUpdateInfo()
        self.au.ClearAppleUpdateInfo()
        self.mox.VerifyAll()

    def testDownloadAvailableUpdates(self):
        """Tests DownloadAvailableUpdates()."""
        self._MockMunkiDisplay()
        self.mox.StubOutWithMock(self.au, '_ResetMunkiStatusAndDisplayMessage')
        self.mox.StubOutWithMock(self.au, '_RunSoftwareUpdate')
        self.mox.StubOutWithMock(appleupdates.os.path, 'exists')
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'getOsVersion')
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'stopRequested')

        msg = 'Downloading available Apple Software Updates...'
        catalog_url = 'file://localhost' + appleupdates.urllib2.quote(
            self.au.local_download_catalog_path)

        self.au._ResetMunkiStatusAndDisplayMessage(msg).AndReturn(None)

        appleupdates.os.path.exists(
            self.au.local_download_catalog_path).AndReturn(True)
        appleupdates.munkicommon.getOsVersion(as_tuple=True).AndReturn((10, 7))
        self.au._RunSoftwareUpdate(
            ['-d', '-a'],
            catalog_url=catalog_url,
            stop_allowed=True).AndReturn(0)
        appleupdates.munkicommon.stopRequested().AndReturn(False)

        self.mox.ReplayAll()
        self.assertTrue(self.au.DownloadAvailableUpdates())
        self.mox.VerifyAll()

    def testDownloadAvailableUpdatesLeopard(self):
        """Tests DownloadAvailableUpdates() with Leopard."""
        self._MockMunkiDisplay()
        self.mox.StubOutWithMock(self.au, '_ResetMunkiStatusAndDisplayMessage')
        self.mox.StubOutWithMock(self.au, '_LeopardDownloadAvailableUpdates')
        self.mox.StubOutWithMock(appleupdates.os.path, 'exists')
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'getOsVersion')

        catalog_url = 'file://localhost' + appleupdates.urllib2.quote(
            self.au.local_download_catalog_path)

        msg = 'Downloading available Apple Software Updates...'
        self.au._ResetMunkiStatusAndDisplayMessage(msg).AndReturn(None)
        appleupdates.os.path.exists(
            self.au.local_download_catalog_path).AndReturn(True)
        appleupdates.munkicommon.getOsVersion(as_tuple=True).AndReturn((10,5))
        self.au._LeopardDownloadAvailableUpdates(catalog_url).AndReturn(2)
        appleupdates.munkicommon.display_error('softwareupdate error: %s' % 2)

        self.mox.ReplayAll()
        self.assertFalse(self.au.DownloadAvailableUpdates())
        self.mox.VerifyAll()

    def testDownloadAvailableUpdatesMissingCatalog(self):
        """Tests DownloadAvailableUpdates() with a missing catalog."""
        self._MockMunkiDisplay()
        self.mox.StubOutWithMock(self.au, '_ResetMunkiStatusAndDisplayMessage')
        self.mox.StubOutWithMock(appleupdates.os.path, 'exists')

        msg = 'Downloading available Apple Software Updates...'
        self.au._ResetMunkiStatusAndDisplayMessage(msg).AndReturn(None)

        appleupdates.os.path.exists(
            self.au.local_download_catalog_path).AndReturn(False)
        appleupdates.munkicommon.display_error(
            'Missing local Software Update catalog at %s',
            self.au.local_download_catalog_path)

        self.mox.ReplayAll()
        self.assertFalse(self.au.DownloadAvailableUpdates())
        self.mox.VerifyAll()

    def testGetAvailableUpdateProductIDsFailedSoftwareUpdate(self):
        """Tests GetAvailableUpdateProductIDs() with failed softwareupdate."""
        self._MockMunkiDisplay()
        self.mox.StubOutWithMock(self.au, '_RunSoftwareUpdate')
        self.mox.StubOutWithMock(self.au, '_ResetMunkiStatusAndDisplayMessage')
        self.mox.StubOutWithMock(appleupdates.os, 'unlink')
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'getOsVersion')
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'stopRequested')

        msg = 'Checking for available Apple Software Updates...'
        self.au._ResetMunkiStatusAndDisplayMessage(msg)
        appleupdates.os.unlink(self.au.applicable_updates_plist).AndRaise(
            OSError)

        appleupdates.munkicommon.getOsVersion(as_tuple=True).AndReturn((10, 6))
        catalog_url = 'file://localhost' + appleupdates.urllib2.quote(
            self.au.extracted_catalog_path)
        self.au._RunSoftwareUpdate(
            ['-l', '-f', self.au.applicable_updates_plist],
            catalog_url=catalog_url, 
            stop_allowed=True).AndReturn(1)

        appleupdates.munkicommon.display_error('softwareupdate error: %s' % 1)
        appleupdates.munkicommon.stopRequested().AndReturn(False)

        self.mox.ReplayAll()
        output = self.au.GetAvailableUpdateProductIDs()
        self.assertEqual(output, [])
        self.mox.VerifyAll()

    def testGetAvailableUpdateProductIDsFailureReadingApplicableUpdates(self):
        """Tests GetAvailableUpdateProductIDs() failed applicable updates."""
        self._MockFoundationPlist()
        self.mox.StubOutWithMock(self.au, '_RunSoftwareUpdate')
        self.mox.StubOutWithMock(self.au, '_ResetMunkiStatusAndDisplayMessage')
        self.mox.StubOutWithMock(appleupdates.os, 'unlink')
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'getOsVersion')

        msg = 'Checking for available Apple Software Updates...'
        self.au._ResetMunkiStatusAndDisplayMessage(msg)
        appleupdates.os.unlink(self.au.applicable_updates_plist).AndRaise(
            OSError)

        appleupdates.munkicommon.getOsVersion(as_tuple=True).AndReturn((10, 6))
        catalog_url = 'file://localhost' + appleupdates.urllib2.quote(
            self.au.extracted_catalog_path)
        self.au._RunSoftwareUpdate(
            ['-l', '-f', self.au.applicable_updates_plist],
            catalog_url=catalog_url, 
            stop_allowed=True).AndReturn(0)

        exc = appleupdates.FoundationPlist.NSPropertyListSerializationException
        appleupdates.FoundationPlist.readPlist(
            self.au.applicable_updates_plist).AndRaise(exc)

        self.mox.ReplayAll()
        output = self.au.GetAvailableUpdateProductIDs()
        self.assertEqual(output, [])
        self.mox.VerifyAll()

    def testGetAvailableUpdateProductIDsEmptyApplicableUpdates(self):
        """Tests GetAvailableUpdateProductIDs() empty applicable updates."""
        self._MockFoundationPlist()
        self.mox.StubOutWithMock(self.au, '_RunSoftwareUpdate')
        self.mox.StubOutWithMock(self.au, '_ResetMunkiStatusAndDisplayMessage')
        self.mox.StubOutWithMock(appleupdates.os, 'unlink')
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'getOsVersion')

        msg = 'Checking for available Apple Software Updates...'
        self.au._ResetMunkiStatusAndDisplayMessage(msg)
        appleupdates.os.unlink(self.au.applicable_updates_plist).AndRaise(
            OSError)

        appleupdates.munkicommon.getOsVersion(as_tuple=True).AndReturn((10, 6))
        catalog_url = 'file://localhost' + appleupdates.urllib2.quote(
            self.au.extracted_catalog_path)
        self.au._RunSoftwareUpdate(
            ['-l', '-f', self.au.applicable_updates_plist],
            catalog_url=catalog_url, 
            stop_allowed=True).AndReturn(0)

        appleupdates.FoundationPlist.readPlist(
            self.au.applicable_updates_plist).AndReturn({})

        self.mox.ReplayAll()
        output = self.au.GetAvailableUpdateProductIDs()
        self.assertEqual(output, [])
        self.mox.VerifyAll()

    def testGetAvailableUpdateProductIDsSuccess(self):
        """Tests GetAvailableUpdateProductIDs()."""
        self._MockFoundationPlist()
        self.mox.StubOutWithMock(self.au, '_RunSoftwareUpdate')
        self.mox.StubOutWithMock(self.au, '_ResetMunkiStatusAndDisplayMessage')
        self.mox.StubOutWithMock(appleupdates.os, 'unlink')
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'getOsVersion')

        updates_plist_dict = {
            'phaseResultsArray': [
                {'productKey': '4zzz'},
                {'noProductKeyHere': True},
                {'productKey': 'zzz5'},
            ]
        }

        msg = 'Checking for available Apple Software Updates...'
        self.au._ResetMunkiStatusAndDisplayMessage(msg)
        appleupdates.os.unlink(self.au.applicable_updates_plist).AndRaise(
            OSError)

        appleupdates.munkicommon.getOsVersion(as_tuple=True).AndReturn((10, 6))
        catalog_url = 'file://localhost' + appleupdates.urllib2.quote(
            self.au.extracted_catalog_path)
        self.au._RunSoftwareUpdate(
            ['-l', '-f', self.au.applicable_updates_plist],
             catalog_url=catalog_url,
             stop_allowed=True).AndReturn(0)

        appleupdates.FoundationPlist.readPlist(
            self.au.applicable_updates_plist).AndReturn(updates_plist_dict)

        self.mox.ReplayAll()
        output = self.au.GetAvailableUpdateProductIDs()
        self.assertEqual(len(output), 2)
        self.assertTrue('4zzz' in output)
        self.assertTrue('zzz5' in output)
        self.mox.VerifyAll()

    def testExtractAndCopyDownloadedCatalogMakedirsError(self):
        """Tests ExtractAndCopyDownloadedCatalog() with os.makedirs error."""
        self.mox.StubOutWithMock(appleupdates.os, 'makedirs')
        self.mox.StubOutWithMock(appleupdates.os.path, 'exists')

        appleupdates.os.path.exists(self.au.local_catalog_dir).AndReturn(False)
        appleupdates.os.makedirs(self.au.local_catalog_dir).AndRaise(
            OSError)

        self.mox.ReplayAll()
        self.assertRaises(
            appleupdates.ReplicationError,
            self.au.ExtractAndCopyDownloadedCatalog)
        self.mox.VerifyAll()

    def testExtractAndCopyDownloadedCatalogPlaintextCatalog(self):
        """Tests ExtractAndCopyDownloadedCatalog() with plain-text catalog."""
        self.mox.StubOutWithMock(appleupdates.os.path, 'exists')

        appleupdates.os.path.exists(self.au.local_catalog_dir).AndReturn(True)
        local_apple_sus_catalog = appleupdates.os.path.join(
            self.au.local_catalog_dir,
            appleupdates.APPLE_EXTRACTED_CATALOG_NAME)

        contents = 'non-gzipped text'
        mock_open = self.mox.CreateMockAnything()
        mock_file = self.mox.CreateMockAnything()
        mock_open(self.au.apple_download_catalog_path, 'rb').AndReturn(
            mock_file)
        mock_file.read(2).AndReturn(contents)
        mock_file.seek(0).AndReturn(None)
        mock_file.read().AndReturn(contents)
        mock_file.close().AndReturn(None)
        mock_open(local_apple_sus_catalog, 'wb').AndReturn(mock_file)
        mock_file.write(contents)
        mock_file.close()

        self.mox.ReplayAll()
        self.au.ExtractAndCopyDownloadedCatalog(_open=mock_open)
        self.mox.VerifyAll()

    def testExtractAndCopyDownloadedCatalogGzippedCatalog(self):
        """Tests ExtractAndCopyDownloadedCatalog() with gzipped catalog."""
        self.mox.StubOutWithMock(appleupdates.os.path, 'exists')
        self.mox.StubOutWithMock(appleupdates.gzip, 'open')

        appleupdates.os.path.exists(self.au.local_catalog_dir).AndReturn(True)
        local_apple_sus_catalog = appleupdates.os.path.join(
            self.au.local_catalog_dir,
            appleupdates.APPLE_EXTRACTED_CATALOG_NAME)

        contents = 'gzipped text'
        mock_open = self.mox.CreateMockAnything()
        mock_file = self.mox.CreateMockAnything()
        mock_open(self.au.apple_download_catalog_path, 'rb').AndReturn(
            mock_file)
        mock_file.read(2).AndReturn('\x1f\x8b')
        mock_file.close().AndReturn(None)
        appleupdates.gzip.open(
            self.au.apple_download_catalog_path, 'rb').AndReturn(mock_file)
        mock_file.read().AndReturn(contents)
        mock_file.close()
        mock_open(local_apple_sus_catalog, 'wb').AndReturn(mock_file)
        mock_file.write(contents)
        mock_file.close()

        self.mox.ReplayAll()
        self.au.ExtractAndCopyDownloadedCatalog(_open=mock_open)
        self.mox.VerifyAll()

    def testGetAppleCatalogURLMunki(self):
        """Tests _GetAppleCatalogURL() with Munki's pref."""
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'pref')

        appleupdates.munkicommon.pref('SoftwareUpdateServerURL').AndReturn(
            'url')

        self.mox.ReplayAll()
        self.assertEqual('url', self.au._GetAppleCatalogURL())
        self.mox.VerifyAll()

    def testGetAppleCatalogURLSoftwareUpdateOrMCX(self):
        """Tests _GetAppleCatalogURL() with SoftwareUpdate.plist or MCX pref."""
        self.mox.StubOutWithMock(self.au, 'GetSoftwareUpdatePref')
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'pref')

        appleupdates.munkicommon.pref('SoftwareUpdateServerURL').AndReturn(None)
        self.au.GetSoftwareUpdatePref('CatalogURL').AndReturn('url')

        self.mox.ReplayAll()
        self.assertEqual('url', self.au._GetAppleCatalogURL())
        self.mox.VerifyAll()

    def testGetAppleCatalogURLDefault(self):
        """Tests _GetAppleCatalogURL() with default URL."""
        self.mox.StubOutWithMock(self.au, 'GetSoftwareUpdatePref')
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'pref')
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'getOsVersion')

        # Grab the first os_version/url combo to use for this test.
        os_version = appleupdates.DEFAULT_CATALOG_URLS.keys()[0]
        url = appleupdates.DEFAULT_CATALOG_URLS[os_version]

        appleupdates.munkicommon.pref('SoftwareUpdateServerURL').AndReturn(None)
        self.au.GetSoftwareUpdatePref('CatalogURL').AndReturn(None)
        appleupdates.munkicommon.getOsVersion().AndReturn(os_version)

        self.mox.ReplayAll()
        self.assertEqual(url, self.au._GetAppleCatalogURL())
        self.mox.VerifyAll()

    def testGetAppleCatalogURLNotFound(self):
        """Tests _GetAppleCatalogURL() when the catalog URL is not found."""
        self.mox.StubOutWithMock(self.au, 'GetSoftwareUpdatePref')
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'pref')
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'getOsVersion')

        appleupdates.munkicommon.pref('SoftwareUpdateServerURL').AndReturn(None)
        self.au.GetSoftwareUpdatePref('CatalogURL').AndReturn(None)
        appleupdates.munkicommon.getOsVersion().AndReturn('UKNOWN OS VERSION!')

        self.mox.ReplayAll()
        self.assertRaises(
            appleupdates.CatalogNotFoundError, self.au._GetAppleCatalogURL)
        self.mox.VerifyAll()

    def testCacheAppleCatalog(self):
        """Tests CacheAppleCatalog()."""
        self._MockMunkiDisplay()
        self.mox.StubOutWithMock(self.au, '_GetAppleCatalogURL')
        self.mox.StubOutWithMock(self.au, 'ExtractAndCopyDownloadedCatalog')
        self.mox.StubOutWithMock(appleupdates.os, 'makedirs')
        self.mox.StubOutWithMock(appleupdates.os.path, 'exists')
        self.mox.StubOutWithMock(self.au, 'GetSoftwareUpdateResource')

        url = 'url'
        self.au._GetAppleCatalogURL().AndReturn(url)
        appleupdates.os.path.exists(self.au.temp_cache_dir).AndReturn(False)
        appleupdates.os.makedirs(self.au.temp_cache_dir).AndReturn(None)

        appleupdates.munkicommon.display_status_major(
            'Checking Apple Software Update catalog...')
        appleupdates.munkicommon.display_detail(
            'Caching CatalogURL %s', url)
        self.au.GetSoftwareUpdateResource(
            url, self.au.apple_download_catalog_path, resume=True).AndReturn(
                0)
        self.au.ExtractAndCopyDownloadedCatalog().AndReturn(None)

        self.mox.ReplayAll()
        self.au.CacheAppleCatalog()
        self.mox.VerifyAll()

    def testCacheAppleCatalogWithBadCatalogURL(self):
        """Tests CacheAppleCatalog() with a bad catalog URL."""
        self._MockMunkiDisplay()
        self.mox.StubOutWithMock(self.au, '_GetAppleCatalogURL')

        exc = appleupdates.CatalogNotFoundError('foo error')
        self.au._GetAppleCatalogURL().AndRaise(exc)
        appleupdates.munkicommon.display_error('foo error')

        self.mox.ReplayAll()
        self.assertRaises(
            appleupdates.CatalogNotFoundError, self.au.CacheAppleCatalog)
        self.mox.VerifyAll()

    def testCacheAppleCatalogMakedirsError(self):
        """Tests CacheAppleCatalog() with os.makedirs error."""
        self._MockMunkiDisplay()
        self.mox.StubOutWithMock(self.au, '_GetAppleCatalogURL')
        self.mox.StubOutWithMock(appleupdates.os, 'makedirs')
        self.mox.StubOutWithMock(appleupdates.os.path, 'exists')

        self.au._GetAppleCatalogURL().AndReturn('url')
        appleupdates.os.path.exists(self.au.temp_cache_dir).AndReturn(False)
        appleupdates.os.makedirs(self.au.temp_cache_dir).AndRaise(OSError)

        self.mox.ReplayAll()
        self.assertRaises(
            appleupdates.ReplicationError, self.au.CacheAppleCatalog)
        self.mox.VerifyAll()

    def testCacheAppleCatalogMunkiDownloadError(self):
        """Tests CacheAppleCatalog() with a MunkiDownloadError."""
        self._MockMunkiDisplay()
        self.mox.StubOutWithMock(self.au, '_GetAppleCatalogURL')
        self.mox.StubOutWithMock(self.au, 'ExtractAndCopyDownloadedCatalog')
        self.mox.StubOutWithMock(appleupdates.os, 'makedirs')
        self.mox.StubOutWithMock(appleupdates.os.path, 'exists')
        self.mox.StubOutWithMock(self.au, 'GetSoftwareUpdateResource')

        url = 'url'
        self.au._GetAppleCatalogURL().AndReturn(url)
        appleupdates.os.path.exists(self.au.temp_cache_dir).AndReturn(False)
        appleupdates.os.makedirs(self.au.temp_cache_dir).AndReturn(None)

        appleupdates.munkicommon.display_status_major(
            'Checking Apple Software Update catalog...')
        appleupdates.munkicommon.display_detail(
            'Caching CatalogURL %s', url)
        self.au.GetSoftwareUpdateResource(
            url, self.au.apple_download_catalog_path, resume=True).AndRaise(
                appleupdates.fetch.MunkiDownloadError)

        self.mox.ReplayAll()
        self.assertRaises(
            appleupdates.fetch.MunkiDownloadError,
            self.au.CacheAppleCatalog)
        self.mox.VerifyAll()

    def _InstalledApplePackagesHaveChangedHelper(
        self, old_checksum, new_checksum):
        """Helper method for InstalledApplePackagesHaveChanged() testing."""
        self.mox.StubOutWithMock(appleupdates.subprocess, 'Popen')
        self.mox.StubOutWithMock(appleupdates.hashlib, 'sha256')
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'pref')

        cmd = ['/usr/sbin/pkgutil', '--regexp', '--pkg-info-plist',
               'com\.apple\.*']
        output = 'output!'

        mock_proc = self.mox.CreateMockAnything()
        appleupdates.subprocess.Popen(
            cmd, shell=False, bufsize=1,
            stdin=appleupdates.subprocess.PIPE,
            stdout=appleupdates.subprocess.PIPE,
            stderr=appleupdates.subprocess.PIPE).AndReturn(mock_proc)
        mock_proc.communicate().AndReturn((output, 'unused foo'))
        mock_hash = self.mox.CreateMockAnything()
        appleupdates.hashlib.sha256(output).AndReturn(mock_hash)
        mock_hash.hexdigest().AndReturn(new_checksum)
        appleupdates.munkicommon.pref(
            'InstalledApplePackagesChecksum').AndReturn(old_checksum)
        if old_checksum != new_checksum:
            self.mox.StubOutWithMock(appleupdates.munkicommon, 'set_pref')
            appleupdates.munkicommon.set_pref(
                'InstalledApplePackagesChecksum', new_checksum)

        self.mox.ReplayAll()
        if old_checksum == new_checksum:
          self.assertFalse(self.au.InstalledApplePackagesHaveChanged())
        else:
          self.assertTrue(self.au.InstalledApplePackagesHaveChanged())
        self.mox.VerifyAll()

    def testInstalledApplePackagesHaveChangedWhenNoChange(self):
        """Tests InstalledApplePackagesHaveChanged() when haven't changed."""
        self._InstalledApplePackagesHaveChangedHelper('zzzz', 'zzzz')

    def testInstalledApplePackagesHaveChangedWhenChanged(self):
        """Tests InstalledApplePackagesHaveChanged() when they have changed."""
        self._InstalledApplePackagesHaveChangedHelper('asdf', 'zzzz')

    def testAvailableUpdatesAreDownloadedNoUpdateInfo(self):
        """Tests AvailableUpdatesAreDownloaded() when update info is empty."""
        self.mox.StubOutWithMock(self.au, 'GetSoftwareUpdateInfo')
        self.au.GetSoftwareUpdateInfo().AndReturn(None)

        self.mox.ReplayAll()
        self.assertTrue(self.au.AvailableUpdatesAreDownloaded())
        self.mox.VerifyAll()

    def testIsForceCheckNeccessaryWithChangedHash(self):
        """Tests _IsForceCheckNeccessary() when the hash has changed."""
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'getsha256hash')
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'log')

        appleupdates.munkicommon.getsha256hash(
            self.au.apple_download_catalog_path).AndReturn('omg changed hash')
        appleupdates.munkicommon.log('Apple update catalog has changed.')

        self.mox.ReplayAll()
        self.assertTrue(self.au._IsForceCheckNeccessary('outdated hash'))
        self.mox.VerifyAll()

    def testIsForceCheckNeccessaryWhenInstalledPackagesHaveChanged(self):
        """Tests _IsForceCheckNeccessary() when installed pkgs have changed."""
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'getsha256hash')
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'log')
        self.mox.StubOutWithMock(self.au, 'InstalledApplePackagesHaveChanged')

        appleupdates.munkicommon.getsha256hash(
            self.au.apple_download_catalog_path).AndReturn('hash')
        self.au.InstalledApplePackagesHaveChanged().AndReturn(True)
        appleupdates.munkicommon.log('Installed Apple packages have changed.')

        self.mox.ReplayAll()
        self.assertTrue(self.au._IsForceCheckNeccessary('hash'))
        self.mox.VerifyAll()

    def testIsForceCheckNeccessaryWhenAvailableUpdatesAreNotDownloaded(self):
        """Tests _IsForceCheckNeccessary(); new updates aren't downloaded."""
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'getsha256hash')
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'log')
        self.mox.StubOutWithMock(self.au, 'InstalledApplePackagesHaveChanged')
        self.mox.StubOutWithMock(self.au, 'AvailableUpdatesAreDownloaded')

        appleupdates.munkicommon.getsha256hash(
            self.au.apple_download_catalog_path).AndReturn('hash')
        self.au.InstalledApplePackagesHaveChanged().AndReturn(False)
        self.au.AvailableUpdatesAreDownloaded().AndReturn(False)
        appleupdates.munkicommon.log(
            'Downloaded updates do not match our list of available updates.')

        self.mox.ReplayAll()
        self.assertTrue(self.au._IsForceCheckNeccessary('hash'))
        self.mox.VerifyAll()

    def testIsForceCheckNeccessaryWhenForceIsNotNeeded(self):
        """Tests _IsForceCheckNeccessary() when force is not needed."""
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'getsha256hash')
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'log')
        self.mox.StubOutWithMock(self.au, 'InstalledApplePackagesHaveChanged')
        self.mox.StubOutWithMock(self.au, 'AvailableUpdatesAreDownloaded')

        appleupdates.munkicommon.getsha256hash(
            self.au.apple_download_catalog_path).AndReturn('hash')
        self.au.InstalledApplePackagesHaveChanged().AndReturn(False)
        self.au.AvailableUpdatesAreDownloaded().AndReturn(True)

        self.mox.ReplayAll()
        self.assertFalse(self.au._IsForceCheckNeccessary('hash'))
        self.mox.VerifyAll()

    def _CheckForSoftwareUpdatesCacheAppleCatalogExceptionHelper(
        self, exc, s=''):
        """Helper method for CheckForSoftwareUpdates() exception handling."""
        self._MockMunkiDisplay()
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'getsha256hash')
        self.mox.StubOutWithMock(self.au, 'CacheAppleCatalog')

        appleupdates.munkicommon.getsha256hash(
            self.au.apple_download_catalog_path).AndReturn(None)
        self.au.CacheAppleCatalog().AndRaise(exc(s))
        if exc == appleupdates.ReplicationError or \
           exc == appleupdates.fetch.MunkiDownloadError:
            appleupdates.munkicommon.display_warning(
                'Could not download Apple SUS catalog:')
            appleupdates.munkicommon.display_warning('\t%s', s)

        self.mox.ReplayAll()
        self.assertFalse(self.au.CheckForSoftwareUpdates())
        self.mox.VerifyAll()

    def testCheckForSoftwareUpdatesCatalogNotFound(self):
        """Tests CheckForSoftwareUpdates() with CatalogNotFoundError."""
        self._CheckForSoftwareUpdatesCacheAppleCatalogExceptionHelper(
            appleupdates.CatalogNotFoundError)

    def testCheckForSoftwareUpdatesReplicationError(self):
        """Tests CheckForSoftwareUpdates() with ReplicationError."""
        self._CheckForSoftwareUpdatesCacheAppleCatalogExceptionHelper(
            appleupdates.ReplicationError, s='foo error')

    def testCheckForSoftwareUpdatesMunkiDownloadError(self):
        """Tests CheckForSoftwareUpdates() with MunkiDownloadError."""
        self._CheckForSoftwareUpdatesCacheAppleCatalogExceptionHelper(
            appleupdates.fetch.MunkiDownloadError)

    def testCheckForSoftwareUpdatesWhenForceCheckNotNeeded(self):
        """Tests CheckForSoftwareUpdates() when a force check is not needed."""
        self._MockMunkiDisplay()
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'getsha256hash')
        self.mox.StubOutWithMock(self.au, 'CacheAppleCatalog')
        self.mox.StubOutWithMock(self.au, '_IsForceCheckNeccessary')
        self.mox.StubOutWithMock(self.au, 'GetSoftwareUpdateInfo')

        appleupdates.munkicommon.getsha256hash(
            self.au.apple_download_catalog_path).AndReturn('hash')
        self.au.CacheAppleCatalog().AndReturn(None)
        self.au._IsForceCheckNeccessary('hash').AndReturn(False)
        appleupdates.munkicommon.display_info(
            'Skipping Apple Software Update check because sucatalog is '
            'unchanged, installed Apple packages are unchanged and we '
            'recently did a full check.')
        # mock out GetSoftwareUpdateInfo() because its return value
        # depends on whether or not we have cached updates
        # this implies we might need some tests that deal with
        # cached updates...
        self.au.GetSoftwareUpdateInfo().AndReturn(False)

        self.mox.ReplayAll()
        self.assertFalse(self.au.CheckForSoftwareUpdates(force_check=False))
        self.mox.VerifyAll()

    def testCheckForSoftwareUpdatesWhenUpdateListEmpty(self):
        """Tests CheckForSoftwareUpdates() when updatelist is empty."""
        self.mox.StubOutWithMock(self.au, 'CacheAppleCatalog')
        self.mox.StubOutWithMock(self.au, 'GetAvailableUpdateProductIDs')
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'getsha256hash')
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'set_pref')
        # Cannot stub out the builtin date() method, so stub the entire module.
        mock_nsdate_module = self.mox.CreateMockAnything()
        self.mox.StubOutWithMock(appleupdates, 'NSDate', mock_nsdate_module)
        mock_nsdate_module.date = self.mox.CreateMockAnything()

        appleupdates.munkicommon.getsha256hash(
            self.au.apple_download_catalog_path).AndReturn('hash')
        self.au.CacheAppleCatalog().AndReturn(None)
        self.au.GetAvailableUpdateProductIDs().AndReturn([])
        appleupdates.NSDate.date().AndReturn('d')
        appleupdates.munkicommon.set_pref('LastAppleSoftwareUpdateCheck', 'd')

        self.mox.ReplayAll()
        self.assertFalse(self.au.CheckForSoftwareUpdates())
        self.mox.VerifyAll()

    def testCheckForSoftwareUpdatesWhenCacheUpdateMetadataError(self):
        """Tests CheckForSoftwareUpdates() when CacheUpdateMetadata() fails."""
        self._MockMunkiDisplay()
        self.mox.StubOutWithMock(self.au, 'CacheAppleCatalog')
        self.mox.StubOutWithMock(self.au, 'GetAvailableUpdateProductIDs')
        self.mox.StubOutWithMock(self.au, '_WriteFilteredCatalog')
        self.mox.StubOutWithMock(self.au, 'CacheUpdateMetadata')
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'getsha256hash')

        update_list = ['non-empty list']

        appleupdates.munkicommon.getsha256hash(
            self.au.apple_download_catalog_path).AndReturn('hash')
        self.au.CacheAppleCatalog().AndReturn(None)
        self.au.GetAvailableUpdateProductIDs().AndReturn(update_list)
        self.au._WriteFilteredCatalog(
            update_list, self.au.filtered_catalog_path).AndReturn(None)
        exc = appleupdates.ReplicationError('foo err')
        self.au.CacheUpdateMetadata().AndRaise(exc)
        appleupdates.munkicommon.display_warning(
            'Could not replicate software update metadata:')
        appleupdates.munkicommon.display_warning('\t%s', 'foo err')

        self.mox.ReplayAll()
        self.assertFalse(self.au.CheckForSoftwareUpdates())
        self.mox.VerifyAll()

    def testCheckForSoftwareUpdatesWhenDownloadAvailableUpdateFails(self):
        """Tests CheckForSoftwareUpdates() when DownloadAvailUpdates() fails."""
        self._MockMunkiDisplay()
        self.mox.StubOutWithMock(self.au, 'CacheAppleCatalog')
        self.mox.StubOutWithMock(self.au, 'GetAvailableUpdateProductIDs')
        self.mox.StubOutWithMock(self.au, '_WriteFilteredCatalog')
        self.mox.StubOutWithMock(self.au, 'CacheUpdateMetadata')
        self.mox.StubOutWithMock(self.au, 'DownloadAvailableUpdates')
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'getsha256hash')

        update_list = ['non-empty list']

        appleupdates.munkicommon.getsha256hash(
            self.au.apple_download_catalog_path).AndReturn('hash')
        self.au.CacheAppleCatalog().AndReturn(None)
        self.au.GetAvailableUpdateProductIDs().AndReturn(update_list)
        self.au._WriteFilteredCatalog(
            update_list, self.au.filtered_catalog_path).AndReturn(None)
        self.au.CacheUpdateMetadata().AndReturn(None)
        self.au.DownloadAvailableUpdates().AndReturn(False)

        self.mox.ReplayAll()
        self.assertFalse(self.au.CheckForSoftwareUpdates())
        self.mox.VerifyAll()

    def testCheckForSoftwareUpdatesSuccess(self):
        """Tests CheckForSoftwareUpdates() success."""
        self._MockMunkiDisplay()
        self.mox.StubOutWithMock(self.au, 'CacheAppleCatalog')
        self.mox.StubOutWithMock(self.au, 'GetAvailableUpdateProductIDs')
        self.mox.StubOutWithMock(self.au, '_WriteFilteredCatalog')
        self.mox.StubOutWithMock(self.au, 'CacheUpdateMetadata')
        self.mox.StubOutWithMock(self.au, 'DownloadAvailableUpdates')
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'getsha256hash')
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'set_pref')
        # Cannot stub out the builtin date() method, so stub the entire module.
        mock_nsdate_module = self.mox.CreateMockAnything()
        self.mox.StubOutWithMock(appleupdates, 'NSDate', mock_nsdate_module)
        mock_nsdate_module.date = self.mox.CreateMockAnything()

        update_list = ['non-empty list']

        appleupdates.munkicommon.getsha256hash(
            self.au.apple_download_catalog_path).AndReturn('hash')
        self.au.CacheAppleCatalog().AndReturn(None)
        self.au.GetAvailableUpdateProductIDs().AndReturn(update_list)
        self.au._WriteFilteredCatalog(
            update_list, self.au.filtered_catalog_path).AndReturn(None)
        self.au.CacheUpdateMetadata().AndReturn(None)
        self.au.DownloadAvailableUpdates().AndReturn(True)
        appleupdates.NSDate.date().AndReturn('d')
        appleupdates.munkicommon.set_pref('LastAppleSoftwareUpdateCheck', 'd')

        self.mox.ReplayAll()
        self.assertTrue(self.au.CheckForSoftwareUpdates())
        self.mox.VerifyAll()

    def testAvailableUpdatesAreDownloadedFoundationPlistError(self):
        """Tests AvailableUpdatesAreDownloaded() when invalid index_plist."""
        self._MockFoundationPlist()
        self.mox.StubOutWithMock(self.au, 'GetSoftwareUpdateInfo')
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'log')

        index_plist = '/Library/Updates/index.plist'
        self.au.GetSoftwareUpdateInfo().AndReturn(True)
        exc = appleupdates.FoundationPlist.FoundationPlistException
        appleupdates.FoundationPlist.readPlist(index_plist).AndRaise(exc)
        appleupdates.munkicommon.log(
            'Apple downloaded update index is invalid: %s' % index_plist)

        self.mox.ReplayAll()
        self.assertFalse(self.au.AvailableUpdatesAreDownloaded())
        self.mox.VerifyAll()

    def testAvailableUpdatesAreDownloadedWithProductIdNotDownloaded(self):
        """Tests AvailableUpdatesAreDownloaded(); product_id not downloaded."""
        self._MockFoundationPlist()
        self.mox.StubOutWithMock(self.au, 'GetSoftwareUpdateInfo')
        self.mox.StubOutWithMock(appleupdates.os.path, 'isdir')
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'log')

        index_plist = '/Library/Updates/index.plist'
        apple_updates = [
            {'productKey': '1', 'name': 'name1'},
            {'productKey': '999', 'name': 'name999'},
            {'NOTproductKey': 'boo', 'name': 'nameboo'},
        ]
        download_index = {
            'ProductPaths': {
                '1': 'path1', '3': 'path3', '5': 'path5',
            }
        }
        self.au.GetSoftwareUpdateInfo().AndReturn(apple_updates)
        exc = appleupdates.FoundationPlist.FoundationPlistException
        appleupdates.FoundationPlist.readPlist(index_plist).AndReturn(
            download_index)
        appleupdates.os.path.isdir(os.path.join(
            '/Library/Updates', 'path1')).AndReturn(True)
        appleupdates.os.path.isdir('/Library/Updates/').AndReturn(True)
        appleupdates.munkicommon.log(
            'Apple Update product is not downloaded: %s' % 'name999')

        self.mox.ReplayAll()
        self.assertFalse(self.au.AvailableUpdatesAreDownloaded())
        self.mox.VerifyAll()

    def testAvailableUpdatesAreDownloadedWithNonExistentProductDir(self):
        """Tests AvailableUpdatesAreDownloaded(); non-existent product dir."""
        self._MockFoundationPlist()
        self.mox.StubOutWithMock(self.au, 'GetSoftwareUpdateInfo')
        self.mox.StubOutWithMock(appleupdates.os.path, 'isdir')
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'log')

        index_plist = '/Library/Updates/index.plist'
        apple_updates = [
            {'productKey': '1', 'name': 'name1'},
            {'productKey': '3', 'name': 'name3'},
            {'NOTproductKey': 'boo', 'name': 'nameboo'},
        ]
        download_index = {
            'ProductPaths': {
                '1': 'path1', '3': 'path3', '5': 'path5',
            }
        }
        self.au.GetSoftwareUpdateInfo().AndReturn(apple_updates)
        exc = appleupdates.FoundationPlist.FoundationPlistException
        appleupdates.FoundationPlist.readPlist(index_plist).AndReturn(
            download_index)
        appleupdates.os.path.isdir(os.path.join(
            '/Library/Updates', 'path1')).AndReturn(True)
        appleupdates.os.path.isdir(os.path.join(
            '/Library/Updates', 'path3')).AndReturn(False)
        appleupdates.munkicommon.log(
            'Apple Update product directory is missing: %s' % 'name3')

        self.mox.ReplayAll()
        self.assertFalse(self.au.AvailableUpdatesAreDownloaded())
        self.mox.VerifyAll()

    def testAvailableUpdatesAreDownloadedSuccess(self):
        """Tests AvailableUpdatesAreDownloaded() with success."""
        self._MockFoundationPlist()
        self.mox.StubOutWithMock(self.au, 'GetSoftwareUpdateInfo')
        self.mox.StubOutWithMock(appleupdates.os.path, 'isdir')
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'log')

        index_plist = '/Library/Updates/index.plist'
        apple_updates = [
            {'productKey': '1', 'name': 'name1'},
            {'productKey': '3', 'name': 'name3'},
            {'NOTproductKey': 'boo', 'name': 'nameboo'},
        ]
        download_index = {
            'ProductPaths': {
                '1': 'path1', '3': 'path3', '5': 'path5',
            }
        }
        self.au.GetSoftwareUpdateInfo().AndReturn(apple_updates)
        exc = appleupdates.FoundationPlist.FoundationPlistException
        appleupdates.FoundationPlist.readPlist(index_plist).AndReturn(
            download_index)
        appleupdates.os.path.isdir(os.path.join(
            '/Library/Updates', 'path1')).AndReturn(True)
        appleupdates.os.path.isdir(os.path.join(
            '/Library/Updates', 'path3')).AndReturn(True)

        self.mox.ReplayAll()
        self.assertTrue(self.au.AvailableUpdatesAreDownloaded())
        self.mox.VerifyAll()

    def testGetSoftwareUpdateInfo(self):
        """Tests GetSoftwareUpdateInfo()."""
        self._MockFoundationPlist()
        self.mox.StubOutWithMock(appleupdates.os.path, 'exists')
        self.mox.StubOutWithMock(self.au, 'GetBlockingApps')
        self.mox.StubOutWithMock(self.au, 'GetFirmwareAlertText')

        blocking_apps = ['blocking1', 'blocking2']
        applicable_updates = {
            'phaseResultsArray': [
                {'description': 'desc1', 'ignoreKey': 'name1',
                 'version': 'ver1', 'name': 'display_name1', 'sizeInKB': 1000,
                 'productKey': 'prodid1'},
                {'description': 'desc2', 'ignoreKey': 'name2',
                 'version': 'ver2', 'name': 'display_name2', 'sizeInKB': 2000,
                 'productKey': 'prodid2', 'restartRequired': 'YES'},
            ]
        }
        expected_output = [
            {'apple_product_name': 'display_name1',
             'blocking_applications': blocking_apps,
             'description': 'desc1', 
             'name': 'name1',
             'version_to_install': 'ver1', 
             'display_name': 'display_name1',
             'installed_size': 1000, 
             'productKey': 'prodid1'},
            {'apple_product_name': 'display_name2',
             'description': 'desc2', 
             'firmware_alert_text': 'This is a firmware update',
             'name': 'name2',
             'version_to_install': 'ver2', 
             'display_name': 'display_name2',
             'installed_size': 2000, 
             'productKey': 'prodid2',
             'RestartAction': 'RequireRestart'},
        ]

        appleupdates.os.path.exists(self.au.applicable_updates_plist).AndReturn(
            True)
        appleupdates.FoundationPlist.readPlist(
            self.au.applicable_updates_plist).AndReturn(applicable_updates)
        self.au.GetBlockingApps(
            applicable_updates['phaseResultsArray'][0]['productKey']).AndReturn(
                blocking_apps)
        self.au.GetFirmwareAlertText(
            applicable_updates['phaseResultsArray'][0]['productKey']).AndReturn(
                '')
        self.au.GetBlockingApps(
            applicable_updates['phaseResultsArray'][1]['productKey']).AndReturn(
                [])
        self.au.GetFirmwareAlertText(
            applicable_updates['phaseResultsArray'][1]['productKey']).AndReturn(
                'This is a firmware update')

        self.mox.ReplayAll()
        self.assertEqual(expected_output, self.au.GetSoftwareUpdateInfo())
        self.mox.VerifyAll()

    def testGetSoftwareUpdateInfoWhenApplicableUpdatesDoesntExist(self):
        """Tests GetSoftwareUpdateInfo(); Applicable Updates does not exist."""
        self.mox.StubOutWithMock(appleupdates.os.path, 'exists')

        appleupdates.os.path.exists(self.au.applicable_updates_plist).AndReturn(
            False)
        self.mox.ReplayAll()
        self.assertEqual([], self.au.GetSoftwareUpdateInfo())
        self.mox.VerifyAll()

    def testWriteAppleUpdatesFile(self):
        """Tests WriteAppleUpdatesFile()."""
        self._MockFoundationPlist()
        self._MockUpdateCheck()
        self.mox.StubOutWithMock(self.au, 'GetSoftwareUpdateInfo')
        self.au.GetSoftwareUpdateInfo().AndReturn('appleupdates')
        appleupdates.updatecheck.getPrimaryManifestCatalogs(
            '', force_refresh=False).AndReturn(None)
        appleupdates.FoundationPlist.writePlist(
            {'AppleUpdates': 'appleupdates'},
            self.au.apple_updates_plist).AndReturn(None)
        self.mox.ReplayAll()
        self.assertTrue(self.au.WriteAppleUpdatesFile() == len('appleupdates'))
        self.mox.VerifyAll()

    def testWriteAppleUpdatesFileFailure(self):
        """Tests WriteAppleUpdatesFile() with failure."""
        self._MockFoundationPlist()
        self._MockUpdateCheck()
        self.mox.StubOutWithMock(self.au, 'GetSoftwareUpdateInfo')
        self.mox.StubOutWithMock(appleupdates.os, 'unlink')
        self.au.GetSoftwareUpdateInfo().AndReturn(None)
        appleupdates.os.unlink(self.au.apple_updates_plist).AndRaise(OSError)

        self.mox.ReplayAll()
        self.assertTrue(self.au.WriteAppleUpdatesFile() == 0)
        self.mox.VerifyAll()

    def testDisplayAppleUpdateInfo(self):
        """Tests DisplayAppleUpdateInfo()."""
        self._MockFoundationPlist()
        self._MockMunkiDisplay()
        appleupdates.munkicommon.report = {}

        apple_updates = {'AppleUpdates': [
            {'display_name': 'name1', 'version_to_install': 'ver1',
             'RestartAction': 'RequireRestart'},
            {'display_name': 'name2', 'version_to_install': 'ver2',
             'RestartAction': 'RequireLogout'},
            {'display_name': 'name3', 'version_to_install': 'ver3'},
        ]}

        appleupdates.FoundationPlist.readPlist(
            self.au.apple_updates_plist).AndReturn(apple_updates)
        appleupdates.munkicommon.display_info(
            'The following Apple Software Updates are available to install:')
        appleupdates.munkicommon.display_info('    + %s-%s' % ('name1', 'ver1'))
        appleupdates.munkicommon.display_info('       *Restart required')
        appleupdates.munkicommon.display_info('    + %s-%s' % ('name2', 'ver2'))
        appleupdates.munkicommon.display_info('       *Logout required')
        appleupdates.munkicommon.display_info('    + %s-%s' % ('name3', 'ver3'))

        self.mox.ReplayAll()
        self.assertTrue(
            'RestartRequired' not in appleupdates.munkicommon.report)
        self.assertTrue('LogoutRequired' not in appleupdates.munkicommon.report)
        self.au.DisplayAppleUpdateInfo()
        self.assertTrue(appleupdates.munkicommon.report['RestartRequired'])
        self.assertTrue(appleupdates.munkicommon.report['LogoutRequired'])
        self.mox.VerifyAll()

    def testDisplayAppleUpdateInfoWhenReadPlistFailed(self):
        """Tests DisplayAppleUpdateInfo() when readPlist() fails."""
        self._MockFoundationPlist()
        self._MockMunkiDisplay()

        exc = appleupdates.FoundationPlist.FoundationPlistException
        appleupdates.FoundationPlist.readPlist(
            self.au.apple_updates_plist).AndRaise(exc)
        appleupdates.munkicommon.display_error(
            'Error reading: %s', self.au.apple_updates_plist)

        self.mox.ReplayAll()
        self.au.DisplayAppleUpdateInfo()
        self.mox.VerifyAll()

    def testGetSoftwareUpdatePref(self):
        """Tests GetSoftwareUpdatePref()."""
        self.mox.StubOutWithMock(appleupdates, 'CFPreferencesCopyAppValue')
        pref_name = 'foo'
        expected_return = 'bar'
        appleupdates.CFPreferencesCopyAppValue(
            pref_name,
            appleupdates.APPLE_SOFTWARE_UPDATE_PREFS_DOMAIN
            ).AndReturn(expected_return)

        self.mox.ReplayAll()
        self.au.GetSoftwareUpdatePref(pref_name)
        self.mox.VerifyAll()

    def testLeopardSetupSoftwareUpdateCheck(self):
        """Tests _LeopardSetupSoftwareUpdateCheck()."""
        self._MockMunkiDisplay()
        self.mox.StubOutWithMock(appleupdates, 'CFPreferencesSetValue')
        self.mox.StubOutWithMock(appleupdates, 'CFPreferencesAppSynchronize')
        appleupdates.CFPreferencesSetValue(
            'AgreedToLicenseAgreement', True,
            appleupdates.APPLE_SOFTWARE_UPDATE_PREFS_DOMAIN,
            appleupdates.kCFPreferencesCurrentUser,
            appleupdates.kCFPreferencesCurrentHost).AndReturn(None)
        appleupdates.CFPreferencesSetValue(
            'AutomaticDownload', True,
            appleupdates.APPLE_SOFTWARE_UPDATE_PREFS_DOMAIN,
            appleupdates.kCFPreferencesCurrentUser,
            appleupdates.kCFPreferencesCurrentHost).AndReturn(None)
        appleupdates.CFPreferencesSetValue(
            'LaunchAppInBackground', True,
            appleupdates.APPLE_SOFTWARE_UPDATE_PREFS_DOMAIN,
            appleupdates.kCFPreferencesCurrentUser,
            appleupdates.kCFPreferencesCurrentHost).AndReturn(None)
        appleupdates.CFPreferencesAppSynchronize(
            appleupdates.APPLE_SOFTWARE_UPDATE_PREFS_DOMAIN).AndReturn(None)
        appleupdates.munkicommon.display_error(
            'Error setting com.apple.SoftwareUpdate ByHost preferences.')

        self.mox.ReplayAll()
        self.au._LeopardSetupSoftwareUpdateCheck()
        self.mox.VerifyAll()

    # TODO(ogle): _LeopardDownloadAvailableUpdates, _RunSoftwareUpdate, and
    #             InstallAppleUpdates tests are missing here.

    def testAppleSoftwareUpdatesAvailableWhenCheckNeeded(self):
        """Tests AppleSoftwareUpdatesAvailable() when check needed."""
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'stopRequested')
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'pref')
        self.mox.StubOutWithMock(self.au, 'CheckForSoftwareUpdates')
        self.mox.StubOutWithMock(self.au, 'WriteAppleUpdatesFile')
        #self.mox.StubOutWithMock(self.au, 'DisplayAppleUpdateInfo')
        # Cannot stub out the builtin NSDate methods, so stub the entire module.
        mock_nsdate_module = self.mox.CreateMockAnything()
        self.mox.StubOutWithMock(appleupdates, 'NSDate', mock_nsdate_module)
        mock_nsdate_new = self.mox.CreateMockAnything()
        mock_nsdate_datewithstring = self.mox.CreateMockAnything()
        mock_nsdate_module.new = mock_nsdate_new
        mock_nsdate_module.dateWithString_ = mock_nsdate_datewithstring

        now_nsdate = NSDate.dateWithString_('2011-08-22 18:00:00 -400')
        appleupdates.NSDate.new().AndReturn(now_nsdate)

        # use a date barely older than the 24 hour threshold.
        recent_date_str = '2011-08-21 17:59:00 -0400'
        recent_date_nsdate = NSDate.dateWithString_(recent_date_str)
        appleupdates.munkicommon.pref('LastAppleSoftwareUpdateCheck').AndReturn(
            recent_date_str)
        appleupdates.NSDate.dateWithString_(recent_date_str).AndReturn(
            recent_date_nsdate)

        self.au.CheckForSoftwareUpdates(force_check=True).AndReturn(True)
        appleupdates.munkicommon.stopRequested().AndReturn(False)
        self.au.WriteAppleUpdatesFile().AndReturn(True)
        #self.au.DisplayAppleUpdateInfo().AndReturn(None)

        self.mox.ReplayAll()
        out = self.au.AppleSoftwareUpdatesAvailable(
            force_check=False, suppress_check=False)
        self.assertTrue(out)
        self.mox.VerifyAll()

    def testAppleSoftwareUpdatesAvailableWhenRecentlyChecked(self):
        """Tests AppleSoftwareUpdatesAvailable() when recently check."""
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'stopRequested')
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'pref')
        self.mox.StubOutWithMock(self.au, 'CheckForSoftwareUpdates')
        self.mox.StubOutWithMock(self.au, 'WriteAppleUpdatesFile')
        #self.mox.StubOutWithMock(self.au, 'DisplayAppleUpdateInfo')
        # Cannot stub out the builtin NSDate methods, so stub the entire module.
        mock_nsdate_module = self.mox.CreateMockAnything()
        self.mox.StubOutWithMock(appleupdates, 'NSDate', mock_nsdate_module)
        mock_nsdate_new = self.mox.CreateMockAnything()
        mock_nsdate_datewithstring = self.mox.CreateMockAnything()
        mock_nsdate_module.new = mock_nsdate_new
        mock_nsdate_module.dateWithString_ = mock_nsdate_datewithstring

        now_nsdate = NSDate.dateWithString_('2011-08-22 18:00:00 -400')
        appleupdates.NSDate.new().AndReturn(now_nsdate)

        # use a date barely newer than the 24 hour threshold.
        recent_date_str = '2011-08-21 18:01:00 -0400'
        recent_date_nsdate = NSDate.dateWithString_(recent_date_str)
        appleupdates.munkicommon.pref('LastAppleSoftwareUpdateCheck').AndReturn(
            recent_date_str)
        appleupdates.NSDate.dateWithString_(recent_date_str).AndReturn(
            recent_date_nsdate)

        self.au.CheckForSoftwareUpdates(force_check=False).AndReturn(True)
        appleupdates.munkicommon.stopRequested().AndReturn(False)
        self.au.WriteAppleUpdatesFile().AndReturn(True)
        #self.au.DisplayAppleUpdateInfo().AndReturn(None)

        self.mox.ReplayAll()
        out = self.au.AppleSoftwareUpdatesAvailable(
            force_check=False, suppress_check=False)
        self.assertTrue(out)
        self.mox.VerifyAll()

    def testAppleSoftwareUpdatesAvailableWhenNsDateValueError(self):
        """Tests AppleSoftwareUpdatesAvailable() when ValueError is raised."""
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'stopRequested')
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'pref')
        self.mox.StubOutWithMock(self.au, 'CheckForSoftwareUpdates')
        self.mox.StubOutWithMock(self.au, 'WriteAppleUpdatesFile')
        #self.mox.StubOutWithMock(self.au, 'DisplayAppleUpdateInfo')

        # use a date string that will not parse correctly.
        appleupdates.munkicommon.pref('LastAppleSoftwareUpdateCheck').AndReturn(
            'zomg this is not a date!!!!!')

        self.au.CheckForSoftwareUpdates(force_check=True).AndReturn(True)
        appleupdates.munkicommon.stopRequested().AndReturn(False)
        self.au.WriteAppleUpdatesFile().AndReturn(True)
        #self.au.DisplayAppleUpdateInfo().AndReturn(None)

        self.mox.ReplayAll()
        out = self.au.AppleSoftwareUpdatesAvailable(
            force_check=False, suppress_check=False)
        self.assertTrue(out)
        self.mox.VerifyAll()

    def testAppleSoftwareUpdatesAvailableForceCheck(self):
        """Tests AppleSoftwareUpdatesAvailable() with force_check=True."""
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'stopRequested')
        self.mox.StubOutWithMock(self.au, 'CheckForSoftwareUpdates')
        self.mox.StubOutWithMock(self.au, 'WriteAppleUpdatesFile')
        #self.mox.StubOutWithMock(self.au, 'DisplayAppleUpdateInfo')

        self.au.CheckForSoftwareUpdates(force_check=True).AndReturn(True)
        appleupdates.munkicommon.stopRequested().AndReturn(False)
        self.au.WriteAppleUpdatesFile().AndReturn(True)
        #self.au.DisplayAppleUpdateInfo().AndReturn(None)

        self.mox.ReplayAll()
        out = self.au.AppleSoftwareUpdatesAvailable(
            force_check=True, suppress_check=False)
        self.assertTrue(out)
        self.mox.VerifyAll()

    def testAppleSoftwareUpdatesAvailableSuppressCheck(self):
        """Tests AppleSoftwareUpdatesAvailable() with suppress_check=True."""
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'stopRequested')
        self.mox.StubOutWithMock(self.au, 'WriteAppleUpdatesFile')
        #self.mox.StubOutWithMock(self.au, 'DisplayAppleUpdateInfo')

        appleupdates.munkicommon.stopRequested().AndReturn(False)
        self.au.WriteAppleUpdatesFile().AndReturn(True)
        #self.au.DisplayAppleUpdateInfo().AndReturn(None)

        self.mox.ReplayAll()
        out = self.au.AppleSoftwareUpdatesAvailable(
            force_check=False, suppress_check=True)
        self.assertTrue(out)
        self.mox.VerifyAll()

    def testAppleSoftwareUpdatesAvailableSuppressCheckNoneAvailable(self):
        """Tests AppleSoftwareUpdatesAvailable() when no updates available."""
        self.mox.StubOutWithMock(appleupdates.munkicommon, 'stopRequested')
        self.mox.StubOutWithMock(self.au, 'WriteAppleUpdatesFile')
        #self.mox.StubOutWithMock(self.au, 'DisplayAppleUpdateInfo')

        appleupdates.munkicommon.stopRequested().AndReturn(False)
        self.au.WriteAppleUpdatesFile().AndReturn(False)

        self.mox.ReplayAll()
        out = self.au.AppleSoftwareUpdatesAvailable(
            force_check=False, suppress_check=True)
        self.assertFalse(out)
        self.mox.VerifyAll()

    def testSoftwareUpdateListCached(self):
        """Tests SoftwareUpdateList() when update list is cached."""
        self.au._update_list_cache = 'not none'

        output = self.au.SoftwareUpdateList()
        self.assertEqual(output, self.au._update_list_cache)

    def testSoftwareUpdateList(self):
        """Tests SoftwareUpdateList() success."""
        self._MockMunkiDisplay()
        self.mox.StubOutWithMock(appleupdates.subprocess, 'Popen')

        process_output = (
            '   * Foo Package 1\n'
            '   * Bar Update 2\n'
            ' ignore more, because I do not start with "   * "\n'
            '   * Zoo Install 3\n'
            '   * Security Patch!\n'
        )
        expected_output = [
            'Foo Package 1', 'Bar Update 2', 'Zoo Install 3', 'Security Patch!'
        ]

        appleupdates.munkicommon.display_detail(
            'Getting list of available Apple Software Updates')
        mock_process = self.mox.CreateMockAnything()
        appleupdates.subprocess.Popen(
            ['/usr/sbin/softwareupdate', '-l'], shell=False, bufsize=-1,
            stdin=appleupdates.subprocess.PIPE,
            stdout=appleupdates.subprocess.PIPE,
            stderr=appleupdates.subprocess.PIPE).AndReturn(mock_process)
        mock_process.communicate().AndReturn((process_output, 'unused'))
        mock_process.returncode = 0
        appleupdates.munkicommon.display_detail(
            'softwareupdate returned %d updates.', 4)

        self.mox.ReplayAll()
        output = self.au.SoftwareUpdateList()
        self.assertTrue(self.au._update_list_cache is not None)
        self.assertEqual(output, expected_output)
        self.mox.VerifyAll()



class TestAppleUpdatesModule(mox.MoxTestBase):
    """Test appleupdates module."""

    def setUp(self):
        mox.MoxTestBase.setUp(self)
        self.stubs = stubout.StubOutForTesting()

    def tearDown(self):
        self.mox.UnsetStubs()
        self.stubs.UnsetAll()

    def testGlobals(self):
        """Test global variables."""
        self.assertTrue(
            type(getattr(appleupdates, 'DEFAULT_CATALOG_URLS', None)) is dict)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
