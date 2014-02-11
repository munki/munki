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

from HTMLParser import HTMLParser

from Foundation import *
from AppKit import *

import FoundationPlist

class MSUHTMLFilter(HTMLParser):
    '''Filters HTML and HTML fragments for use inside description paragraphs'''
    # ignore everything inside one of these tags
    ignore_elements = ['script', 'style', 'head', 'table', 'form']
    # preserve these tags
    preserve_tags = ['a', 'b', 'i', 'strong', 'em', 'small', 'sub', 'sup', 'ins',
                     'del', 'mark', 'span']
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
    filtered_html = ''
    
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
                self.filtered_html += '</%s>' % tag
    
    def handle_data(self, data):
        if not self.current_ignore_element:
            self.filtered_html += data
    
    def handle_entityref(self, name):
        if not self.current_ignore_element:
            # add the entity reference as-is
            self.filtered_html += '&%s;' % name
    
    def handle_charref(self, name):
        if not self.current_ignore_element:
            # just pass on unmodified
            self.filtered_html += name


def filtered_html(text):
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
    '''Converts an application icns file to a png file, chosing the representation
        closest to (but >= than if possible) the desired_size. Returns True if
        successful, False otherwise'''
    app_path = os.path.join('/Applications', app_name + '.app')
    if not os .path.exists(app_path):
        return False
    try:
        info = FoundationPlist.readPlist(os.path.join(app_path, 'Contents/Info.plist'))
    except (FoundationPlist.FoundationPlistException):
        info = {}
    icon_filename = info.get('CFBundleIconFile', app_name)
    icon_path = os.path.join(app_path, 'Contents/Resources', icon_filename)
    if not os.path.splitext(icon_path)[1]:
        # no file extension, so add '.icns'
        icon_path += '.icns'
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
        return NSLocalizedString(u'No pending updates',
                                 u'NoUpdatesMessage').encode('utf-8')
    if count == 1:
        return NSLocalizedString(u'1 pending update',
                                 u'OneUpdateMessage').encode('utf-8')
    else:
        return (NSLocalizedString(u'%s pending updates',
                                  u'MultipleUpdatesMessage').encode('utf-8')
                                  % count)


def displayTextForStatus(status):
    '''Return localized status display text'''
    map = {'installed':
                NSLocalizedString(u'Installed',
                          u'InstalledDisplayText').encode('utf-8'),
            'installing':
                NSLocalizedString(u'Installing',
                                  u'InstallingDisplayText').encode('utf-8'),
            'installed-not-removable':
                NSLocalizedString(u'Installed',
                                  u'InstalledDisplayText').encode('utf-8'),
            'not-installed':
                NSLocalizedString(u'Not installed',
                                  u'NotInstalledDisplayText').encode('utf-8'),
            'will-be-installed':
                NSLocalizedString(u'Will be installed',
                                  u'WillBeInstalledDisplayText').encode('utf-8'),
            'will-be-removed':
                NSLocalizedString(u'Will be removed',
                                  u'WillBeRemovedDisplayText').encode('utf-8'),
            'removing':
                NSLocalizedString(u'Removing',
                                  u'RemovingDisplayText').encode('utf-8'),
            'update-will-be-installed':
                NSLocalizedString(u'Update will be installed',
                                  u'UpdateWillBeInstalledDisplayText').encode('utf-8'),
            'update-available':
                NSLocalizedString(u'Update available',
                                  u'UpdateAvailableDisplayText').encode('utf-8'),
            'no-licenses-available':
                NSLocalizedString(u'No licenses available',
                                  u'NoLicensesAvailableDisplayText').encode('utf-8'),
                          
    }
    return map.get(status, status)


def shortActionTextForStatus(status):
    '''Return localized 'short' action text for button'''
    map = { 'installed':
                NSLocalizedString(u'Remove',
                          u'RemoveShortActionText').encode('utf-8'),
            'installing':
                NSLocalizedString(u'Installing',
                                  u'InstallingShortActionText').encode('utf-8'),
            'installed-not-removable':
                NSLocalizedString(u'Installed',
                                  u'InstalledShortActionText').encode('utf-8'),
            'not-installed':
                NSLocalizedString(u'Install',
                                  u'InstallShortActionText').encode('utf-8'),
            'will-be-installed':
                NSLocalizedString(u'Cancel',
                                  u'CancelInstallShortActionText').encode('utf-8'),
            'will-be-removed':
                NSLocalizedString(u'Cancel',
                                  u'CancelRemovalShortActionText').encode('utf-8'),
            'removing':
                NSLocalizedString(u'Removing',
                                  u'RemovingShortActionText').encode('utf-8'),
            'update-will-be-installed':
                NSLocalizedString(u'Cancel',
                                  u'CancelUpdateShortActionText').encode('utf-8'),
            'update-available':
                NSLocalizedString(u'Update',
                                  u'UpdateShortActionText').encode('utf-8'),
            'no-licenses-available':
                NSLocalizedString(u'Unavailable',
                                  u'UnavailableShortActionText').encode('utf-8'),
    }
    return map.get(status, status)


def longActionTextForStatus(status):
    '''Return localized 'long' action text for button'''
    map = {'installed':
                NSLocalizedString(u'Remove',
                          u'RemoveLongActionText').encode('utf-8'),
            'installing':
                NSLocalizedString(u'Installing',
                                  u'InstallingLongActionText').encode('utf-8'),
            'installed-not-removable':
                NSLocalizedString(u'Installed',
                                  u'InstalledLongActionText').encode('utf-8'),
            'not-installed':
                NSLocalizedString(u'Install',
                                  u'InstallLongActionText').encode('utf-8'),
            'will-be-installed':
                NSLocalizedString(u'Cancel install',
                                  u'CancelInstallLongActionText').encode('utf-8'),
            'will-be-removed':
                NSLocalizedString(u'Cancel removal',
                                  u'CancelRemovalLongActionText').encode('utf-8'),
            'removing':
                NSLocalizedString(u'Removing',
                                  u'RemovingLongActionText').encode('utf-8'),
            'update-will-be-installed':
                NSLocalizedString(u'Cancel update',
                                  u'CancelUpdateLongActionText').encode('utf-8'),
            'update-available':
                NSLocalizedString(u'Update',
                                  u'UpdateLongActionText').encode('utf-8'),
            'no-licenses-available':
                NSLocalizedString(u'Currently Unavailable',
                                  u'UnavailableShortActionText').encode('utf-8'),
    }
    return map.get(status, status)


def myItemActionTextForStatus(status):
    '''Return localized 'My Item' action text for button'''
    map = { 'installed':
                NSLocalizedString(u'Remove',
                                  u'RemoveLongActionText').encode('utf-8'),
            'installing':
                NSLocalizedString(u'Installing',
                                  u'InstallingLongActionText').encode('utf-8'),
            'installed-not-removable':
                NSLocalizedString(u'Installed',
                                  u'InstalledLongActionText').encode('utf-8'),
            'will-be-removed':
                NSLocalizedString(u'Cancel removal',
                                  u'CancelRemovalLongActionText').encode('utf-8'),
            'removing':
                NSLocalizedString(u'Removing',
                                  u'RemovingLongActionText').encode('utf-8'),
            'update-will-be-installed':
                NSLocalizedString(u'Remove',
                                  u'RemoveLongActionText').encode('utf-8'),
            'will-be-installed':
                NSLocalizedString(u'Cancel install',
                                  u'CancelInstallLongActionText').encode('utf-8'),

    }
    return map.get(status, status)


def getInstallAllButtonTextForCount(count):
    if count == 0:
        return NSLocalizedString(u'Check Again',
                                 u'CheckAgainButtonLabel').encode('utf-8')
    elif count == 1:
        return NSLocalizedString(u'Update',
                                 u'UpdateButtonLabel').encode('utf-8')
    else:
        return NSLocalizedString(u'Update All',
                                 u'UpdateAllButtonLabel').encode('utf-8')


def getRestartActionForUpdateList(update_list):
    '''Returns a localized overall restart action message for the list of updates'''
    if [item for item in update_list if 'Restart' in item.get('RestartAction', '')]:
        # found at least one item containing 'Restart' in its RestartAction
        return NSLocalizedString(u'Restart Required',
                                 u'RequireRestartMessage').encode('utf-8')
    if [item for item in update_list if 'Logout' in item.get('RestartAction', '')]:
        # found at least one item containing 'Logout' in its RestartAction
        return NSLocalizedString(u'Logout Required',
                                 u'RequireLogoutMessage').encode('utf-8')
    else:
        return ''


def addSidebarLabels(page):
    '''adds localized labels for the detail view sidebars'''
    page['informationLabel'] = NSLocalizedString(
                                   u'Information',
                                   u'InformationLabel').encode('utf-8')
    page['categoryLabel'] = NSLocalizedString(
                                   u'Category:',
                                   u'CategoryLabel').encode('utf-8')
    page['versionLabel'] = NSLocalizedString(
                                    u'Version:',
                                    u'VersionLabel').encode('utf-8')
    page['sizeLabel'] = NSLocalizedString(
                                    u'Size:',
                                    u'SizeLabel').encode('utf-8')
    page['developerLabel'] = NSLocalizedString(
                                    u'Developer:',
                                    u'DeveloperLabel').encode('utf-8')
    page['statusLabel'] = NSLocalizedString(
                                    u'Status:', u'StatusLabel').encode('utf-8')
    page['moreByDeveloperLabel'] = NSLocalizedString(
                                    u'More by %s',
                                    u'MoreByDeveloperLabel').encode('utf-8')
    page['moreInCategoryLabel'] = NSLocalizedString(
                                    u'More in %s',
                                    u'MoreInCategoryLabel').encode('utf-8')
    page['typeLabel'] = NSLocalizedString(
                                    u'Type:', u'TypeLabel').encode('utf-8')
    page['dueLabel'] = NSLocalizedString(
                                    u'Due:', u'DueLabel').encode('utf-8')


def setupHtmlDir():
    '''sets up our local html cache directory'''
    bundle_id = NSBundle.mainBundle().bundleIdentifier()
    cache_dir_urls = NSFileManager.defaultManager().URLsForDirectory_inDomains_(
        NSCachesDirectory, NSUserDomainMask)
    if cache_dir_urls:
        cache_dir = cache_dir_urls[0].path()
    else:
        cache_dir = '/private/tmp'
    our_cache_dir = os.path.join(cache_dir, bundle_id)
    if not os.path.exists(our_cache_dir):
         os.mkdir(our_cache_dir)
    html_dir = os.path.join(our_cache_dir, 'html')
    if os.path.exists(html_dir):
        # empty it
        shutil.rmtree(html_dir)
    os.mkdir(html_dir)
    # symlink our static files dir
    resourcesPath = NSBundle.mainBundle().resourcePath()
    source_path = os.path.join(resourcesPath, 'WebResources')
    link_path = os.path.join(html_dir, 'static')
    os.symlink(source_path, link_path)
    return html_dir


def getIcon(item, html_dir):
    '''Return name/relative path of image file to use for the icon'''
    for key in ['icon_name', 'display_name', 'name']:
        if key in item:
            name = item[key]
            icon_path = os.path.join(html_dir, name + '.png')
            if os.path.exists(icon_path) or convertIconToPNG(name, icon_path, 350):
                return name + '.png'
    else:
        # use the Generic package icon
        return 'static/Generic.png'


def guessDeveloper(item):
    '''Figure out something to use for the developer name'''
    if item.get('apple_item'):
        return 'Apple'
    if item.get('installer_type', '').startswith('Adobe'):
        return 'Adobe'
    # now we must dig
    if item.get('installs'):
        for install_item in item['installs']:
            if install_item.get('CFBundleIdentifier'):
                parts = install_item['CFBundleIdentifier'].split('.')
                if len(parts) > 1 and parts[0] in ['com', 'org', 'net', 'edu']:
                    return parts[1].title().encode('utf-8')
    return ''


def get_template(template_name):
    '''return an html template'''
    resourcesPath = NSBundle.mainBundle().resourcePath()
    templatePath = os.path.join(resourcesPath, 'templates', template_name)
    try:
        file_ref = open(templatePath)
        template_html = file_ref.read()
        file_ref.close()
        return Template(template_html)
    except (IOError, OSError):
        return None

