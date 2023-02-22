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
updatecheck.licensing

Created by Greg Neagle on 2017-01-01.

"""
from __future__ import absolute_import, print_function

try:
    from urllib import quote_plus
except ImportError:
    # Python 3
    from urllib.parse import quote_plus

from .. import display
from .. import fetch
from .. import prefs
from .. import FoundationPlist


def update_available_license_seats(installinfo):
    '''Records # of available seats for each optional install'''

    license_info_url = prefs.pref('LicenseInfoURL')
    if not license_info_url:
        # nothing to do!
        return
    if not installinfo.get('optional_installs'):
        # nothing to do!
        return

    license_info = {}
    items_to_check = [item['name']
                      for item in installinfo['optional_installs']
                      if item.get('licensed_seat_info_available')
                      and not item['installed']]

    # complicated logic here to 'batch' process our GET requests but
    # keep them under 256 characters each
    start_index = 0
    # Use ampersand when the license_info_url contains a ?
    q_char = "?"
    if "?" in license_info_url:
        q_char = "&"
    while start_index < len(items_to_check):
        end_index = len(items_to_check)
        while True:
            query_items = ['name=' + quote_plus(item)
                           for item in items_to_check[start_index:end_index]]
            url = license_info_url + q_char + '&'.join(query_items)
            if len(url) < 256:
                break
            # drop an item and see if we're under 256 characters
            end_index = end_index - 1

        display.display_debug1('Fetching licensed seat data from %s', url)
        try:
            license_data = fetch.getDataFromURL(url)
            display.display_debug1('Got: %s', license_data)
            license_dict = FoundationPlist.readPlistFromString(
                license_data.encode("UTF-8"))
        except fetch.Error as err:
            # problem fetching from URL
            display.display_error('Error from %s: %s', url, err)
        except FoundationPlist.FoundationPlistException:
            # no data or bad data from URL
            display.display_error(
                'Bad license data from %s: %s', url, license_data)
        else:
            # merge data from license_dict into license_info
            license_info.update(license_dict)
        start_index = end_index

    # use license_info to update our remaining seats
    for item in installinfo['optional_installs']:
        if item['name'] in items_to_check:
            display.display_debug2(
                'Looking for license info for %s', item['name'])
            # record available seats for this item
            seats_available = False
            seat_info = license_info.get(item['name'], 0)
            try:
                seats_available = int(seat_info) > 0
                display.display_debug1(
                    'Recording available seats for %s: %s',
                    item['name'], seats_available)
            except ValueError:
                display.display_warning(
                    'Bad license data for %s: %s', item['name'], seat_info)

            item['licensed_seats_available'] = seats_available


if __name__ == '__main__':
    print('This is a library of support tools for the Munki Suite.')
