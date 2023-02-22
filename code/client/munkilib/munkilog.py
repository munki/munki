# encoding: utf-8
#
# Copyright 2009-2023 Greg Neagle.
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
munkilog.py

Created by Greg Neagle on 2016-12-14.


Logging functions for Munki
"""
from __future__ import absolute_import, print_function

import codecs
import logging
import logging.handlers
import os
import time

from . import prefs


def logging_level():
    '''Returns the logging level, which might be defined badly by the admin'''
    try:
        return int(prefs.pref('LoggingLevel'))
    except TypeError:
        return 1


def log(msg, logname=''):
    """Generic logging function."""
    if len(msg) > 1000:
        # See http://bugs.python.org/issue11907 and RFC-3164
        # break up huge msg into chunks and send 1000 characters at a time
        msg_buffer = msg
        while msg_buffer:
            logging.info(msg_buffer[:1000])
            msg_buffer = msg_buffer[1000:]
    else:
        logging.info(msg)  # noop unless configure_syslog() is called first.

    # date/time format string
    formatstr = '%b %d %Y %H:%M:%S %z'
    if not logname:
        # use our regular logfile
        logpath = prefs.pref('LogFile')
    else:
        logpath = os.path.join(os.path.dirname(prefs.pref('LogFile')), logname)
    try:
        fileobj = codecs.open(logpath, mode='a', encoding='UTF-8')
        try:
            fileobj.write("%s %s\n" % (time.strftime(formatstr), msg))
        except (OSError, IOError):
            pass
        fileobj.close()
    except (OSError, IOError):
        pass


def configure_syslog():
    """Configures logging to system.log, when pref('LogToSyslog') == True."""
    logger = logging.getLogger()
    # Remove existing handlers to avoid sending unexpected messages.
    for handler in logger.handlers:
        logger.removeHandler(handler)
    logger.setLevel(logging.DEBUG)

    # If /System/Library/LaunchDaemons/com.apple.syslogd.plist is restarted
    # then /var/run/syslog stops listening.  If we fail to catch this then
    # Munki completely errors.
    try:
        syslog = logging.handlers.SysLogHandler('/var/run/syslog')
    except BaseException:
        log('LogToSyslog is enabled but socket connection failed.')
        return

    syslog.setFormatter(logging.Formatter('munki: %(message)s'))
    syslog.setLevel(logging.INFO)
    logger.addHandler(syslog)


def rotatelog(logname=''):
    """Rotate a log"""
    if not logname:
        # use our regular logfile
        logpath = prefs.pref('LogFile')
    else:
        logpath = os.path.join(os.path.dirname(prefs.pref('LogFile')), logname)
    if os.path.exists(logpath):
        for i in range(3, -1, -1):
            try:
                os.unlink(logpath + '.' + str(i + 1))
            except (OSError, IOError):
                pass
            try:
                os.rename(logpath + '.' + str(i), logpath + '.' + str(i + 1))
            except (OSError, IOError):
                pass
        try:
            os.rename(logpath, logpath + '.0')
        except (OSError, IOError):
            pass


def rotate_main_log():
    """Rotate our main log"""
    main_log = prefs.pref('LogFile')
    if os.path.exists(main_log):
        if os.path.getsize(main_log) > 1000000:
            rotatelog(main_log)


def reset_warnings():
    """Rotate our warnings log."""
    warningsfile = os.path.join(
        os.path.dirname(prefs.pref('LogFile')), 'warnings.log')
    if os.path.exists(warningsfile):
        rotatelog(warningsfile)


def reset_errors():
    """Rotate our errors.log"""
    errorsfile = os.path.join(
        os.path.dirname(prefs.pref('LogFile')), 'errors.log')
    if os.path.exists(errorsfile):
        rotatelog(errorsfile)


if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
