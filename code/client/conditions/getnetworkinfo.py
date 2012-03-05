#!/usr/bin/python
'''This is a basic example of a conditional script which outputs 2 key/value pairs:
Examples:
primary_interface_name: en0
primary_ip_address: 192.168.1.128

NOTE: Information gathered is ONLY for the primary interface'''

from SystemConfiguration import *    # from pyObjC
import socket
import collections
import os
import plistlib

from Foundation import CFPreferencesCopyAppValue

# Read the location of the ManagedInstallDir from ManagedInstall.plist
BUNDLE_ID = 'ManagedInstalls'
pref_name = 'ManagedInstallDir'
managedinstalldir = CFPreferencesCopyAppValue(pref_name, BUNDLE_ID)
# Make sure we're outputting our information to "ConditionalItems.plist"
conditionalitemspath = os.path.join(managedinstalldir, 'ConditionalItems.plist')

NETWORK_INFO = {}
def getIPAddress(service_uuid):
    ds = SCDynamicStoreCreate(None, 'GetIPv4Addresses', None, None)
    newpattern = SCDynamicStoreKeyCreateNetworkServiceEntity(None,
                                                          kSCDynamicStoreDomainState,
                                                          service_uuid,
                                                          kSCEntNetIPv4)

    newpatterns = CFArrayCreate(None, (newpattern, ), 1, kCFTypeArrayCallBacks)
    ipaddressDict = SCDynamicStoreCopyMultiple(ds, None, newpatterns)
    for ipaddress in ipaddressDict.values():
        ipv4address = ipaddress['Addresses'][0]
        return ipv4address


def getNetworkInfo():
    ds = SCDynamicStoreCreate(None, 'GetIPv4Addresses', None, None)

    pattern = SCDynamicStoreKeyCreateNetworkGlobalEntity(None,
                                                        kSCDynamicStoreDomainState,
                                                        kSCEntNetIPv4);
    patterns = CFArrayCreate(None, (pattern, ), 1, kCFTypeArrayCallBacks)
    valueDict = SCDynamicStoreCopyMultiple(ds, None, patterns)

    ipv4info = collections.namedtuple('ipv4info', 'ifname ip router service')

    for serviceDict in valueDict.values():
        ifname = serviceDict[u'PrimaryInterface']
        NETWORK_INFO['interface'] = serviceDict[u'PrimaryInterface']
        NETWORK_INFO['service_uuid'] = serviceDict[u'PrimaryService']
        NETWORK_INFO['router'] = serviceDict[u'Router']
        NETWORK_INFO['ip_address'] = getIPAddress(serviceDict[u'PrimaryService'])

        netinfo_dict = dict(
            primary_interface_name = ifname,
            primary_ip_address = NETWORK_INFO['ip_address'],
        )

        # CRITICAL!
        if os.path.exists(conditionalitemspath):
            # "ConditionalItems.plist" exists, so read it FIRST (existing_dict)
            existing_dict = plistlib.readPlist(conditionalitemspath)
            # Create output_dict which joins new data generated in this script with existing data
            output_dict = dict(existing_dict.items() + netinfo_dict.items())
        else:
            # "ConditionalItems.plist" does not exist,
            # output only consists of data generated in this script
            output_dict = netinfo_dict

        # Write out data to "ConditionalItems.plist"
        plistlib.writePlist(output_dict, conditionalitemspath)

getNetworkInfo()
