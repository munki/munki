# -*- coding: utf-8 -*-
#
#  passwdutil.py
#  Managed Software Center
#
#  Created by Greg Neagle on 4/18/17.
#  Copyright (c) 2018-2019 The Munki Project. All rights reserved.
#
'''Code to interact with the OpenDirectory framework'''


import OpenDirectory as OD
from Foundation import NSLog

def findODuserRecords(username, nodename='/Search'):
    '''Uses OpenDirectory methods to find user records for username'''
    mySession = OD.ODSession.defaultSession()
    if not mySession:
        NSLog('DS session error: no default session')
        return None
    searchNode, err = OD.ODNode.nodeWithSession_name_error_(
                                                mySession, nodename, None)
    if not searchNode:
        NSLog('DS node error: %s' % err)
        return None
    myQuery, err = OD.ODQuery.queryWithNode_forRecordTypes_attribute_matchType_queryValues_returnAttributes_maximumResults_error_(
            searchNode,
            OD.kODRecordTypeUsers,
            OD.kODAttributeTypeRecordName,
            OD.kODMatchEqualTo, 
            username, 
            OD.kODAttributeTypeAllAttributes,
            0, 
            None)
    results, err = myQuery.resultsAllowingPartial_error_(False, None)
    if not results:
        return None
    return results


def findODuserRecord(username, nodename='/Search'):
    '''Returns first record found for username.'''
    records = findODuserRecords(username, nodename)
    if records:
        return records[0]
    else:
        return None


def verifyPassword(username, password):
    '''Uses OpenDirectory methods to verify password for username'''
    result = False
    userRecord = findODuserRecord(username)
    if userRecord:
        result, unused_err = userRecord.verifyPassword_error_(
                                                            password, None)
    return result