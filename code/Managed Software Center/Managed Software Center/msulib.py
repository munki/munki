# encoding: utf-8
#
#  msulib.py
#
#  Created by Greg Neagle on 12/10/13.
#  Copyright 2010-2014 Greg Neagle.
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
'''Some functions used a few places that don't (yet) have an obvious home'''


import os
import sys

import shutil

from HTMLParser import HTMLParser

from Foundation import *
from AppKit import *

import munki

_html_dir = None

class MSUHTMLFilter(HTMLParser):
    '''Filters HTML and HTML fragments for use inside description paragraphs'''
    # ignore everything inside one of these tags
    ignore_elements = ['script', 'style', 'head', 'table', 'form']
    # preserve these tags
    preserve_tags = ['a', 'b', 'i', 'strong', 'em', 'small', 'sub', 'sup', 'ins',
                     'del', 'mark', 'span', 'br']
    # transform these tags
    transform_starttags = { 'ul': '<br>',
        'ol': '<br>',
        'li': '&nbsp;&nbsp;&bull; ',
        'h1': '<strong>',
        'h2': '<strong>',
        'h3': '<strong>',
        'h4': '<strong>',
        'h5': '<strong>',
        'h6': '<strong>',
        'p': ''}
    transform_endtags =   { 'ul': '<br>',
        'ol': '<br>',
        'li': '<br>',
        'h1': '</strong><br>',
        'h2': '</strong><br>',
        'h3': '</strong><br>',
        'h4': '</strong><br>',
        'h5': '</strong><br>',
        'h6': '</strong><br>',
        'p': '<br>'}
    # track the currently-ignored element if any
    current_ignore_element = None
    # track the number of tags we found
    tag_count = 0
    # store our filtered/transformed html fragment
    filtered_html = u''
    
    def handle_starttag(self, tag, attrs):
        self.tag_count += 1
        if not self.current_ignore_element:
            if tag in self.ignore_elements:
                self.current_ignore_element = tag
            elif tag in self.transform_starttags:
                self.filtered_html += self.transform_starttags[tag]
            elif tag in self.preserve_tags:
                self.filtered_html += self.get_starttag_text()
    
    def handle_endtag(self, tag):
        if tag == self.current_ignore_element:
            self.current_ignore_element = None
        elif not self.current_ignore_element:
            if tag in self.transform_endtags:
                self.filtered_html += self.transform_endtags[tag]
            elif tag in self.preserve_tags:
                self.filtered_html += u'</%s>' % tag
    
    def handle_data(self, data):
        if not self.current_ignore_element:
            self.filtered_html += data
    
    def handle_entityref(self, name):
        if not self.current_ignore_element:
            # add the entity reference as-is
            self.filtered_html += u'&%s;' % name
    
    def handle_charref(self, name):
        if not self.current_ignore_element:
            # just pass on unmodified
            self.filtered_html += name


def filtered_html(text):
    '''Returns filtered HTML for use in description paragraphs'''
    parser = MSUHTMLFilter()
    parser.feed(text)
    if parser.tag_count:
        # found at least one html tag, so this is probably HTML
        return parser.filtered_html
    else:
        # might be plain text, so we should escape a few entities and
        # add <br> for line breaks
        text = text.replace('&', '&amp;')
        text = text.replace('<', '&lt;')
        text = text.replace('>', '&gt;')
        return text.replace('\n', '<br>\n')


def updateCountMessage(count):
    '''Return a localized message describing the count of updates to install'''
    if count == 0:
        return NSLocalizedString(u'No pending updates', u'NoUpdatesMessage')
    if count == 1:
        return NSLocalizedString(u'1 pending update', u'OneUpdateMessage')
    else:
        return (NSLocalizedString(u'%s pending updates',
                                  u'MultipleUpdatesMessage') % count)


def getInstallAllButtonTextForCount(count):
    '''Return localized display text for action button in Updates view'''
    if count == 0:
        return NSLocalizedString(u'Check Again',
                                 u'CheckAgainButtonLabel')
    elif count == 1:
        return NSLocalizedString(u'Update',
                                 u'UpdateButtonLabel')
    else:
        return NSLocalizedString(u'Update All',
                                 u'UpdateAllButtonLabel')


def html_dir():
    '''sets up our local html cache directory'''
    global _html_dir
    if _html_dir:
        return _html_dir
    bundle_id = NSBundle.mainBundle().bundleIdentifier()
    cache_dir_urls = NSFileManager.defaultManager().URLsForDirectory_inDomains_(
        NSCachesDirectory, NSUserDomainMask)
    if cache_dir_urls:
        cache_dir = cache_dir_urls[0].path()
    else:
        cache_dir = u'/private/tmp'
    our_cache_dir = os.path.join(cache_dir, bundle_id)
    if not os.path.exists(our_cache_dir):
         os.mkdir(our_cache_dir)
    _html_dir = os.path.join(our_cache_dir, 'html')
    if os.path.exists(_html_dir):
        # empty it
        shutil.rmtree(_html_dir)
    os.mkdir(_html_dir)
    # symlink our static files dir
    resourcesPath = NSBundle.mainBundle().resourcePath()
    source_path = os.path.join(resourcesPath, 'WebResources')
    link_path = os.path.join(_html_dir, 'static')
    os.symlink(source_path, link_path)
    # symlink the Managed Installs icons dir
    managed_install_dir = munki.pref('ManagedInstallDir')
    source_path = os.path.join(managed_install_dir, 'icons')
    link_path = os.path.join(_html_dir, 'icons')
    os.symlink(source_path, link_path)
    return _html_dir
