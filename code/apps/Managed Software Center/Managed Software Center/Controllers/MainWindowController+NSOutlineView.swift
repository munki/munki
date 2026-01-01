//
//  MainWindowController+NSOutlineView.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 6/28/25.
//  Copyright © 2025-2026 The Munki Project. All rights reserved.
//

import Cocoa

extension MainWindowController: NSOutlineViewDataSource {
    // Number of items in the sidebar
    func outlineView(_ outlineView: NSOutlineView, numberOfChildrenOfItem item: Any?) -> Int {
        return sidebar_items.count
    }
    
    // Items to be added to sidebar
    func outlineView(_ outlineView: NSOutlineView, child index: Int, ofItem item: Any?) -> Any {
        return sidebar_items[index]
    }
    
    // Whether rows are expandable by an arrow
    func outlineView(_ outlineView: NSOutlineView, isItemExpandable item: Any) -> Bool {
        return false
    }
    
    func outlineView(_ outlineView: NSOutlineView, rowViewForItem item: Any) -> NSTableRowView? {
        return MSCTableRowView(frame: NSZeroRect);
    }
    
    func outlineView(_ outlineView: NSOutlineView, didAdd rowView: NSTableRowView, forRow row: Int) {
        rowView.selectionHighlightStyle = .sourceList
    }
    
    func outlineViewSelectionDidChange(_ notification: Notification) {
        sidebarList.enumerateAvailableRowViews { rowView, row in
            if let cellView = rowView.view(atColumn: 0) as? MSCTableCellView {
                let isSelected = row == sidebarList.selectedRow
                cellView.title.textColor = isSelected ? .controlAccentColor : .labelColor
                cellView.imgView.contentTintColor = isSelected ? .controlAccentColor : .secondaryLabelColor
            }
        }
    }
}

extension MainWindowController: NSOutlineViewDelegate {
    
    func outlineView(_ outlineView: NSOutlineView, viewFor tableColumn: NSTableColumn?, item: Any) -> NSView? {
        guard let sidebarItem = item as? SidebarItem else { return nil }

        guard let view = outlineView.makeView(withIdentifier: NSUserInterfaceItemIdentifier(rawValue: "ItemCell"), owner: self) as? MSCTableCellView else {
            return nil
        }

        let isSelected = (sidebarList.row(forItem: item) == sidebarList.selectedRow)

        view.title.stringValue = sidebarItem.title.localized(withComment: "\(sidebarItem.title) label")
        view.title.textColor = isSelected ? .controlAccentColor : .labelColor

        if let image = NSImage(named: NSImage.Name(sidebarItem.icon)) {
            image.isTemplate = true
            view.imgView.image = image
            view.imgView.contentTintColor = isSelected ? .controlAccentColor : .secondaryLabelColor
        } else if #available(macOS 11.0, *) {
            if let image = NSImage(systemSymbolName: sidebarItem.icon, accessibilityDescription: nil) {
                image.isTemplate = true
                view.imgView.image = image
                view.imgView.contentTintColor = isSelected ? .controlAccentColor : .secondaryLabelColor
            } else {
                view.imgView.image = nil
            }
        } else {
            view.imgView.image = nil
        }

        return view
    }
}

extension NSImage {
    func tint(color: NSColor) -> NSImage {
        guard !self.isTemplate else { return self }
        
        let image = self.copy() as! NSImage
        image.lockFocus()
        
        color.set()
        
        let imageRect = NSRect(origin: NSZeroPoint, size: image.size)
        imageRect.fill(using: .sourceAtop)
        
        image.unlockFocus()
        image.isTemplate = true
        
        return image
    }
}

extension String {
    func localized(withComment comment: String? = nil) -> String {
        return NSLocalizedString(self, comment: comment ?? "")
    }
}

