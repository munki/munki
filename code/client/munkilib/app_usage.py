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
app_usage

Created by Greg Neagle on 2017-02-18.

Code for working with the app usage database.
Much code lifted from the application_usage scripts created by Google MacOps:
    https://github.com/google/macops/tree/master/crankd

"""
from __future__ import absolute_import, print_function

# standard Python libs
import logging
import os
import sqlite3
import time

# our libs
#from . import display
from . import prefs


# SQLite db to store application usage data
APPLICATION_USAGE_DB = os.path.join(
    prefs.pref('ManagedInstallDir'), 'application_usage.sqlite')
# SQL to detect existence of application usage table
APPLICATION_USAGE_TABLE_DETECT = 'SELECT * FROM application_usage LIMIT 1'
# This table creates ~64 bytes of disk data per event.
APPLICATION_USAGE_TABLE_CREATE = (
    'CREATE TABLE application_usage ('
    'event TEXT,'
    'bundle_id TEXT,'
    'app_version TEXT,'
    'app_path TEXT,'
    'last_time INTEGER DEFAULT 0,'
    'number_times INTEGER DEFAULT 0,'
    'PRIMARY KEY (event, bundle_id)'
    ')')

APPLICATION_USAGE_TABLE_INSERT = (
    'INSERT INTO application_usage VALUES ('
    '?, '  # event
    '?, '  # bundle_id
    '?, '  # app_version
    '?, '  # app_path
    '?, '  # last_time
    '? '   # number_times
    ')'
    )

# keep same order of columns as APPLICATION_USAGE_TABLE_INSERT
APPLICATION_USAGE_TABLE_SELECT = (
    'SELECT '
    'event, bundle_id, app_version, app_path, last_time, number_times '
    'FROM application_usage'
    )

APPLICATION_USAGE_TABLE_UPDATE = (
    'UPDATE application_usage SET '
    'app_version=?,'
    'app_path=?,'
    'last_time=?,'
    'number_times=number_times+1 '
    'WHERE event=? and bundle_id=?'
    )

INSTALL_REQUEST_TABLE_DETECT = 'SELECT * FROM install_requests LIMIT 1'

INSTALL_REQUEST_TABLE_CREATE = (
    'CREATE TABLE install_requests ('
    'event TEXT,'
    'item_name TEXT,'
    'item_version TEXT,'
    'last_time INTEGER DEFAULT 0,'
    'number_times INTEGER DEFAULT 0,'
    'PRIMARY KEY (event, item_name)'
    ')')

INSTALL_REQUEST_TABLE_INSERT = (
    'INSERT INTO install_requests VALUES ('
    '?, '  # event
    '?, '  # item_name
    '?, '  # item_version
    '?, '  # last_time
    '? '   # number_times
    ')'
    )

# keep same order of columns as INSTALL_REQUEST_TABLE_INSERT
INSTALL_REQUEST_TABLE_SELECT = (
    'SELECT '
    'event, item_name, item_version, last_time, number_times '
    'FROM install_requests'
    )

INSTALL_REQUEST_TABLE_UPDATE = (
    'UPDATE install_requests SET '
    'item_version=?,'
    'last_time=?,'
    'number_times=number_times+1 '
    'WHERE event=? and item_name=?'
    )


class ApplicationUsageRecorder(object):
    """Tracks application launches, activations, and quits.
    Also tracks Munki selfservice install and removal requests."""

    def _connect(self, database_name=None):
        """Connect to database.
        Args:
          database_name: str, default APPLICATION_USAGE_DB
        Returns:
          sqlite3.Connection instance
        """
        # pylint: disable=no-self-use
        if database_name is None:
            database_name = APPLICATION_USAGE_DB

        conn = sqlite3.connect(database_name)
        return conn

    def _close(self, conn):
        """Close database.
        Args:
          conn: sqlite3.Connection instance
        """
        # pylint: disable=no-self-use
        conn.close()

    def _detect_table(self, conn, table_detection_sql):
        """Detect whether the application usage table exists.
        Args:
          conn: sqlite3.Connection object
          table_detection_sql: sql query used to detect if the
                               table exists
        Returns:
          True if the table exists, False if not.
        Raises:
          sqlite3.Error: if error occurs
        """
        # pylint: disable=no-self-use
        try:
            conn.execute(table_detection_sql)
            exists = True
        except sqlite3.OperationalError as err:
            if err.args[0].startswith('no such table'):
                exists = False
            else:
                raise
        return exists

    def _detect_application_usage_table(self, conn):
        """Detect whether the application usage table exists.
        Args:
          conn: sqlite3.Connection object
        Returns:
          True if the table exists, False if not.
        Raises:
          sqlite3.Error: if error occurs
        """
        # pylint: disable=no-self-use
        return self._detect_table(conn, APPLICATION_USAGE_TABLE_DETECT)

    def _detect_install_request_table(self, conn):
        """Detect whether the application usage table exists.
        Args:
          conn: sqlite3.Connection object
        Returns:
          True if the table exists, False if not.
        Raises:
          sqlite3.Error: if error occurs
        """
        # pylint: disable=no-self-use
        return self._detect_table(conn, INSTALL_REQUEST_TABLE_DETECT)

    def _create_application_usage_table(self, conn):
        """Create application usage table when it does not exist.
        Args:
          conn: sqlite3.Connection object
        Raises:
          sqlite3.Error: if error occurs
        """
        # pylint: disable=no-self-use
        conn.execute(APPLICATION_USAGE_TABLE_CREATE)

    def _insert_application_usage(self, conn, event, app_dict):
        """Insert usage data into application usage table.
        Args:
          conn: sqlite3.Connection object
          event: str
          app_dict: {bundle_id: str,
                     version: str,
                     path: str}
        """
        # pylint: disable=no-self-use
        # this looks weird, but it's the simplest way to do an update or insert
        # operation in sqlite, and atomically update number_times, that I could
        # figure out.  plus we avoid using transactions and multiple SQL
        # statements in most cases.

        now = int(time.time())
        bundle_id = app_dict.get('bundle_id', 'UNKNOWN_APP')
        app_version = app_dict.get('version', '0')
        app_path = app_dict.get('path', '')
        data = (app_version, app_path, now, event, bundle_id)
        query = conn.execute(APPLICATION_USAGE_TABLE_UPDATE, data)
        if query.rowcount == 0:
            number_times = 1
            data = (event, bundle_id, app_version, app_path, now, number_times)
            conn.execute(APPLICATION_USAGE_TABLE_INSERT, data)

    def _create_install_request_table(self, conn):
        """Create install request table when it does not exist.
        Args:
          conn: sqlite3.Connection object
        Raises:
          sqlite3.Error: if error occurs
        """
        # pylint: disable=no-self-use
        conn.execute(INSTALL_REQUEST_TABLE_CREATE)

    def _insert_install_request(self, conn, request_dict):
        """Insert usage data into application usage table.
        Args:
          conn: sqlite3.Connection object
          event: str
          request_dict: {name: str,
                         version: str}
        """
        # pylint: disable=no-self-use
        # this looks weird, but it's the simplest way to do an update or insert
        # operation in sqlite, and atomically update number_times, that I could
        # figure out.  plus we avoid using transactions and multiple SQL
        # statements in most cases.

        now = int(time.time())
        event = request_dict.get('event', 'UNKNOWN_EVENT')
        item_name = request_dict.get('name', 'UNKNOWN_ITEM')
        item_version = request_dict.get('version', '0')
        data = (item_version, now, event, item_name)
        query = conn.execute(INSTALL_REQUEST_TABLE_UPDATE, data)
        if query.rowcount == 0:
            number_times = 1
            data = (event, item_name, item_version, now, number_times)
            conn.execute(INSTALL_REQUEST_TABLE_INSERT, data)

    def _recreate_database(self):
        """Recreate a database.
        Returns:
          int number of rows that were recovered from old database
          and written into new one
        """
        recovered = 0

        tables = [{'select_sql': APPLICATION_USAGE_TABLE_SELECT,
                   'create_sql': APPLICATION_USAGE_TABLE_CREATE,
                   'insert_sql': APPLICATION_USAGE_TABLE_INSERT,
                   'rows': []},
                  {'select_sql': INSTALL_REQUEST_TABLE_SELECT,
                   'create_sql': INSTALL_REQUEST_TABLE_CREATE,
                   'insert_sql': INSTALL_REQUEST_TABLE_INSERT,
                   'rows': []}]

        try:
            conn = self._connect()
            for table in tables:
                query = conn.execute(table['select_sql'])
                try:
                    while True:
                        row = query.fetchone()
                        if not row:
                            break
                        table['rows'].append(row)
                except sqlite3.Error:
                    pass
                    # ok, done, hit an error
            conn.close()
        except sqlite3.Error as err:
            logging.error('Unhandled error reading existing db: %s', str(err))
            return recovered

        usage_db_tmp = '%s.tmp.%d' % (APPLICATION_USAGE_DB, os.getpid())

        recovered = 0
        try:
            conn = self._connect(usage_db_tmp)
            for table in tables:
                conn.execute(table['create_sql'])
                for row in table['rows']:
                    if row[1] == '':
                        # skip rows with empty bundle_id or item_name
                        continue
                    try:
                        conn.execute(table['insert_sql'], row)
                        conn.commit()
                        recovered += 1
                    except sqlite3.IntegrityError as err:
                        logging.error(
                            'Ignored error: %s: %s', str(err), str(row))
            self._close(conn)
            os.unlink(APPLICATION_USAGE_DB)
            os.rename(usage_db_tmp, APPLICATION_USAGE_DB)
        except sqlite3.Error as err:
            logging.error('Unhandled error: %s', str(err))
            recovered = 0

        return recovered

    def verify_database(self, fix=False):
        """Verify database integrity."""
        conn = self._connect()
        try:
            for sql in [APPLICATION_USAGE_TABLE_SELECT,
                        INSTALL_REQUEST_TABLE_SELECT]:
                query = conn.execute(sql)
                dummy_rows = query.fetchall()
            query_ok = True
        except sqlite3.Error:
            query_ok = False

        if not query_ok:
            if fix:
                logging.warning('Recreating database.')
                logging.warning(
                    'Recovered %d rows.', self._recreate_database())
            else:
                logging.warning('Database is malformed.')
        else:
            logging.info('Database is OK.')

    def log_application_usage(self, event, app_dict):
        """Log application usage.
        Args:
            event: str, like "launch" or "quit"
            app_dict: Dictionary containing bundle_id, version, path
        """
        if app_dict.get('bundle_id') is None:
            logging.warning(
                'Application object had no bundle_id: %s', app_dict.get('path'))
            return

        logging.debug('%s: bundle_id: %s version: %s path: %s', event,
                      app_dict.get('bundle_id'),
                      app_dict.get('version'),
                      app_dict.get('path'))
        try:
            conn = self._connect()
            if not self._detect_application_usage_table(conn):
                self._create_application_usage_table(conn)
            self._insert_application_usage(conn, event, app_dict)
            conn.commit()
        except sqlite3.OperationalError as err:
            logging.error('Error writing %s event to database: %s', event, err)
        except sqlite3.DatabaseError as err:
            if err.args[0] == 'database disk image is malformed':
                self._recreate_database()
            logging.error('Database error: %s', err)
        self._close(conn)

    def log_install_request(self, request_dict):
        """Log install request.
        Args:
            request_dict: Dictionary containing:
                event: str, like "install" or "remove"
                name: str
                version: str
        """
        if (request_dict.get('event') is None or
                request_dict.get('name') is None):
            logging.warning(
                'Request dict is missing event or name: %s', request_dict)
            return

        logging.debug('%s: name: %s version: %s',
                      request_dict.get('event'),
                      request_dict.get('name'),
                      request_dict.get('version'))

        try:
            conn = self._connect()
            if not self._detect_install_request_table(conn):
                self._create_install_request_table(conn)
            self._insert_install_request(conn, request_dict)
            conn.commit()
        except sqlite3.OperationalError as err:
            logging.error('Error writing install request to database: %s', err)
        except sqlite3.DatabaseError as err:
            if err.args[0] == 'database is malformed':
                self._recreate_database()
            logging.error('Database error: %s', err)
        self._close(conn)


class ApplicationUsageQuery(object):
    '''A class to query our application usage db to determine the last time
    an application was activated'''

    def __init__(self):
        '''Open connection to DB'''
        self.database = APPLICATION_USAGE_DB
        self.day_in_seconds = 24 * 60 * 60
        try:
            self.conn = sqlite3.connect(self.database)
        except sqlite3.Error as err:
            logging.error(
                'Error connecting to %s: %s', self.database, str(err))
            self.conn = None

    def __del__(self):
        '''Close connection to DB'''
        if self.conn:
            try:
                self.conn.close()
            except sqlite3.Error:
                pass

    def days_of_data(self):
        '''Returns how many days of data we have on file'''

        oldest_record_query = (
            'SELECT last_time FROM application_usage '
            'ORDER BY last_time ASC LIMIT 1'
        )

        if not self.conn:
            return None
        try:
            query = self.conn.execute(oldest_record_query)
            row = query.fetchone()
            time_diff = int(time.time()) - int(row[0])
            return int(time_diff/self.day_in_seconds)
        except sqlite3.Error as err:
            logging.error(
                'Error querying %s: %s', self.database, str(err))
            return 0

    def days_since_last_usage_event(self, event, bundle_id):
        '''Perform db query and return the number of days since the last event
        occurred for bundle_id.
        Returns None if database is missing or broken;
        Returns -1 if there is no event record for the bundle_id
        Returns int number of days since last event otherwise'''

        usage_query = (
            'SELECT last_time FROM application_usage '
            'WHERE event=? AND bundle_id=?'
        )

        if not self.conn:
            return None
        try:
            query = self.conn.execute(usage_query, (event, bundle_id))
            # should be only one!
            row = query.fetchone()
            if row:
                time_diff = int(time.time()) - int(row[0])
                return int(time_diff/self.day_in_seconds)
            # no row
            return -1
        except sqlite3.Error as err:
            logging.error(
                'Error querying %s: %s', self.database, str(err))
            return None

    def days_since_last_install_event(self, event, item_name):
        '''Perform db query and return the number of days since the last
        install request event occurred for item_name.
        Returns None if database is missing or broken;
        Returns -1 if there are no matching records for the item_name
        Returns int number of days since last event otherwise'''

        install_query = (
            'SELECT last_time FROM install_requests '
            'WHERE event=? AND item_name=?'
        )

        if not self.conn:
            return None
        try:
            query = self.conn.execute(install_query, (event, item_name))
            # should be only one!
            row = query.fetchone()
            if row:
                time_diff = int(time.time()) - int(row[0])
                return int(time_diff/self.day_in_seconds)
            # no row
            return -1
        except sqlite3.Error as err:
            logging.error(
                'Error querying %s: %s', self.database, str(err))
            return None


if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
