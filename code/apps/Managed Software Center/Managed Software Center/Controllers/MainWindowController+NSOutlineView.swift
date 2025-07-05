//
//  MainWindowController+NSOutlineView.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 6/28/25.
//  Copyright © 2025 The Munki Project. All rights reserved.
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
        rowView.selectionHighlightStyle = .regular
    }
}

extension MainWindowController: NSOutlineViewDelegate {
    
    func outlineView(_ outlineView: NSOutlineView, viewFor tableColumn: NSTableColumn?, item: Any) -> NSView? {
        var view: MSCTableCellView?
        let itemDict = item as? [String: String]
        if let title = itemDict?["title"], let icon = itemDict?["icon"] {
            view = outlineView.makeView(withIdentifier: NSUserInterfaceItemIdentifier(rawValue: "ItemCell"), owner: self) as? MSCTableCellView
            if let textField = view?.title {
                textField.stringValue = title.localized(withComment: "\(title) label")
            }
            if let imageView = view?.imgView {
                imageView.image = NSImage(named: NSImage.Name(icon))?.tint(color: .secondaryLabelColor)
            }
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
        image.isTemplate = false
        
        return image
    }
}

extension String {
    func localized(withComment comment: String? = nil) -> String {
        return NSLocalizedString(self, comment: comment ?? "")
    }
}

