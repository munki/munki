# encoding: utf-8
#
#  msclog.py
#  Managed Software Center
#
#  Created by Greg Neagle on 2/23/14.
#  Original by John Randolph <jrand@google.com>
#
# Copyright 2009-2019 Greg Neagle.
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

'''Implements client logging for Managed Software Center.app'''

import logging
import os
import random
import stat

import munki

from Foundation import NSLog

MSULOGDIR = \
    "/Users/Shared/.com.googlecode.munki.ManagedSoftwareUpdate.logs"
MSULOGFILE = "%s.log"
MSULOGENABLED = False
MSUDEBUGLOGENABLED = False

class FleetingFileHandler(logging.FileHandler):
    """File handler which opens/closes the log file only during log writes."""

    def __init__(self, filename, mode='a', encoding=None, delay=True):
        if hasattr(self, '_open'):  # if py2.6+ ...
            logging.FileHandler.__init__(self, filename, mode, encoding, delay)
        else:
            logging.FileHandler.__init__(self, filename, mode, encoding)
            # lots of py <=2.5 fixes to support delayed open and immediate
            # close.
            self.encoding = encoding
            self._open = self.__open
            self.flush = self.__flush
            self._close()

    def __open(self):
        """Open the log file."""
        if self.encoding is None:
            stream = open(self.baseFilename, self.mode)
        else:
            stream = logging.codecs.open(
                         self.baseFilename, self.mode, self.encoding)
        return stream

    def __flush(self):
        """Flush the stream if it is open."""
        if self.stream:
            self.stream.flush()

    def _close(self):
        """Close the log file if it is open."""
        if self.stream:
            self.flush()
            if hasattr(self.stream, 'close'):
                self.stream.close()
        self.stream = None

    def close(self):
        """Close the entire handler if it is open."""
        if self.stream:
            return logging.FileHandler.close(self)

    def emit(self, record):
        """Open the log, emit a record and close the log."""
        if self.stream is None:
            self.stream = self._open()
        logging.FileHandler.emit(self, record)
        self._close()


def setup_logging(username=None):
    """Setup logging module.

    Args:
        username: str, optional, current login name
    """
    global MSULOGENABLED
    global MSUDEBUGLOGENABLED

    if (logging.root.handlers and
        logging.root.handlers[0].__class__ is FleetingFileHandler):
        return
        
    if  munki.pref('MSUDebugLogEnabled'):
        MSUDEBUGLOGENABLED = True

    if munki.pref('MSULogEnabled'):
        MSULOGENABLED = True

    if not MSULOGENABLED:
        return

    if username is None:
        username = os.getlogin() or 'UID%d' % os.getuid()

    if not os.path.exists(MSULOGDIR):
        try:
            os.mkdir(MSULOGDIR, 01777)
        except OSError, err:
            logging.error('mkdir(%s): %s', MSULOGDIR, str(err))
            return

    if not os.path.isdir(MSULOGDIR):
        logging.error('%s is not a directory', MSULOGDIR)
        return

    # freshen permissions, if possible.
    try:
        os.chmod(MSULOGDIR, 01777)
    except OSError:
        pass

    # find a safe log file to write to for this user
    filename = os.path.join(MSULOGDIR, MSULOGFILE % username)
    attempt = 0
    ours = False

    while attempt < 10:
        try:
            fref = os.open(filename, os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW, 0600)
            st = os.fstat(fref)
            ours = stat.S_ISREG(st.st_mode) and st.st_uid == os.getuid()
            os.close(fref)
            if ours:
                break
        except (OSError, IOError):
            pass  # permission denied, symlink, ...

        # avoid creating many separate log files by using one static suffix
        # as the first alternative.  if unsuccessful, switch to totally
        # randomly suffixed files.
        if attempt == 0:
            random.seed(hash(username))
        elif attempt == 1:
            random.seed()

        filename = os.path.join(
            MSULOGDIR, MSULOGFILE % (
                '%s_%d' % (username, random.randint(0, 2**32))))

        attempt += 1

    if not ours:
        logging.error('No logging is possible')
        return

    # setup log handler

    log_format = '%(created)f %(levelname)s ' + username + ' : %(message)s'
    ffh = None

    try:
        ffh = FleetingFileHandler(filename)
    except IOError, err:
        logging.error('Error opening log file %s: %s', filename, str(err))

    ffh.setFormatter(logging.Formatter(log_format, None))
    logging.root.addHandler(ffh)
    logging.getLogger().setLevel(logging.INFO)


def log(source, event, msg=None, *args):
    """Log an event from a source.

    Args:
        source: str, like "MSU" or "user"
        event: str, like "exit"
        msg: str, optional, additional log output
        args: list, optional, arguments supplied to msg as format args
    """
    if not MSULOGENABLED:
        return

    if msg:
        if args:
            logging.info('@@%s:%s@@ ' + msg, source, event, *args)
        else:
            logging.info('@@%s:%s@@ %s', source, event, msg)
    else:
        logging.info('@@%s:%s@@', source, event)


def debug_log(msg):
    """Log to Apple System Log facility and also to MSU log if configured"""
    if MSUDEBUGLOGENABLED:
        NSLog('%@', msg)
        log('MSC', 'debug', msg)

