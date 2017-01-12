# encoding: utf-8
#
# Copyright 2009-2017 Greg Neagle.
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
dist.py

Created by Greg Neagle on 2017-01-04.

Utilities for working with Apple software update dist files
"""

import os
import re
from xml.dom import minidom
from xml.parsers import expat

# PyLint cannot properly find names inside Cocoa libraries, so issues bogus
# No name 'Foo' in module 'Bar' warnings. Disable them.
# pylint: disable=E0611
from AppKit import NSAttributedString
from LaunchServices import LSFindApplicationForInfo
# pylint: enable=E0611

from .. import display
from .. import pkgutils
from .. import FoundationPlist


def get_restart_action(restart_action_list):
    """Returns the highest-weighted restart action of those in the list"""
    restart_actions = [
        'None', 'RequireLogout', 'RecommendRestart', 'RequireRestart']
    highest_action_index = 0
    for action in restart_action_list:
        try:
            highest_action_index = max(
                restart_actions.index(action), highest_action_index)
        except ValueError:
            # action wasn't in our list
            pass
    return restart_actions[highest_action_index]


def get_firmware_alert_text(dom):
    '''If the update is a firmware update, returns some alert
    text to display to the user, otherwise returns an empty
    string. If we cannot read a custom firmware readme to use as
    the alert, return "_DEFAULT_FIRMWARE_ALERT_TEXT_" '''

    type_is_firmware = False
    options = dom.getElementsByTagName('options')
    for option in options:
        if 'type' in option.attributes.keys():
            type_value = option.attributes['type'].value
            if type_value == 'firmware':
                type_is_firmware = True
                break
    if type_is_firmware:
        firmware_alert_text = '_DEFAULT_FIRMWARE_ALERT_TEXT_'
        readmes = dom.getElementsByTagName('readme')
        if len(readmes):
            html = readmes[0].firstChild.data
            html_data = buffer(html.encode('utf-8'))
            attributed_string, _ = NSAttributedString.alloc(
                ).initWithHTML_documentAttributes_(html_data, None)
            firmware_alert_text = attributed_string.string()
        return firmware_alert_text
    return ''


# TO-DO: remove this function once it's clear the replacement works
# (replacement: passing the string to FoundationPlist.readPlistFromString)
def parse_cdata(cdata_str):
    '''Parses the CDATA string from an Apple Software Update distribution
    file and returns a dictionary with key/value pairs.

    The data in the CDATA string is in the format of an OS X .strings file,
    which is generally:

    "KEY1" = "VALUE1";
    "KEY2"='VALUE2';
    "KEY3" = 'A value
    that spans
    multiple lines.
    ';

    Values can span multiple lines; either single or double-quotes can be
    used to quote the keys and values, and the alternative quote character
    is allowed as a literal inside the other, otherwise the quote character
    is escaped.

    //-style comments and blank lines are allowed in the string; these
    should be skipped by the parser unless within a value.

    '''

    parsed_data = {}
    regex_text = (r"""^\s*"""
                  r"""(?P<key_quote>['"]?)(?P<key>[^'"]+)(?P=key_quote)"""
                  r"""\s*=\s*"""
                  r"""(?P<value_quote>['"])(?P<value>.*?)(?P=value_quote);$""")
    regex = re.compile(regex_text, re.MULTILINE | re.DOTALL)

    # iterate through the string, finding all possible non-overlapping
    # matches
    for match_obj in re.finditer(regex, cdata_str):
        match_dict = match_obj.groupdict()
        if 'key' in match_dict.keys() and 'value' in match_dict.keys():
            key = match_dict['key']
            value = match_dict['value']
            # now 'de-escape' escaped quotes
            quote = match_dict.get('value_quote')
            if quote:
                escaped_quote = '\\' + quote
                value = value.replace(escaped_quote, quote)
            parsed_data[key] = value

    return parsed_data

def parse_su_dist(filename):
    '''Parses a softwareupdate dist file, looking for information of
    interest. Returns a dictionary containing the info we discovered in a
    Munki-friendly format.'''
    try:
        dom = minidom.parse(filename)
    except expat.ExpatError:
        display.display_error(
            'Invalid XML in %s', filename)
        return None
    except IOError, err:
        display.display_error(
            'Error reading %s: %s', filename, err)
        return None

    su_choice_id_key = 'su'
    # look for <choices-outline ui='SoftwareUpdate'
    choice_outlines = dom.getElementsByTagName('choices-outline') or []
    for outline in choice_outlines:
        if ('ui' in outline.attributes.keys() and
                outline.attributes['ui'].value == 'SoftwareUpdate'):
            lines = outline.getElementsByTagName('line')
            if lines and 'choice' in lines[0].attributes.keys():
                su_choice_id_key = (
                    lines[0].attributes['choice'].value)

    # get values from choice id=su_choice_id_key
    # (there may be more than one!)
    pkgs = {}
    su_choice = {}
    choice_elements = dom.getElementsByTagName('choice') or []
    for choice in choice_elements:
        keys = choice.attributes.keys()
        if 'id' in keys:
            choice_id = choice.attributes['id'].value
            if choice_id == su_choice_id_key:
                # this is the one Software Update uses
                for key in keys:
                    su_choice[key] = choice.attributes[key].value
                pkg_refs = choice.getElementsByTagName('pkg-ref') or []
                for pkg in pkg_refs:
                    if 'id' in pkg.attributes.keys():
                        pkg_id = pkg.attributes['id'].value
                        if not pkg_id in pkgs.keys():
                            pkgs[pkg_id] = {}
                # now get all pkg-refs so we can assemble all metadata
                # there is additional metadata in pkg-refs outside of the
                # choices element
                pkg_refs = dom.getElementsByTagName('pkg-ref') or []
                for pkg in pkg_refs:
                    if 'id' in pkg.attributes.keys():
                        pkg_id = pkg.attributes['id'].value
                        if not pkg_id in pkgs.keys():
                            # this pkg_id was not in our choice list
                            continue
                        if pkg.firstChild:
                            try:
                                pkg_name = pkg.firstChild.wholeText
                                if pkg_name:
                                    pkgs[pkg_id]['name'] = pkg_name
                            except AttributeError:
                                pass
                        if 'onConclusion' in pkg.attributes.keys():
                            pkgs[pkg_id]['RestartAction'] = (
                                pkg.attributes['onConclusion'].value)
                        if 'version' in pkg.attributes.keys():
                            pkgs[pkg_id]['version'] = (
                                pkg.attributes['version'].value)
                        if 'installKBytes' in pkg.attributes.keys():
                            pkgs[pkg_id]['installed_size'] = int(
                                pkg.attributes['installKBytes'].value)
                        if 'packageIdentifier' in pkg.attributes.keys():
                            pkgs[pkg_id]['packageid'] = (
                                pkg.attributes['packageIdentifier'].value)

    # look for localization and parse strings data into a dict
    strings_data = {}
    localizations = dom.getElementsByTagName('localization')
    if localizations:
        string_elements = localizations[0].getElementsByTagName('strings')
        if string_elements:
            strings = string_elements[0]
            if strings.firstChild:
                try:
                    text = strings.firstChild.wholeText
                    #strings_data = parse_cdata(text)
                    # strings data can be parsed by FoundationPlist
                    strings_data = FoundationPlist.readPlistFromString(
                        "\n" + text)
                except (AttributeError,
                        FoundationPlist.FoundationPlistException):
                    strings_data = {}

    # get blocking_applications, if any.
    # First, find all the must-close items.
    must_close_app_ids = []
    must_close_items = dom.getElementsByTagName('must-close')
    for item in must_close_items:
        apps = item.getElementsByTagName('app')
        for app in apps:
            keys = app.attributes.keys()
            if 'id' in keys:
                must_close_app_ids.append(app.attributes['id'].value)

    # next, we convert Apple's must-close items to
    # Munki's blocking_applications
    blocking_apps = []
    # this will only find blocking_applications that are currently installed
    # on the machine running this code, but that's OK for our needs
    #
    # use set() to eliminate any duplicate application ids
    for app_id in set(must_close_app_ids):
        dummy_resultcode, dummy_fileref, nsurl = LSFindApplicationForInfo(
            0, app_id, None, None, None)
        if nsurl and nsurl.isFileURL():
            pathname = nsurl.path()
            dirname = os.path.dirname(pathname)
            executable = pkgutils.getAppBundleExecutable(pathname)
            if executable:
                # path to executable should be location agnostic
                executable = executable[len(dirname + '/'):]
            blocking_apps.append(executable or pathname)

    # get firmware alert text if any
    firmware_alert_text = get_firmware_alert_text(dom)

    # assemble!
    info = {}
    info['name'] = su_choice.get('suDisabledGroupID', '')
    info['display_name'] = su_choice.get('title', '')
    info['apple_product_name'] = info['display_name']
    info['version_to_install'] = su_choice.get('versStr', '')
    info['description'] = su_choice.get('description', '')
    for key in info:
        if info[key].startswith('SU_'):
            # get value from strings_data dictionary
            info[key] = strings_data.get(info[key], info[key])
    #info['pkg_refs'] = pkgs
    installed_size = 0
    for pkg in pkgs.values():
        installed_size += pkg.get('installed_size', 0)
    info['installed_size'] = installed_size
    if blocking_apps:
        info['blocking_applications'] = blocking_apps
    restart_actions = [pkg['RestartAction']
                       for pkg in pkgs.values() if 'RestartAction' in pkg]
    effective_restart_action = get_restart_action(restart_actions)
    if effective_restart_action != 'None':
        info['RestartAction'] = effective_restart_action
    if firmware_alert_text:
        info['firmware_alert_text'] = firmware_alert_text

    return info


if __name__ == '__main__':
    print 'This is a library of support tools for the Munki Suite.'
