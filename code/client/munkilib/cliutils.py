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
cliutils

Created by Greg Neagle on 2017-03-12.

Functions supporting the admin command-line tools
"""
from __future__ import absolute_import, print_function

import ctypes
from ctypes.util import find_library
import os
import readline
import sys
import tempfile
try:
    # Python 2
    import thread
except ImportError:
    # Python 3
    import _thread as thread
import time
try:
    # Python 2
    from urllib import pathname2url
except ImportError:
    # Python 3
    from urllib.request import pathname2url
try:
    # Python 2
    from urlparse import urlparse, urljoin
except ImportError:
    # Python 3
    from urllib.parse import urlparse, urljoin
from xml.parsers.expat import ExpatError

from munkilib.wrappers import unicode_or_str, get_input, readPlist, writePlist, PlistReadError

FOUNDATION_SUPPORT = True
try:
    # PyLint cannot properly find names inside Cocoa libraries, so issues bogus
    # No name 'Foo' in module 'Bar' warnings. Disable them.
    # pylint: disable=E0611
    from Foundation import CFPreferencesAppSynchronize
    from Foundation import CFPreferencesCopyAppValue
    from Foundation import CFPreferencesSetAppValue
    # pylint: enable=E0611
except ImportError:
    # CoreFoundation/Foundation isn't available
    FOUNDATION_SUPPORT = False

BUNDLE_ID = 'com.googlecode.munki.munkiimport'
PREFSNAME = BUNDLE_ID + '.plist'
PREFSPATH = os.path.expanduser(os.path.join('~/Library/Preferences', PREFSNAME))

if FOUNDATION_SUPPORT:
    def pref(prefname):
        """Return a preference. Since this uses CFPreferencesCopyAppValue,
        Preferences can be defined several places. Precedence is:
            - MCX/Configuration Profile
            - ~/Library/Preferences/ByHost/
                com.googlecode.munki.munkiimport.XX.plist
            - ~/Library/Preferences/com.googlecode.munki.munkiimport.plist
            - /Library/Preferences/com.googlecode.munki.munkiimport.plist
        """
        return CFPreferencesCopyAppValue(prefname, BUNDLE_ID)

else:
    def pref(prefname):
        """Returns a preference for prefname. This is a fallback mechanism if
        CoreFoundation functions are not available -- for example to allow the
        possible use of makecatalogs or manifestutil on Linux"""
        if not hasattr(pref, 'cache'):
            pref.cache = None
        if not pref.cache:
            try:
                pref.cache = readPlist(PREFSPATH)
            except (IOError, OSError, ExpatError, PlistReadError):
                pref.cache = {}
        if prefname in pref.cache:
            return pref.cache[prefname]
        # no pref found
        return None


def get_version():
    """Returns version of munkitools, reading version.plist"""
    # this implementation avoids calling Foundation and will work on
    # non Apple OSes.
    vers = "UNKNOWN"
    build = ""
    # find the munkilib directory, and the version file
    munkilibdir = os.path.dirname(os.path.abspath(__file__))
    versionfile = os.path.join(munkilibdir, "version.plist")
    if os.path.exists(versionfile):
        try:
            vers_plist = readPlist(versionfile)
        except (IOError, OSError, ExpatError):
            pass
        else:
            try:
                vers = vers_plist['CFBundleShortVersionString']
                build = vers_plist['BuildNumber']
            except KeyError:
                pass
    if build:
        vers = vers + "." + build
    return vers


def path2url(path):
    '''Converts a path to a file: url'''
    return urljoin(
        'file:', 
        pathname2url(os.path.abspath(os.path.expanduser(path)))
    )


def print_utf8(text):
    '''Print Unicode text as UTF-8'''
    print(text.encode('UTF-8'))


def print_err_utf8(text):
    '''Print Unicode text to stderr as UTF-8'''
    print(text.encode('UTF-8'), file=sys.stderr)


class TempFile(object):
    '''A class that creates a temp file that is automatically deleted when
    the object goes out of scope.'''
    # pylint: disable=too-few-public-methods
    def __init__(self):
        filedesc, filepath = tempfile.mkstemp()
        # we just want the path; close the file descriptor
        os.close(filedesc)
        self.path = filepath

    def __del__(self):
        try:
            os.unlink(self.path)
        except OSError:
            pass


# pylint: disable=invalid-name
libedit = None
if 'libedit' in readline.__doc__:
    # readline module was compiled against libedit
    libedit = ctypes.cdll.LoadLibrary(find_library('libedit'))
# pylint: enable=invalid-name


def get_input_with_default(prompt, default_text):
    '''Get input from user with a prompt and a suggested default value'''

    # 10.6's libedit doesn't have the rl_set_prompt function, so we fall back
    # to the previous behavior
    darwin_vers = int(os.uname()[2].split('.')[0])
    if darwin_vers == 10:
        if default_text:
            prompt = '%s [%s]: ' % (prompt.rstrip(': '), default_text)
            return (unicode_or_str(get_input(prompt), encoding=sys.stdin.encoding) or
                    unicode_or_str(default_text))
        # no default value, just call raw_input
        return unicode_or_str(get_input(prompt), encoding=sys.stdin.encoding)

    # A nasty, nasty hack to get around Python readline limitations under
    # macOS. Gives us editable default text for configuration and munkiimport
    # choices'''
    def insert_default_text(prompt, text):
        '''Helper function'''
        time.sleep(0.01)
        if not isinstance(prompt, bytes):
            prompt = prompt.encode(sys.stdin.encoding)
        libedit.rl_set_prompt(prompt)
        if isinstance(text, bytes):
            text = text.decode(sys.stdin.encoding)
        readline.insert_text(text)
        libedit.rl_forced_update_display()

    readline.clear_history()
    if not default_text:
        return unicode_or_str(get_input(prompt), encoding=sys.stdin.encoding)
    elif libedit:
        # readline module was compiled against libedit
        thread.start_new_thread(
            insert_default_text, (prompt, default_text))
        return unicode_or_str(get_input(), encoding=sys.stdin.encoding)
    else:
        readline.set_startup_hook(lambda: readline.insert_text(default_text))
        try:
            return unicode_or_str(get_input(prompt), encoding=sys.stdin.encoding)
        finally:
            readline.set_startup_hook()


class ConfigurationSaveError(Exception):
    '''Error to raise if there's an error saving configuration'''
    pass


def configure(prompt_list):
    """Gets configuration options and saves them to preferences store"""
    darwin_vers = int(os.uname()[2].split('.')[0])
    edited_prefs = {}
    for (key, prompt) in prompt_list:
        newvalue = get_input_with_default('%15s: ' % prompt, pref(key))
        if darwin_vers == 10:
            # old behavior in SL: hitting return gives you an empty string,
            # and means accept the default value.
            edited_prefs[key] = newvalue or pref(key) or ''
        else:
            # just use the edited value as-is
            edited_prefs[key] = newvalue

    if FOUNDATION_SUPPORT:
        for key, value in edited_prefs.items():
            try:
                CFPreferencesSetAppValue(key, value, BUNDLE_ID)
            except BaseException:
                print('Could not save configuration!', file=sys.stderr)
                raise ConfigurationSaveError
            # remove repo_path if it exists since we don't use that
            # any longer (except for backwards compatibility) and we don't
            # want it getting out of sync with the repo_url
            CFPreferencesSetAppValue('repo_path', None, BUNDLE_ID)
        CFPreferencesAppSynchronize(BUNDLE_ID)

    else:
        try:
            existing_prefs = readPlist(PREFSPATH)
            existing_prefs.update(edited_prefs)
            # remove repo_path if it exists since we don't use that
            # any longer (except for backwards compatibility) and we don't
            # want it getting out of sync with the repo_url
            if 'repo_path' in existing_prefs:
                del existing_prefs['repo_path']
            writePlist(existing_prefs, PREFSPATH)
        except (IOError, OSError, ExpatError):
            print('Could not save configuration to %s' % PREFSPATH,
                  file=sys.stderr)
            raise ConfigurationSaveError


if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
