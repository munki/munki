//
//  SelfService.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 6/12/18.
//  Copyright © 2018-2026 The Munki Project. All rights reserved.
//

import Foundation

// TO-DO: get rid of these globals
var user_install_selections: Set<String> = []
var user_removal_selections: Set<String> = []


func post_install_request_notification(_ event: String, _ item: GenericItem) {
    let user_info: PlistDict = [
        "event": event,
        "name": item["name"] as? String ?? "",
        "version": item["version_to_install"] as? String ?? "0"
    ]
    let dnc = DistributedNotificationCenter.default()
    dnc.post(
        name: NSNotification.Name(rawValue: "com.googlecode.munki.managedsoftwareupdate.installrequest"),
        object: nil,
        userInfo: user_info
    )
}

enum SelfServiceError: Error {
    // General error class for SelfService exceptions
    case error(description: String)
}

struct SelfService {
    var _installs: Set<String> = []
    var _uninstalls: Set<String> = []
    var installs: [String] {
        return Array(_installs)
    }
    var uninstalls: [String] {
        return Array(_uninstalls)
    }

    init() {
        let selfServiceData = readSelfServiceManifest()
        _installs = Set(
            selfServiceData["managed_installs"] as? [String] ?? [String]())
        _uninstalls = Set(
            selfServiceData["managed_uninstalls"] as? [String] ?? [String]())
    }
    
    mutating func subscribe(_ item_name: String) -> Bool {
        _installs.insert(item_name)
        _uninstalls.remove(item_name)
        return save_self_service_choices()
    }
    
    mutating func unsubscribe(_ item_name: String) -> Bool {
        _installs.remove(item_name)
        _uninstalls.insert(item_name)
        return save_self_service_choices()
    }
    
    mutating func unmanage(_ item_name: String) -> Bool {
        _installs.remove(item_name)
        _uninstalls.remove(item_name)
        return save_self_service_choices()
    }
    
    func save_self_service_choices() -> Bool {
        var current_choices = PlistDict()
        current_choices["managed_installs"] = installs
        current_choices["managed_uninstalls"] = uninstalls
        return writeSelfServiceManifest(current_choices)
    }
}

extension SelfService: Equatable {
    static func == (lhs: SelfService, rhs: SelfService) -> Bool {
        return (lhs._installs == rhs._installs &&
                lhs._uninstalls == rhs._uninstalls)
    }
}

func subscribe(_ item: OptionalItem) -> Bool {
    // Add item to SelfServeManifest's managed_installs.
    // Also track user selections.
    if let item_name = item["name"] as? String {
        var self_service = SelfService()
        if self_service.subscribe(item_name) {
            user_install_selections.insert(item_name)
            post_install_request_notification("install", item)
            return true
        }
    }
    return false
}

func unsubscribe(_ item: OptionalItem) -> Bool {
    // Add item to SelfServeManifest's managed_uninstalls.
    // Also track user selections.
    if let item_name = item["name"] as? String {
        var self_service = SelfService()
        if self_service.unsubscribe(item_name) {
            user_removal_selections.insert(item_name)
            post_install_request_notification("remove", item)
            return true
        }
    }
    return false
}

func unmanage(_ item: OptionalItem) -> Bool {
    // Remove item from SelfServeManifest.
    // Also track user selections.
    if let item_name = item["name"] as? String {
        var self_service = SelfService()
        if self_service.unmanage(item_name) {
            user_install_selections.remove(item_name)
            user_removal_selections.remove(item_name)
            return true
        }
    }
    return false
}


