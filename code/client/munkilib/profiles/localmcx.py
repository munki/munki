# encoding: utf-8
#
# Copyright 2014-2023 Greg Neagle.
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
"""
localmcx.py
Munki module for installing managed preferences from configuration profiles
on Big Sur+
"""
from __future__ import absolute_import, print_function

import os
import subprocess
import tempfile

# PyLint cannot properly find names inside Cocoa libraries, so issues bogus
# No name 'Foo' in module 'Bar' warnings. Disable them.
# pylint: disable=E0611
from Foundation import NSBundle
from SystemConfiguration import (
    SCNetworkInterfaceCopyAll,
    SCNetworkInterfaceGetBSDName,
    SCNetworkInterfaceGetHardwareAddressString
)
# pylint: enable=E0611

from .. import display
from .. import osutils
from .. import utils
from .. import FoundationPlist


def install_profile(profile):
    '''Extracts managed preferences from a configuration profile and installs
    them as local MCX. Returns a boolean indicating success (or not)'''
    if not profile.get('PayloadType') == 'Configuration':
        display.display_error('Unsupported profile PayloadType: %s'
                              % profile.get('PayloadType'))
        return False
    mcx_data = profile_to_mcx(profile)
    if not mcx_data:
        display.display_error(
            'No Managed Preferences found in profile %s: %s'
            % (profile.get('PayloadIdentifier'),
               profile.get('PayloadDisplayName'))
        )
        return False
    groupname = profile.get('PayloadIdentifier')
    if not groupname:
        display.display_error('Profile is missing PayloadIdentifier')
        return False
    if create_computer_group_with_mcx(groupname, mcx_data):
        refresh_mcx()
        return True
    return False


def remove_profile(identifier):
    '''Removes the computer group containing the managed preferences for
    identifier. Returns a boolean indicating success (or not)'''
    if delete_computer_group(identifier):
        refresh_mcx()
        return True
    return False


def profile_is_installed(identifier):
    '''Returns true if the list of/Local/Default ComputerGroups contains
    identifier'''
    cmd = ['/usr/bin/dscl', '.', 'list', '/ComputerGroups']
    output, err, exitcode = run(cmd)
    if exitcode:
        display.display_warning(
            'Could not get list of local ComputerGroups: %s' % err)
        return False
    return identifier in output.splitlines()


def profile_to_mcx(profile):
    '''Converts a configuration profile to a plist we can use with
    dscl. mcximport'''
    mcx = {}
    for payload_content in profile.get('PayloadContent'):
        mcx.update(convert(payload_content))
    return mcx


def convert(payload_content):
    '''Converts config profile PayloadContent into mcximport-able data'''
    payload_metadata_keys = (
        'PayloadType',
        'PayloadContent',
        'PayloadVersion',
        'PayloadIdentifier',
        'PayloadEnabled',
        'PayloadUUID',
        'PayloadDisplayName',
        'PayloadOrganization',
    )
    state_mapping = {
        'Forced': 'always',
        'Set-Once': 'often',
    }
    mcx = {}
    payload_type = payload_content.get('PayloadType')
    if payload_type == 'com.apple.ManagedClient.preferences':
        prefs_content = payload_content.get('PayloadContent', {})
        for prefs_domain in prefs_content:
            mcx[prefs_domain] = {}
            for state_key, prefs_list in prefs_content[prefs_domain].items():
                state = state_mapping.get(state_key)
                if not state:
                    continue
                for item in prefs_list:
                    if 'mcx_data_timestamp' in item:
                        state = 'once'
                    settings = item.get('mcx_preference_settings', {})
                    for key, value in settings.items():
                        mcx[prefs_domain][key] = {}
                        mcx[prefs_domain][key]['state'] = state
                        mcx[prefs_domain][key]['value'] = value
                        if 'mcx_union_policy_keys' in item:
                            mcx[prefs_domain][key]['upk'] = item['mcx_union_policy_keys']

    elif domain_is_handled_by_plugin(payload_type):
        display.display_warning(
            'Can\'t handle configuration profile PayloadType %s' % payload_type)
        display.display_warning(
            'Configuration profile support is limited to managed preferences.')

    elif payload_type:
        prefs_domain = payload_type
        mcx[prefs_domain] = {}
        for key, value in payload_content.items():
            if key not in payload_metadata_keys:
                mcx[prefs_domain][key] = {}
                mcx[prefs_domain][key]['state'] = 'always'
                mcx[prefs_domain][key]['value'] = value

    return mcx


def get_en0_mac():
    '''Returns the MAC layer address of en0'''
    for interface in SCNetworkInterfaceCopyAll():
        if SCNetworkInterfaceGetBSDName(interface) == "en0":
            return SCNetworkInterfaceGetHardwareAddressString(interface)
    return None


def run(cmd):
    '''Runs a command using subprocess.
    Returns a tuple of stdout, stderr, exitcode'''
    proc = subprocess.Popen(cmd,
                            shell=False,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    output, errors = proc.communicate()
    return (output.decode("UTF-8"), errors.decode("UTF-8"), proc.returncode)


def refresh_mcx():
    '''Attempt to refresh the MCX cache'''
    _, err, exitcode = run(['/usr/bin/mcxrefresh', '-u', '0'])
    if exitcode:
        display.display_warning("mcxrefresh error: %s" % err)


def add_mcx_to_local_computer_record(recordname):
    '''Adds some dummy MCX data to the local computer record to prevent
    MCX compositor from deleting it'''
    cmd = ['/usr/bin/dscl', '.', 'mcxset', '/Computers/' + recordname,
           'com.github.munki.munki', 'LocalMCX', 'always', '-int', '1']
    run(cmd)


def local_computer_record():
    '''Finds or creates a local computer record we can use for LocalMCX'''
    mac_layer_addr = get_en0_mac()
    if not mac_layer_addr:
        display.display_error("Could not get MAC layer address for en0")
        display.display_error("Cannot create local mcx computer record")
        return None
    cmd = ['/usr/bin/dscl', '.', 'search', '/Computers',
           'ENetAddress', mac_layer_addr]
    output, _, exitcode = run(cmd)
    if exitcode == 0 and output:
        recordname = output.split()[0]
    else:
        recordname = 'mcx_computer'
        cmd = ['/usr/bin/dscl', '.', 'create', '/Computers/' + recordname,
               'ENetAddress', mac_layer_addr]
        _, err, exitcode = run(cmd)
        if exitcode:
            display.display_error(
                "Error creating local mcx computer record: %s" % err)
            display.display_error("Cannot create local mcx computer record")
            return None
    add_mcx_to_local_computer_record(recordname)
    return recordname


def add_local_computer_record_to_computer_group(groupname):
    '''Adds the local computer record to the computer group.
    Returns a boolean indicating success (or not)'''
    local_computer_record_name = local_computer_record()
    if not local_computer_record_name:
        display.display_error("Could not get local computer record")
        return False
    cmd = ['/usr/sbin/dseditgroup', '-o', 'edit',
           '-a', local_computer_record_name, '-t', 'computer',
           '-T', 'computergroup', groupname]
    _, err, exitcode = run(cmd)
    if exitcode:
        display.display_error(
            "Error adding local mcx computer to %s: %s" % (groupname, err))
        return False
    return True


def create_computer_group_with_mcx(groupname, mcx_data):
    '''Creates or replaces a computer group containing MCX data
    Returns a boolean indicating success (or not)'''
    # with -q option an existing group will be replaced without confirmation
    cmd = ['/usr/sbin/dseditgroup', '-q', '-o', 'create',
           '-T', 'computergroup', groupname]
    _, err, exitcode = run(cmd)
    if exitcode:
        display.display_error(
            "Error creating computergroup %s: %s" % (groupname, err))
        return False
    mcx_plist = os.path.join(
        tempfile.mkdtemp(dir=osutils.tmpdir()), 'mcx')
    FoundationPlist.writePlist(mcx_data, mcx_plist)
    computer_group_path = "/ComputerGroups/" + groupname
    cmd = ['/usr/bin/dscl', '.', 'mcximport', computer_group_path, mcx_plist]
    _, err, exitcode = run(cmd)
    try:
        os.unlink(mcx_plist)
    except OSError:
        pass
    if exitcode:
        display.display_error(
            "Error importing mcx into computergroup %s: %s" % (groupname, err))
        return False
    return add_local_computer_record_to_computer_group(groupname)


def delete_computer_group(groupname):
    '''Deletes a computer group.
    Returns a boolean indicating success (or not)'''
    cmd = ['/usr/bin/dscl', '.', 'delete', '/ComputerGroups/' + groupname]
    _, err, exitcode = run(cmd)
    if exitcode:
        display.display_error(
            "Error deleting computergroup %s: %s" % (groupname, err))
        return False
    return True


@utils.Memoize
def domains_handled_by_plugins():
    '''Returns a list of profile PayloadTypes handled by plugins'''
    xpcservices = ('/System/Library/PrivateFrameworks/'
                   'ConfigurationProfiles.framework/XPCServices')
    domain_list = []
    for item in os.listdir(xpcservices):
        info_plist = os.path.join(xpcservices, item, "Contents/Info.plist")
        try:
            info = FoundationPlist.readPlist(info_plist)
            domains_supported = info.get(
                'ProfileDomainService', {}).get('DomainsSupported')
            if domains_supported:
                domain_list.extend(domains_supported)
        except FoundationPlist.FoundationPlistException:
            pass

    plugin_dirs = (
        '/System/Library/CoreServices/ManagedClient.app/Contents/PlugIns',
        '/System/Library/ConfigurationProfiles/PlugIns',
    )
    ignore_plugins = (
        'mcx.profileDomainPlugin',
        'loginwindow.profileDomainPlugin',
    )
    for plugin_dir in plugin_dirs:
        for item in os.listdir(plugin_dir):
            if item in ignore_plugins:
                continue
            if not item.endswith('.profileDomainPlugin'):
                continue
            plugin_path = os.path.join(plugin_dir, item)
            plugin = NSBundle.bundleWithPath_(plugin_path)
            principal_class = plugin.principalClass()
            domains_supported = list(
                principal_class.new().pdp_pluginDomainsSupported())
            if domains_supported:
                domain_list.extend(domains_supported)

    return domain_list


def domain_is_handled_by_plugin(domain):
    '''Returns a boolean -- True if the domain/PayloadType is handled by
    a plugin'''
    return domain in domains_handled_by_plugins()
