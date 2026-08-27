//
//  MainWindowController+Toolbar.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 6/25/25.
//  Copyright © 2025-2026 The Munki Project. All rights reserved.
//

import Cocoa

private extension NSToolbarItem.Identifier {
    static let progressIndicatorItem: NSToolbarItem.Identifier = NSToolbarItem.Identifier("ProgressIndicatorItem")
    static let navigationGoBackItem: NSToolbarItem.Identifier = NSToolbarItem.Identifier("NavigationGoBackItem")
}

extension MainWindowController: NSToolbarDelegate {
    
    // MARK: NSToolbarDelegate functions
    
    func toolbarDefaultItemIdentifiers(_ toolbar: NSToolbar) -> [NSToolbarItem.Identifier] {
        if #available(macOS 11.0, *) {
            return [
                .flexibleSpace,
                .progressIndicatorItem,
                .sidebarTrackingSeparator,
                .navigationGoBackItem,
                .flexibleSpace,
            ]
        } else {
            // Fallback on earlier versions
            return [
                .progressIndicatorItem,
                .navigationGoBackItem
            ]
        }
    }
    
    func toolbarAllowedItemIdentifiers(_ toolbar: NSToolbar) -> [NSToolbarItem.Identifier] {
        return [
            .progressIndicatorItem,
            .navigationGoBackItem,
            .flexibleSpace,
            .space,
        ]
    }
    
    func toolbar(_ toolbar: NSToolbar, itemForItemIdentifier itemIdentifier: NSToolbarItem.Identifier, willBeInsertedIntoToolbar flag: Bool) -> NSToolbarItem? {
        switch itemIdentifier {
        case .progressIndicatorItem:
            if pageLoadProgress == nil {
                pageLoadProgress = NSProgressIndicator()
                pageLoadProgress!.isIndeterminate = true
                pageLoadProgress!.style = .spinning
                pageLoadProgress!.controlSize = .small
                pageLoadProgress!.isDisplayedWhenStopped = false
            }
            let progressSpinner = customToolbarItem(
                itemForItemIdentifier: NSToolbarItem.Identifier.progressIndicatorItem.rawValue,
                label: "Progress",
                paletteLabel: "Progress",
                toolTip: "Shows page load progress",
                itemContent: pageLoadProgress!
            )
            progressSpinner?.isBordered = false
            return progressSpinner
        case .navigationGoBackItem:
            let toolbarItem = customToolbarItem(
                itemForItemIdentifier: NSToolbarItem.Identifier.navigationGoBackItem.rawValue,
                label: "Go back",
                paletteLabel: "Go back",
                toolTip: "Navigates to previous page",
                itemContent: NSImage(named: "NSGoBackTemplate")!
            )
            toolbarItem?.isBordered = true
            toolbarItem?.isEnabled = true
            toolbarItem?.action = #selector(self.navigateBackBtnClicked)
            if #available(macOS 15.0, *) {
                // this item is never available when the app is first launched,
                // so let's start with it hidden
                toolbarItem?.isHidden = true
            }
            navigateBackButton = toolbarItem
            return toolbarItem
        default:
            return NSToolbarItem(itemIdentifier: itemIdentifier)
        }
    }
    
    // MARK: utility functions
    
    func customToolbarItem(
        itemForItemIdentifier itemIdentifier: String,
        label: String,
        paletteLabel: String,
        toolTip: String,
        itemContent: AnyObject) -> NSToolbarItem? {
        
        let toolbarItem = NSToolbarItem(itemIdentifier: NSToolbarItem.Identifier(rawValue: itemIdentifier))
        
        toolbarItem.label = label
        toolbarItem.paletteLabel = paletteLabel
        toolbarItem.toolTip = toolTip
        toolbarItem.target = self
        
        // Set the right attribute, depending on if we were given an image or a view.
        if itemContent is NSImage {
            if let image = itemContent as? NSImage {
                toolbarItem.image = image
            }
        } else if itemContent is NSView {
            if let view = itemContent as? NSView {
                toolbarItem.view = view
            }
        } else {
            assertionFailure("Invalid itemContent: object")
        }
        
        // We actually need an NSMenuItem here, so we construct one.
        let menuItem: NSMenuItem = NSMenuItem()
        menuItem.submenu = nil
        menuItem.title = label
        toolbarItem.menuFormRepresentation = menuItem
        
        return toolbarItem
    }
    
    func hideNavigationToolbarItem() {
        if #available(macOS 15.0, *) {
            navigateBackButton?.isHidden = true
        } else {
            // Fallback on earlier versions
            for (index, item) in toolbar.items.enumerated() {
                if item.itemIdentifier == .navigationGoBackItem {
                    toolbar.removeItem(at: index)
                    break
                }
            }
        }
    }
    
    func showNavigationToolbarItem() {
        if #available(macOS 15.0, *) {
            navigateBackButton?.isHidden = false
        } else {
            // Fallback on earlier versions
            var itemFound = false
            for item in toolbar.items {
                if item.itemIdentifier == .navigationGoBackItem {
                    itemFound = true
                    break
                }
            }
            if !itemFound {
                if #available(macOS 11.0, *) {
                    toolbar.insertItem(withItemIdentifier: .navigationGoBackItem, at: 3)
                } else {
                    toolbar.insertItem(withItemIdentifier: .navigationGoBackItem, at: 1)
                }
            }
        }
    }
}
