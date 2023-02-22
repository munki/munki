# encoding: utf-8
#
# Copyright 2018-2023 Greg Neagle.
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
updatecheck.autoconfig

Created by Greg Neagle on 2018-04-17.

Functions for automatically discovering and configuring some Munki settings.
"""
from __future__ import absolute_import, print_function

# Apple frameworks via PyObjC
# PyLint cannot properly find names inside Cocoa libraries, so issues bogus
# No name 'Foo' in module 'Bar' warnings. Disable them.
# pylint: disable=E0611
from SystemConfiguration import SCDynamicStoreCopyValue
# pylint: enable=E0611

# our libs
from .. import display
from .. import fetch
from .. import prefs


def get_domain_name():
    '''Return current domain name'''
    dns_config = SCDynamicStoreCopyValue(None, 'State:/Network/Global/DNS')
    try:
        return dns_config.get('DomainName')
    except AttributeError:
        return None


def guess_repo_url():
    '''Tries a few default URLs and returns the first one that doesn't fail
    utterly'''

    # default to the default repo for Munki up until version 3.2.x
    autodetected_url = prefs.DEFAULT_INSECURE_REPO_URL

    domain_name = get_domain_name()
    if domain_name is None:
        # No DomainName set
        return autodetected_url

    if domain_name == 'local':
        # no guesses if we are on a .local domain
        return autodetected_url

    possible_urls = [
        'https://munki.' + domain_name + '/repo',
        'https://munki.' + domain_name + '/munki_repo',
        'http://munki.' + domain_name + '/repo',
        'http://munki.' + domain_name + '/munki_repo'
    ]
    for url in possible_urls:
        try:
            display.display_info('Checking for Munki repo at: %s', url)
            # a normal Munki repo should have a catalog at this URL
            # if it returns anything, we'll use this as the repo
            fetch.getDataFromURL(url + '/catalogs/all')
            autodetected_url = url
            break
        except fetch.Error as err:
            # couldn't connect or other error
            display.display_info('URL error: %s', err)

    return autodetected_url


def autodetect_repo_url_if_needed():
    '''If Munki repo URL is not defined, (or is the insecure default) attempt
    to discover one. If successful, record the discovered URL in Munki's
    preferences.'''
    if prefs.pref('SoftwareRepoURL') not in (None, prefs.DEFAULT_INSECURE_REPO_URL):
        # SoftwareRepoURL key is defined. exit.
        return
    all_keys_defined = True
    # it's OK if SoftwareRepoURL is not defined as long as all of these
    # other keys are defined. I think in the real world we'll never see this.
    for key in ['CatalogURL', 'IconURL', 'ManifestURL', 'PackageURL'
                'ClientResourceURL']:
        if not prefs.pref(key):
            # some repo url key is not defined. break.
            all_keys_defined = False
            break

    if not all_keys_defined:
        display.display_info('Looking for local Munki repo server...')
        detected_url = guess_repo_url()
        if detected_url:
            display.display_info(
                'Auto-detected Munki repo at %s', detected_url)
            if detected_url != prefs.DEFAULT_INSECURE_REPO_URL:
                # save it to Munki's prefs
                prefs.set_pref('SoftwareRepoURL', detected_url)


if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
