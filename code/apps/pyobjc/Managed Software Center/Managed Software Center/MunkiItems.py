# encoding: utf-8
#
#  MunkiItems.py
#  Managed Software Center
#
#  Created by Greg Neagle on 2/21/14.
#
# Copyright 2014-2019 Greg Neagle.
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

import os
#import sys
import msclib
import munki

from operator import itemgetter
from HTMLParser import HTMLParser, HTMLParseError

# pylint: disable=wildcard-import
from CocoaWrapper import *
# pylint: enable=wildcard-import

# PyLint cannot properly find names inside Cocoa libraries, so issues bogus
# No name 'Foo' in module 'Bar' warnings. Disable them.
# pylint: disable=no-name-in-module
from Quartz import (CGImageSourceCreateWithURL, CGImageSourceCreateImageAtIndex,
                    CGImageDestinationCreateWithURL, CGImageDestinationAddImage,
                    CGImageDestinationFinalize,
                    CGImageSourceGetCount, CGImageSourceCopyPropertiesAtIndex,
                    kCGImagePropertyDPIHeight, kCGImagePropertyPixelHeight)
# pylint: enable=no-name-in-module

import FoundationPlist

# Disable PyLint complaining about 'invalid' camelCase names
# pylint: disable=C0103

user_install_selections = set()
user_removal_selections = set()

# place to cache our expensive-to-calculate data
_cache = {}


def quote(a_string):
    '''Replacement for urllib.quote that handles Unicode strings'''
    return str(
        NSString.stringWithString_(
            a_string).stringByAddingPercentEscapesUsingEncoding_(
                NSUTF8StringEncoding))


def reset():
    '''clear all our cached values'''
    global _cache
    _cache = {}


def getAppleUpdates():
    if not 'apple_updates' in _cache:
        _cache['apple_updates'] = munki.getAppleUpdates()
    return _cache['apple_updates']


def getInstallInfo():
    if not 'install_info' in _cache:
        _cache['install_info'] = munki.getInstallInfo()
    return _cache['install_info']


def getOptionalInstallItems():
    if munki.pref('AppleSoftwareUpdatesOnly'):
        return []
    if not 'optional_install_items' in _cache:
        _cache['optional_install_items'] = [
            OptionalItem(item)
            for item in getInstallInfo().get('optional_installs', [])]
        featured_items = getInstallInfo().get('featured_items', [])
        for item in _cache['optional_install_items']:
            if item['name'] in featured_items:
                item['featured'] = True
    return _cache['optional_install_items']


def getProblemItems():
    if not 'problem_items' in _cache:
        problem_items = getInstallInfo().get('problem_items', [])
        for item in problem_items:
            item['status'] = 'problem-item'
        _cache['problem_items'] = sorted(
            [UpdateItem(item) for item in problem_items],
            key=itemgetter('due_date_sort', 'restart_sort',
                           'developer_sort', 'size_sort'))
    return _cache['problem_items']


def updateCheckNeeded():
    '''Returns True if any item in optional installs list has
    'updatecheck_needed' == True'''
    return len([item for item in getOptionalInstallItems()
                if item.get('updatecheck_needed')]) != 0


def optionalItemForName_(item_name):
    for item in getOptionalInstallItems():
        if item['name'] == item_name:
            return item
    return None


def getOptionalWillBeInstalledItems():
    return [item for item in getOptionalInstallItems()
            if item['status'] in ['install-requested', 'will-be-installed',
                                  'update-will-be-installed', 'install-error']]


def getOptionalWillBeRemovedItems():
    return [item for item in getOptionalInstallItems()
            if item['status'] in ['removal-requested', 'will-be-removed',
                                  'removal-error']]


def getUpdateList():
    if not 'update_list'in _cache:
        _cache['update_list'] = _build_update_list()
    return _cache['update_list']


def display_name(item_name):
    '''Returns a display_name for item_name, or item_name if not found'''
    for item in getOptionalInstallItems():
        if item['name'] == item_name:
            return item['display_name']
    return item_name


def _build_update_list():
    update_items = []
    if not munki.munkiUpdatesContainAppleItems():
        apple_updates = getAppleUpdates()
        apple_update_items = apple_updates.get('AppleUpdates', [])
        for item in apple_update_items:
            item['developer'] = u'Apple'
            item['status'] = u'will-be-installed'
        update_items.extend(apple_update_items)

    install_info = getInstallInfo()
    managed_installs = install_info.get('managed_installs', [])
    for item in managed_installs:
        item['status'] = u'will-be-installed'
    update_items.extend(managed_installs)

    removal_items = install_info.get('removals', [])
    for item in removal_items:
        item['status'] = u'will-be-removed'
    # TO-DO: handle the case where removal detail is suppressed
    update_items.extend(removal_items)

#    problem_items = install_info.get('problem_items', [])
#    for item in problem_items:
#        item['status'] = u'problem-item'
#    update_items.extend(problem_items)

    # use our list to make UpdateItems
    update_list = [UpdateItem(item) for item in update_items]
    # sort it and return it
    return sorted(update_list, key=itemgetter(
        'due_date_sort', 'restart_sort', 'developer_sort', 'size_sort'))


def updatesRequireLogout():
    '''Return True if any item in the update list requires a logout or if
    Munki's InstallRequiresLogout preference is true.'''
    if munki.installRequiresLogout():
        return True
    return len([item for item in getUpdateList()
                if 'Logout' in item.get('RestartAction', '')]) > 0


def updatesRequireRestart():
    '''Return True if any item in the update list requires a restart'''
    return len([item for item in getUpdateList()
                if 'Restart' in item.get('RestartAction', '')]) > 0


def updatesContainNonUserSelectedItems():
    '''Does the list of updates contain items not selected by the user?'''
    if not munki.munkiUpdatesContainAppleItems() and getAppleUpdates():
        # available Apple updates are not user selected
        return True
    install_info = getInstallInfo()
    install_items = install_info.get('managed_installs', [])
    removal_items = install_info.get('removals', [])
    filtered_installs = [item for item in install_items
                         if item['name'] not in user_install_selections]
    if filtered_installs:
        return True
    filtered_uninstalls = [item for item in removal_items
                           if item['name'] not in user_removal_selections]
    if filtered_uninstalls:
        return True
    return False


def getEffectiveUpdateList():
    '''Combine the updates Munki has found with any optional choices to
       make the effective list of updates'''
    # get pending optional items separately since OptionalItems have
    # extra details/attributes
    optional_installs = getOptionalWillBeInstalledItems()
    optional_removals = getOptionalWillBeRemovedItems()
    optional_item_names = [item['name']
                           for item in optional_installs + optional_removals]
    # filter out pending optional items from the list of all pending updates
    # so we can add in the items with additional optional detail
    mandatory_updates = [item for item in getUpdateList()
                         if item['name'] not in optional_item_names]

    return mandatory_updates + optional_installs + optional_removals


def getMyItemsList():
    '''Returns a list of optional_installs items the user has chosen
        to install or to remove'''
    self_service_installs = SelfService().installs()
    self_service_uninstalls = SelfService().uninstalls()
    item_list = [item for item in getOptionalInstallItems()
                 if item['name'] in self_service_installs]
    items_to_remove = [item for item in getOptionalInstallItems()
                       if item['name'] in self_service_uninstalls
                       and item.get('installed')]
    item_list.extend(items_to_remove)
    return item_list


def dependentItems(this_name):
    '''Returns the names of any selected optional items that require this
    optional item'''
    if not 'optional_installs_with_dependencies' in _cache:
        self_service_installs = SelfService().installs()
        optional_installs = getInstallInfo().get('optional_installs', [])
        _cache['optional_installs_with_dependencies'] = [
            item for item in optional_installs
            if item['name'] in self_service_installs and 'requires' in item]
    dependent_items = []
    for item in _cache['optional_installs_with_dependencies']:
        if this_name in item['requires']:
            dependent_items.append(item['name'])
    return dependent_items


def convertIconToPNG(app_name, destination_path, desired_size):
    '''Converts an application icns file to a png file, choosing the
    representation closest to (but >= than if possible) the desired_size.
    Returns True if successful, False otherwise'''
    # find the application
    app_path = os.path.join('/Applications', app_name + '.app')
    if not os.path.exists(app_path):
        return False
    try:
        # read the Info.plist
        info = FoundationPlist.readPlist(
            os.path.join(app_path, 'Contents/Info.plist'))
    except FoundationPlist.FoundationPlistException:
        info = {}
    try:
        try:
            # look for an icon name in the Info.plist, falling back to the
            # appname
            icon_filename = info.get('CFBundleIconFile', app_name)
        except AttributeError:
            icon_filename = app_name
        icon_path = os.path.join(app_path, 'Contents/Resources', icon_filename)
        if not os.path.splitext(icon_path)[1]:
            # no file extension, so add '.icns'
            icon_path += u'.icns'
        if os.path.exists(icon_path):
            # we found an icns file, convert to png
            icns_url = NSURL.fileURLWithPath_(icon_path)
            png_url = NSURL.fileURLWithPath_(destination_path)
            desired_dpi = 72

            image_source = CGImageSourceCreateWithURL(icns_url, None)
            if not image_source:
                return False
            number_of_images = CGImageSourceGetCount(image_source)
            if number_of_images == 0:
                return False

            selected_index = 0
            candidate = {}
            # iterate through the individual icon sizes to find the "best" one
            for index in range(number_of_images):
                try:
                    properties = CGImageSourceCopyPropertiesAtIndex(
                        image_source, index, None)
                    dpi = int(properties.get(kCGImagePropertyDPIHeight, 0))
                    height = int(properties.get(kCGImagePropertyPixelHeight, 0))
                    if (not candidate or
                            (height < desired_size and
                             height > candidate['height']) or
                            (height >= desired_size and
                             height < candidate['height']) or
                            (height == candidate['height'] and
                             dpi == desired_dpi)):
                        candidate = {'index': index, 'dpi': dpi,
                                     'height': height}
                        selected_index = index
                except ValueError:
                    pass

            image = CGImageSourceCreateImageAtIndex(
                image_source, selected_index, None)
            image_dest = CGImageDestinationCreateWithURL(
                png_url, 'public.png', 1, None)
            CGImageDestinationAddImage(image_dest, image, None)
            return CGImageDestinationFinalize(image_dest)

    except Exception:
        return False

    return False


class MSCHTMLFilter(HTMLParser):
    '''Filters HTML and HTML fragments for use inside description paragraphs'''
    def __init__(self):
        HTMLParser.__init__(self)
        # ignore everything inside one of these tags
        self.ignore_elements = ['script', 'style', 'head', 'table', 'form']
        # preserve these tags
        self.preserve_tags = ['a', 'b', 'i', 'strong', 'em', 'small', 'sub',
                              'sup', 'ins', 'del', 'mark', 'span', 'br', 'img']
        # transform these tags
        self.transform_starttags = {'ul': '<br>',
                                    'ol': '<br>',
                                    'li': '&nbsp;&nbsp;&bull; ',
                                    'h1': '<strong>',
                                    'h2': '<strong>',
                                    'h3': '<strong>',
                                    'h4': '<strong>',
                                    'h5': '<strong>',
                                    'h6': '<strong>',
                                    'p': ''}
        self.transform_endtags = {'ul': '<br>',
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
        self.current_ignore_element = None
        # track the number of tags we found
        self.tag_count = 0
        # track the number of HTML entities we found
        self.entity_count = 0
        # store our filtered/transformed html fragment
        self.filtered_html = u''

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
        self.entity_count += 1
        if not self.current_ignore_element:
            # add the entity reference as-is
            self.filtered_html += u'&%s;' % name

    def handle_charref(self, name):
        self.entity_count += 1
        if not self.current_ignore_element:
            # add the char reference as-is
            self.filtered_html += u'&#%s;' % name


def filtered_html(text, filter_images=False):
    '''Returns filtered HTML for use in description paragraphs
       or converts plain text into basic HTML for the same use'''
    parser = MSCHTMLFilter()
    if filter_images:
        parser.preserve_tags.remove('img')
    parser.feed(text)
    if parser.tag_count or parser.entity_count:
        # found at least one HTML tag or HTML entity, so this is probably HTML
        return parser.filtered_html
    else:
        # might be plain text, so we should escape a few entities and
        # add <br> for line breaks
        text = text.replace('&', '&amp;')
        text = text.replace('<', '&lt;')
        text = text.replace('>', '&gt;')
        return text.replace('\n', '<br>\n')


def post_install_request_notification(event, item):
    '''Post an NSDistributedNotification to be recorded by the
    app_usage_monitor'''
    user_info = {'event': event,
                 'name': item['name'],
                 'version': item.get('version_to_install', '0')}
    dnc = NSDistributedNotificationCenter.defaultCenter()
    dnc.postNotificationName_object_userInfo_options_(
        'com.googlecode.munki.managedsoftwareupdate.installrequest',
        None,
        user_info,
        NSNotificationDeliverImmediately + NSNotificationPostToAllSessions)


class SelfServiceError(Exception):
    '''General error class for SelfService exceptions'''
    pass


class SelfService(object):
    '''An object to wrap interactions with the SelfServiceManifest'''
    def __init__(self):
        self._installs = set(
            munki.readSelfServiceManifest().get('managed_installs', []))
        self._uninstalls = set(
            munki.readSelfServiceManifest().get('managed_uninstalls', []))

    def __eq__(self, other):
        return (sorted(self._installs) == sorted(other._installs)
                and sorted(self._uninstalls) == sorted(other._uninstalls))

    def __ne__(self, other):
        return (sorted(self._installs) != sorted(other._installs)
                or sorted(self._uninstalls) != sorted(other._uninstalls))

    def installs(self):
        return list(self._installs)

    def uninstalls(self):
        return list(self._uninstalls)

    def subscribe(self, item):
        self._installs.add(item['name'])
        self._uninstalls.discard(item['name'])
        self._save_self_service_choices()

    def unsubscribe(self, item):
        self._installs.discard(item['name'])
        self._uninstalls.add(item['name'])
        self._save_self_service_choices()

    def unmanage(self, item):
        self._installs.discard(item['name'])
        self._uninstalls.discard(item['name'])
        self._save_self_service_choices()

    def _save_self_service_choices(self):
        current_choices = {}
        current_choices['managed_installs'] = list(self._installs)
        current_choices['managed_uninstalls'] = list(self._uninstalls)
        if not munki.writeSelfServiceManifest(current_choices):
            raise SelfServiceError(
                'Could not save self-service choices to %s'
                % munki.WRITEABLE_SELF_SERVICE_MANIFEST_PATH)

def subscribe(item):
    '''Add item to SelfServeManifest's managed_installs.
       Also track user selections.'''
    SelfService().subscribe(item)
    user_install_selections.add(item['name'])
    post_install_request_notification('install', item)


def unsubscribe(item):
    '''Add item to SelfServeManifest's managed_uninstalls.
       Also track user selections.'''
    SelfService().unsubscribe(item)
    user_removal_selections.add(item['name'])
    post_install_request_notification('remove', item)


def unmanage(item):
    '''Remove item from SelfServeManifest.
       Also track user selections.'''
    SelfService().unmanage(item)
    user_install_selections.discard(item['name'])
    user_removal_selections.discard(item['name'])


def getLocalizedShortNoteForItem(item, is_update=False):
    '''Attempt to localize a note. Currently handle only two types.'''
    note = item.get('note')
    if is_update:
        return NSLocalizedString(u"Update available",
                                 u"Update available display text")
    if note.startswith('Insufficient disk space to download and install'):
        return NSLocalizedString(u"Not enough disk space",
                                 u"Not Enough Disk Space display text")
    if note.startswith('Requires macOS version '):
        return NSLocalizedString(u"macOS update required",
                                 u"macOS update required text")
    # we don't know how to localize this note, return None
    return None


def getLocalizedLongNoteForItem(item, is_update=False):
    '''Attempt to localize a note. Currently handle only two types.'''
    note = item.get('note')
    if note.startswith('Insufficient disk space to download and install'):
        if is_update:
            return NSLocalizedString(
                u"An older version is currently installed. There is not enough "
                "disk space to download and install this update.",
                u"Long Not Enough Disk Space For Update display text")
        else:
            return NSLocalizedString(
                u"There is not enough disk space to download and install this "
                "item.",
                u"Long Not Enough Disk Space display text")
    if note.startswith('Requires macOS version '):
        if is_update:
            base_string = NSLocalizedString(
                u"An older version is currently installed. You must upgrade to "
                "macOS version %s or higher to be able to install this update.",
                u"Long update requires a higher OS version text")
        else:
            base_string = NSLocalizedString(
                u"You must upgrade to macOS version %s to be able to "
                "install this item.",
                u"Long item requires a higher OS version text")
        os_version = item.get('minimum_os_version', 'UNKNOWN')
        return base_string % os_version
    # we don't know how to localize this note, return None
    return None

class GenericItem(dict):
    '''Base class for our types of Munki items'''

    def __init__(self, *arg, **kw):
        super(GenericItem, self).__init__(*arg, **kw)
        if self.get('localized_strings'):
            self.add_localizations()
        # now normalize values
        if not self.get('display_name'):
            self['display_name'] = self['name']
        self['display_name_lower'] = self['display_name'].lower()
        if not self.get('developer'):
            self['developer'] = self.guess_developer()
        if self.get('description'):
            try:
                self['raw_description'] = filtered_html(self['description'])
            except HTMLParseError:
                self['raw_description'] = (
                    'Invalid HTML in description for %s' % self['display_name'])
            del self['description']
        if not 'raw_description' in self:
            self['raw_description'] = u''
            del self['description']
        self['icon'] = self.getIcon()
        self['due_date_sort'] = NSDate.distantFuture()
        # sort items that need restart highest, then logout, then other
        self['restart_action_text'] = u''
        self['restart_sort'] = 2
        if self.get('RestartAction') in ['RequireRestart', 'RecommendRestart']:
            self['restart_sort'] = 0
            self['restart_action_text'] = NSLocalizedString(
                u"Restart Required", u"Restart Required title")
            self['restart_action_text'] += (
                u'<div class="restart-needed-icon"></div>')
        elif self.get('RestartAction') in ['RequireLogout', 'RecommendLogout']:
            self['restart_sort'] = 1
            self['restart_action_text'] = NSLocalizedString(
                u"Logout Required", u"Logout Required title")
            self['restart_action_text'] += (
                u'<div class="logout-needed-icon"></div>')

        # sort bigger installs to the top
        if self.get('installed_size'):
            self['size_sort'] = -int(self['installed_size'])
            self['size'] = munki.humanReadable(self['installed_size'])
        elif self.get('installer_item_size'):
            self['size_sort'] = -int(self['installer_item_size'])
            self['size'] = munki.humanReadable(self['installer_item_size'])
        else:
            self['size_sort'] = 0
            self['size'] = u''

    def __getitem__(self, name):
        '''Allow access to instance variables and methods via dictionary syntax.
           This allows us to use class instances as a data source
           for our HTML templates (which want a dictionary-like object)'''
        try:
            return super(GenericItem, self).__getitem__(name)
        except KeyError, err:
            try:
                attr = getattr(self, name)
            except AttributeError:
                raise KeyError(err)
            if callable(attr):
                return attr()
            else:
                return attr

    def description(self):
        return self['raw_description']

    def description_without_images(self):
        return filtered_html(self.description(), filter_images=True)

    def dependency_description(self):
        '''Return an html description of items this item depends on'''
        description = u''
        prologue = NSLocalizedString(
            u"This item is required by:", u"Dependency List prologue text")
        if self.get('dependent_items'):
            description = u'<strong>' + prologue
            for item in self['dependent_items']:
                description += u'<br/>&nbsp;&nbsp;&bull; ' + display_name(item)
            description += u'</strong><br/><br/>'
        return description

    def guess_developer(self):
        '''Figure out something to use for the developer name'''
        if self.get('apple_item'):
            return 'Apple'
        if self.get('installer_type', '').startswith('Adobe'):
            return 'Adobe'
        # now we must dig
        if self.get('installs'):
            for install_item in self['installs']:
                if install_item.get('CFBundleIdentifier'):
                    parts = install_item['CFBundleIdentifier'].split('.')
                    if (len(parts) > 1
                            and parts[0] in ['com', 'org', 'net', 'edu']):
                        return parts[1].title()
        return ''

    def getIcon(self):
        '''Return name/relative path of image file to use for the icon'''
        # first look for downloaded icons
        icon_known_exts = ['.bmp', '.gif', '.icns', '.jpg', '.jpeg', '.png',
                           '.psd', '.tga', '.tif', '.tiff', '.yuv']
        icon_name = self.get('icon_name') or self['name']
        if not os.path.splitext(icon_name)[1] in icon_known_exts:
            icon_name += '.png'
        icon_path = os.path.join(msclib.html_dir(), 'icons', icon_name)
        if os.path.exists(icon_path):
            return 'icons/' + quote(icon_name)
        # didn't find one in the downloaded icons
        # so create one if needed from a locally installed app
        for key in ['icon_name', 'display_name', 'name']:
            if key in self:
                name = self[key]
                icon_name = name
                if not os.path.splitext(icon_name)[1] in icon_known_exts:
                    icon_name += '.png'
                icon_path = os.path.join(msclib.html_dir(), icon_name)
                if (os.path.exists(icon_path)
                        or convertIconToPNG(name, icon_path, 350)):
                    return quote(icon_name)

        # use the Generic package icon
        return 'static/Generic.png'

    def unavailable_reason_text(self, is_update=False):
        '''There are several reasons an item might be unavailable for install.
           Return the relevant reason'''
        if ('licensed_seats_available' in self
                and not self['licensed_seats_available']):
            return NSLocalizedString(u"No licenses available",
                                     u"No Licenses Available display text")
        localizedNote = getLocalizedShortNoteForItem(self, is_update=is_update)
        if localizedNote:
            return '<span class="warning">' + localizedNote + '</span>'
        # return generic reason
        return NSLocalizedString(u"Not currently available",
                                 u"Not Currently Available display text")

    def status_text(self):
        '''Return localized status display text'''
        if self['status'] == 'unavailable':
            return self.unavailable_reason_text()
        if (self['status'] in ['installed', 'installed-not-removable'] and
                self.get('note')):
            return self.unavailable_reason_text(is_update=True)
        text_map = {
            'install-error':
                NSLocalizedString(u"Installation Error",
                                  u"Install Error status text"),
            'removal-error':
                NSLocalizedString(u"Removal Error",
                                  u"Removal Error status text"),
            'installed':
                NSLocalizedString(u"Installed",
                                  u"Installed status text"),
            'installing':
                NSLocalizedString(u"Installing",
                                  u"Installing status text"),
            'installed-not-removable':
                NSLocalizedString(u"Installed",
                                  u"Installed status text"),
            'not-installed':
                NSLocalizedString(u"Not installed",
                                  u"Not Installed status text"),
            'install-requested':
                NSLocalizedString(u"Install requested",
                                  u"Install Requested status text"),
            'downloading':
                NSLocalizedString(u"Downloading",
                                  u"Downloading status text"),
            'will-be-installed':
                NSLocalizedString(u"Will be installed",
                                  u"Will Be Installed status text"),
            'must-be-installed':
                NSLocalizedString(u"Will be installed",
                                  u"Will Be Installed status text"),
            'removal-requested':
                NSLocalizedString(u"Removal requested",
                                  u"Removal Requested status text"),
            'preparing-removal':
                NSLocalizedString(u"Preparing removal",
                                  u"Preparing Removal status text"),
            'will-be-removed':
                NSLocalizedString(u"Will be removed",
                                  u"Will Be Removed status text"),
            'removing':
                NSLocalizedString(u"Removing",
                                  u"Removing status text"),
            'update-will-be-installed':
                NSLocalizedString(u"Update will be installed",
                                  u"Update Will Be Installed status text"),
            'update-must-be-installed':
                NSLocalizedString(u"Update will be installed",
                                  u"Update Will Be Installed status text"),
            'update-available':
                NSLocalizedString(u"Update available",
                                  u"Update Available status text"),
            'unavailable':
                NSLocalizedString(u"Unavailable",
                                  u"Unavailable status text"),
        }
        return text_map.get(self['status'], self['status'])

    def short_action_text(self):
        '''Return localized 'short' action text for button'''
        text_map = {
            'install-error':
                NSLocalizedString(u"Cancel",
                                  u"Cancel button title/short action text"),
            'removal-error':
                NSLocalizedString(u"Cancel",
                                  u"Cancel button title/short action text"),
            'installed':
                NSLocalizedString(u"Remove",
                                  u"Remove action text"),
            'installing':
                NSLocalizedString(u"Installing",
                                  u"Installing status text"),
            'installed-not-removable':
                NSLocalizedString(u"Installed",
                                  u"Installed status text"),
            'not-installed':
                NSLocalizedString(u"Install",
                                  u"Install action text"),
            'install-requested':
                NSLocalizedString(u"Cancel",
                                  u"Cancel button title/short action text"),
            'downloading':
                NSLocalizedString(u"Cancel",
                                  u"Cancel button title/short action text"),
            'will-be-installed':
                NSLocalizedString(u"Cancel",
                                  u"Cancel button title/short action text"),
            'must-be-installed':
                NSLocalizedString(u"Required",
                                  u"Install Required action text"),
            'removal-requested':
                NSLocalizedString(u"Cancel",
                                  u"Cancel button title/short action text"),
            'preparing-removal':
                NSLocalizedString(u"Cancel",
                                  u"Cancel button title/short action text"),
            'will-be-removed':
                NSLocalizedString(u"Cancel",
                                  u"Cancel button title/short action text"),
            'removing':
                NSLocalizedString(u"Removing",
                                  u"Removing status text"),
            'update-will-be-installed':
                NSLocalizedString(u"Cancel",
                                  u"Cancel button title/short action text"),
            'update-must-be-installed':
                NSLocalizedString(u"Required",
                                  u"Install Required action text"),
            'update-available':
                NSLocalizedString(u"Update",
                                  u"Update button title/action text"),
            'unavailable':
                NSLocalizedString(u"Unavailable",
                                  u"Unavailable status text"),
        }
        return text_map.get(self['status'], self['status'])

    def long_action_text(self):
        '''Return localized 'long' action text for button'''
        text_map = {
            'install-error':
                NSLocalizedString(u"Cancel install",
                                  u"Cancel Install long action text"),
            'removal-error':
                NSLocalizedString(u"Cancel removal",
                                  u"Cancel Removal long action text"),
            'installed':
                NSLocalizedString(u"Remove",
                                  u"Remove action text"),
            'installing':
                NSLocalizedString(u"Installing",
                                  u"Installing status text"),
            'installed-not-removable':
                NSLocalizedString(u"Installed",
                                  u"Installed status text"),
            'not-installed':
                NSLocalizedString(u"Install",
                                  u"Install action text"),
            'install-requested':
                NSLocalizedString(u"Cancel install",
                                  u"Cancel Install long action text"),
            'downloading':
                NSLocalizedString(u"Cancel install",
                                  u"Cancel Install long action text"),
            'will-be-installed':
                NSLocalizedString(u"Cancel install",
                                  u"Cancel Install long action text"),
            'must-be-installed':
                NSLocalizedString(u"Install Required",
                                  u"Install Required action text"),
            'removal-requested':
                NSLocalizedString(u"Cancel removal",
                                  u"Cancel Removal long action text"),
            'preparing-removal':
                NSLocalizedString(u"Cancel removal",
                                  u"Cancel Removal long action text"),
            'will-be-removed':
                NSLocalizedString(u"Cancel removal",
                                  u"Cancel Removal long action text"),
            'removing':
                NSLocalizedString(u"Removing",
                                  u"Removing status text"),
            'update-will-be-installed':
                NSLocalizedString(u"Cancel update",
                                  u"Cancel Update long action text"),
            'update-must-be-installed':
                NSLocalizedString(u"Update Required",
                                  u"Update Required long action text"),
            'update-available':
                NSLocalizedString(u"Update",
                                  u"Update button title/action text"),
            'unavailable':
                NSLocalizedString(u"Currently Unavailable",
                                  u"Unavailable long action text"),
        }
        return text_map.get(self['status'], self['status'])

    def myitem_action_text(self):
        '''Return localized 'My Items' action text for button'''
        text_map = {
            'install-error':
                NSLocalizedString(u"Cancel install",
                                  u"Cancel Install long action text"),
            'removal-error':
                NSLocalizedString(u"Cancel removal",
                                  u"Cancel Removal long action text"),
            'installed':
                NSLocalizedString(u"Remove",
                                  u"Remove action text"),
            'installing':
                NSLocalizedString(u"Installing",
                                  u"Installing status text"),
            'installed-not-removable':
                NSLocalizedString(u"Installed",
                                  u"Installed status text"),
            'removal-requested':
                NSLocalizedString(u"Cancel removal",
                                  u"Cancel Removal long action text"),
            'preparing-removal':
                NSLocalizedString(u"Cancel removal",
                                  u"Cancel Removal long action text"),
            'will-be-removed':
                NSLocalizedString(u"Cancel removal",
                                  u"Cancel Removal long action text"),
            'removing':
                NSLocalizedString(u"Removing",
                                  u"Removing status text"),
            'update-available':
                NSLocalizedString(u"Update",
                                  u"Update button title/action text"),
            'update-will-be-installed':
                NSLocalizedString(u"Remove",
                                  u"Remove action text"),
            'update-must-be-installed':
                NSLocalizedString(u"Update Required",
                                  u"Update Required long action text"),
            'install-requested':
                NSLocalizedString(u"Cancel install",
                                  u"Cancel Install long action text"),
            'downloading':
                NSLocalizedString(u"Cancel install",
                                  u"Cancel Install long action text"),
            'will-be-installed':
                NSLocalizedString(u"Cancel install",
                                  u"Cancel Install long action text"),
            'must-be-installed':
                NSLocalizedString(u"Required",
                                  u"Install Required action text"),
        }
        return text_map.get(self['status'], self['status'])

    def version_label(self):
        '''Text for the version label'''
        if self['status'] == 'will-be-removed':
            removal_text = NSLocalizedString(
                u"Will be removed", u"Will Be Removed status text")
            return '<span class="warning">%s</span>' % removal_text
        if self['status'] == 'removal-requested':
            removal_text = NSLocalizedString(
                u"Removal requested", u"Removal Requested status text")
            return '<span class="warning">%s</span>' % removal_text
        else:
            return NSLocalizedString(u"Version", u"Sidebar Version label")

    def display_version(self):
        '''Version number for display'''
        if self['status'] == 'will-be-removed':
            return ''
        else:
            return self.get('version_to_install', '')

    def developer_sort(self):
        '''returns sort priority based on developer and install/removal
        status'''
        if self['status'] != 'will-be-removed' and self['developer'] == 'Apple':
            return 0
        return 1

    def more_link_text(self):
        return NSLocalizedString(u"More", u"More link text")

    def add_localizations(self):
        available_locales = list(self['localized_strings'])
        fallback_locale = self['localized_strings'].get('fallback_locale')
        if fallback_locale:
            available_locales.remove('fallback_locale')
            available_locales.append(fallback_locale)
        language_code = self._get_preferred_locale(available_locales)
        if language_code != fallback_locale:
            locale_dict = self['localized_strings'].get(language_code)
            if locale_dict:
                localized_keys = ['category',
                                  'description',
                                  'display_name',
                                  'preinstall_alert',
                                  'preuninstall_alert',
                                  'preupgrade_alert']
                for key in localized_keys:
                    if key in locale_dict:
                        self[key] = locale_dict[key]

    def _get_preferred_locale(self, available_locales):
        code = NSBundle.preferredLocalizationsFromArray_forPreferences_(
            available_locales, None)
        return code[0]

class OptionalItem(GenericItem):
    '''Dictionary subclass that models a given optional install item'''

    def __init__(self, *arg, **kw):
        '''Initialize an OptionalItem from a item dict from the
        InstallInfo.plist optional_installs array'''
        super(OptionalItem, self).__init__(*arg, **kw)
        if 'category' not in self:
            self['category'] = NSLocalizedString(u"Uncategorized",
                                                 u"No Category name")
        if 'featured' not in self:
            self['featured'] = False
        if self['developer']:
            self['category_and_developer'] = u'%s - %s' % (
                self['category'], self['developer'])
        else:
            self['category_and_developer'] = self['category']
        self['dependent_items'] = dependentItems(self['name'])
        if self.get('installer_item_size'):
            self['size'] = munki.humanReadable(self['installer_item_size'])
        elif self.get('installed_size'):
            self['size'] = munki.humanReadable(self['installed_size'])
        else:
            self['size'] = u''
        self['detail_link'] = u'detail-%s.html' % quote(self['name'])
        self['hide_cancel_button'] = u''
        if not self.get('note'):
            self['note'] = self._get_note_from_problem_items()
        if not self.get('status'):
            self['status'] = self._get_status()

    def _get_status(self):
        '''Calculates initial status for an item and also sets a boolean
        if a updatecheck is needed'''
        managed_update_names = getInstallInfo().get('managed_updates', [])
        self_service_installs = SelfService().installs()
        self_service_uninstalls = SelfService().uninstalls()
        self['updatecheck_needed'] = False
        self['user_directed_action'] = False
        if self.get('installed'):
            if self.get('removal_error'):
                status = u'removal-error'
            elif self.get('will_be_removed'):
                status = u'will-be-removed'
            elif self['dependent_items']:
                status = u'installed-not-removable'
            elif self['name'] in self_service_uninstalls:
                status = u'removal-requested'
                self['updatecheck_needed'] = True
            else: # not in managed_uninstalls
                if not self.get('needs_update'):
                    if self.get('uninstallable'):
                        status = u'installed'
                    else: # not uninstallable
                        status = u'installed-not-removable'
                else: # there is an update available
                    if self['name'] in managed_update_names:
                        status = u'update-must-be-installed'
                    elif self['dependent_items']:
                        status = u'update-must-be-installed'
                    elif self['name'] in self_service_installs:
                        status = u'update-will-be-installed'
                    else: # not in managed_installs
                        status = u'update-available'
        else: # not installed
            if self.get('install_error'):
                status = u'install-error'
            elif self.get('note'):
                # TO-DO: handle this case better
                # some reason we can't install
                # usually not enough disk space
                # but can also be:
                #   'Integrity check failed'
                #   'Download failed (%s)' % errmsg
                #   'Can\'t install %s because: %s', manifestitemname, errmsg
                #   'Insufficient disk space to download and install.'
                #   and others in the future
                #
                # for now we prevent install this way
                status = u'unavailable'
            elif ('licensed_seats_available' in self
                  and not self['licensed_seats_available']):
                status = u'unavailable'
            elif self['dependent_items']:
                status = u'must-be-installed'
            elif self.get('will_be_installed'):
                status = u'will-be-installed'
            elif self['name'] in self_service_installs:
                status = u'install-requested'
                self['updatecheck_needed'] = True
            else: # not in managed_installs
                status = u'not-installed'
        return status

    def _get_note_from_problem_items(self):
        '''Checks InstallInfo's problem_items for any notes for self that might
        give feedback why this item can't be downloaded or installed'''
        problem_items = getInstallInfo().get('problem_items', [])
        # check problem items for any whose name matches the name of
        # the current item
        matches = [item for item in problem_items
                   if item['name'] == self['name']]
        if len(matches):
            return matches[0].get('note', '')

    def description(self):
        '''return a full description for the item, inserting dynamic data
           if needed'''
        start_text = ''
        if self.get('install_error'):
            warning_text = NSLocalizedString(
                u"An installation attempt failed. "
                "Installation will be attempted again.\n"
                "If this situation continues, contact your systems "
                "administrator.",
                u"Install Error message")
            start_text += ('<span class="warning">%s</span><br/><br/>'
                           % filtered_html(warning_text))
        if self.get('removal_error'):
            warning_text = NSLocalizedString(
                u"A removal attempt failed. "
                "Removal will be attempted again.\n"
                "If this situation continues, contact your systems "
                "administrator.",
                u"Removal Error message")
            start_text += ('<span class="warning">%s</span><br/><br/>'
                           % filtered_html(warning_text))
        if self.get('note'):
            is_update = self['status'] in ['installed', 'installed-not-removable']
            warning_text = getLocalizedLongNoteForItem(self, is_update=is_update)
            if not warning_text:
                # some other note. Probably won't be localized, but we can try
                warning_text = NSBundle.mainBundle().localizedStringForKey_value_table_(
                    self['note'], self['note'], None)
            start_text += ('<span class="warning">%s</span><br/><br/>'
                           % filtered_html(warning_text))
        if self.get('dependent_items'):
            start_text += self.dependency_description()

        return start_text + self['raw_description']

    def update_status(self):
        # user clicked an item action button - update the item's state
        # also sets a boolean indicating if we should run an updatecheck
        self['updatecheck_needed'] = True
        original_status = self['status']
        managed_update_names = getInstallInfo().get('managed_updates', [])
        if self['status'] == 'update-available':
            # mark the update for install
            self['status'] = u'install-requested'
            subscribe(self)
        elif self['status'] == 'update-will-be-installed':
            # cancel the update
            self['status'] = u'update-available'
            unmanage(self)
        elif self['status'] in ['will-be-removed', 'removal-requested',
                                'preparing-removal', 'removal-error']:
            if self['name'] in managed_update_names:
                # update is managed, so user can't opt out
                self['status'] = u'installed'
            elif self.get('needs_update'):
                # update being installed; can opt-out
                self['status'] = u'update-will-be-installed'
            else:
                # item is simply installed
                self['status'] = u'installed'
            if self.get('was_self_service_install'):
                subscribe(self)
            else:
                unmanage(self)
            if original_status == 'removal-requested':
                self['updatecheck_needed'] = False
        elif self['status'] in ['will-be-installed', 'install-requested',
                                'downloading', 'install-error']:
            # cancel install
            if self.get('needs_update'):
                self['status'] = u'update-available'
            else:
                self['status'] = u'not-installed'
            unmanage(self)
            if original_status == 'install-requested':
                self['updatecheck_needed'] = False
        elif self['status'] == 'not-installed':
            # mark for install
            self['status'] = u'install-requested'
            subscribe(self)
        elif self['status'] == 'installed':
            # mark for removal
            self['status'] = u'removal-requested'
            if self['name'] in SelfService().installs():
                self['was_self_service_install'] = True
            unsubscribe(self)


class UpdateItem(GenericItem):
    '''GenericItem subclass that models an update install item'''

    def __init__(self, *arg, **kw):
        super(UpdateItem, self).__init__(*arg, **kw)
        identifier = (self.get('name', '') + '--version-'
                      + self.get('version_to_install', ''))
        self['detail_link'] = 'updatedetail-%s.html' % quote(identifier)
        if not self.get('status') == 'will-be-removed':
            force_install_after_date = self.get('force_install_after_date')
            if force_install_after_date:
                self['type'] = NSLocalizedString(
                    u"Critical Update", u"Critical Update type")
                self['due_date_sort'] = force_install_after_date

        if not 'type' in self:
            self['type'] = NSLocalizedString(u"Managed Update",
                                             u"Managed Update type")
        self['hide_cancel_button'] = u'hidden'
        self['dependent_items'] = dependentItems(self['name'])

    def description(self):
        start_text = ''
        if not self['status'] == 'will-be-removed':
            force_install_after_date = self.get('force_install_after_date')
            if force_install_after_date:
                # insert installation deadline into description
                try:
                    local_date = munki.discardTimeZoneFromDate(
                        force_install_after_date)
                except munki.BadDateError:
                    # some issue with the stored date
                    pass
                else:
                    date_str = munki.stringFromDate(local_date)
                    forced_date_text = NSLocalizedString(
                        u"This item must be installed by %s",
                        u"Forced Date warning")
                    start_text += ('<span class="warning">'
                                   + forced_date_text % date_str
                                   + '</span><br><br>')
            elif self['status'] == 'problem-item':
                if self.get('install_error'):
                    warning_text = NSLocalizedString(
                        u"An installation attempt failed. "
                        "Installation will be attempted again.\n"
                        "If this situation continues, contact your systems "
                        "administrator.",
                        u"Install Error message")
                    start_text += ('<span class="warning">%s</span><br/><br/>'
                                   % filtered_html(warning_text))
                elif self.get('removal_error'):
                    warning_text = NSLocalizedString(
                        u"A removal attempt failed. "
                        "Removal will be attempted again.\n"
                        "If this situation continues, contact your systems "
                        "administrator.",
                        u"Removal Error message")
                    start_text += ('<span class="warning">%s</span><br/><br/>'
                                   % filtered_html(warning_text))
                elif self.get('note'):
                    warning_text = getLocalizedLongNoteForItem(self)
                    if not warning_text:
                        # some other note. Probably won't be localized, but we can try
                        warning_text = NSBundle.mainBundle().localizedStringForKey_value_table_(
                            self['note'], self['note'], None)
                    start_text += ('<span class="warning">%s</span><br/><br/>'
                                   % filtered_html(warning_text))
            if self.get('dependent_items'):
                start_text += self.dependency_description()

        return start_text + self['raw_description']
