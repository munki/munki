//
//  mschtml.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 6/15/18.
//  Copyright © 2018-2026 The Munki Project. All rights reserved.
//

import Cocoa

extension Array {
    // Randomizes the order of an array's elements
    mutating func shuffle() {
        for _ in 0..<count {
            sort { (_,_) in arc4random() < arc4random() }
        }
    }
}


func interfaceTheme() -> String {
    // Returns "dark" if using Dark Mode, otherwise "light"
    if #available(OSX 10.15, *) {
        let appearanceDescription = NSApplication.shared.effectiveAppearance.debugDescription.lowercased()
        if appearanceDescription.contains("dark") {
            return "dark"
        }
    } else {
        let os_vers = OperatingSystemVersion(majorVersion: 10, minorVersion: 14, patchVersion: 0)
        if ProcessInfo().isOperatingSystemAtLeast(os_vers) || UserDefaults.standard.bool(forKey: "AllowDarkModeOnUnsupportedOSes") {
            if let appleInterfaceStyle = UserDefaults.standard.string(forKey: "AppleInterfaceStyle") {
                if appleInterfaceStyle.lowercased().contains("dark") {
                    return "dark"
                }
            }
        }
    }
    return "light"
}


func getRawTemplate(_ template_name: String) -> String {
    // return a raw html template.
    let customTemplatesPath = NSString.path(withComponents: [html_dir(), "custom/templates"])
    let resourcesPath = Bundle.main.resourcePath ?? ""
    let defaultTemplatesPath = NSString.path(withComponents: [resourcesPath, "templates"])
    for directory in [customTemplatesPath, defaultTemplatesPath] {
        let templatePath = NSString.path(withComponents: [directory, template_name])
        var fileContents = ""
        if FileManager.default.fileExists(atPath: templatePath) {
            do {
                fileContents = try NSString(
                    contentsOfFile: templatePath, encoding: String.Encoding.utf8.rawValue) as String
            } catch {
                return ""
            }
            return fileContents
        }
    }
    return ""
}

func getTemplate(_ template_name: String) -> Template {
    // return a Template object containing our html template
    return Template(getRawTemplate(template_name))
}

func buildPage(_ filename: String) throws {
    // Dispatch request to build a page to the appropriate function
    msc_debug_log("build_page for \(filename)")
    let name = (filename as NSString).deletingPathExtension
    let parts = name.split(separator: "-", maxSplits: 1, omittingEmptySubsequences: false)
    let key = parts[0]
    let value = parts.count > 1 ? String(parts[1]) : ""
    //msc_debug_log("buildPage key: \(key), value: \(value)")
    switch key {
    case "detail":
        try buildDetailPage(item_name: value)
    case "category":
        try buildListPage(category: value)
    case "categories":
        try buildCategoriesPage()
    case "filter":
        try buildListPage(filter: value)
    case "developer":
        try buildListPage(developer: value)
    case "myitems":
        try buildMyItemsPage()
    case "updates":
        try buildUpdatesPage()
    case "updatedetail":
        try buildUpdateDetailPage(value)
    default:
        try buildItemNotFoundPage(filename)
    }
}

func writePage(name: String, html: String) throws {
    // write html to page_name in our local html directory
    let html_file = NSString.path(withComponents: [html_dir(), name])
    try html.write(toFile: html_file, atomically: true, encoding: .utf8)
}

func assemblePage(fromTemplate template_name: String,
                   usingItem pageItem: GenericItem,
                   additionalTemplates additional_subs: BaseItem = BaseItem() ) -> String {
    // Returns HTML for our page from one or more templates
    // and a dictionary of keys and values
    // add current appearance style/theme
    pageItem["data_theme"] = interfaceTheme()
    // make sure our general labels are present
    pageItem.addGeneralLabels()
    // get our main template
    let main_page = getTemplate(template_name)
    // incorporate any sub-templates
    let html_template = Template(main_page.substitute(additional_subs))
    // now substitute page variables
    return html_template.substitute(pageItem)
}

func generatePage(named page_name: String,
                  fromTemplate template_name: String,
                  usingItem pageItem: GenericItem,
                  additionalTemplates additional_subs: BaseItem = BaseItem()) throws {
    // Assembles HTML and writes the page to page_name in our local html directory
    msc_debug_log("generate_page for \(page_name)")
    let html = assemblePage(fromTemplate: template_name,
                            usingItem: pageItem,
                            additionalTemplates: additional_subs)
    try writePage(name: page_name, html: html)
}

func escapeQuotes(_ text: String) -> String {
    //Escape single and double-quotes for JavaScript
    return text.replacingOccurrences(of: "'", with: "\\'").replacingOccurrences(of: "\"", with: "\\\"")
}

func escapeHTML(_ text: String) -> String {
    // Convert some problematic characters to entities
    let html_escape_table = [
        ["&",  "&amp;"],
        ["\"", "&quot;"],
        ["'",  "&#39;"],
        [">",  "&gt;"],
        ["<",  "&lt;"],
    ]
    var mutable_text = text
    for subs in html_escape_table {
        mutable_text = mutable_text.replacingOccurrences(of: subs[0], with: subs[1])
    }
    return mutable_text
}

extension GenericItem {
    func escapeAndQuoteCommonFields() {
        // Adds _escaped and _quoted versions of several commonly-used fields
        my["name_escaped"] = escapeHTML(self["name"] as? String ?? "")
        my["name_quoted"] = escapeQuotes(self["name"] as? String ?? "")
        my["display_name_escaped"] = escapeHTML(self["display_name"] as? String ?? "")
        my["developer_escaped"] = escapeHTML(self["developer"] as? String ?? "")
        my["display_version_escaped"] = escapeHTML(self["display_version"] as? String ?? "")
        if my["status"] as? String ?? "" == "will-be-removed" {
            my["display_version_escaped_and_size"] = ""
        } else {
            my["display_version_escaped_and_size"] = (my["display_version_escaped"] as? String ?? "") + " • " + (my["size"] as? String ?? "")
        }
    }

    func addGeneralLabels() {
        // adds localized labels for Software, Categories, My Items and Updates to html pages
        my["SoftwareLabel"] = NSLocalizedString("Software", comment: "Software label")
        my["CategoriesLabel"] = NSLocalizedString("Categories", comment: "Categories label")
        my["MyItemsLabel"] = NSLocalizedString("My Items", comment: "My Items label")
        my["UpdatesLabel"] = NSLocalizedString("Updates", comment: "Updates label")
    }

    func addDetailSidebarLabels() {
        // adds localized labels for the detail view sidebars
        my["informationLabel"] = NSLocalizedString(
            "Information", comment: "Sidebar Information label")
        my["categoryLabel"] = NSLocalizedString(
            "Category:", comment: "Sidebar Category label").trimmingCharacters(
                in: CharacterSet(charactersIn: ":"))
        my["versionLabel"] = NSLocalizedString(
            "Version:", comment: "Sidebar Version label").trimmingCharacters(
                in: CharacterSet(charactersIn: ":"))
        my["sizeLabel"] = NSLocalizedString(
            "Size:", comment: "Sidebar Size label").trimmingCharacters(
                in: CharacterSet(charactersIn: ":"))
        my["developerLabel"] = NSLocalizedString(
            "Developer:", comment: "Sidebar Developer label").trimmingCharacters(
                in: CharacterSet(charactersIn: ":"))
        my["statusLabel"] = NSLocalizedString(
            "Status:", comment: "Sidebar Status label").trimmingCharacters(
                in: CharacterSet(charactersIn: ":"))
        my["moreByDeveloperLabel"] = NSLocalizedString(
            "More by %@", comment: "Sidebar More By Developer label")
        my["moreInCategoryLabel"] = NSLocalizedString(
            "More in %@", comment: "Sidebar More In Category label")
        my["typeLabel"] = NSLocalizedString(
            "Type", comment: "Sidebar Type label")
        my["dueLabel"] = NSLocalizedString(
            "Due:", comment: "Sidebar Due label").trimmingCharacters(
                in: CharacterSet(charactersIn: ":"))
        my["seeAllLocalizedString"] = NSLocalizedString("See All", comment: "See All link text")
    }
    
    func addMoreInCategory(of item: GenericItem, fromItems items: [GenericItem]) {
        // make "More in CategoryFoo" list
        let item_name = item["name"] as? String ?? ""
        my["hide_more_in_category"] = "hidden"
        var more_in_category_html = ""
        //var excludeFromMoreByDeveloperNames = [String]()
        if let category = item["category"] as? String {
            let developer = item["developer"] as? String ?? "non-existent-developer-name"
            my["category_link"] = "munki://category-\(quote(category)).html"
            var more_in_category = items.filter(
                {
                    ( $0["category"] as? String == category &&
                      $0["name"] as? String != item_name &&
                      $0["status"] as? String != "installed" &&
                      $0["developer"] as? String != developer
                    )
                }
            )
            if more_in_category.count > 0 {
                my["hide_more_in_category"] = ""
                let formatStr = my["moreInCategoryLabel"] as? NSString ?? ""
                my["moreInCategoryLabel"] = NSString(format: formatStr, category)
                more_in_category.shuffle()
                more_in_category_html = buildItemListHTML(
                    Array(more_in_category[..<min(4, more_in_category.count)]))
            }
        }
        //my["_excludeFromMoreByDeveloperNames"] = excludeFromMoreByDeveloperNames
        my["more_in_category"] = more_in_category_html
    }
    
    func addMoreFromDeveloper(of item: GenericItem, fromItems items: [GenericItem]) {
        // make "More by DeveloperFoo" list
        let item_name = item["name"] as? String ?? ""
        my["hide_more_by_developer"] = "hidden"
        var more_by_developer_html = ""
        var more_by_developer = [GenericItem]()
        let excludeFromMoreByDeveloperNames = my["_excludeFromMoreByDeveloperNames"] as? [String] ?? []
        my["_excludeFromMoreByDeveloperNames"] = nil
        if let developer = item["developer"] as? String {
            my["developer_link"] = "munki://developer-\(quote(developer)).html"
            more_by_developer = items.filter(
                {
                    ( !excludeFromMoreByDeveloperNames.contains($0["name"] as? String ?? "") &&
                      $0["developer"] as? String == developer &&
                      $0["name"] as? String != item_name &&
                      $0["status"] as? String != "installed"
                    )
                }
            )
            if more_by_developer.count > 0 {
                my["hide_more_by_developer"] = ""
                let formatStr = my["moreByDeveloperLabel"] as? NSString ?? ""
                my["moreByDeveloperLabel"] = NSString(format: formatStr, developer)
                more_by_developer.shuffle()
                more_by_developer_html = buildItemListHTML(
                    Array(more_by_developer[..<min(4, more_by_developer.count)]))
            }
        }
        my["more_by_developer"] = more_by_developer_html
    }
}

func buildItemNotFoundPage(_ page_name: String) throws {
    // Build item not found page
    let page = GenericItem([String:String]())
    page["item_not_found_title"] = NSLocalizedString(
        "Not Found", comment: "Item Not Found title")
    page["item_not_found_message"] = NSLocalizedString(
        "Cannot display the requested item.", comment: "Item Not Found message")
    let footer = getRawTemplate("footer_template.html")
    try generatePage(named: page_name,
                     fromTemplate: "page_not_found_template.html",
                     usingItem: page,
                     additionalTemplates: BaseItem(["footer": footer]))
}

func buildDetailPage(item_name: String) throws {
    // Build page showing detail for a single optional item
    msc_debug_log("buildDetailPage for \(item_name)")
    let items = getOptionalInstallItems()
    let page_name = "detail-\(item_name).html"
    for item in items {
        if item["name"] as? String == item_name {
            // make a copy of the item to use to build our page
            let page = OptionalItem(item)
            page.escapeAndQuoteCommonFields()
            page.addDetailSidebarLabels()
            page.addMoreInCategory(of: item, fromItems: items)
            page.addMoreFromDeveloper(of: item, fromItems: items)
            // might need better logic here eventually
            page["dueLabel"] = ""
            page["short_due_date"] = ""
            item["hide_cancel_button"] = ""
            let footer = getRawTemplate("footer_template.html")
            try generatePage(named: page_name,
                             fromTemplate: "detail_template.html",
                             usingItem: page,
                             additionalTemplates: BaseItem(["footer": footer]))
            return
        }
    }
    msc_debug_log("No detail found for \(item_name)")
    try buildItemNotFoundPage(page_name)
}

func buildListPage(category: String = "",
                   developer: String = "",
                   filter: String = "") throws {
    // Build page listing available optional items
    var category = category
    let items = getOptionalInstallItems()
    
    var header = NSLocalizedString("All items", comment: "AllItemsHeaderText")
    var page_name = "category-all.html"
    if category == "all" {
        category = ""
    }
    if !category.isEmpty {
        header = category
        page_name = "category-\(category).html"
    } else if !developer.isEmpty {
        header = developer
        page_name = "developer-\(developer).html"
    } else if !filter.isEmpty {
        header = "Search results for \(filter)" //TO-DO: localize?
        page_name = "filter-\(filter).html"
    }
    msc_debug_log("page name: \(page_name)")
    
    let featured_items = items.filter({ $0["featured"] as? Bool == true })
    if !featured_items.isEmpty && category.isEmpty && developer.isEmpty && filter.isEmpty {
        header  = NSLocalizedString("Featured items",
                                    comment: "FeaturedItemsHeaderText")
    }
    
    // make HTML for Categories pop-up menu
    var all_categories_label = NSLocalizedString("All Categories",
                                                 comment: "AllCategoriesLabel")
    if !featured_items.isEmpty {
        all_categories_label = NSLocalizedString("Featured", comment: "FeaturedLabel")
    }
    var categories_html = "<option>\(all_categories_label)</option>\n"
    if category.isEmpty {
        categories_html = "<option selected>\(all_categories_label)</option>\n"
    }
    
    var category_set = Set<String>()
    for item in items {
        if let category_name = item["category"] as? String {
            category_set.insert(category_name)
        }
    }
    
    for item in Array(category_set).sorted() {
        if item == category {
            categories_html += "<option selected>\(item)</option>\n"
        } else {
            categories_html += "<option>\(item)</option>\n"
        }
    }
    
    // make HTML for list of categories
    var categories_html_list = ""
    for item in Array(category_set).sorted() {
        categories_html_list += (
            "<li class=\"link\"><a href=\"munki://category-\(quote(item)).html\">\(item)</a></li>\n")
    }
    
    let item_hmtl = buildListPageItemsHTML(
        category: category, developer: developer, filter: filter)
    
    // assemble!
    let page = GenericItem()
    page["list_items"] = item_hmtl
    page["category_items"] = categories_html
    page["category_list"] = categories_html_list
    page["header_text"] = header
    let more_templates = BaseItem()
    more_templates["showcase"] = getRawTemplate("showcase_template.html")
    /*if category.isEmpty && filter.isEmpty && developer.isEmpty {
        more_templates["showcase"] = getRawTemplate("showcase_template.html")
    } else {
        more_templates["showcase"] = ""
    }*/
    more_templates["sidebar"] = getRawTemplate("sidebar_template.html")
    more_templates["footer"] = getRawTemplate("footer_template.html")
    try generatePage(named: page_name,
                     fromTemplate: "list_template.html",
                     usingItem: page,
                     additionalTemplates: more_templates)
}


func buildItemListHTML(_ items: [GenericItem],
                       template: String = "list_item_template.html",
                       sort: Bool = true) -> String {
    var item_html = ""
    var sorted_items: [GenericItem] = []
    let item_template = getTemplate(template)
    if sort {
        // sort items by display_name_lowercase
        sorted_items = items.sorted(by:
            { $0["display_name_lower"] as? String ?? "" < $1["display_name_lower"] as? String ?? "" })
    } else {
        sorted_items = items
    }
    for item in sorted_items {
        item.escapeAndQuoteCommonFields()
        let category_and_developer = item["category_and_developer"] as? String ?? ""
        item["category_and_developer_escaped"] = escapeHTML(category_and_developer)
        item_html += item_template.substitute(item)
    }
    return item_html
}


func buildListPageItemsHTML(category: String = "",
                            developer: String = "",
                            filter: String = "") -> String {
    // Returns HTML for the items on the list page
    var items = getOptionalInstallItems()
    var item_html = ""
    if !filter.isEmpty {
        msc_debug_log("Filtering on \(filter)")
        let lc_filter = filter.lowercased()
        items = items.filter(
            {
                ($0["display_name"] as? String ?? "").lowercased().contains(lc_filter) ||
                ($0["description"] as? String ?? "").lowercased().contains(lc_filter) ||
                ($0["developer"] as? String ?? "").lowercased().contains(lc_filter) ||
                ($0["category"] as? String ?? "").lowercased().contains(lc_filter)
            }
        )
    }
    if !category.isEmpty {
        items = items.filter(
            { ($0["category"] as? String ?? "").lowercased() == category.lowercased() }
        )
    }
    if !developer.isEmpty {
        items = items.filter(
            { ($0["developer"] as? String ?? "").lowercased() == developer.lowercased() }
        )
    }
    if category.isEmpty && developer.isEmpty && filter.isEmpty {
        // this is the default (formerly) "all items" view
        // look for featured items and display those if we have them
        let featured_items = items.filter(
            { pythonishBool($0["featured"]) == true }
        )
        if !featured_items.isEmpty {
            items = featured_items
        }
    }
    if !items.isEmpty {
        item_html = buildItemListHTML(items)
    } else {
        // no items; build appropriate alert messages
        let status_results_template = getTemplate("status_results_template.html")
        let alert = BaseItem()
        if !filter.isEmpty {
            alert["primary_status_text"] = NSLocalizedString(
                "Your search had no results.",
                comment: "No Search Results primary text")
            alert["secondary_status_text"] = NSLocalizedString(
                "Try searching again.", comment: "No Search Results secondary text")
        } else if !category.isEmpty {
            alert["primary_status_text"] = NSLocalizedString(
                "There are no items in this category.",
                comment: "No Category Results primary text")
            alert["secondary_status_text"] = NSLocalizedString(
                "Try selecting another category.",
                comment: "No Category Results secondary text")
        } else if !developer.isEmpty {
            alert["primary_status_text"] = NSLocalizedString(
                "There are no items from this developer.",
                comment: "No Developer Results primary text")
            alert["secondary_status_text"] = NSLocalizedString(
                "Try selecting another developer.",
                comment: "No Developer Results secondary text")
        } else {
            alert["primary_status_text"] = NSLocalizedString(
                "There are no available software items.",
                comment: "No Items primary text")
            alert["secondary_status_text"] = NSLocalizedString(
                "Try again later.",
                comment: "No Items secondary text")
        }
        alert["hide_progress_bar"] = "hidden"
        alert["progress_bar_value"] = ""
        item_html = status_results_template.substitute(alert)
    }
    return item_html
}

func buildCategoriesPage() throws {
    // Build page showing available categories and some items in each one
    let all_items = getOptionalInstallItems()
    var category_list = Set<String>()
    for item in all_items {
        if let category = item["category"] as? String {
            category_list.insert(category)
        }
    }
    
    let all_categories_label = NSLocalizedString("All Categories", comment: "AllCategoriesLabel")
    var categories_html = "<option selected>\(all_categories_label)</option>\n"
    for item in category_list.sorted() {
        categories_html += "<option>\(item)</option>\n"
    }
    
    let page = GenericItem()
    page["list_items"] = buildCategoryItemsHTML()
    page["category_items"] = categories_html
    page["header_text"] = NSLocalizedString("Categories", comment: "Categories label")
    let footer = getRawTemplate("footer_template.html")
    let additional_templates = BaseItem(
        ["showcase": "<div class=\"showcase-empty-placeholder\"></div>",
         "sidebar": "",
         "footer": footer]
    )
    try generatePage(named: "categories.html",
                     fromTemplate: "list_template.html",
                     usingItem: page,
                     additionalTemplates: additional_templates)
}

func buildCategoryItemsHTML() -> String {
    // Returns HTML for the items on the Categories page
    var item_html = ""
    
    let all_items = getOptionalInstallItems()
    var category_list = Set<String>()
    for item in all_items {
        if let category = item["category"] as? String {
            category_list.insert(category)
        }
    }
    if all_items.isEmpty {
        // no items
        let status_results_template = getTemplate("status_results_template.html")
        let alert = BaseItem()
        alert["primary_status_text"] = NSLocalizedString(
            "There are no available software items.",
            comment: "No Items primary text")
        alert["secondary_status_text"] = NSLocalizedString(
            "Try again later.",
            comment: "No Items secondary text")
        alert["hide_progress_bar"] = "hidden"
        alert["progress_bar_value"] = ""
        item_html = status_results_template.substitute(alert)
    } else {
        let item_template = getTemplate("category_item_template.html")
        for category in category_list.sorted() {
            let category_data = BaseItem()
            category_data["category_name_escaped"] = escapeHTML(category)
            category_data["category_link"] = "munki://category-\(quote(category)).html"
            var category_items = all_items.filter(
                { ($0["category"] as? String ?? "") == category }
            )
            category_items.shuffle()
            category_data["item1_icon"] = category_items[0]["icon"] as? String ?? ""
            category_data["item1_display_name_escaped"] = escapeHTML(
                category_items[0]["display_name"] as? String ?? "")
            category_data["item1_detail_link"] = category_items[0]["detail_link"] as? String ?? ""
            if category_items.count > 1 {
                category_data["item2_display_name_escaped"] = escapeHTML(
                    category_items[1]["display_name"] as? String ?? "")
                category_data["item2_detail_link"] = category_items[1]["detail_link"] as? String ?? ""
            } else {
                category_data["item2_display_name_escaped"] = ""
                category_data["item2_detail_link"] = "#"
            }
            if category_items.count > 2 {
                category_data["item3_display_name_escaped"] = escapeHTML(
                    category_items[2]["display_name"] as? String ?? "")
                category_data["item3_detail_link"] = category_items[2]["detail_link"] as? String ?? ""
            } else {
                category_data["item3_display_name_escaped"] = ""
                category_data["item3_detail_link"] = "#"
            }
            item_html += item_template.substitute(category_data)
        }
    }
    return item_html
}

func buildMyItemsPage() throws {
    // Builds "My Items" page, which shows all current optional items the user has chosen
    let page = GenericItem()
    page["my_items_header_label"] = NSLocalizedString(
        "My Items", comment: "My Items label")
    page["myitems_rows"] = buildMyItemsRows()
    
    let additional_templates = BaseItem(["footer": getRawTemplate("footer_template.html")])
    try generatePage(named: "myitems.html",
                     fromTemplate: "myitems_template.html",
                     usingItem: page,
                     additionalTemplates: additional_templates)
}

func buildMyItemsRows() -> String {
    // Returns HTML for the items on the 'My Items' page
    var myitems_rows = ""
    let item_list = getMyItemsList()
    if !item_list.isEmpty {
        myitems_rows = buildItemListHTML(item_list,
                                         template: "myitems_item_template.html")
    } else {
        let status_results_template = getTemplate("status_results_template.html")
        let alert = BaseItem()
        alert["primary_status_text"] = NSLocalizedString(
            "You have no selected software.",
            comment: "No Installed Software primary text")
        let select_software_msg = NSLocalizedString(
            "Select software to install.",
            comment: "No Installed Software secondary text")
        alert["secondary_status_text"] = (
            "<a href=\"munki://category-all.html\">\(select_software_msg)</a>" )
        alert["hide_progress_bar"] = "hidden"
        myitems_rows = status_results_template.substitute(alert)
    }
    return myitems_rows
}

func buildUpdatesPage() throws {
    // available/pending updates
    if (NSApp.delegate! as! AppDelegate).mainWindowController._update_in_progress {
        try buildUpdateStatusPage()
        return
    }
    var show_additional_updates = true
    if (NSApp.delegate! as! AppDelegate).mainWindowController.weShouldBeObnoxious() {
        show_additional_updates = false
    }

    let item_list = getEffectiveUpdateList()
    for item in item_list {
        item["added_class"] = ""
        if item["note"] == nil {
            item["note"] = ""
        }
    }
    let update_names = item_list.map({$0["name"] as? String ?? ""})
    let problem_updates = getProblemItems()
    for item in problem_updates {
        item["added_class"] = ""
        item["hide_cancel_button"] = "hidden"
    }
    var other_updates = [OptionalItem]()
    if show_additional_updates {
        // find any optional installs with update available
        // that aren't already in our list of updates
        other_updates = getOptionalInstallItems().filter(
            { ($0["status"] as? String ?? "") == "update-available" &&
                !update_names.contains($0["name"] as? String ?? "")
            }
        )
        // find any listed optional install updates that require a higher OS
        // or have insufficient disk space or other blockers (because they have a
        // note)
        let blocked_optional_updates = getOptionalInstallItems().filter(
            {
                (($0["status"] as? String ?? "") == "installed" &&
                 !(($0["note"] as? String ?? "").isEmpty))
            }
        )
        for item in blocked_optional_updates {
            item["hide_cancel_button"] = "hidden"
        }
        other_updates += blocked_optional_updates
        for item in other_updates {
            item["added_class"] = ""
        }
    }
    let page = GenericItem()
    page["update_rows"] = ""
    page["hide_progress_spinner"] = "hidden"
    page["hide_problem_updates"] = "hidden"
    page["hide_other_updates"] = "hidden"
    page["install_all_button_classes"] = ""
    
    if item_list.isEmpty && other_updates.isEmpty && problem_updates.isEmpty {
        let status_results_template = getTemplate("status_results_template.html")
        let alert = BaseItem()
        alert["primary_status_text"] = NSLocalizedString(
            "Your software is up to date.", comment: "No Pending Updates primary text")
        alert["secondary_status_text"] = NSLocalizedString(
            "There is no new software for your computer at this time.",
            comment: "No Pending Updates secondary text")
        alert["hide_progress_bar"] = "hidden"
        alert["progress_bar_value"] = ""
        page["update_rows"] = status_results_template.substitute(alert)
    } else {
        if !item_list.isEmpty {
            page["update_rows"] = buildItemListHTML(
                item_list, template: "update_item_template.html", sort: false)
        }
    }
    
    let count = item_list.count
    // in Python was count = len([item for item in item_list if item['status'] != 'problem-item'])
    page["update_count"] = updateCountMessage(count)
    page["install_btn_label"] = getInstallAllButtonTextForCount(count)
    page["warning_text"] = getWarningText(shouldFilterAppleUpdates())
    
    // build problem updates table
    page["problem_updates_header_message"] = NSLocalizedString(
        "Problem updates", comment: "Problem Updates label")
    page["problem_update_rows"] = ""
    if !problem_updates.isEmpty {
        page["hide_problem_updates"] = ""
        page["problem_update_rows"] = buildItemListHTML(
            problem_updates, template: "update_item_template.html")
    }
    
    // build other available updates table
    page["other_updates_header_message"] = NSLocalizedString(
        "Other available updates",
        comment: "Other Available Updates label")
    page["other_update_rows"] = ""
    if !other_updates.isEmpty {
        page["hide_other_updates"] = ""
        page["other_update_rows"] = buildItemListHTML(
            other_updates, template: "update_item_template.html")
    }
    
    let additional_templates = BaseItem(["footer": getRawTemplate("footer_template.html")])
    try generatePage(named: "updates.html",
                     fromTemplate: "updates_template.html",
                     usingItem: page,
                     additionalTemplates: additional_templates)
}

func buildUpdateStatusPage() throws {
    // generates our update status page
    let status_title_default = NSLocalizedString("Checking for updates...",
                                                 comment: "Checking For Updates message")
    let page = GenericItem()
    page["update_rows"] = ""
    page["hide_progress_spinner"] = ""
    page["hide_problem_updates"] = "hidden"
    page["hide_other_updates"] = "hidden"
    page["other_updates_header_message"] = ""
    page["other_update_rows"] = ""
    
    // don't like this bit as it ties us to a different object
    guard let status_controller = (NSApp.delegate as? AppDelegate)?.statusController else {
        msc_debug_log("Could not get statusController object in buildUpdateStatusPage")
        return
    }
    guard let main_window_controller = (NSApp.delegate as? AppDelegate)?.mainWindowController else {
        msc_debug_log("Could not get mainWindowController object in buildUpdateStatusPage")
        return
    }
    let status_results_template = getTemplate("status_results_template.html")
    let alert = BaseItem()
    if status_controller._status_message.isEmpty {
        alert["primary_status_text"] = NSLocalizedString("Update in progress.",
                                                         comment: "Update In Progress primary text")
    } else {
        alert["primary_status_text"] = status_controller._status_message
    }
    if status_controller._status_detail.isEmpty {
        alert["secondary_status_text"] = "&nbsp;"
    } else {
        alert["secondary_status_text"] = status_controller._status_detail
    }
    alert["hide_progress_bar"] = ""
    if status_controller._status_percent < 0 {
        alert["progress_bar_attributes"] = "class=\"indeterminate\""
    } else {
        alert["progress_bar_attributes"] = "style=\"width: \(status_controller._status_percent)%\""
    }
    page["update_rows"] = status_results_template.substitute(alert)
    
    var install_all_button_classes = [String]()
    if status_controller._status_stopBtnHidden {
        install_all_button_classes.append("hidden")
    }
    if status_controller._status_stopBtnDisabled {
        install_all_button_classes.append("disabled")
    }
    page["install_all_button_classes"] = install_all_button_classes.joined(separator: " ")
    
    // don't like this bit as it ties us to yet another object
    page["update_count"] = !main_window_controller._status_title.isEmpty ? main_window_controller._status_title : status_title_default
    page["install_btn_label"] = NSLocalizedString("Cancel", comment: "Cancel button title/short action text")
    page["warning_text"] = ""

    let additional_templates = BaseItem(["footer": getRawTemplate("footer_template.html")])
    try generatePage(named: "updates.html",
                     fromTemplate: "updates_template.html",
                     usingItem: page,
                     additionalTemplates: additional_templates)
}

func getRestartActionForUpdateList(_ update_list: [GenericItem]) -> String {
    // Returns a localized overall restart action message for the list of updates
    if update_list.isEmpty {
        return ""
    }
    let restart_items = update_list.filter(
        { ($0["RestartAction"] as? String ?? "").contains("Restart") }
    )
    if !restart_items.isEmpty {
        // found at least one item containing 'Restart' in its RestartAction
        return NSLocalizedString("Restart Required", comment: "Restart Required title")
    }
    let logout_items = update_list.filter(
        { ($0["RestartAction"] as? String ?? "").contains("Logout") }
    )
    if !logout_items.isEmpty {
        // found at least one item containing 'Logout' in its RestartAction
        return NSLocalizedString("Logout Required", comment: "Logout Required title")
    }
    return ""
}

func getWarningText(_ filterAppleUpdates: Bool) -> String {
    // Return localized text warning about forced installs and/or
    // logouts and/or restarts
    let item_list = getEffectiveUpdateList()
    var warning_text = ""
    //if let forced_install_date = earliestForceInstallDate(item_list) {
    if let forced_install_date = earliestForceInstallDate() {
        let date_str = stringFromDate(forced_install_date)
        let forced_date_text = NSLocalizedString(
            "One or more items must be installed by %@",
            comment: "Forced Install Date summary")
        warning_text = NSString(format: forced_date_text as NSString, date_str) as String
    } else if !filterAppleUpdates && shouldAggressivelyNotifyAboutAppleUpdates() {
        warning_text = NSLocalizedString(
            "One or more important Apple updates must be installed",
            comment: "Pending Apple Updates warning"
        )
    }
    let restart_text = getRestartActionForUpdateList(item_list)
    if !restart_text.isEmpty {
        if warning_text.isEmpty {
            warning_text = restart_text
        } else {
            warning_text += " &bull; " + restart_text
        }
    }
    return warning_text
}

func buildUpdateDetailPage(_ identifier: String) throws {
    // Build detail page for a non-optional update
    let items = getUpdateList() + getProblemItems()
    let components = (identifier as NSString).components(separatedBy: "--version-")
    let name = components[0]
    let version = (components.count > 1 ? components[1] : "")
    let page_name = "updatedetail-\(identifier).html"
    for item in items {
        if ((item["name"] as? String ?? "") == name &&
            (item["version_to_install"] as? String ?? "") == version) {
            let page = UpdateItem(item)
            page.escapeAndQuoteCommonFields()
            page.addDetailSidebarLabels()
            page.addMoreInCategory(of: item, fromItems: getOptionalInstallItems())
            page.addMoreFromDeveloper(of: item, fromItems: getOptionalInstallItems())
            if let force_install_after_date = item["force_install_after_date"] as? Date {
                let local_date = discardTimeZoneFromDate(force_install_after_date)
                let date_str = shortRelativeStringFromDate(local_date)
                page["dueLabel"] = (page["dueLabel"] as? String ?? "") + " "
                page["short_due_date"] = date_str
            } else {
                page["dueLabel"] = ""
                page["short_due_date"] = ""
            }
            let additional_templates = BaseItem(["footer": getRawTemplate("footer_template.html")])
            try generatePage(named: page_name,
                             fromTemplate: "detail_template.html",
                             usingItem: page,
                             additionalTemplates: additional_templates)
            return
        }
    }
    // if we get here we didn't find any item matching identifier
    msc_debug_log("No update detail found for \(identifier)")
    try buildItemNotFoundPage(page_name)
}
