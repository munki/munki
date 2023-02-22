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
display.py

Created by Greg Neagle on 2016-12-13.

Common output functions
"""
from __future__ import absolute_import, print_function

import sys
import warnings

from . import munkilog
from . import reports
from . import munkistatus
from .wrappers import unicode_or_str


def _getsteps(num_of_steps, limit):
    """
    Helper function for display_percent_done
    """
    steps = []
    current = 0.0
    for i in range(0, num_of_steps):
        if i == num_of_steps-1:
            steps.append(int(round(limit)))
        else:
            steps.append(int(round(current)))
        current += float(limit)/float(num_of_steps-1)
    return steps


def display_percent_done(current, maximum):
    """
    Mimics the command-line progress meter seen in some
    of Apple's tools (like softwareupdate), and tells
    MunkiStatus to display percent done via progress bar.
    """
    if current >= maximum:
        percentdone = 100
    else:
        percentdone = int(float(current)/float(maximum)*100)
    if munkistatusoutput:
        munkistatus.percent(str(percentdone))

    if verbose:
        step = _getsteps(16, maximum)
        output = ''
        indicator = ['\t0', '.', '.', '20', '.', '.', '40', '.', '.',
                     '60', '.', '.', '80', '.', '.', '100\n']
        for i in range(0, 16):
            if current >= step[i]:
                output += indicator[i]
        if output:
            sys.stdout.write('\r' + output)
            sys.stdout.flush()


def str_to_ascii(a_string):
    """Given str (unicode, latin-1, or not) return ascii.

    Args:
      s: str, likely in Unicode-16BE, UTF-8, or Latin-1 charset
    Returns:
      str, ascii form, no >7bit chars
    """
    try:
        return unicode_or_str(a_string).encode('ascii', 'ignore')
    except UnicodeDecodeError:
        return a_string.decode('ascii', 'ignore')


def _to_unicode(obj, encoding='UTF-8'):
    """Coerces obj to unicode"""
    # pylint: disable=basestring-builtin, unicode-builtin
    try:
        if isinstance(obj, basestring):
            if not isinstance(obj, unicode):
                obj = unicode(obj, encoding)
    except NameError:
        # Python 3
        if isinstance(obj, bytes):
            obj = obj.decode(encoding)
    return obj


def _concat_message(msg, *args):
    """Concatenates a string with any additional arguments,
    making sure everything is unicode"""
    # coerce msg to unicode if it's not already
    msg = _to_unicode(msg)
    if args:
        # coerce all args to unicode as well
        args = [_to_unicode(arg) for arg in args]
        try:
            msg = msg % tuple(args)
        except TypeError as dummy_err:
            warnings.warn(
                'String format does not match concat args: %s'
                % (str(sys.exc_info())))
    return msg.rstrip()


def display_status_major(msg, *args):
    """
    Displays major status messages, formatting as needed
    for verbose/non-verbose and munkistatus-style output.
    """
    msg = _concat_message(msg, *args)
    munkilog.log(msg)
    if munkistatusoutput:
        munkistatus.message(msg)
        munkistatus.detail('')
        munkistatus.percent(-1)
    if verbose:
        if msg.endswith('.') or msg.endswith(u'…'):
            print('%s' % msg)
        else:
            print('%s...' % msg)
        sys.stdout.flush()


def display_status_minor(msg, *args):
    """
    Displays minor status messages, formatting as needed
    for verbose/non-verbose and munkistatus-style output.
    """
    msg = _concat_message(msg, *args)
    munkilog.log(u'    ' + msg)
    if munkistatusoutput:
        munkistatus.detail(msg)
    if verbose:
        if msg.endswith('.') or msg.endswith(u'…'):
            print('    %s' % msg)
        else:
            print('    %s...' % msg)
        sys.stdout.flush()


def display_info(msg, *args):
    """
    Displays info messages.
    Not displayed in MunkiStatus.
    """
    msg = _concat_message(msg, *args)
    munkilog.log(u'    ' + msg)
    if verbose > 0:
        print('    %s' % msg)
        sys.stdout.flush()


def display_detail(msg, *args):
    """
    Displays minor info messages.
    Not displayed in MunkiStatus.
    These are usually logged only, but can be printed to
    stdout if verbose is set greater than 1
    """
    msg = _concat_message(msg, *args)
    if verbose > 1:
        print('    %s' % msg)
        sys.stdout.flush()
    if munkilog.logging_level() > 0:
        munkilog.log(u'    ' + msg)


def display_debug1(msg, *args):
    """
    Displays debug messages, formatting as needed.
    """
    msg = _concat_message(msg, *args)
    if verbose > 2:
        print('    %s' % msg)
        sys.stdout.flush()
    if munkilog.logging_level() > 1:
        munkilog.log('DEBUG1: %s' % msg)


def display_debug2(msg, *args):
    """
    Displays debug messages, formatting as needed.
    """
    msg = _concat_message(msg, *args)
    if verbose > 3:
        print('    %s' % msg)
    if munkilog.logging_level() > 2:
        munkilog.log('DEBUG2: %s' % msg)


def display_warning(msg, *args):
    """
    Prints warning msgs to stderr and the log
    """
    msg = _concat_message(msg, *args)
    warning = 'WARNING: %s' % msg
    if verbose > 0:
        print(warning, file=sys.stderr)
    munkilog.log(warning)
    # append this warning to our warnings log
    munkilog.log(warning, 'warnings.log')
    # collect the warning for later reporting
    if 'Warnings' not in reports.report:
        reports.report['Warnings'] = []
    reports.report['Warnings'].append('%s' % msg)


def display_error(msg, *args):
    """
    Prints msg to stderr and the log
    """
    msg = _concat_message(msg, *args)
    errmsg = 'ERROR: %s' % msg
    if verbose > 0:
        print(errmsg, file=sys.stderr)
    munkilog.log(errmsg)
    # append this error to our errors log
    munkilog.log(errmsg, 'errors.log')
    # collect the errors for later reporting
    if 'Errors' not in reports.report:
        reports.report['Errors'] = []
    reports.report['Errors'].append('%s' % msg)


# module globals
# pylint: disable=invalid-name
verbose = 1
munkistatusoutput = True
# pylint: enable=invalid-name


if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
