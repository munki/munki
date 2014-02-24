#
#  MunkiItems.py
#  Managed Software Center
#
#  Created by Greg Neagle on 2/21/14.
#
# Copyright 2009-2014 Greg Neagle.
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
import msulib
import munki

from operator import itemgetter
from urllib import quote_plus, unquote_plus

from Foundation import NSLocalizedString
from Foundation import NSDate
from Foundation import NSLog

_cache = {}
# cache reads from AppleUpdates.plist, InstallInfo.plist
_cache['apple_updates'] = None
_cache['install_info'] = None

# cache lists
_cache['optional_install_items'] = None
_cache['update_list'] = None


def reset():
    '''clear all our cached values'''
    for key in _cache.keys():
        _cache[key] = None


def getAppleUpdates():
    if _cache['apple_updates'] is None:
        _cache['apple_updates'] = munki.getAppleUpdates()
    return _cache['apple_updates']


def getInstallInfo():
    if _cache['install_info'] is None:
        _cache['install_info'] = munki.getInstallInfo()
    return _cache['install_info']


def getOptionalInstallItems():
    if _cache['optional_install_items'] is None:
        _cache['optional_install_items'] = [OptionalItem(item)
                                   for item in getInstallInfo().get('optional_installs', [])]
    return _cache['optional_install_items']


def optionalItemForName_(item_name):
    for item in getOptionalInstallItems():
        if item['name'] == item_name:
            return item
    return None


def getOptionalWillBeInstalledItems():
    return [item for item in getOptionalInstallItems()
            if item['status'] in ['will-be-installed', 'update-will-be-installed']]


def getOptionalWillBeRemovedItems():
    return [item for item in getOptionalInstallItems()
            if item['status'] == 'will-be-removed']


def getUpdateList():
    if _cache['update_list'] is None:
        _cache['update_list'] = _build_update_list()
    return _cache['update_list']


def _build_update_list():
    update_items = []
    if not munki.munkiUpdatesContainAppleItems():
        apple_updates = getAppleUpdates()
        apple_update_items = apple_updates.get('AppleUpdates', [])
        for item in apple_update_items:
            item['developer'] = 'Apple'
            item['status'] = 'will-be-installed'
        update_items.extend(apple_update_items)
    
    install_info = getInstallInfo()
    managed_installs = install_info.get('managed_installs', [])
    for item in managed_installs:
        item['status'] = 'will-be-installed'
    update_items.extend(managed_installs)
    
    removal_items = install_info.get('removals', [])
    for item in removal_items:
        item['status'] = 'will-be-removed'
    # TO-DO: handle the case where removal detail is suppressed
    update_items.extend(removal_items)
    # use our list to make UpdateItems
    update_list = [UpdateItem(item) for item in update_items]
    # sort it and return it
    return sorted(update_list, key=itemgetter(
                    'due_date_sort', 'restart_sort', 'developer_sort', 'size_sort'))


def getEffectiveUpdateList():
    '''Combine the updates Munki has found with any optional choices to
        make the effective list of updates'''
    update_list = getUpdateList()
    managed_update_names = getInstallInfo().get('managed_updates', [])
    optional_item_names = [item['name'] for item in getOptionalInstallItems()]
    self_service_uninstalls = munki.readSelfServiceManifest().get('managed_uninstalls', [])
    # items in the update_list that are part of optional_items
    # could have their installation state changed; so filter those out
    filtered_updates = [item for item in getUpdateList()
                        if (item['name'] in managed_update_names
                        and not item['name'] in self_service_uninstalls)
                        or item['name'] not in optional_item_names]
    optional_installs = getOptionalWillBeInstalledItems()
    optional_removals = getOptionalWillBeRemovedItems()
    return filtered_updates + optional_installs + optional_removals


def getMyItemsList():
    '''Returns a list of optional_installs items the user has chosen
        to install or to remove'''
    self_service_installs = munki.readSelfServiceManifest().get('managed_installs', [])
    self_service_uninstalls = munki.readSelfServiceManifest().get('managed_uninstalls', [])
    item_list = [item for item in getOptionalInstallItems()
                 if item['name'] in self_service_installs]
    items_to_remove = [item for item in getOptionalInstallItems()
                       if item['name'] in self_service_uninstalls
                       and item.get('installed')]
    item_list.extend(items_to_remove)
    return item_list


class SelfService(object):
    '''An object to wrap interactions with the SelfServiceManifest'''
    def __init__(self):
        self.self_service_installs = set(
            munki.readSelfServiceManifest().get('managed_installs', []))
        self.self_service_uninstalls = set(
            munki.readSelfServiceManifest().get('managed_uninstalls', []))

    def subscribe(self, item):
        self.self_service_installs.add(item['name'])
        self.self_service_uninstalls.discard(item['name'])
        self._save_self_service_choices()

    def unsubscribe(self, item):
        self.self_service_installs.discard(item['name'])
        self.self_service_uninstalls.add(item['name'])
        self._save_self_service_choices()
    
    def unmanage(self, item):
        self.self_service_installs.discard(item['name'])
        self.self_service_uninstalls.discard(item['name'])
        self._save_self_service_choices()

    def _save_self_service_choices(self):
        current_choices = {}
        current_choices['managed_installs'] = list(self.self_service_installs)
        current_choices['managed_uninstalls'] = list(self.self_service_uninstalls)
        munki.writeSelfServiceManifest(current_choices)


def subscribe(item):
    SelfService().subscribe(item)


def unsubscribe(item):
    SelfService().unsubscribe(item)


def unmanage(item):
    SelfService().unmanage(item)


class GenericItem(dict):
    '''Base class for our types of Munki items'''
    
    def __init__(self, *arg, **kw):
        super(GenericItem, self).__init__(*arg, **kw)
        # now normalize values
        for key, value in self.items():
            if isinstance(value, unicode):
                self[key] = value.encode('utf-8')
        if not self.get('display_name'):
            self['display_name'] = self['name']
        self['display_name_lower'] = self['display_name'].lower()
        if not self.get('developer'):
            self['developer'] = self.guess_developer()
        if self.get('description'):
            self['description'] = msulib.filtered_html(self['description'])
        else:
            self['description'] = ''
        self['icon'] = self.getIcon()
        self['version_label'] = NSLocalizedString(
                                        u'Version',
                                        u'VersionLabel').encode('utf-8')
        self['due_date_sort'] = NSDate.distantFuture()
        # sort items that need restart highest, then logout, then other
        if self.get('RestartAction') in [None, 'None']:
            self['restart_action_text'] = ''
            self['restart_sort'] = 2
        elif self['RestartAction'] in ['RequireRestart', 'RecommendRestart']:
            self['restart_sort'] = 0
            self['restart_action_text'] = NSLocalizedString(
                u'Restart Required', u'RequireRestartMessage').encode('utf-8')
            self['restart_action_text'] += '<div class="restart-needed-icon"></div>'
        elif self['RestartAction'] in ['RequireLogout', 'RecommendLogout']:
            self['restart_sort'] = 1
            self['restart_action_text'] = NSLocalizedString(
                u'Logout Required', u'RequireLogoutMessage').encode('utf-8')
            self['restart_action_text'] += '<div class="logout-needed-icon"></div>'

        # sort bigger installs to the top
        if self.get('installed_size'):
            self['size_sort'] = -int(self['installed_size'])
            self['size'] = munki.humanReadable(self['installed_size'])
        elif self.get('installer_item_size'):
            self['size_sort'] = -int(self['installer_item_size'])
            self['size'] = munki.humanReadable(self['installer_item_size'])
        else:
            self['size_sort'] = 0
            self['size'] = ''

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
                        return parts[1].title().encode('utf-8')
        return ''

    def getIcon(self):
        '''Return name/relative path of image file to use for the icon'''
        for key in ['icon_name', 'display_name', 'name']:
            if key in self:
                name = self[key]
                icon_path = os.path.join(msulib.html_dir(), name + '.png')
                if os.path.exists(icon_path) or msulib.convertIconToPNG(name, icon_path, 350):
                    return name + '.png'
        else:
            # use the Generic package icon
            return 'static/Generic.png'

    def status_text(self):
        '''Return localized status display text'''
        map = { 'installed':
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
        return map.get(self['status'], self['status'])

    def short_action_text(self):
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
        return map.get(self['status'], self['status'])

    def long_action_text(self):
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
        return map.get(self['status'], self['status'])

    def myitem_action_text(self):
        '''Return localized 'My Items' action text for button'''
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
        return map.get(self['status'], self['status'])

    def version_label(self):
        '''Text for the version info in the detail sidebar'''
        if self['status'] == 'will-be-removed':
            removal_text = NSLocalizedString(
                u'Will be removed', u'WillBeRemovedDisplayText').encode('utf-8')
            return '<span class="warning">%s</span>' % removal_text
        else:
            return NSLocalizedString(u'Version', u'VersionLabel').encode('utf-8')

    def developer_sort(self):
        '''returns sort priority based on developer and install/removal status'''
        if self['status'] != 'will-be-removed' and self['developer'] == 'Apple':
            return 0
        return 1

    def more_link_text(self):
        return NSLocalizedString(u'More', u'MoreLinkText').encode('utf-8')


class OptionalItem(GenericItem):
    '''Dictionary subclass that models a given optional install item'''
    
    def __init__(self, *arg, **kw):
        '''Initialize an OptionalItem from a item dict from the
        InstallInfo.plist optional_installs array'''
        super(OptionalItem, self).__init__(*arg, **kw)
        if 'category' not in self:
            self['category'] = NSLocalizedString(
                                        u'Uncategorized',
                                        u'NoCategoryName').encode('utf-8')
        if self['developer']:
            self['category_and_developer'] = '%s - %s' % (
                self['category'], self['developer'])
        else:
            self['category_and_developer'] = self['category']
        if not self.get('status'):
            self['status'] = self._get_status()
        # track original status of item
        self['original_status'] = self['status']
        if self.get('installer_item_size'):
            self['size'] = munki.humanReadable(self['installer_item_size'])
        elif self.get('installed_size'):
            self['size'] = munki.humanReadable(self['installed_size'])
        else:
            self['size'] = ''
        self['detail_link'] = 'detail-%s.html' % quote_plus(self['name'])
        self['hide_cancel_button'] = ''
            
    def _get_status(self):
        '''Calculates initial status for an item'''
        managed_update_names = getInstallInfo().get('managed_updates', [])
        self_service_installs = SelfService().self_service_installs
        self_service_uninstalls = SelfService().self_service_uninstalls
        if self.get('installed'):
            if self['name'] in self_service_uninstalls:
                status = 'will-be-removed'
            else: # not in managed_uninstalls
                if not self.get('needs_update'):
                    if self.get('uninstallable'):
                        status = 'installed'
                    else: # not uninstallable
                        status = 'installed-not-removable'
                else: # there is an update available
                    if self['name'] in self_service_installs:
                        if self['name'] in managed_update_names:
                            status = 'update-must-be-installed'
                        else: # not in managed_updates
                            status = 'update-will-be-installed'
                    else: # not in managed_installs
                        status = 'update-available'
        else: # not installed
            if self['name'] in self_service_installs:
                status = 'will-be-installed'
            else: # not in managed_installs
                if ('licensed_seats_available' in self
                    and not self['licensed_seats_available']):
                    status = 'no-licenses-available'
                elif self.get('note'):
                    # TO-DO: handle this case
                    # some reason we can't install
                    # usually not enough disk space
                    # for now we prevent install
                    status = 'no-licenses-available'
                else: # licensed seats are available
                    status = 'not-installed'
        return status

    def update_status(self):
        # user clicked an item action button - update the item's state
        managed_update_names = getInstallInfo().get('managed_updates', [])
        if self['status'] == 'update-available':
            # mark the update for install
            self['status'] = 'update-will-be-installed'
            subscribe(self)
        elif self['status'] == 'update-will-be-installed':
            # cancel the update
            self['status'] = 'update-available'
            unmanage(self)
        elif self['status'] == 'will-be-removed':
            if self['name'] in managed_update_names:
                # update is managed, so user can't opt out
                self['status'] = 'installed'
            elif self.get('needs_update'):
                # update being installed; can opt-out
                self['status'] = 'update-will-be-installed'
            else:
                # item is simply installed
                self['status'] = 'installed'
            unmanage(self)
        elif self['status'] == 'will-be-installed':
            # cancel install
            self['status'] = 'not-installed'
            unmanage(self)
        elif self['status'] == 'not-installed':
            # mark for install
            self['status'] = 'will-be-installed'
            subscribe(self)
        elif self['status'] == 'installed':
            # mark for removal
            self['status'] = 'will-be-removed'
            unsubscribe(self)


class UpdateItem(GenericItem):
    '''GenericItem subclass that models an update install item'''
    
    def __init__(self, *arg, **kw):
        super(UpdateItem, self).__init__(*arg, **kw)
        self['detail_link'] = ('updatedetail-%s.html'
                                   % quote_plus(self['name']))
        if not self['status'] == 'will-be-removed':
            force_install_after_date = self.get('force_install_after_date')
            if force_install_after_date:
                self['category'] = NSLocalizedString(
                                u'Critical Update', u'CriticalUpdateType')
                self['due_date_sort'] = force_install_after_date
                # insert installation deadline into description
                local_date = munki.discardTimeZoneFromDate(
                                                force_install_after_date)
                date_str = munki.stringFromDate(local_date).encode('utf-8')
                forced_date_text = NSLocalizedString(
                                    u'This item must be installed by %s',
                                    u'ForcedDateWarning').encode('utf-8')
                description = self['description']
                # prepend deadline info to description.
                self['description'] = (
                    '<span class="warning">' + forced_date_text % date_str
                    + '</span><br><br>' + description)
        if not 'category' in self:
             self['category'] = NSLocalizedString(u'Managed Update',
                                                  u'ManagedUpdateType').encode('utf-8')
        self['hide_cancel_button'] = 'hidden'
