# encoding: utf-8
#
# Copyright 2017-2023 Greg Neagle.
#
# Licensed under the Apache License, Version 2.0 (the 'License');
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an 'AS IS' BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
updatecheck.unused_software

Created by Greg Neagle on 2017-02-18.

Functions for removing unused optional install items
"""
from __future__ import absolute_import, print_function

# Apple frameworks via PyObjC
# PyLint cannot properly find names inside Cocoa libraries, so issues bogus
# No name 'Foo' in module 'Bar' warnings. Disable them.
# pylint: disable=E0611
from AppKit import NSWorkspace
# pylint: enable=E0611

# our libs
from .. import app_usage
from .. import display


def bundleid_is_running(app_bundleid):
    '''Returns a boolean indicating if the application with the given
    bundleid is currently running.'''
    workspace = NSWorkspace.sharedWorkspace()
    running_apps = workspace.runningApplications()
    for app in running_apps:
        if app.bundleIdentifier() == app_bundleid:
            return True
    return False


def bundleids_from_installs_list(pkginfo_pl):
    '''Extracts a list of application bundle_ids from the installs list of a
    pkginfo item'''
    installs_list = pkginfo_pl.get('installs', [])
    bundle_ids = [item.get('CFBundleIdentifier') for item in installs_list
                  if (item.get('CFBundleIdentifier') and
                      item.get('type') == 'application'
                      or (item.get('type') == 'bundle' and
                          item.get('path', '').endswith('.app')))]
    return bundle_ids


def should_be_removed(item_pl):
    """Determines if an optional install item should be removed due to lack of
    use.
    Returns a boolean."""

    name = item_pl['name']
    removal_info = item_pl.get('unused_software_removal_info')
    # do we have unused_software_removal_info?
    if not removal_info:
        return False

    display.display_debug1(
        '\tChecking to see if %s should be removed due to lack of use...', name)
    try:
        removal_days = int(removal_info.get('removal_days', 0))
        if removal_days < 1:
            raise ValueError
    except ValueError:
        display.display_warning('Invalid removal_days: %s for item %s'
                                % (removal_info.get('removal_days'), name))
        return False

    display.display_debug1(
        '\t\tNumber of days until removal is %s', removal_days)
    usage = app_usage.ApplicationUsageQuery()
    usage_data_days = usage.days_of_data()
    if usage_data_days is None or usage_data_days < removal_days:
        # we don't have usage data old enough to judge
        display.display_debug1(
            '\t\tApplication usage data covers fewer than %s days.',
            removal_days)
        return False

    # check to see if we have an install request within the removal_days
    days_since_install_request = usage.days_since_last_install_event(
        'install', name)
    if (days_since_install_request is not None and
            days_since_install_request != -1 and
            days_since_install_request <= removal_days):
        display.display_debug1('\t\t%s had an install request %s days ago.',
                               name, days_since_install_request)
        return False

    # get list of application bundle_ids to check
    if 'bundle_ids' in removal_info:
        bundle_ids = removal_info['bundle_ids']
    else:
        # get application bundle_ids from installs list
        bundle_ids = bundleids_from_installs_list(item_pl)
    if not bundle_ids:
        display.display_debug1('\\tNo application bundle_ids to check.')
        return False

    # now check each bundleid to see if it's currently running or has been
    # activated in the past removal_days days
    display.display_debug1('\t\tChecking bundle_ids: %s', bundle_ids)
    for bundle_id in bundle_ids:
        if bundleid_is_running(bundle_id):
            display.display_debug1(
                '\t\tApplication %s is currently running.' % bundle_id)
            return False
        days_since_last_activation = usage.days_since_last_usage_event(
            'activate', bundle_id)
        if days_since_last_activation == -1:
            display.display_debug1(
                '\t\t%s has not been activated in more than %s days...',
                bundle_id, usage.days_of_data())
        elif days_since_last_activation <= removal_days:
            display.display_debug1('\t\t%s was last activated %s days ago',
                                   bundle_id, days_since_last_activation)
            return False
        else:
            display.display_debug1('\t\t%s was last activated %s days ago',
                                   bundle_id, days_since_last_activation)

    # if we get this far we must not have found any apps used in the past
    # removal_days days, so we should set up a removal
    display.display_info('Will add %s to the removal list since it has been '
                         'unused for at least %s days...', name, removal_days)
    return True


if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
