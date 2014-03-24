# encoding: utf-8
#
#  msuhtml.py
#  Managed Software Center
#
#  Created by Greg Neagle on 2/24/14.
#

import os

from operator import itemgetter
from random import shuffle
from urllib import quote_plus, unquote_plus

import MunkiItems
import msulib
import munki

from AppKit import NSApp
from Foundation import NSLog
from Foundation import NSLocalizedString


def build_page(filename):
    '''Dispatch request to build a page to the appropriate function'''
    name = os.path.splitext(filename)[0]
    key, p, quoted_value = name.partition('-')
    value = unquote_plus(quoted_value)
    if key == 'detail':
        build_detail_page(value)
    if key == 'category':
        build_list_page(category=value)
    if key == 'categories':
        build_categories_page()
    if key == 'filter':
        build_list_page(filter=value)
    if key == 'developer':
        build_list_page(developer=value)
    if key == 'myitems':
        build_myitems_page()
    if key == 'updates':
        build_updates_page()
    if key == 'updatedetail':
        build_updatedetail_page(value)


def write_page(page_name, html):
    '''write html to page_name in our local html directory'''
    html_file = os.path.join(msulib.html_dir(), page_name)
    f = open(html_file, 'w')
    f.write(html.encode('utf-8'))
    f.close()


def build_detail_page(item_name):
    '''Build page showing detail for a single optional item'''
    items = MunkiItems.getOptionalInstallItems()
    page_name = u'detail-%s.html' % quote_plus(item_name)
    for item in items:
        if item['name'] == item_name:
            page = MunkiItems.OptionalItem(item)
            msulib.addSidebarLabels(page)
            # make "More by DeveloperFoo" list
            page['hide_more_by_developer'] = u'hidden'
            more_by_developer_html = u''
            more_by_developer = []
            if item.get('developer'):
                developer = item['developer']
                page['developer_link'] = (u'developer-%s.html'
                                          % quote_plus(developer))
                more_by_developer = [a for a in items
                                     if a.get('developer') == developer
                                     and a != item
                                     and a.get('status') != 'installed']
                if more_by_developer:
                    page['hide_more_by_developer'] = u''
                    page['moreByDeveloperLabel'] = (
                        page['moreByDeveloperLabel'] % developer)
                    shuffle(more_by_developer)
                    more_template = msulib.get_template(
                                        'detail_more_items_template.html')
                    for more_item in more_by_developer[:4]:
                        more_item['second_line'] = more_item.get('category', '')
                        more_by_developer_html += more_template.safe_substitute(more_item)
            page['more_by_developer'] = more_by_developer_html
            # make "More by CategoryFoo" list
            page['hide_more_in_category'] = u'hidden'
            more_in_category_html = u''
            if item.get('category'):
                category = item['category']
                page['category_link'] = u'category-%s.html' % quote_plus(category)
                more_in_category = [a for a in items
                                    if a.get('category') == category
                                    and a != item
                                    and a not in more_by_developer
                                    and a.get('status') != 'installed']
                if more_in_category:
                    page['hide_more_in_category'] = u''
                    page['moreInCategoryLabel'] = page['moreInCategoryLabel'] % page['category']
                    shuffle(more_in_category)
                    more_template = msulib.get_template('detail_more_items_template.html')
                    for more_item in more_in_category[:4]:
                        more_item['second_line'] = more_item.get('developer', '')
                        more_in_category_html += more_template.safe_substitute(more_item)
            page['more_in_category'] = more_in_category_html
            page['footer'] = msulib.getFooter()

            template = msulib.get_template('detail_template.html')
            html = template.safe_substitute(page)
            write_page(page_name, html)
            return
    NSLog('No detail found for %s' % item_name)
    return None # TO-DO: need an error html file!


def build_list_page(category=None, developer=None, filter=None):
    '''Build page listing available optional items'''
    items = MunkiItems.getOptionalInstallItems()

    header = u'All items'
    page_name = u'category-all.html'
    if category == 'all':
        category = None
    if category:
        header = category
        page_name = u'category-%s.html' % quote_plus(category)
    if developer:
        header = developer
        page_name = u'developer-%s.html' % quote_plus(developer)
    if filter:
        header = u'Search results for %s' % filter
        page_name = u'filter-%s.html' % quote_plus(filter)

    category_list = []
    for item in items:
        if 'category' in item and item['category'] not in category_list:
            category_list.append(item['category'])

    item_html = build_list_page_items_html(
                            category=category, developer=developer, filter=filter)

    if category:
        categories_html = u'<option>All Categories</option>\n'
    else:
        categories_html = u'<option selected>All Categories</option>\n'

    for item in sorted(category_list):
        if item == category:
            categories_html += u'<option selected>%s</option>\n' % item
        else:
            categories_html += u'<option>%s</option>\n' % item

    page = {}
    page['list_items'] = item_html
    page['category_items'] = categories_html
    page['header_text'] = header
    page['footer'] = msulib.getFooter()
    if category or filter or developer:
        page['hide_showcase'] = u'hidden'
    else:
        page['hide_showcase'] = u''
    html_template = msulib.get_template('list_template.html')
    html = html_template.safe_substitute(page)
    write_page(page_name, html)


def build_list_page_items_html(category=None, developer=None, filter=None):
    '''Returns HTML for the items on the list page'''
    items = MunkiItems.getOptionalInstallItems()
    item_html = u''
    if filter:
        items = [item for item in items
                 if filter in item['display_name'].lower()
                 or filter in item['description'].lower()
                 or filter in item['developer'].lower()
                 or filter in item['category'].lower()]
    if category:
        items = [item for item in items
                 if category.lower() in item.get('category', '').lower()]
    if developer:
        items = [item for item in items
                 if developer.lower() in item.get('developer', '').lower()]

    if items:
        item_template = msulib.get_template('list_item_template.html')
        for item in sorted(items, key=itemgetter('display_name_lower')):
            item_html += item_template.safe_substitute(item)
        # pad with extra empty items so we have a multiple of 3
        if len(items) % 3:
            for x in range(3 - (len(items) % 3)):
                item_html += u'<div class="lockup"></div>\n'
    else:
        # no items; build appropriate alert messages
        status_results_template = msulib.get_template('status_results_template.html')
        alert = {}
        if filter:
            alert['primary_status_text'] = NSLocalizedString(
                u'Your search had no results.',
                u'NoSearchResultsPrimaryText')
            alert['secondary_status_text'] = NSLocalizedString(
                u'Try searching again.', u'NoSearchResultsSecondaryText')
        elif category:
            alert['primary_status_text'] = NSLocalizedString(
                u'There are no items in this category.',
                u'NoCategoryResultsPrimaryText')
            alert['secondary_status_text'] = NSLocalizedString(
                u'Try selecting another category.',
                u'NoCategoryResultsSecondaryText')
        elif developer:
            alert['primary_status_text'] = NSLocalizedString(
               u'There are no items from this developer.',
               u'NoDeveloperResultsPrimaryText')
            alert['secondary_status_text'] = NSLocalizedString(
               u'Try selecting another developer.',
               u'NoDeveloperResultsSecondaryText')
        else:
            alert['primary_status_text'] = NSLocalizedString(
               u'There are no available software items.',
               u'NoItemsPrimaryText')
            alert['secondary_status_text'] = NSLocalizedString(
               u'Try again later.',
               u'NoItemsSecondaryText')
        alert['hide_progress_bar'] = u'hidden'
        alert['progress_bar_value'] = u''
        item_html = status_results_template.safe_substitute(alert)
    return item_html


def build_categories_page():
    '''Build page showing available categories and some items in each one'''
    all_items = MunkiItems.getOptionalInstallItems()
    header = u'Categories'
    page_name = u'categories.html'
    category_list = []
    for item in all_items:
        if 'category' in item and item['category'] not in category_list:
            category_list.append(item['category'])

    item_html = build_category_items_html()

    categories_html = u'<option selected>All Categories</option>\n'
    for item in sorted(category_list):
        categories_html += u'<option>%s</option>\n' % item

    page = {}
    page['list_items'] = item_html
    page['category_items'] = categories_html
    page['header_text'] = header
    page['footer'] = msulib.getFooter()
    page['hide_showcase'] = u'hidden'
    html_template = msulib.get_template('list_template.html')
    html = html_template.safe_substitute(page)
    write_page(page_name, html)


def build_category_items_html():
    '''Returns HTML for the items on the Categories page'''
    all_items = MunkiItems.getOptionalInstallItems()
    if all_items:
        category_list = []
        for item in all_items:
            if 'category' in item and item['category'] not in category_list:
                category_list.append(item['category'])

        item_template = msulib.get_template('category_item_template.html')
        item_html = u''
        for category in sorted(category_list):
            category_data = {}
            category_data['category_name'] = category
            category_data['category_link'] = u'category-%s.html' % quote_plus(category)
            category_items = [item for item in all_items if item.get('category') == category]
            shuffle(category_items)
            category_data['item1_icon'] = category_items[0]['icon']
            category_data['item1_display_name'] = category_items[0]['display_name']
            category_data['item1_detail_link'] = category_items[0]['detail_link']
            if len(category_items) > 1:
                category_data['item2_display_name'] = category_items[1]['display_name']
                category_data['item2_detail_link'] = category_items[1]['detail_link']
            else:
                category_data['item2_display_name'] = u''
                category_data['item2_detail_link'] = u'#'
            if len(category_items) > 2:
                category_data['item3_display_name'] = category_items[2]['display_name']
                category_data['item3_detail_link'] = category_items[2]['detail_link']
            else:
                category_data['item3_display_name'] = u''
                category_data['item3_detail_link'] = u'#'

            item_html += item_template.safe_substitute(category_data)

        # pad with extra empty items so we have a multiple of 3
        if len(category_list) % 3:
            for x in range(3 - (len(category_list) % 3)):
                item_html += u'<div class="lockup"></div>\n'

    else:
        # no items
        status_results_template = msulib.get_template('status_results_template.html')
        alert = {}
        alert['primary_status_text'] = NSLocalizedString(
            u'There are no available software items.',
            u'NoItemsPrimaryText')
        alert['secondary_status_text'] = NSLocalizedString(
            u'Try again later.',
            u'NoItemsSecondaryText')
        alert['hide_progress_bar'] = u'hidden'
        alert['progress_bar_value'] = u''
        item_html = status_results_template.safe_substitute(alert)
    return item_html


def build_myitems_page():
    '''Builds "My Items" page, which shows all current optional choices'''
    page_name = u'myitems.html'
    page_template = msulib.get_template('myitems_template.html')

    page = {}
    page['my_items_header_label'] = NSLocalizedString(
        u'My Items', u'MyItemsHeaderLabel')
    page['myitems_rows'] = build_myitems_rows()
    page['footer'] = msulib.getFooter()

    html = page_template.safe_substitute(page)
    write_page(page_name, html)


def build_myitems_rows():
    '''Returns HTML for the items on the 'My Items' page'''
    item_list = MunkiItems.getMyItemsList()
    if item_list:
        item_template = msulib.get_template('myitems_row_template.html')
        myitems_rows = u''
        for item in sorted(item_list, key=itemgetter('display_name_lower')):
            myitems_rows += item_template.safe_substitute(item)
    else:
        status_results_template = msulib.get_template('status_results_template.html')
        alert = {}
        alert['primary_status_text'] = NSLocalizedString(
            u'You have no selected software.',
            u'NoInstalledSoftwarePrimaryText')
        alert['secondary_status_text'] = NSLocalizedString(
            u'<a href="category-all.html">Select software to install.</a>',
            u'NoInstalledSoftwareSecondaryText')
        alert['hide_progress_bar'] = u'hidden'
        myitems_rows = status_results_template.safe_substitute(alert)
    return myitems_rows


def build_updates_page():
    '''available/pending updates'''
    page_name = u'updates.html'
    
    # need to consolidate/centralize this flag. Accessing it this way is ugly.
    if NSApp.delegate().mainWindowController._update_in_progress:
        return build_update_status_page()

    item_list = MunkiItems.getEffectiveUpdateList()

    other_updates = [
        item for item in MunkiItems.getOptionalInstallItems()
        if item['status'] == 'update-available']

    page = {}
    page['update_rows'] = u''
    page['hide_progress_spinner'] = u'hidden'
    page['hide_other_updates'] = u'hidden'
    page['install_all_button_classes'] = u''
    
    item_template = msulib.get_template('update_row_template.html')

    if item_list:
        for item in item_list:
            page['update_rows'] += item_template.safe_substitute(item)
    elif not other_updates:
        status_results_template = msulib.get_template('status_results_template.html')
        alert = {}
        alert['primary_status_text'] = NSLocalizedString(
             u'Your software is up to date.', u'NoPendingUpdatesPrimaryText')
        alert['secondary_status_text'] = NSLocalizedString(
             u'There is no new software for your computer at this time.',
             u'NoPendingUpdatesSecondaryText')
        alert['hide_progress_bar'] = u'hidden'
        alert['progress_bar_value'] = u''
        page['update_rows'] = status_results_template.safe_substitute(alert)

    count = len(item_list)
    page['update_count'] = msulib.updateCountMessage(count)
    page['install_btn_label'] = msulib.getInstallAllButtonTextForCount(count)
    page['warning_text'] = get_warning_text()

    page['other_updates_header_message'] = NSLocalizedString(
        u'Other available updates',
        u'OtherAvailableUpdatesLabel')
    page['other_update_rows'] = u''

    if other_updates:
        page['hide_other_updates'] = u''
        for item in other_updates:
            page['other_update_rows'] += item_template.safe_substitute(item)
    
    page['footer'] = msulib.getFooter()

    page_template = msulib.get_template('updates_template.html')
    html = page_template.safe_substitute(page)
    write_page(page_name, html)


def build_update_status_page():
    '''returns our update status page'''
    page_name = u'updates.html'
    item_list = []
    other_updates = []
    
    status_title_default = NSLocalizedString(u'Checking for updates...',
                                             u'CheckingForUpdatesMessage')
    page = {}
    page['update_rows'] = u''
    page['hide_progress_spinner'] = u''
    page['hide_other_updates'] = u'hidden'
    page['other_updates_header_message'] = u''
    page['other_update_rows'] = u''
    
    # don't like this bit as it ties us to a different object
    status_controller = NSApp.delegate().statusController
    status_results_template = msulib.get_template('status_results_template.html')
    alert = {}
    alert['primary_status_text'] = (
        status_controller._status_message
        or NSLocalizedString(u'Update in progress.',
                             u'UpdateInProgressPrimaryText'))
    alert['secondary_status_text'] = (status_controller._status_detail or '&nbsp;')
    alert['hide_progress_bar'] = u''
    if status_controller._status_percent < 0:
        alert['progress_bar_attributes'] = u'class="indeterminate"'
    else:
        alert['progress_bar_attributes'] = (u'style="width: %s%%"'
                                            % status_controller._status_percent)
    page['update_rows'] = status_results_template.safe_substitute(alert)
    
    install_all_button_classes = []
    if status_controller._status_stopBtnHidden:
        install_all_button_classes.append(u'hidden')
    if status_controller._status_stopBtnDisabled:
        install_all_button_classes.append(u'disabled')
    page['install_all_button_classes'] = u' '.join(install_all_button_classes)

    # don't like this bit as it ties us yet another object
    page['update_count'] = NSApp.delegate().mainWindowController._status_title or status_title_default
    page['install_btn_label'] = NSLocalizedString(
                                    u'Cancel', u'CancelButtonText')
    page['warning_text'] = u''
    page['footer'] = msulib.getFooter()

    page_template = msulib.get_template('updates_template.html')
    html = page_template.safe_substitute(page)
    write_page(page_name, html)


def get_warning_text():
    '''Return localized text warning about forced installs and/or
        logouts and/or restarts'''
    item_list = MunkiItems.getEffectiveUpdateList()
    warning_text = u''
    forced_install_date = munki.earliestForceInstallDate(item_list)
    if forced_install_date:
        date_str = munki.stringFromDate(forced_install_date)
        forced_date_text = NSLocalizedString(
                            u'One or more items must be installed by %s',
                            u'ForcedInstallDateSummary')
        warning_text = forced_date_text % date_str
    restart_text = msulib.getRestartActionForUpdateList(item_list)
    if restart_text:
        if warning_text:
            warning_text += u' &bull; ' + restart_text
        else:
            warning_text = restart_text
    return warning_text

def build_updatedetail_page(identifier):
    '''Build detail page for a non-optional update'''
    items = MunkiItems.getUpdateList()
    page_name = u'updatedetail-%s.html' % quote_plus(identifier)
    name, sep, version = identifier.partition('--version-')
    for item in items:
        if item['name'] == name and item['version_to_install'] == version:
            page = MunkiItems.UpdateItem(item)
            page['footer'] = msulib.getFooter()
            msulib.addSidebarLabels(page)
            force_install_after_date = item.get('force_install_after_date')
            if force_install_after_date:
                local_date = munki.discardTimeZoneFromDate(
                                                force_install_after_date)
                date_str = munki.shortRelativeStringFromDate(
                                                local_date)
                page['dueLabel'] += u' '
                page['short_due_date'] = date_str
            else:
                page['dueLabel'] = u''
                page['short_due_date'] = u''

            template = msulib.get_template('updatedetail_template.html')
            html = template.safe_substitute(page)
            write_page(page_name, html)
            return
    NSLog('No update detail found for %s' % item_name)
    return None # TO-DO: need an error html file!

