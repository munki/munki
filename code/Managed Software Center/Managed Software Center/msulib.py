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


import os
import sys

import shutil
from string import Template
from urllib import quote_plus

from HTMLParser import HTMLParser

from Foundation import *
from AppKit import *

import FoundationPlist
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


def convertIconToPNG(app_name, destination_path, desired_size):
    '''Converts an application icns file to a png file, choosing the representation
        closest to (but >= than if possible) the desired_size. Returns True if
        successful, False otherwise'''
    app_path = os.path.join('/Applications', app_name + '.app')
    if not os.path.exists(app_path):
        return False
    try:
        info = FoundationPlist.readPlist(os.path.join(app_path, 'Contents/Info.plist'))
    except (FoundationPlist.FoundationPlistException):
        info = {}
    icon_filename = info.get('CFBundleIconFile', app_name)
    icon_path = os.path.join(app_path, 'Contents/Resources', icon_filename)
    if not os.path.splitext(icon_path)[1]:
        # no file extension, so add '.icns'
        icon_path += u'.icns'
    if os.path.exists(icon_path):
        image_data = NSData.dataWithContentsOfFile_(icon_path)
        bitmap_reps = NSBitmapImageRep.imageRepsWithData_(image_data)
        chosen_rep = None
        for bitmap_rep in bitmap_reps:
            if not chosen_rep:
                chosen_rep = bitmap_rep
            elif (bitmap_rep.pixelsHigh() >= desired_size
                  and bitmap_rep.pixelsHigh() < chosen_rep.pixelsHigh()):
                chosen_rep = bitmap_rep
        if chosen_rep:
            png_data = chosen_rep.representationUsingType_properties_(NSPNGFileType, None)
            png_data.writeToFile_atomically_(destination_path, False)
            return True
    return False


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


def getRestartActionForUpdateList(update_list):
    '''Returns a localized overall restart action message for the list of updates'''
    if [item for item in update_list if 'Restart' in item.get('RestartAction', '')]:
        # found at least one item containing 'Restart' in its RestartAction
        return NSLocalizedString(u'Restart Required',
                                 u'RequireRestartMessage')
    if [item for item in update_list if 'Logout' in item.get('RestartAction', '')]:
        # found at least one item containing 'Logout' in its RestartAction
        return NSLocalizedString(u'Logout Required',
                                 u'RequireLogoutMessage')
    else:
        return ''


def addSidebarLabels(page):
    '''adds localized labels for the detail view sidebars'''
    page['informationLabel'] = NSLocalizedString(
                                   u'Information',
                                   u'InformationLabel')
    page['categoryLabel'] = NSLocalizedString(
                                   u'Category:',
                                   u'CategoryLabel')
    page['versionLabel'] = NSLocalizedString(
                                    u'Version:',
                                    u'VersionLabel')
    page['sizeLabel'] = NSLocalizedString(
                                    u'Size:',
                                    u'SizeLabel')
    page['developerLabel'] = NSLocalizedString(
                                    u'Developer:',
                                    u'DeveloperLabel')
    page['statusLabel'] = NSLocalizedString(
                                    u'Status:', u'StatusLabel')
    page['moreByDeveloperLabel'] = NSLocalizedString(
                                    u'More by %s',
                                    u'MoreByDeveloperLabel')
    page['moreInCategoryLabel'] = NSLocalizedString(
                                    u'More in %s',
                                    u'MoreInCategoryLabel')
    page['typeLabel'] = NSLocalizedString(
                                    u'Type:', u'TypeLabel')
    page['dueLabel'] = NSLocalizedString(
                                    u'Due:', u'DueLabel')


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
    return _html_dir


def get_template(template_name):
    '''return an html template'''
    resourcesPath = NSBundle.mainBundle().resourcePath()
    templatePath = os.path.join(resourcesPath, 'templates', template_name)
    try:
        file_ref = open(templatePath)
        template_html = file_ref.read()
        file_ref.close()
        return Template(template_html.decode('utf-8'))
    except (IOError, OSError):
        return None


def getFooter(vars=None):
    '''Return html footer'''
    if not vars:
        vars = {}
    footer_template = get_template('footer_template.html')
    return footer_template.safe_substitute(vars)
