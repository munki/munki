#!/usr/bin/python
'''This is a basic example of a conditional script which outputs 2 key/value pairs:
Examples:
if_name,en0
ip_address,192.168.1.128

NOTE: Information gathered is ONLY for the primary interface'''

from SystemConfiguration import *    # from pyObjC
import socket
import collections
import os

NETWORK_INFO = {}

def getIPAddress(service_uuid):
    # print service_uuid
    ds = SCDynamicStoreCreate(None, 'GetIPv4Addresses', None, None)
    newpattern = SCDynamicStoreKeyCreateNetworkServiceEntity(None,
                                                          kSCDynamicStoreDomainState,
                                                          service_uuid,
                                                          kSCEntNetIPv4)
    
    newpatterns = CFArrayCreate(None, (newpattern, ), 1, kCFTypeArrayCallBacks)
    ipaddressDict = SCDynamicStoreCopyMultiple(ds, None, newpatterns)
    for ipaddress in ipaddressDict.values():
        ipaddy = ipaddress['Addresses'][0]
        return ipaddy


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
        print "if_name,%s" % ifname
        print "ip_address,%s" % NETWORK_INFO['ip_address']


getNetworkInfo()
