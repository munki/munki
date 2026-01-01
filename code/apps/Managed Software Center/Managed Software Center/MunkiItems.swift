//
//  MunkiItems.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 6/7/18.
//  Copyright © 2018-2026 The Munki Project. All rights reserved.
//

import AppKit
import Foundation

private var filterAppleUpdates = false
private var filterStagedOSUpdate = false

class Cache {
    // A class to cache key/value pairs
    
    static let shared = Cache()
    private var my = [String: Any]()
    var keys: [String] {
        return [String](my.keys)
    }
    
    subscript(key: String) -> Any? {
        get {
            return my[key]
        }
        set {
            my[key] = newValue
        }
    }
    
    func clear() {
        my = [String: Any]()
    }
    
    func contains(_ key: String) -> Bool {
        return my.keys.contains(key)
    }
}

func quote(_ aString: String) -> String {
   return NSString(
        string: aString).addingPercentEncoding(withAllowedCharacters: CharacterSet.urlPathAllowed) ?? aString
}

func unquote(_ aString: String) -> String {
    return NSString(string: aString).removingPercentEncoding ?? aString
}

func clearMunkiItemsCache() {
    // formerly known as reset()
    Cache.shared.clear()
}

class BaseItem {
    // Base class for our types of Munki items
    var my = [String: Any]()
    var attr_to_func = [String: ()->Any]()
    var keys: [String] {
        return [String](my.keys) + [String](attr_to_func.keys)
    }

    init() {
        // Do nothing
    }
    
    init(_ anotherItem: BaseItem) {
        my = anotherItem.my
        attr_to_func = anotherItem.attr_to_func
    }
    
    init(_ aDict: [String: Any]) {
        my = aDict
    }
    
    subscript(key: String) -> Any? {
        get {
            if let value = my[key] {
                return value
            } else if let function = attr_to_func[key] {
                return function()
            } else {
                return nil
            }
        }
        set(newValue) {
            my[key] = newValue
        }
    }
    
}

class GenericItem: BaseItem {
    // Base class for our types of Munki items
    
    func init_attr_to_func() {
        // maps subscript names to method calls
        attr_to_func = [
            "description": description,
            "description_without_images": description_without_images,
            "dependency_description": dependency_description,
            "status_text": status_text,
            "short_action_text": short_action_text,
            "long_action_text": long_action_text,
            "myitem_action_text": myitem_action_text,
            "version_label": version_label,
            "display_version": display_version,
            "developer_sort": developer_sort,
            "more_link_text": more_link_text,
        ]
    }
    
    override init() {
        super.init()
        init_attr_to_func()
    }
    
    init(_ anotherItem: GenericItem) {
        super.init(anotherItem)
    }
    
    override init(_ aDict: [String: Any]) {
        super.init(aDict)
        init_attr_to_func()
        if my["localized_strings"] != nil {
            add_localizations()
        }
        // normalize some values
        if (my["display_name"] as? String ?? "").isEmpty {
            my["display_name"] = my["name"]
        }
        my["display_name_lower"] = (my["display_name"] as? String ?? "").lowercased()
        if my["developer"] == nil {
            my["developer"] = guess_developer()
        }
        if let description = my["description"] as? String {
            my["raw_description"] = filtered_html(description)
            my["description"] = nil
        }
        my["icon"] = getIcon()
        my["due_date_sort"] = Date.distantFuture
        // sort items that need restart highest, then logout, then other
        my["restart_action_text"] = ""
        my["restart_sort"] = 2
        let restartAction = my["RestartAction"] as? String ?? ""
        if ["RequireRestart", "RecommendRestart"].contains(restartAction) {
            my["restart_sort"] = 0
            var restartActionText = NSLocalizedString(
                "Restart Required", comment: "Restart Required title")
            restartActionText += "<div class=\"restart-needed-icon\"></div>"
            my["restart_action_text"] = restartActionText
        } else if ["RequireLogout", "RecommendLogout"].contains(restartAction) {
            my["restart_sort"] = 1
            var restartActionText = NSLocalizedString(
                "Logout Required", comment: "Logout Required title")
            restartActionText += "<div class=\"logout-needed-icon\"></div>"
            my["restart_action_text"] = restartActionText
        }
        
        // sort bigger installs to the top
        if let installed_size = my["installed_size"] as? Int {
            my["size_sort"] = -installed_size
            my["size"] = humanReadable(installed_size)
        } else if let installer_item_size = my["installer_item_size"] as? Int {
            my["size_sort"] = -installer_item_size
            my["size"] = humanReadable(installer_item_size)
        } else {
            my["size_sort"] = 0
            my["size"] = "-"
        }
    }

    func description() -> String {
        return my["raw_description"] as? String ?? ""
    }
    
    func description_without_images() -> String {
        return filtered_html(description(), filter_images: true)
    }
    
    func dependency_description() -> String {
        // Return an html description of items this item depends on
        var description = ""
        let prologue = NSLocalizedString(
            "This item is required by:", comment: "Dependency List prologue text")
        if let dependent_items = my["dependent_items"] as? [String] {
            description = "<strong>" + prologue
            for item in dependent_items {
                description += "<br/>&nbsp;&nbsp;&bull; \(display_name(item))"
            }
            description += "</strong><br/><br/>"
        }
        return description
    }
    
    func guess_developer() -> String {
        // Figure out something to use for the developer
        if (my["apple_item"] as? Bool ?? false) {
            return "Apple"
        }
        if (my["installer_type"] as? String ?? "").hasPrefix("Adobe") {
            return "Adobe"
        }
        // Now we must dig
        if let installs = my["installs"] as? [[String:String]] {
            for install_item in installs {
                if let bundleIdentifier = install_item["CFBundleIdentifier"] {
                    let parts = bundleIdentifier.split(separator: ".")
                    if parts.count > 1 && ["com", "org", "net", "edu"].contains(parts[0]) {
                        return String(parts[1]).capitalized
                    }
                }
            }
        }
        return ""
    }
    
    func getIcon() -> String {
        // Return name/relative path of image file to use for the icon
        // first look for downloaded icons
        let icon_known_exts = ["bmp", "gif", "icns", "jpg", "jpeg", "png",
                               "psd", "tga", "tif", "tiff", "yuv"]
        var icon_name = my["icon_name"] as? String ?? ""
        if icon_name == "" {
            icon_name = my["name"] as? String ?? ""
        }
        if !icon_known_exts.contains((icon_name as NSString).pathExtension) {
            icon_name += ".png"
        }
        let icon_path = NSString.path(withComponents: [html_dir(), "icons", icon_name])
        if FileManager.default.fileExists(atPath: icon_path) {
            return "icons/" + quote(icon_name)
        }
        // didn't find one in the downloaded icons
        // so create one if needed from a locally installed app
        for key in ["icon_name", "display_name", "name"] {
            if var icon_name = my[key] as? String {
                if !icon_known_exts.contains((icon_name as NSString).pathExtension) {
                    icon_name += ".png"
                }
                // slightly different path since we can't write to the icons directory
                let icon_path = NSString.path(withComponents: [html_dir(), icon_name])
                if (FileManager.default.fileExists(atPath: icon_path) ||
                        convertIconToPNG(icon_name, destination: icon_path, preferredSize: 350)) {
                    return quote(icon_name)
                }
            }
        }
        // if it's an Apple Software Update, use the Software Update icon
        if let apple_update = my["apple_update"] as? Bool {
            if apple_update {
                return "static/SoftwareUpdate.png"
            }
        }
        // use the Generic package icon
        return "static/Generic.png"
    }
    
    func unavailable_reason_text(is_update: Bool = false) -> String {
        // There are several reasons an item might be unavailable for install.
        // Return the relevant reason
        let licensed_seats_available = my["licensed_seats_available"] as? Bool ?? true
        if !licensed_seats_available {
            return NSLocalizedString("No licenses available",
                                     comment: "No Licenses Available display text")
        }
        // is there a note?
        let localizedNote = getLocalizedShortNoteForItem(is_update: is_update)
        if !localizedNote.isEmpty {
            return "<span class=\"warning\">\(localizedNote)</span>"
        }
        // return generic reason
        return NSLocalizedString("Not currently available",
                                 comment: "Not Currently Available display text")
    }
    
    func status_text() -> String {
        // Return localized status display text
        let status = my["status"] as? String ?? ""
        if status == "unavailable" {
            return unavailable_reason_text()
        }
        let note = my["note"] as? String ?? ""
        if (["installed", "installed-not-removable"].contains(status) && !note.isEmpty) {
            return unavailable_reason_text(is_update: true)
        }
        let text_for = [
            "install-error":
                NSLocalizedString("Installation Error",
                                  comment: "Install Error status text"),
            "removal-error":
                NSLocalizedString("Removal Error",
                                  comment: "Removal Error status text"),
            "installed":
                NSLocalizedString("Installed",
                                  comment: "Installed status text"),
            "installing":
                NSLocalizedString("Installing",
                                  comment: "Installing status text"),
            "installed-not-removable":
                NSLocalizedString("Installed",
                                  comment: "Installed status text"),
            "not-installed":
                NSLocalizedString("Not installed",
                                  comment: "Not Installed status text"),
            "install-requested":
                NSLocalizedString("Install requested",
                                  comment: "Install Requested status text"),
            "downloading":
                NSLocalizedString("Downloading",
                                  comment: "Downloading status text"),
            "staged-os-installer":
                NSLocalizedString("Will be installed",
                                  comment: "Will Be Installed status text"),
            "will-be-installed":
                NSLocalizedString("Will be installed",
                                  comment: "Will Be Installed status text"),
            "must-be-installed":
                NSLocalizedString("Will be installed",
                                  comment: "Will Be Installed status text"),
            "removal-requested":
                NSLocalizedString("Removal requested",
                                  comment: "Removal Requested status text"),
            "preparing-removal":
                NSLocalizedString("Preparing removal",
                                  comment: "Preparing Removal status text"),
            "will-be-removed":
                NSLocalizedString("Will be removed",
                                  comment: "Will Be Removed status text"),
            "removing":
                NSLocalizedString("Removing",
                                  comment: "Removing status text"),
            "update-will-be-installed":
                NSLocalizedString("Update will be installed",
                                  comment: "Update Will Be Installed status text"),
            "update-must-be-installed":
                NSLocalizedString("Update will be installed",
                                  comment: "Update Will Be Installed status text"),
            "update-available":
                NSLocalizedString("Update available",
                                  comment: "Update available text"),
            "unavailable":
                NSLocalizedString("Unavailable",
                                  comment: "Unavailable status text")
        ]
        return text_for[status] ?? status
    }
    
    func short_action_text() -> String {
        // Return localized 'short' action text for button
        let text_for = [
            "install-error":
                NSLocalizedString("Cancel",
                                  comment: "Cancel button title/short action text"),
            "removal-error":
                NSLocalizedString("Cancel",
                                  comment: "Cancel button title/short action text"),
            "installed":
                NSLocalizedString("Remove",
                                  comment: "Remove action text"),
            "installing":
                NSLocalizedString("Installing",
                                  comment: "Installing status text"),
            "installed-not-removable":
                NSLocalizedString("Installed",
                                  comment: "Installed status text"),
            "not-installed":
                NSLocalizedString("Install",
                                  comment: "Install action text"),
            "install-requested":
                NSLocalizedString("Cancel",
                                  comment: "Cancel button title/short action text"),
            "downloading":
                NSLocalizedString("Cancel",
                                  comment: "Cancel button title/short action text"),
            "staged-os-installer":
                NSLocalizedString("Cancel",
                                  comment: "Cancel button title/short action text"),
            "will-be-installed":
                NSLocalizedString("Cancel",
                                  comment: "Cancel button title/short action text"),
            "must-be-installed":
                NSLocalizedString("Required",
                                  comment: "Install Required action text"),
            "removal-requested":
                NSLocalizedString("Cancel",
                                  comment: "Cancel button title/short action text"),
            "preparing-removal":
                NSLocalizedString("Cancel",
                                  comment: "Cancel button title/short action text"),
            "will-be-removed":
                NSLocalizedString("Cancel",
                                  comment: "Cancel button title/short action text"),
            "removing":
                NSLocalizedString("Removing",
                                  comment: "Removing status text"),
            "update-will-be-installed":
                NSLocalizedString("Cancel",
                                  comment: "Cancel button title/short action text"),
            "update-must-be-installed":
                NSLocalizedString("Required",
                                  comment: "Install Required action text"),
            "update-available":
                NSLocalizedString("Update",
                                  comment: "Update button title/action text"),
            "unavailable":
                NSLocalizedString("Unavailable",
                                  comment: "Unavailable status text")
        ]
        let status = my["status"] as? String ?? ""
        return text_for[status] ?? status
    }
    
    func long_action_text() -> String {
        // Return localized 'long' action text for button
        let text_for = [
            "install-error":
                NSLocalizedString("Cancel install",
                                  comment: "Cancel Install long action text"),
            "removal-error":
                NSLocalizedString("Cancel removal",
                                  comment: "Cancel Removal long action text"),
            "installed":
                NSLocalizedString("Remove",
                                  comment: "Remove action text"),
            "installing":
                NSLocalizedString("Installing",
                                  comment: "Installing status text"),
            "installed-not-removable":
                NSLocalizedString("Installed",
                                  comment: "Installed status text"),
            "not-installed":
                NSLocalizedString("Install",
                                  comment: "Install action text"),
            "install-requested":
                NSLocalizedString("Cancel install",
                                  comment: "Cancel Install long action text"),
            "downloading":
                NSLocalizedString("Cancel install",
                                  comment: "Cancel Install long action text"),
            "staged-os-installer":
                NSLocalizedString("Cancel install",
                                  comment: "Cancel Install long action text"),
            "will-be-installed":
                NSLocalizedString("Cancel install",
                                  comment: "Cancel Install long action text"),
            "must-be-installed":
                NSLocalizedString("Install Required",
                                  comment: "Install Required action text"),
            "removal-requested":
                NSLocalizedString("Cancel removal",
                                  comment: "Cancel Removal long action text"),
            "preparing-removal":
                NSLocalizedString("Cancel removal",
                                  comment: "Cancel Removal long action text"),
            "will-be-removed":
                NSLocalizedString("Cancel removal",
                                  comment: "Cancel Removal long action text"),
            "removing":
                NSLocalizedString("Removing",
                                  comment: "Removing status text"),
            "update-will-be-installed":
                NSLocalizedString("Cancel update",
                                  comment: "Cancel Update long action text"),
            "update-must-be-installed":
                NSLocalizedString("Update Required",
                                  comment: "Update Required long action text"),
            "update-available":
                NSLocalizedString("Update",
                                  comment: "Update button title/action text"),
            "unavailable":
                NSLocalizedString("Currently Unavailable",
                                  comment: "Unavailable long action text")
        ]
        let status = my["status"] as? String ?? ""
        return text_for[status] ?? status
    }
    
    func myitem_action_text() -> String {
        let text_for = [
            "install-error":
                NSLocalizedString("Cancel install",
                                  comment: "Cancel Install long action text"),
            "removal-error":
                NSLocalizedString("Cancel removal",
                                  comment: "Cancel Removal long action text"),
            "installed":
                NSLocalizedString("Remove",
                                  comment: "Remove action text"),
            "installing":
                NSLocalizedString("Installing",
                                  comment: "Installing status text"),
            "installed-not-removable":
                NSLocalizedString("Installed",
                                  comment: "Installed status text"),
            "removal-requested":
                NSLocalizedString("Cancel removal",
                                  comment: "Cancel Removal long action text"),
            "preparing-removal":
                NSLocalizedString("Cancel removal",
                                  comment: "Cancel Removal long action text"),
            "will-be-removed":
                NSLocalizedString("Cancel removal",
                                  comment: "Cancel Removal long action text"),
            "removing":
                NSLocalizedString("Removing",
                                  comment: "Removing status text"),
            "update-available":
                NSLocalizedString("Update",
                                  comment: "Update button title/action text"),
            "update-will-be-installed":
                NSLocalizedString("Remove",
                                  comment: "Remove action text"),
            "update-must-be-installed":
                NSLocalizedString("Update Required",
                                  comment: "Update Required long action text"),
            "install-requested":
                NSLocalizedString("Cancel install",
                                  comment: "Cancel Install long action text"),
            "downloading":
                NSLocalizedString("Cancel install",
                                  comment: "Cancel Install long action text"),
            "staged-os-installer":
                NSLocalizedString("Cancel install",
                                  comment: "Cancel Install long action text"),
            "will-be-installed":
                NSLocalizedString("Cancel install",
                                  comment: "Cancel Install long action text"),
            "must-be-installed":
                NSLocalizedString("Required",
                                  comment: "Install Required action text"),
        ]
        let status = my["status"] as? String ?? ""
        return text_for[status] ?? status
    }
    
    func version_label() -> String {
        // Text for the version label
        let status = my["status"] as? String ?? ""
        switch status {
        case "will-be-removed":
            let removal_text = NSLocalizedString(
                "Will be removed", comment: "Will Be Removed status text")
            return "<span class=\"warning\">\(removal_text)</span>"
        case "removal-requested":
            let removal_text = NSLocalizedString(
                "Removal requested", comment: "Removal Requested status text")
            return "<span class=\"warning\">\(removal_text)</span>"
        default:
            return NSLocalizedString("Version", comment: "Sidebar Version label")
        }
    }
    
    func display_version() -> String {
        // Version number for display
        let status = my["status"] as? String ?? ""
        if status == "will-be-removed" {
            return "-"
        }
        return my["version_to_install"] as? String ?? ""
    }
    
    func developer_sort() -> Int {
        // Returns sort priority based on developer and install/removal status
        let status = my["status"] as? String ?? ""
        let developer = my["developer"] as? String ?? ""
        if status != "will-be-removed" && developer == "Apple" {
            return 0
        }
        return 1
    }
    
    func more_link_text() -> String {
        return NSLocalizedString("More", comment: "More link text")
    }
    
    func _get_preferred_locale(_ available_locales: [String]) -> String {
        let language_codes = Bundle.preferredLocalizations(
            from: available_locales, forPreferences: nil)
        return language_codes[0]
    }
    
    func getLocalizedShortNoteForItem(is_update: Bool = false) -> String {
        // Attempt to localize a note. Currently handle only two types
        let note = my["note"] as? String ?? ""
        if is_update {
            return NSLocalizedString("Update available",
                                     comment: "Update available text")
        } else if note.hasPrefix("Insufficient disk space to download and install") {
            return NSLocalizedString("Not enough disk space",
                                     comment: "Not Enough Disk Space display text")
        } else if note.hasPrefix("Requires macOS version ") {
            return NSLocalizedString("macOS update required",
                                     comment: "macOS update required text")
        }
        // we don't know how to localize this note, return empty string
        return ""
    }
    
    func getLocalizedLongNoteForItem(is_update: Bool = false) -> String {
        // Attempt to localize a note. Currently handle only two types.
        let note = my["note"] as? String ?? ""
        if note.hasPrefix("Insufficient disk space to download and install") {
            if is_update {
                return NSLocalizedString(
                    "An older version is currently installed. There is not enough " +
                    "disk space to download and install this update.",
                    comment: "Long Not Enough Disk Space For Update display text")
            } else {
                return NSLocalizedString(
                    "There is not enough disk space to download and install this item.",
                    comment: "Long Not Enough Disk Space display text")
            }
        } else if note.hasPrefix("Requires macOS version ") {
            var base_string = ""
            if is_update {
                base_string = NSLocalizedString(
                    "An older version is currently installed. You must upgrade to " +
                    "macOS version %@ or higher to be able to install this update.",
                    comment: "Long update requires a higher OS version text")
            } else {
                base_string = NSLocalizedString(
                    "You must upgrade to macOS version %@ to be able to " +
                    "install this item.",
                    comment: "Long item requires a higher OS version text")
            }
            let os_version = my["minimum_os_version"] as? String ?? "UNKNOWN"
            return NSString(format: base_string as NSString, os_version as NSString) as String
        }
        // we don't know how to localize this note, return empty string
        return ""
    }
    
    func add_localizations() {
        // add localized names, descriptions, etc if available
        let localized_strings = my["localized_strings"] as? [String: Any] ?? [String: Any]()
        var available_locales = [String](localized_strings.keys)
        let fallback_locale = localized_strings["fallback_locale"] as? String ?? ""
        if !fallback_locale.isEmpty {
            available_locales = available_locales.filter({ $0 != "fallback_locale" })
            available_locales.append(fallback_locale)
        }
        let language_code = _get_preferred_locale(available_locales)
        if language_code != fallback_locale {
            if let locale_dict = localized_strings[language_code] as? [String: Any] {
                let localized_keys = ["category",
                                      "description",
                                      "display_name",
                                      "preinstall_alert",
                                      "preuninstall_alert",
                                      "preupgrade_alert"]
                for key in localized_keys {
                    if let value = locale_dict[key] {
                        my[key] = value
                    }
                }
            }
        }
    }
}

class OptionalItem: GenericItem {
    // Dictionary subclass that models a given optional install item
    
    init(_ anotherItem: OptionalItem) {
        super.init(anotherItem)
    }
    
    override init(_ aDict: [String: Any]) {
        // Initialize an OptionalItem from a item dict from the
        // InstallInfo.plist optional_installs array
        super.init(aDict)
        var category = my["category"] as? String ?? ""
        if category.isEmpty {
            category = NSLocalizedString(
                "Uncategorized", comment: "No Category name")
            my["category"] = category
        }
        my["featured"] = my["featured"] as? Bool ?? false
        let developer = my["developer"] as? String ?? ""
        if !developer.isEmpty {
            my["category_and_developer"] = "\(category) - \(developer)"
        } else {
            my["category_and_developer"] = category
        }
        let name = my["name"] as? String ?? ""
        if !name.isEmpty {
            my["dependent_items"] = dependentItems(name)
        }
        let installer_item_size = my["installer_item_size"] as? Int ?? 0
        let installed_size = my["installed_size"] as? Int ?? 0
        if installer_item_size > 0 {
            my["size"] = humanReadable(installer_item_size)
        } else if installed_size > 0 {
            my["size"] = humanReadable(installed_size)
        } else {
            my["size"] = ""
        }
        my["detail_link"] = "munki://detail-\(quote(name)).html"
        my["hide_cancel_button"] = ""
        let note = my["note"] as? String ?? ""
        if note.isEmpty {
            my["note"] = _get_note_from_problem_items()
        }
        let status = my["status"] as? String ?? ""
        if status.isEmpty {
            my["status"] = _get_status()
        }
        my["days_available"] = getDaysPending(name)
    }
    
    func _get_status() -> String {
        // Calculates initial status for an item and also sets a boolean
        // if a updatecheck is needed
        let managed_update_names = cachedInstallInfo()["managed_updates"] as? [String] ?? [String]()
        let self_service = SelfService()
        my["updatecheck_needed"] = false
        my["user_directed_action"] = false
        let name = my["name"] as? String ?? ""
        let installed = my["installed"] as? Bool ?? false
        let dependent_items = my["dependent_items"] as? [String] ?? [String]()
        var status = ""
        if installed {
            let removal_error = my["removal_error"] as? String ?? ""
            let will_be_removed = my["will_be_removed"] as? Bool ?? false
            if !removal_error.isEmpty {
                status = "removal-error"
            } else if will_be_removed {
                status = "will-be-removed"
            } else if !dependent_items.isEmpty {
                status = "installed-not-removable"
            } else if self_service.uninstalls.contains(name) {
                status = "removal-requested"
                my["updatecheck_needed"] = true
            } else {
                // not in managed uninstalls
                let needs_update = my["needs_update"] as? Bool ?? false
                let uninstallable = my["uninstallable"] as? Bool ?? false
                if !needs_update {
                    if uninstallable {
                        status = "installed"
                    } else {
                        status = "installed-not-removable"
                    }
                } else {
                    // needs_update is true
                    if managed_update_names.contains(name) {
                        status = "update-must-be-installed"
                    } else if !dependent_items.isEmpty {
                        status = "update-must-be-installed"
                    } else if self_service.installs.contains(name) {
                        status = "update-will-be-installed"
                    } else {
                        // not in self-service managed_installs
                        status = "update-available"
                    }
                }
            }
        } else {
            // not installed
            let install_error = my["install_error"] as? String ?? ""
            let note = my["note"] as? String ?? ""
            let licensed_seats_available = my["licensed_seats_available"] as? Bool ?? true
            let will_be_installed = my["will_be_installed"] as? Bool ?? false
            if !install_error.isEmpty {
                status = "install-error"
            } else if !note.isEmpty {
                /* TO-DO: handle this case better
                   some reason we can't install
                   usually not enough disk space
                   but can also be:
                   'Integrity check failed'
                   'Download failed \(errmsg)'
                   'Can't install \(manifestitemname) because: \(errmsg)',
                   'Insufficient disk space to download and install.'
                   and others in the future
 
                   for now we prevent install this way */
                status = "unavailable"
            } else if !licensed_seats_available {
                status = "unavailable"
            } else if !dependent_items.isEmpty {
                status = "must-be-installed"
            } else if will_be_installed {
                status = "will-be-installed"
            } else if self_service.installs.contains(name) {
                status = "install-requested"
                my["updatecheck_needed"] = true
            } else {
                // not in managed_installs
                status = "not-installed"
            }
        }
        return status
    }
    
    func _get_note_from_problem_items() -> String {
        // Checks InstallInfo's problem_items for any notes for self that might
        // give feedback why this item can't be downloaded or installed
        let problem_items = cachedInstallInfo()["problem_items"] as? [[String:Any]] ?? [[String:Any]]()
        // filter problem items for any whose name matches the name of
        // the current item
        let name = my["name"] as? String ?? ""
        let matches = problem_items.filter({ $0["name"] as? String == name })
        if !matches.isEmpty {
            return matches[0]["note"] as? String ?? ""
        }
        return ""
    }
    
    override func description() -> String {
        // return a full description for the item, inserting dynamic data
        // if needed
        let status = my["status"] as? String ?? ""
        let install_error = my["install_error"] as? String ?? ""
        let removal_error = my["removal_error"] as? String ?? ""
        let note = my["note"] as? String ?? ""
        let dependent_items = my["dependent_items"] as? [String] ?? [String]()
        var start_text = ""
        if !install_error.isEmpty {
            let warning_text = NSLocalizedString(
                "An installation attempt failed. " +
                "Installation will be attempted again.\n" +
                "If this situation continues, contact your systems " +
                "administrator.",
                comment: "Install Error message")
            start_text += "<span class=\"warning\">\(filtered_html(warning_text))</span><br/><br/>"
        } else if !removal_error.isEmpty {
            let warning_text = NSLocalizedString(
                "A removal attempt failed. " +
                "Removal will be attempted again.\n" +
                "If this situation continues, contact your systems " +
                "administrator.",
                comment: "Removal Error message")
            start_text += "<span class=\"warning\">\(filtered_html(warning_text))</span><br/><br/>"
        } else if !note.isEmpty {
            let is_update = ["installed", "installed-not-removable"].contains(status)
            var warning_text = getLocalizedLongNoteForItem(is_update: is_update)
            if warning_text.isEmpty {
                // some other note. Probably won't be localized, but we can try
                warning_text = Bundle.main.localizedString(forKey: note, value: note, table: nil)
            }
            start_text += "<span class=\"warning\">\(filtered_html(warning_text))</span><br/><br/>"
        } else {
            if let days_available = my["days_available"] as? Int {
                if days_available > 2 {
                    let format_str = NSLocalizedString(
                        "This update has been pending for %@ days.",
                        comment: "Pending days message")
                    let formatted_str = NSString(format: format_str as NSString,
                                             String(days_available) as NSString)
                    start_text += "<span class=\"warning\">\(formatted_str)</span><br><br>"
                }
            }
            if !(dependent_items.isEmpty) {
                start_text += dependency_description()
            }
        }
        return start_text + (my["raw_description"] as? String ?? "")
    }
    
    func update_status() -> Bool {
        // user clicked an item action button - update the item's state
        // also sets a boolean indicating if we should run an updatecheck
        my["updatecheck_needed"] = true
        var self_service_change_success = true
        let original_status = my["status"] as? String ?? ""
        let managed_update_names = cachedInstallInfo()["managed_updates"] as? [String] ?? [String]()
        let status = my["status"] as? String ?? ""
        let name = my["name"] as? String ?? ""
        let needs_update = my["needs_update"] as? Bool ?? false
        switch status {
        case "update-available":
            // mark the update for install
            my["status"] = "install-requested"
            self_service_change_success = subscribe(self)
        case "update-will-be-installed":
            // cancel the update
            my["status"] = "update-available"
            self_service_change_success = unmanage(self)
        case "will-be-removed", "removal-requested", "preparing-removal", "removal-error":
            if managed_update_names.contains(name) {
                // update is managed, so user can't opt out
                my["status"] = "installed"
            } else if needs_update {
                // update is being installed, can opt-out
                my["status"] = "update-will-be-installed"
            } else {
                /// item is simply installed
                my["status"] = "installed"
            }
            let was_self_service_install = my["was_self_service_install"] as? Bool ?? false
            if was_self_service_install {
                self_service_change_success = subscribe(self)
            } else {
                self_service_change_success = unmanage(self)
            }
            if original_status == "removal-requested" {
                my["updatecheck_needed"] = false
            }
        case "staged-os-installer", "will-be-installed", "install-requested", "downloading", "install-error":
            // cancel install request
            if needs_update {
                my["status"] = "update-available"
            } else {
                my["status"] = "not-installed"
            }
            self_service_change_success = unmanage(self)
            if original_status == "install-requested" {
                my["updatecheck_needed"] = false
            }
        case "not-installed":
            // mark for install
            my["status"] = "install-requested"
            self_service_change_success = subscribe(self)
        case "installed":
            // mark for removal
            my["status"] = "removal-requested"
            if SelfService().installs.contains(name) {
                my["was_self_service_install"] = true
            }
            self_service_change_success = unsubscribe(self)
        default:
            // do nothing
            my["status"] = status
        }
        return self_service_change_success
    }
    
}

class UpdateItem: GenericItem {
    // GenericItem subclass that models an update install item
    
    init(_ anotherItem: UpdateItem) {
        super.init(anotherItem)
    }
    
    override init(_ aDict: [String : Any]) {
        super.init(aDict)
        let name = my["name"] as? String ?? ""
        let version = my["version_to_install"] as? String ?? ""
        let identifier = "\(name)--version-\(version)"
        my["detail_link"] = "munki://updatedetail-\(quote(identifier)).html"
        let status = my["status"] as? String ?? ""
        if status != "will-be-removed" {
            if let force_install_after_date = my["force_install_after_date"] as? Date {
                my["type"] = NSLocalizedString("Critical Update",
                                               comment: "Critical Update type")
                my["due_date_sort"] = force_install_after_date
            }
        }
        if my["type"] == nil {
            my["type"] = NSLocalizedString("Managed Update",
                                           comment: "Managed Update type")
        }
        my["category"] = NSLocalizedString("Managed Update",
                                           comment: "Managed Update type")
        my["hide_cancel_button"]  = "hidden"
        my["dependent_items"] = dependentItems(name)
        my["days_available"] = getDaysPending(name)
    }
    
    override func description() -> String {
        var start_text = ""
        let status = my["status"] as? String ?? ""
        if status != "will-be-removed" {
            if let force_install_after_date = my["force_install_after_date"] as? Date {
                // insert installation deadline into description
                let local_date = discardTimeZoneFromDate(force_install_after_date)
                let date_str = stringFromDate(local_date)
                let forced_date_text = NSLocalizedString(
                    "This item must be installed by %@",
                    comment: "Forced Date warning")
                let formatted_str = NSString(format: forced_date_text as NSString,
                                             date_str as NSString)
                start_text += "<span class=\"warning\">\(formatted_str)</span><br><br>"
            } else if status == "problem-item" {
                let install_error = my["install_error"] as? String ?? ""
                let removal_error = my["removal_error"] as? String ?? ""
                let note = my["note"] as? String ?? ""
                if !install_error.isEmpty {
                    let warning_text = NSLocalizedString(
                        "An installation attempt failed. " +
                        "Installation will be attempted again.\n" +
                        "If this situation continues, contact your systems " +
                        "administrator.",
                        comment: "Install Error message")
                    start_text += "<span class=\"warning\">\(filtered_html(warning_text))</span><br/><br/>"
                } else if !removal_error.isEmpty {
                    let warning_text = NSLocalizedString(
                        "A removal attempt failed. " +
                        "Removal will be attempted again.\n" +
                        "If this situation continues, contact your systems " +
                        "administrator.",
                        comment: "Removal Error message")
                    start_text += "<span class=\"warning\">\(filtered_html(warning_text))</span><br/><br/>"
                } else if !note.isEmpty {
                    var warning_text = getLocalizedLongNoteForItem()
                    if warning_text.isEmpty {
                        // some other note. Probably won't be localized, but we can try
                        warning_text = Bundle.main.localizedString(forKey: note, value: note, table: nil)
                    }
                    start_text += "<span class=\"warning\">\(filtered_html(warning_text))</span><br/><br/>"
                }
            } else if let days_available = my["days_available"] as? Int {
                if days_available > 2 {
                    let format_str = NSLocalizedString(
                        "This update has been pending for %@ days.",
                        comment: "Pending days message")
                    let formatted_str = NSString(format: format_str as NSString,
                                                 String(days_available) as NSString)
                    start_text += "<span class=\"warning\">\(formatted_str)</span><br><br>"
                }
            }
            if !((my["dependent_items"] as? [String] ?? []).isEmpty) {
                start_text += dependency_description()
            }
        }
        return start_text + (my["raw_description"] as? String ?? "")
    }
}

func cachedInstallInfo() -> [String : Any] {
    if !Cache.shared.keys.contains("InstallInfo") {
        Cache.shared["InstallInfo"] = getInstallInfo()
    }
    return Cache.shared["InstallInfo"] as? [String : Any] ?? [String : Any]()
}

func updateTrackingInfo() -> [String : Any] {
    if !Cache.shared.keys.contains("UpdateNotificationTrackingInfo") {
        Cache.shared["UpdateNotificationTrackingInfo"] = getUpdateNotificationTracking()
    }
    return Cache.shared["UpdateNotificationTrackingInfo"] as? [String : Any] ?? [String : Any]()
}

func getDateFirstAvailable(_ itemname: String) -> Date? {
    // Uses UpdateNotificationTracking.plist data to determine when an item
    // was first "discovered"/presented as available
    let trackingInfo = updateTrackingInfo()
    for category in trackingInfo.keys {
        if let items = (trackingInfo[category] as? [String : Any]) {
            for name in items.keys {
                if name == itemname {
                    return (items[name] as? Date)
                }
            }
        }
    }
    return nil
}

func getDaysPending(_ itemname: String) -> Int {
    // Returns the number of days an item has been pending
    if let dateAvailable = getDateFirstAvailable(itemname) {
        let secondsInDay = 60 * 60 * 24
        let timeAvailable = dateAvailable.timeIntervalSinceNow * -1
        let daysAvailable = Int(timeAvailable as Double)/secondsInDay
        return daysAvailable
    }
    return 0
}

func shouldAggressivelyNotifyAboutMunkiUpdates(days: Int = -1) -> Bool {
    // Do we have any Munki updates that have been pending a long time?
    let aggressiveNotificationDays = pref("AggressiveUpdateNotificationDays") as? Int ?? 14
    if aggressiveNotificationDays == 0 {
        return false
    }
    for category in ["StagedOSUpdates", "managed_installs"] {
        if let trackingInfo = updateTrackingInfo()[category] as? [String: Any?] {
            for name in trackingInfo.keys {
                if getDaysPending(name) > aggressiveNotificationDays {
                    return true
                }
            }
        }
    }
    return false
}

func shouldAggressivelyNotifyAboutAppleUpdates(days: Int = -1) -> Bool {
    // Do we have any Apple updates that require a restart that have been
    // pending a long time?
    var maxPendingDays = 0
    let requiresRestartItems = getAppleUpdates().filter(
            { ($0["RestartAction"] as? String ?? "").hasSuffix("Restart") }
        )
    for item in requiresRestartItems {
        if let itemname = item["name"] as? String {
            let thisItemDaysPending = getDaysPending(itemname)
            if thisItemDaysPending > maxPendingDays {
                maxPendingDays = thisItemDaysPending
            }
        }
    }
    if days == -1 {
        let aggressiveNotificationDays = pref("AggressiveUpdateNotificationDays") as? Int ?? 14
        if aggressiveNotificationDays == 0 {
            // never get aggressive
            return false
        }
        return maxPendingDays > aggressiveNotificationDays
    } else {
        return maxPendingDays > days
    }
}

func optionalInstallsExist() -> Bool {
    let optional_items = cachedInstallInfo()["optional_installs"] as? [[String : Any]] ?? [[String : Any]]()
    return optional_items.count > 0
}

func getOptionalInstallItems() -> [OptionalItem] {
    let appleSoftwareUpdatesOnly = pythonishBool(pref("AppleSoftwareUpdatesOnly"))
    if appleSoftwareUpdatesOnly {
        return [OptionalItem]()
    }
    if !Cache.shared.keys.contains("optional_install_items") {
        let optional_items = cachedInstallInfo()["optional_installs"] as? [[String : Any]] ?? [[String : Any]]()
        var optional_install_items = optional_items.map({ OptionalItem($0) })
        let featured_items = cachedInstallInfo()["featured_items"] as? [String] ?? [String]()
        let staged_os_installer = getStagedOSUpdate()
        let staged_os_installer_name = staged_os_installer["name"] as? String ?? ""
        for index in 0..<optional_install_items.count {
            if let name = optional_install_items[index]["name"] as? String {
                if (staged_os_installer_name != "" && staged_os_installer_name == name) {
                    // replace the item with its staged version
                    optional_install_items[index] = OptionalItem(staged_os_installer)
                    optional_install_items[index]["status"] = "staged-os-installer"
                    optional_install_items[index]["updatecheck_needed"] = false
                }
                if featured_items.contains(name) {
                    optional_install_items[index]["featured"] = true
                }
            }
        }
        Cache.shared["optional_install_items"] = optional_install_items
    }
    return Cache.shared["optional_install_items"] as? [OptionalItem] ?? [OptionalItem]()
}

func getProblemItems() -> [UpdateItem] {
    if !Cache.shared.keys.contains("problem_items") {
        var problem_items = cachedInstallInfo()["problem_items"] as? [[String:Any]] ?? [[String:Any]]()
        for i in 0..<problem_items.count {
            problem_items[i]["status"] = "problem-item"
        }
        Cache.shared["problem_items"] = problem_items.map({ UpdateItem($0) }).sorted(by: { update_list_sort($0, $1) })
    }
    return Cache.shared["problem_items"] as? [UpdateItem] ?? [UpdateItem]()
}

func updateCheckNeeded() -> Bool {
    // Returns true if any item in optional installs list has
    // 'updatecheck_needed' == true
    let updatecheck_items = getOptionalInstallItems().filter({ ($0["updatecheck_needed"] as? Bool ?? false) == true })
    return !updatecheck_items.isEmpty
}

func optionalItem(forName name: String) -> OptionalItem? {
    for item in getOptionalInstallItems() {
        let item_name = item["name"] as? String ?? ""
        if item_name == name {
            return item
        }
    }
    return nil
}

func getOptionalWillBeInstalledItems() -> [OptionalItem] {
    let problem_item_names = getProblemItems().map(
        { return $0["name"] as? String ?? "" }
    )
    var will_be_installed_statuses = [
        "install-requested",
        "will-be-installed",
        "update-will-be-installed",
        "install-error"
    ]
    if !shouldFilterStagedOSUpdate() {
        will_be_installed_statuses.append("staged-os-installer")
    }
    return getOptionalInstallItems().filter(
        {
            let status = $0["status"] as? String ?? ""
            let name = $0["name"] as? String ?? ""
            return (will_be_installed_statuses.contains(status) &&
                    !problem_item_names.contains(name))
        }
    )
}

func getOptionalWillBeRemovedItems() -> [OptionalItem] {
    let problem_item_names = getProblemItems().map(
        { return $0["name"] as? String ?? "" }
    )
    return getOptionalInstallItems().filter(
        {
            let status = $0["status"] as? String ?? ""
            let name = $0["name"] as? String ?? ""
            return (["removal-requested", "will-be-removed",
                     "removal-error"].contains(status) &&
                    !problem_item_names.contains(name))
        }
    )
}

func display_name(_ item_name: String) -> String {
    // Returns a display_name for item_name, or item_name if not found
    for item in getOptionalInstallItems() {
        let name = item["name"] as? String ?? ""
        if name == item_name {
            return item["display_name"] as? String ?? item_name
        }
    }
    return item_name
}

func getUpdateList() -> [UpdateItem] {
    if !Cache.shared.keys.contains("update_list") {
        Cache.shared["update_list"] = _build_update_list()
    }
    return Cache.shared["update_list"] as? [UpdateItem] ?? [UpdateItem]()
}

func update_list_sort(_ lh: UpdateItem, _ rh: UpdateItem) -> Bool {
    // sort by due_date_sort, restart_sort, developer_sort, size_sort
    let lh_due_date = lh["due_date_sort"] as? Date ?? Date.distantFuture
    let rh_due_date = rh["due_date_sort"] as? Date ?? Date.distantFuture
    let lh_restart_sort = lh["restart_sort"] as? Int ?? 0
    let rh_restart_sort = rh["restart_sort"] as? Int ?? 0
    let lh_developer_sort = lh["developer_sort"] as? Int ?? 0
    let rh_developer_sort = rh["developer_sort"] as? Int ?? 0
    let lh_size_sort = lh["size_sort"] as? Int ?? 0
    let rh_size_sort = rh["size_sort"] as? Int ?? 0

    if lh_due_date != rh_due_date {
        return lh_due_date < rh_due_date
    } else if lh_restart_sort != rh_restart_sort {
        return lh_restart_sort < rh_restart_sort
    } else if lh_developer_sort != rh_developer_sort {
        return lh_developer_sort <  rh_developer_sort
    } else {
        return lh_size_sort < rh_size_sort
    }
}

func _build_update_list() -> [UpdateItem] {
    var update_items = [[String: Any]]()
    
    var stagedOSupdate = getStagedOSUpdate()
    if !shouldFilterStagedOSUpdate() && pythonishBool(stagedOSupdate) {
        stagedOSupdate["developer"] = "Apple"
        stagedOSupdate["status"] = "will-be-installed"
        stagedOSupdate["staged_os_installer"] = true
        update_items.append(stagedOSupdate)
        // don't show Apple updates if we have a pending staged OS upgrade
        setFilterAppleUpdates(true)
    } else {
        if munkiUpdatesContainAppleItems() {
            // don't show any Apple updates if there are Munki items that are Apple items
            NSLog("%@", "Not displaying Apple updates because one or more Munki update is an Apple item" )
        } else if (shouldFilterAppleUpdates() && isAppleSilicon()) {
            // we can't install any Apple updates on Apple silicon, so filter them all
            NSLog("%@", "Not displaying any Apple updates because we've been asked to filter Apple updates and we're on Apple silicon" )
        } else {
            for var item in getAppleUpdates() {
                if (shouldFilterAppleUpdates() &&
                    ((item["RestartAction"] as? String ?? "").hasSuffix("Restart"))) {
                    // skip this update because it requires a restart and we've been
                    // directed to filter these out
                    continue
                }
                item["developer"] = "Apple"
                item["status"] = "will-be-installed"
                item["apple_update"] = true
                update_items.append(item)
            }
        }
    }
    let install_info = cachedInstallInfo()
    if let managed_installs = install_info["managed_installs"] as? [[String: Any]] {
        for var item in managed_installs {
            item["status"] = "will-be-installed"
            update_items.append(item)
        }
    }
    if let removal_items = install_info["removals"] as? [[String: Any]] {
        for var item in removal_items {
            item["status"] = "will-be-removed"
            update_items.append(item)
        }
    }
    let update_list = update_items.map({ UpdateItem($0) })
    return update_list.sorted(by: { update_list_sort($0, $1) })
}

func updateListContainsStagedOSUpdate() -> Bool {
    // Return true if the update list contains a staged macOS installer
    if shouldFilterStagedOSUpdate() {
        return false
    }
    return getUpdateList().filter(
            { ($0["staged_os_installer"] as? Bool ?? false) }
        ).count > 0
}

func updatesRequireLogout() -> Bool {
    // Return true if any item in the update list requires a logout or if
    // Munki's InstallRequiresLogout preference is true.
    if installRequiresLogout() {
        return true
    }
    let requiresLogout = getUpdateList().filter(
            { ($0["RestartAction"] as? String ?? "").hasSuffix("Logout") }
        ).count > 0
    return requiresLogout
}

func updatesRequireRestart() -> Bool {
    // Return true if any item in the update list requires a restart
    let requiresRestart = getUpdateList().filter(
            { ($0["RestartAction"] as? String ?? "").hasSuffix("Restart") }
        ).count > 0
    return requiresRestart
}

func appleUpdatesRequireRestartOnMojaveAndUp() -> Bool {
    // Return true if any item in the apple update list requires a restart
    if #available(OSX 10.10, *) {
        let os_vers = OperatingSystemVersion(majorVersion: 10, minorVersion: 14, patchVersion: 0)
        if ProcessInfo().isOperatingSystemAtLeast(os_vers) {
            let requiresRestart = getAppleUpdates().filter(
                    { ($0["RestartAction"] as? String ?? "").hasSuffix("Restart") }
                ).count > 0
            return requiresRestart
        }
    }
    return false
}

func appleUpdatesMustBeDoneWithSystemPreferences() -> Bool {
    // Return true if any item in the apple update list must be done with System Preferences Software Update
    if isAppleSilicon() {
        return getAppleUpdates().count > 0
    }
    return appleUpdatesRequireRestartOnMojaveAndUp()
}

func updatesContainNonUserSelectedItems() -> Bool {
    // Does the list of updates contain items not selected by the user?
    if !munkiUpdatesContainAppleItems() && getAppleUpdates().count > 0 {
        // available Apple updates are not user selected
        return true
    }
    let install_info = cachedInstallInfo()
    let install_items = install_info["managed_installs"] as? [[String: Any]] ?? [[String: Any]]()
    let removal_items = install_info["removals"] as? [[String: Any]] ?? [[String: Any]]()
    let filtered_installs = install_items.filter(
        { !user_install_selections.contains($0["name"] as? String ?? "") }
    )
    if filtered_installs.count > 0 {
        return true
    }
    let filtered_uninstalls = removal_items.filter(
        { !user_removal_selections.contains($0["name"] as? String ?? "") }
    )
    if filtered_uninstalls.count > 0 {
        return true
    }
    return false
}

func getEffectiveUpdateList() -> [GenericItem] {
    // Combine the updates Munki has found with any optional choices to
    // make the effective list of updates
    let optional_installs = getOptionalWillBeInstalledItems() as [GenericItem]
    let optional_removals = getOptionalWillBeRemovedItems() as [GenericItem]
    let optional_item_names = (optional_installs + optional_removals).map(
        { return $0["name"] as? String ?? "" }
    )
    // filter out pending optional items from the list of all pending updates
    // so we can add in the items with additional optional detail
    let mandatory_updates = getUpdateList().filter(
        { !optional_item_names.contains($0["name"] as? String ?? "") }
    ) as [GenericItem]
    return mandatory_updates + optional_installs + optional_removals
}

func getMyItemsList() -> [OptionalItem] {
    // Returns a list of optional_installs items the user has chosen
    // to install or to remove
    let self_service = SelfService()
    let install_list = getOptionalInstallItems().filter(
        { self_service.installs.contains($0["name"] as? String ?? "") }
    )
    let uninstall_list = getOptionalInstallItems().filter(
        {
            (self_service.uninstalls.contains($0["name"] as? String ?? "") &&
                ($0["installed"] as? Bool ?? false))
        }
    )
    return install_list + uninstall_list
}

func dependentItems(_ item_name: String) -> [String] {
    // Returns the names of any selected optional items that require this
    // optional item
    if !Cache.shared.keys.contains("optional_installs_with_dependencies") {
        let self_service_installs = SelfService().installs
        if let optional_installs = cachedInstallInfo()["optional_installs"] as? [PlistDict] {
            Cache.shared["optional_installs_with_dependencies"] = (
                optional_installs.filter(
                    {
                        (self_service_installs.contains($0["name"] as? String ?? "") &&
                            $0.keys.contains("requires"))
                    }
                )
            )
        }
    }
    var dependent_items = [String]()
    if let optional_installs_with_dependencies = (
            Cache.shared["optional_installs_with_dependencies"] as? [PlistDict]) {
        for item in optional_installs_with_dependencies {
            if let requires_list = item["requires"] as? [String] {
                if requires_list.contains(item_name) {
                    if let name = item["name"] as? String {
                        dependent_items.append(name)
                    }
                }
            }
        }
    }
    return dependent_items
}

func setFilterAppleUpdates(_ state: Bool) {
    // record our state
    filterAppleUpdates = state
}

func setFilterStagedOSUpdate(_ state: Bool) {
    // record our state
    filterStagedOSUpdate = state
}

func shouldFilterAppleUpdates() -> Bool {
    // should we filter out Apple updates?
    return filterAppleUpdates
}

func shouldFilterStagedOSUpdate() -> Bool {
    // should we filter out a staged OS update?
    return filterStagedOSUpdate
}
