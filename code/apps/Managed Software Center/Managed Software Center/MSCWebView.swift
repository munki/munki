//
//  MSCWebView.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 9/9/18.
//  Copyright © 2018-2019 The Munki Project. All rights reserved.
//

import WebKit

class MSCWebView: WKWebView {
    //Subclass of WKWebView that exists solely to customize the contextual menus.
    
    override func willOpenMenu(_ menu: NSMenu, with event: NSEvent) {
        let removedIds = [
            "WKMenuItemIdentifierOpenLinkInNewWindow",
            "WKMenuItemIdentifierDownloadLinkedFile",
            "WKMenuItemIdentifierOpenImageInNewWindow",
            "WKMenuItemIdentifierDownloadImage",
        ]
        for menuItem in menu.items {
            //print(menuItem.identifier?.rawValue ?? "")
            if let menuItemId = menuItem.identifier?.rawValue {
                if removedIds.contains(menuItemId) {
                    menuItem.isHidden = true
                }
            }
        }
    }

}
