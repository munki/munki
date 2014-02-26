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
    f.write(html)
    f.close()


def build_detail_page(item_name):
    items = MunkiItems.getOptionalInstallItems()
    page_name = 'detail-%s.html' % quote_plus(item_name)
    for item in items:
        if item['name'] == item_name:
            page = MunkiItems.OptionalItem(item)
            msulib.addSidebarLabels(page)
            page['hide_more_by_developer'] = 'hidden'
            more_by_developer_html = ''
            more_by_developer = []
            if page.get('developer'):
                page['developer_link'] = ('developer-%s.html'
                                          % quote_plus(page['developer']))
                more_by_developer = [a for a in items
                                     if (a.get('developer') == page['developer']
                                     and a != item)
                                     and a.get('status') != 'installed']
                if more_by_developer:
                    page['hide_more_by_developer'] = ''
                    page['moreByDeveloperLabel'] = (
                        page['moreByDeveloperLabel'] % page['developer'])
                    shuffle(more_by_developer)
                    more_template = msulib.get_template(
                                        'detail_more_items_template.html')
                    for more_item in more_by_developer[:4]:
                        more_item['second_line'] = more_item.get('category', '')
                        more_by_developer_html += more_template.safe_substitute(more_item)
            page['more_by_developer'] = more_by_developer_html

            page['hide_more_in_category'] = 'hidden'
            more_in_category_html = ''
            if page.get('category'):
                page['category_link'] = 'category-%s.html' % quote_plus(page['category'])
                more_in_category = [a for a in items
                                    if a.get('category') == page['category']
                                    and a != item
                                    and a not in more_by_developer
                                    and a.get('status') != 'installed']
                if more_in_category:
                    page['hide_more_in_category'] = ''
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
    items = MunkiItems.getOptionalInstallItems()

    header = 'All items'
    page_name = 'category-all.html'
    if category == 'all':
        category = None
    if category:
        header = category
        page_name = 'category-%s.html' % quote_plus(category)
    if developer:
        header = developer
        page_name = 'developer-%s.html' % quote_plus(developer)
    if filter:
        header = 'Search results for %s' % filter
        page_name = 'filter-%s.html' % quote_plus(filter)

    category_list = []
    for item in items:
        if 'category' in item and item['category'] not in category_list:
            category_list.append(item['category'])

    item_html = build_list_page_items_html(
                            category=category, developer=developer, filter=filter)

    if category:
        categories_html = '<option>All Categories</option>\n'
    else:
        categories_html = '<option selected>All Categories</option>\n'

    for item in sorted(category_list):
        if item == category:
            categories_html += '<option selected>%s</option>\n' % item
        else:
            categories_html += '<option>%s</option>\n' % item

    page = {}
    page['list_items'] = item_html
    page['category_items'] = categories_html
    page['header_text'] = header
    page['footer'] = msulib.getFooter()
    if category or filter or developer:
        page['hide_showcase'] = 'hidden'
    else:
        page['hide_showcase'] = ''
    html_template = msulib.get_template('list_template.html')
    html = html_template.safe_substitute(page)
    write_page(page_name, html)


def build_list_page_items_html(category=None, developer=None, filter=None):
    items = MunkiItems.getOptionalInstallItems()
    item_html = ''
    if filter:
        filterStr = filter.encode('utf-8')
        items = [item for item in items
                 if filterStr in item['display_name'].lower()
                 or filterStr in item['description'].lower()
                 or filterStr in item['developer'].lower()
                 or filterStr in item['category'].lower()]
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
                item_html += '<div class="lockup"></div>\n'
    else:
        # no items; build appropriate alert messages
        status_results_template = msulib.get_template('status_results_template.html')
        alert = {}
        if filter:
            alert['primary_status_text'] = NSLocalizedString(
                u'Your search had no results.',
                u'NoSearchResultsPrimaryText').encode('utf-8')
            alert['secondary_status_text'] = NSLocalizedString(
                u'Try searching again.', u'NoSearchResultsSecondaryText').encode('utf-8')
        elif category:
            alert['primary_status_text'] = NSLocalizedString(
                u'There are no items in this category.',
                u'NoCategoryResultsPrimaryText').encode('utf-8')
            alert['secondary_status_text'] = NSLocalizedString(
                u'Try selecting another category.',
                u'NoCategoryResultsSecondaryText').encode('utf-8')
        elif developer:
            alert['primary_status_text'] = NSLocalizedString(
               u'There are no items from this developer.',
               u'NoDeveloperResultsPrimaryText').encode('utf-8')
            alert['secondary_status_text'] = NSLocalizedString(
               u'Try selecting another developer.',
               u'NoDeveloperResultsSecondaryText').encode('utf-8')
        else:
            alert['primary_status_text'] = NSLocalizedString(
               u'There are no available software items.',
               u'NoItemsPrimaryText').encode('utf-8')
            alert['secondary_status_text'] = NSLocalizedString(
               u'Try again later.',
               u'NoItemsSecondaryText').encode('utf-8')
        alert['hide_progress_bar'] = 'hidden'
        alert['progress_bar_value'] = ''
        item_html = status_results_template.safe_substitute(alert)
    return item_html


def build_categories_page():
    all_items = MunkiItems.getOptionalInstallItems()
    header = 'Categories'
    page_name = 'categories.html'
    category_list = []
    for item in all_items:
        if 'category' in item and item['category'] not in category_list:
            category_list.append(item['category'])

    item_html = build_category_items_html()

    categories_html = '<option selected>All Categories</option>\n'
    for item in sorted(category_list):
        categories_html += '<option>%s</option>\n' % item

    page = {}
    page['list_items'] = item_html
    page['category_items'] = categories_html
    page['header_text'] = header
    page['footer'] = msulib.getFooter()
    page['hide_showcase'] = 'hidden'
    html_template = msulib.get_template('list_template.html')
    html = html_template.safe_substitute(page)
    write_page(page_name, html)


def build_category_items_html():
    all_items = MunkiItems.getOptionalInstallItems()
    if all_items:
        category_list = []
        for item in all_items:
            if 'category' in item and item['category'] not in category_list:
                category_list.append(item['category'])

        item_template = msulib.get_template('category_item_template.html')
        item_html = ''
        for category in sorted(category_list):
            category_data = {}
            category_data['category_name'] = category
            category_data['category_link'] = 'category-%s.html' % quote_plus(category)
            category_items = [item for item in all_items if item.get('category') == category]
            shuffle(category_items)
            category_data['item1_icon'] = category_items[0]['icon']
            category_data['item1_display_name'] = category_items[0]['display_name']
            category_data['item1_detail_link'] = category_items[0]['detail_link']
            if len(category_items) > 1:
                category_data['item2_display_name'] = category_items[1]['display_name']
                category_data['item2_detail_link'] = category_items[1]['detail_link']
            else:
                category_data['item2_display_name'] = ''
                category_data['item2_detail_link'] = '#'
            if len(category_items) > 2:
                category_data['item3_display_name'] = category_items[2]['display_name']
                category_data['item3_detail_link'] = category_items[2]['detail_link']
            else:
                category_data['item3_display_name'] = ''
                category_data['item3_detail_link'] = '#'

            item_html += item_template.safe_substitute(category_data)

        # pad with extra empty items so we have a multiple of 3
        if len(category_list) % 3:
            for x in range(3 - (len(category_list) % 3)):
                item_html += '<div class="lockup"></div>\n'

    else:
        # no items
        status_results_template = msulib.get_template('status_results_template.html')
        alert = {}
        alert['primary_status_text'] = NSLocalizedString(
            u'There are no available software items.',
            u'NoItemsPrimaryText').encode('utf-8')
        alert['secondary_status_text'] = NSLocalizedString(
            u'Try again later.',
            u'NoItemsSecondaryText').encode('utf-8')
        alert['hide_progress_bar'] = 'hidden'
        alert['progress_bar_value'] = ''
        item_html = status_results_template.safe_substitute(alert)
    return item_html


def build_myitems_page():
    page_name = 'myitems.html'
    page_template = msulib.get_template('myitems_template.html')

    page = {}
    page['my_items_header_label'] = NSLocalizedString(
        u'My Items', u'MyItemsHeaderLabel').encode('utf-8')
    page['myitems_rows'] = build_myitems_rows()
    page['footer'] = msulib.getFooter()

    html = page_template.safe_substitute(page)
    write_page(page_name, html)


def build_myitems_rows():
    item_list = MunkiItems.getMyItemsList()
    if item_list:
        item_template = msulib.get_template('myitems_row_template.html')
        myitems_rows = ''
        for item in sorted(item_list, key=itemgetter('display_name_lower')):
            myitems_rows += item_template.safe_substitute(item)
    else:
        status_results_template = msulib.get_template('status_results_template.html')
        alert = {}
        alert['primary_status_text'] = NSLocalizedString(
            u'You have no selected software.',
            u'NoInstalledSoftwarePrimaryText').encode('utf-8')
        alert['secondary_status_text'] = NSLocalizedString(
            u'<a href="category-all.html">Select software to install.</a>',
            u'NoInstalledSoftwareSecondaryText').encode('utf-8')
        alert['hide_progress_bar'] = 'hidden'
        myitems_rows = status_results_template.safe_substitute(alert)
    return myitems_rows


def build_updates_page():
    '''available/pending updates'''
    page_name = 'updates.html'
    
    # need to consolidate/centralize this flag. Accessing it this way is ugly.
    if NSApp.delegate().mainWindowController._update_in_progress:
        return build_update_status_page()

    item_list = MunkiItems.getEffectiveUpdateList()

    other_updates = [
        item for item in MunkiItems.getOptionalInstallItems()
        if item.get('needs_update')
            and item['status'] not in
                ['installed', 'update-will-be-installed', 'will-be-removed']]

    page = {}
    page['update_rows'] = ''
    page['hide_progress_spinner'] = 'hidden'
    page['hide_other_updates'] = 'hidden'
    page['install_all_button_classes'] = ''
    
    item_template = msulib.get_template('update_row_template.html')

    if item_list:
        for item in item_list:
            page['update_rows'] += item_template.safe_substitute(item)
    elif not other_updates:
        status_results_template = msulib.get_template('status_results_template.html')
        alert = {}
        alert['primary_status_text'] = NSLocalizedString(
             u'Your software is up to date.', u'NoPendingUpdatesPrimaryText').encode('utf-8')
        alert['secondary_status_text'] = NSLocalizedString(
             u'There is no new software for your computer at this time.',
             u'NoPendingUpdatesSecondaryText').encode('utf-8')
        alert['hide_progress_bar'] = 'hidden'
        alert['progress_bar_value'] = ''
        page['update_rows'] = status_results_template.safe_substitute(alert)

    count = len(item_list)
    page['update_count'] = msulib.updateCountMessage(count)
    page['install_btn_label'] = msulib.getInstallAllButtonTextForCount(count)
    page['warning_text'] = get_warning_text()

    page['other_updates_header_message'] = NSLocalizedString(
        u'Other available updates',
        u'OtherAvailableUpdatesLabel').encode('utf-8')
    page['other_update_rows'] = ''

    if other_updates:
        page['hide_other_updates'] = ''
        for item in other_updates:
            page['other_update_rows'] += item_template.safe_substitute(item)
    
    page['footer'] = msulib.getFooter()

    page_template = msulib.get_template('updates_template.html')
    html = page_template.safe_substitute(page)
    write_page(page_name, html)


def build_update_status_page():
    '''returns our update status page'''
    page_name = 'updates.html'
    item_list = []
    other_updates = []
    
    status_title_default = NSLocalizedString(u'Checking for updates...',
                                             u'CheckingForUpdatesMessage').encode('utf-8')
    page = {}
    page['update_rows'] = ''
    page['hide_progress_spinner'] = ''
    page['hide_other_updates'] = 'hidden'
    page['other_updates_header_message'] = ''
    page['other_update_rows'] = ''
    
    # don't like this bit as it ties us to a different object
    status_controller = NSApp.delegate().statusController
    status_results_template = msulib.get_template('status_results_template.html')
    alert = {}
    alert['primary_status_text'] = (
        status_controller._status_message
        or NSLocalizedString(u'Update in progress.',
                             u'UpdateInProgressPrimaryText')).encode('utf-8')
    alert['secondary_status_text'] = (status_controller._status_detail or '&nbsp;')
    alert['hide_progress_bar'] = ''
    if status_controller._status_percent < 0:
        alert['progress_bar_attributes'] = 'class="indeterminate"'
    else:
        alert['progress_bar_attributes'] = ('style="width: %s%%"'
                                            % status_controller._status_percent)
    page['update_rows'] = status_results_template.safe_substitute(alert)
    
    install_all_button_classes = []
    if status_controller._status_stopBtnHidden:
        install_all_button_classes.append('hidden')
    if status_controller._status_stopBtnDisabled:
        install_all_button_classes.append('disabled')
    page['install_all_button_classes'] = ' '.join(install_all_button_classes)

    # don't like this bit as it ties us yet another object
    page['update_count'] = NSApp.delegate().mainWindowController._status_title or status_title_default
    page['install_btn_label'] = NSLocalizedString(
                                    u'Cancel', u'CancelButtonText').encode('utf-8')
    page['warning_text'] = ''
    page['footer'] = msulib.getFooter()

    page_template = msulib.get_template('updates_template.html')
    html = page_template.safe_substitute(page)
    write_page(page_name, html)


def get_warning_text():
    '''Return localized text warning about forced installs and/or
        logouts and/or restarts'''
    item_list = MunkiItems.getEffectiveUpdateList()
    warning_text = ''
    forced_install_date = munki.earliestForceInstallDate(item_list)
    if forced_install_date:
        date_str = munki.stringFromDate(forced_install_date).encode('utf-8')
        forced_date_text = NSLocalizedString(
                            u'One or more items must be installed by %s',
                            u'ForcedInstallDateSummary').encode('utf-8')
        warning_text = forced_date_text % date_str
    restart_text = msulib.getRestartActionForUpdateList(item_list)
    if restart_text:
        if warning_text:
            warning_text += ' &bull; ' + restart_text
        else:
            warning_text = restart_text
    return warning_text


def build_updatedetail_page(item_name):
    items = MunkiItems.getUpdateList()
    page_name = 'updatedetail-%s.html' % quote_plus(item_name)
    for item in items:
        if item['name'] == item_name:
            page = dict(item)
            page['footer'] = msulib.getFooter()
            msulib.addSidebarLabels(page)
            force_install_after_date = item.get('force_install_after_date')
            if force_install_after_date:
                local_date = munki.discardTimeZoneFromDate(
                                                force_install_after_date)
                date_str = munki.shortRelativeStringFromDate(
                                                local_date).encode('utf-8')
                page['dueLabel'] += ' '
                page['short_due_date'] = date_str
            else:
                page['dueLabel'] = ''
                page['short_due_date'] = ''

            template = msulib.get_template('updatedetail_template.html')
            html = template.safe_substitute(page)
            write_page(page_name, html)
            return
    NSLog('No update detail found for %s' % item_name)
    return None # TO-DO: need an error html file!

