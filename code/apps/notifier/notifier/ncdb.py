# -*- coding: utf-8 -*-
#
#  ncdb.py
#  notifier
#
#  Created by Greg Neagle on 4/15/15.
#  Copyright (c) 2015 The Munki Project. All rights reserved.
#

from glob import glob
import os
import subprocess
import sqlite3

def get_nc_db():
    '''Returns a path to the current (hopefully?) NotificationCenter db'''
    nc_db = None
    # try DARWIN_USER_DIR location first
    cmd = ['/usr/bin/getconf', 'DARWIN_USER_DIR']
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, err = proc.communicate()
    darwin_user_dir = output.rstrip()
    nc_db = os.path.join(darwin_user_dir, 'com.apple.notificationcenter/db/db')
    if os.path.exists(nc_db):
        return nc_db
    # try the 'old' path
    nc_nb_path = os.path.expanduser(
            '~/Library/Application Support/NotificationCenter/')
    nc_dbs = glob(nc_nb_path + '*.db')
    if nc_dbs:
        nc_dbs.sort(key=os.path.getmtime)
        # most recently modified will be the last one
        nc_db = nc_dbs[-1]
    return nc_db


def connect_to_db():
    '''Connect to the Notification Center db and return connection object
        and cursor'''
    conn = None
    curs = None
    #Connect To SQLLite
    nc_db = get_nc_db()
    if nc_db:
        conn = sqlite3.connect(nc_db)
        conn.text_factory = str
        curs = conn.cursor()
    return conn, curs


def bundleid_exists(bundle_id):
    '''Returns a boolean telling us if the bundle_id is in the database.'''
    conn, curs = connect_to_db()
    curs.execute("SELECT bundleid from app_info WHERE bundleid IS '%s'"
                 % bundle_id)
    matching_ids = [row[0] for row in curs.fetchall()]
    conn.close()
    return len(matching_ids) > 0


# flags are bits in a 16 bit(?) data structure
DONT_SHOW_IN_CENTER = 1 << 0
BADGE_ICONS = 1 << 1
SOUNDS = 1 << 2
BANNER_STYLE = 1 << 3
ALERT_STYLE = 1 << 4
UNKNOWN_5 = 1 << 5
UNKNOWN_6 = 1 << 6
UNKNOWN_7 = 1 << 7
UNKNOWN_8 = 1 << 8
UNKNOWN_9 = 1 << 9
UNKNOWN_10 = 1 << 10
UNKNOWN_11 = 1 << 11
SUPPRESS_NOTIFICATIONS_ON_LOCKSCREEN = 1 << 12
SHOW_PREVIEWS_ALWAYS = 1 << 13
SUPPRESS_MESSAGE_PREVIEWS = 1 << 14
UNKNOWN_15 = 1 << 15


def get_flags(bundle_id):
    '''Returns flags for bundle_id'''
    conn, curs = connect_to_db()
    curs.execute("SELECT flags from app_info where bundleid='%s'" % (bundle_id))
    try:
        flags = curs.fetchall()[0][0]
    except IndexError:
        flags = 0
    conn.close()
    return int(flags)


def get_alert_style(bundle_id):
    '''Get the alert style for bundle_id'''
    current_flags = get_flags(bundle_id)
    if current_flags & ALERT_STYLE:
        return "alerts"
    elif current_flags & BANNER_STYLE:
        return "banners"
    else:
        return "none"

