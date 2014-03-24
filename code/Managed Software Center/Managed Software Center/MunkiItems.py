# encoding: utf-8
#
#  MunkiItems.py
#  Managed Software Center
#
#  Created by Greg Neagle on 2/21/14.
#
# Copyright 2014 Greg Neagle.
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
_cache['dependent_items'] = None


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
    # use our list to make UpdateItems
    update_list = [UpdateItem(item) for item in update_items]
    # sort it and return it
    return sorted(update_list, key=itemgetter(
                    'due_date_sort', 'restart_sort', 'developer_sort', 'size_sort'))


def updatesRequireLogout():
    '''Return True if any item in the update list requires a logout'''
    return len([item for item in getUpdateList()
                if 'Logout' in item.get('RestartAction', '')]) > 0


def updatesRequireRestart():
    '''Return True if any item in the update list requires a restart'''
    return len([item for item in getUpdateList()
                if 'Restart' in item.get('RestartAction', '')]) > 0


def updatesContainNonOptionalItems():
    '''Does the list of updates contain items not selected by the user?'''
    if not munki.munkiUpdatesContainAppleItems() and getAppleUpdates():
        # available Apple updates are not user selected
        return True
    install_info = getInstallInfo()
    install_items = install_info.get('managed_installs', [])
    removal_items = install_info.get('removals', [])
    filtered_installs = [item for item in install_items
                         if item['name'] not in SelfService().installs()]
    if filtered_installs:
        return True
    filtered_uninstalls = [item for item in removal_items
                           if item['name'] not in SelfService().uninstalls()]
    if filtered_uninstalls:
        return True
    return False


def getEffectiveUpdateList():
    '''Combine the updates Munki has found with any optional choices to
        make the effective list of updates'''
    managed_update_names = getInstallInfo().get('managed_updates', [])
    optional_item_names = [item['name'] for item in getInstallInfo().get('optional_installs')]
    self_service_installs = SelfService().installs()
    self_service_uninstalls = SelfService().uninstalls()
    # items in the update_list that are part of optional_items
    # could have their installation state changed; so filter those out
    optional_installs = getOptionalWillBeInstalledItems()
    optional_removals = getOptionalWillBeRemovedItems()

    mandatory_updates = [item for item in getUpdateList()
                         if (item['name'] in managed_update_names
                             or item.get('dependent_items')
                             or item['name'] not in optional_item_names)]
    
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
    '''Returns the names of any optional items that require this optional item'''
    dependent_items = []
    optional_installs = getInstallInfo().get('optional_installs', [])
    optional_installs_with_dependencies = [item for item in optional_installs
                                           if 'requires' in item]
    for item in optional_installs_with_dependencies:
        if this_name in item['requires']:
            dependent_items.append(item['name'])
    return dependent_items


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
        if not self.get('display_name'):
            self['display_name'] = self['name']
        self['display_name_lower'] = self['display_name'].lower()
        if not self.get('developer'):
            self['developer'] = self.guess_developer()
        if self.get('description'):
            self['raw_description'] = msulib.filtered_html(self['description'])
            del(self['description'])
        if not 'raw_description' in self:
            self['raw_description'] = u''
        self['icon'] = self.getIcon()
        self['due_date_sort'] = NSDate.distantFuture()
        # sort items that need restart highest, then logout, then other
        if self.get('RestartAction') in [None, 'None']:
            self['restart_action_text'] = u''
            self['restart_sort'] = 2
        elif self['RestartAction'] in ['RequireRestart', 'RecommendRestart']:
            self['restart_sort'] = 0
            self['restart_action_text'] = NSLocalizedString(
                u'Restart Required', u'RequireRestartMessage')
            self['restart_action_text'] += u'<div class="restart-needed-icon"></div>'
        elif self['RestartAction'] in ['RequireLogout', 'RecommendLogout']:
            self['restart_sort'] = 1
            self['restart_action_text'] = NSLocalizedString(
                u'Logout Required', u'RequireLogoutMessage')
            self['restart_action_text'] += u'<div class="logout-needed-icon"></div>'

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

    def dependency_description(self):
        '''Return an html description of items this item depends on'''
        _description = u''
        prologue = NSLocalizedString(
            u'This item is required by:', u'DependencyListPrologueText')
        if self.get('dependent_items'):
            _description = u'<br/><br/><strong>' + prologue
            for item in self['dependent_items']:
                _description += u'<br/>&nbsp;&nbsp;&bull; ' + display_name(item)
            _description += u'</strong>'
        return _description

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
        icon_name = self.get('icon_name') or self['name']
        if not os.path.splitext(icon_name)[1]:
            icon_name += '.png'
        icon_path = os.path.join(msulib.html_dir(), 'icons', icon_name)
        if os.path.exists(icon_path):
            return 'icons/' + icon_name
        # didn't find one in the downloaded icons
        # so create one if needed from a locally installed app
        for key in ['icon_name', 'display_name', 'name']:
            if key in self:
                name = self[key]
                icon_name = name
                if not os.path.splitext(icon_name)[1]:
                    icon_name += '.png'
                icon_path = os.path.join(msulib.html_dir(), icon_name)
                if os.path.exists(icon_path) or msulib.convertIconToPNG(name, icon_path, 350):
                    return icon_name
        else:
            # use the Generic package icon
            return 'static/Generic.png'

    def unavailable_reason_text(self):
        '''There are several reasons an item might be unavailable for install.
           Return the relevent reason'''
        if ('licensed_seats_available' in self
            and not self['licensed_seats_available']):
            return NSLocalizedString(u'No licenses available',
                                     u'NoLicensesAvailableDisplayText')
        if self.get('note') == 'Insufficient disk space to download and install.':
            return NSLocalizedString(u'Not enough disk space',
                                     u'NotEnoughDiskSpaceDisplayText')
        # return generic reason
        return NSLocalizedString(u'Not currently available',
                                 u'NotCurrentlyDisplayText')

    def status_text(self):
        '''Return localized status display text'''
        if self['status'] == 'unavailable':
            return self.unavailable_reason_text()
        map = { 'installed':
                    NSLocalizedString(u'Installed',
                        u'InstalledDisplayText'),
                'installing':
                    NSLocalizedString(u'Installing',
                        u'InstallingDisplayText'),
                'installed-not-removable':
                    NSLocalizedString(u'Installed',
                        u'InstalledDisplayText'),
                'not-installed':
                    NSLocalizedString(u'Not installed',
                        u'NotInstalledDisplayText'),
                'will-be-installed':
                    NSLocalizedString(u'Will be installed',
                        u'WillBeInstalledDisplayText'),
                'must-be-installed':
                    NSLocalizedString(u'Will be installed',
                        u'InstallRequiredDisplayText'),
                'will-be-removed':
                    NSLocalizedString(u'Will be removed',
                        u'WillBeRemovedDisplayText'),
                'removing':
                    NSLocalizedString(u'Removing',
                        u'RemovingDisplayText'),
                'update-will-be-installed':
                    NSLocalizedString(u'Update will be installed',
                        u'UpdateWillBeInstalledDisplayText'),
                'update-must-be-installed':
                    NSLocalizedString(u'Update will be installed',
                                  u'UpdateRequiredDisplayText'),
                'update-available':
                    NSLocalizedString(u'Update available',
                        u'UpdateAvailableDisplayText'),
                'unavailable':
                    NSLocalizedString(u'Unavailable',
                        u'UnavailableDisplayText'),
                }
        return map.get(self['status'], self['status'])

    def short_action_text(self):
        '''Return localized 'short' action text for button'''
        map = { 'installed':
                    NSLocalizedString(u'Remove',
                        u'RemoveShortActionText'),
                'installing':
                    NSLocalizedString(u'Installing',
                        u'InstallingShortActionText'),
                'installed-not-removable':
                    NSLocalizedString(u'Installed',
                        u'InstalledShortActionText'),
                'not-installed':
                    NSLocalizedString(u'Install',
                        u'InstallShortActionText'),
                'will-be-installed':
                    NSLocalizedString(u'Cancel',
                        u'CancelInstallShortActionText'),
                'must-be-installed':
                    NSLocalizedString(u'Required',
                        u'InstallRequiredShortActionText'),
                'will-be-removed':
                    NSLocalizedString(u'Cancel',
                        u'CancelRemovalShortActionText'),
                'removing':
                    NSLocalizedString(u'Removing',
                        u'RemovingShortActionText'),
                'update-will-be-installed':
                    NSLocalizedString(u'Cancel',
                        u'CancelUpdateShortActionText'),
                'update-must-be-installed':
                    NSLocalizedString(u'Required',
                        u'UpdateRequiredShortActionText'),
                'update-available':
                    NSLocalizedString(u'Update',
                        u'UpdateShortActionText'),
                'unavailable':
                    NSLocalizedString(u'Unavailable',
                        u'UnavailableShortActionText'),
        }
        return map.get(self['status'], self['status'])

    def long_action_text(self):
        '''Return localized 'long' action text for button'''
        map = {'installed':
                    NSLocalizedString(u'Remove',
                        u'RemoveLongActionText'),
                'installing':
                    NSLocalizedString(u'Installing',
                        u'InstallingLongActionText'),
                'installed-not-removable':
                    NSLocalizedString(u'Installed',
                        u'InstalledLongActionText'),
                'not-installed':
                    NSLocalizedString(u'Install',
                        u'InstallLongActionText'),
                'will-be-installed':
                    NSLocalizedString(u'Cancel install',
                        u'CancelInstallLongActionText'),
                'must-be-installed':
                    NSLocalizedString(u'Install Required',
                        u'InstallRequiredLongActionText'),
                'will-be-removed':
                    NSLocalizedString(u'Cancel removal',
                        u'CancelRemovalLongActionText'),
                'removing':
                    NSLocalizedString(u'Removing',
                        u'RemovingLongActionText'),
                'update-will-be-installed':
                    NSLocalizedString(u'Cancel update',
                        u'CancelUpdateLongActionText'),
                'update-must-be-installed':
                    NSLocalizedString(u'Update Required',
                        u'UpdateRequiresLongActionText'),
                'update-available':
                    NSLocalizedString(u'Update',
                        u'UpdateLongActionText'),
                'unavailable':
                    NSLocalizedString(u'Currently Unavailable',
                        u'UnavailableShortActionText'),
        }
        return map.get(self['status'], self['status'])

    def myitem_action_text(self):
        '''Return localized 'My Items' action text for button'''
        map = { 'installed':
                    NSLocalizedString(u'Remove',
                        u'RemoveLongActionText'),
                'installing':
                    NSLocalizedString(u'Installing',
                        u'InstallingLongActionText'),
                'installed-not-removable':
                    NSLocalizedString(u'Installed',
                        u'InstalledLongActionText'),
                'will-be-removed':
                    NSLocalizedString(u'Cancel removal',
                        u'CancelRemovalLongActionText'),
                'removing':
                    NSLocalizedString(u'Removing',
                        u'RemovingLongActionText'),
                'update-available':
                    NSLocalizedString(u'Update',
                        u'UpdateLongActionText'),
                'update-will-be-installed':
                    NSLocalizedString(u'Remove',
                        u'RemoveLongActionText'),
                'update-must-be-installed':
                    NSLocalizedString(u'Update Required',
                        u'UpdateRequiredLongActionText'),
                'will-be-installed':
                    NSLocalizedString(u'Cancel install',
                        u'CancelInstallLongActionText'),
                'must-be-installed':
                    NSLocalizedString(u'Required',
                        u'InstallRequiredLongActionText'),

        }
        return map.get(self['status'], self['status'])

    def version_label(self):
        '''Text for the version label'''
        if self['status'] == 'will-be-removed':
            removal_text = NSLocalizedString(
                u'Will be removed', u'WillBeRemovedDisplayText')
            return '<span class="warning">%s</span>' % removal_text
        else:
            return NSLocalizedString(u'Version', u'VersionLabel')

    def display_version(self):
        '''Version number for display'''
        if self['status'] == 'will-be-removed':
            return ''
        else:
            return self.get('version_to_install', '')
    
    def developer_sort(self):
        '''returns sort priority based on developer and install/removal status'''
        if self['status'] != 'will-be-removed' and self['developer'] == 'Apple':
            return 0
        return 1

    def more_link_text(self):
        return NSLocalizedString(u'More', u'MoreLinkText')


class OptionalItem(GenericItem):
    '''Dictionary subclass that models a given optional install item'''
    
    def __init__(self, *arg, **kw):
        '''Initialize an OptionalItem from a item dict from the
        InstallInfo.plist optional_installs array'''
        super(OptionalItem, self).__init__(*arg, **kw)
        if 'category' not in self:
            self['category'] = NSLocalizedString(
                                        u'Uncategorized',
                                        u'NoCategoryName')
        if self['developer']:
            self['category_and_developer'] = u'%s - %s' % (
                self['category'], self['developer'])
        else:
            self['category_and_developer'] = self['category']
        self['dependent_items'] = dependentItems(self['name'])
        if not self.get('status'):
            self['status'] = self._get_status()
        if self.get('installer_item_size'):
            self['size'] = munki.humanReadable(self['installer_item_size'])
        elif self.get('installed_size'):
            self['size'] = munki.humanReadable(self['installed_size'])
        else:
            self['size'] = u''
        self['detail_link'] = u'detail-%s.html' % quote_plus(self['name'])
        self['hide_cancel_button'] = u''
            
    def _get_status(self):
        '''Calculates initial status for an item'''
        managed_update_names = getInstallInfo().get('managed_updates', [])
        self_service_installs = SelfService().installs()
        self_service_uninstalls = SelfService().uninstalls()
        if self.get('installed'):
            if self['name'] in self_service_uninstalls:
                status = u'will-be-removed'
            else: # not in managed_uninstalls
                if not self.get('needs_update'):
                    if self['dependent_items']:
                        status = u'installed-not-removable'
                    elif self.get('uninstallable'):
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
            if self.get('note'):
                # TO-DO: handle this case better
                # some reason we can't install
                # usually not enough disk space
                # but can also be:
                #   'Integrity check failed'
                #   'Download failed (%s)' % errmsg
                #   'Can\'t install %s because: %s', manifestitemname, errmsg
                #   'Insufficient disk space to download and install.'
                #
                # for now we prevent install this way
                status = u'unavailable'
            elif ('licensed_seats_available' in self
                    and not self['licensed_seats_available']):
                status = u'unavailable'
            elif self['dependent_items']:
                status = u'must-be-installed'
            elif self['name'] in self_service_installs:
                status = u'will-be-installed'
            else: # not in managed_installs
                status = u'not-installed'
        return status

    def description(self):
        '''return a full description for the item, inserting dynamic data
           if needed'''
        _description = self['raw_description']
        if self.get('dependent_items'):
            # append dependency info to description:
            _description += self.dependency_description()
        return _description

    def update_status(self):
        # user clicked an item action button - update the item's state
        managed_update_names = getInstallInfo().get('managed_updates', [])
        if self['status'] == 'update-available':
            # mark the update for install
            self['status'] = u'update-will-be-installed'
            subscribe(self)
        elif self['status'] == 'update-will-be-installed':
            # cancel the update
            self['status'] = u'update-available'
            unmanage(self)
        elif self['status'] == 'will-be-removed':
            if self['name'] in managed_update_names:
                # update is managed, so user can't opt out
                self['status'] = u'installed'
            elif self.get('needs_update'):
                # update being installed; can opt-out
                self['status'] = u'update-will-be-installed'
            else:
                # item is simply installed
                self['status'] = u'installed'
            unmanage(self)
        elif self['status'] == 'will-be-installed':
            # cancel install
            self['status'] = u'not-installed'
            unmanage(self)
        elif self['status'] == 'not-installed':
            # mark for install
            self['status'] = u'will-be-installed'
            subscribe(self)
        elif self['status'] == 'installed':
            # mark for removal
            self['status'] = u'will-be-removed'
            unsubscribe(self)


class UpdateItem(GenericItem):
    '''GenericItem subclass that models an update install item'''
    
    def __init__(self, *arg, **kw):
        super(UpdateItem, self).__init__(*arg, **kw)
        identifier = self.get('name', '') + '--version-' + self.get('version_to_install', '')
        self['detail_link'] = ('updatedetail-%s.html'
                                   % quote_plus(identifier))
        if not self['status'] == 'will-be-removed':
            force_install_after_date = self.get('force_install_after_date')
            if force_install_after_date:
                self['type'] = NSLocalizedString(
                                u'Critical Update', u'CriticalUpdateType')
                self['due_date_sort'] = force_install_after_date
    
        if not 'type' in self:
             self['type'] = NSLocalizedString(u'Managed Update',
                                              u'ManagedUpdateType')
        self['hide_cancel_button'] = u'hidden'
        self['dependent_items'] = dependentItems(self['name'])

    def description(self):
        _description = self['raw_description']
        if not self['status'] == 'will-be-removed':
            force_install_after_date = self.get('force_install_after_date')
            if force_install_after_date:
                # insert installation deadline into description
                local_date = munki.discardTimeZoneFromDate(
                                                force_install_after_date)
                date_str = munki.stringFromDate(local_date)
                forced_date_text = NSLocalizedString(
                                    u'This item must be installed by %s',
                                    u'ForcedDateWarning')
                # prepend deadline info to description.
                _description = ('<span class="warning">' + forced_date_text % date_str
                    + '</span><br><br>' + _description)
            if self.get('dependent_items'):
                # append dependency info to description:
                _description += self.dependency_description()

        return _description

