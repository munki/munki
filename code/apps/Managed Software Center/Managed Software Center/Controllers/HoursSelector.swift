//
//  HoursSelector.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 6/5/26.
//  Copyright © 2026 The Munki Project. All rights reserved.
//

import Cocoa

class HoursSelector: NSControl {
    // MARK: - Properties

    /// The text labels to display in cells
    var cellLabels: [String] = [] {
        didSet {
            if selectedIndices.isEmpty {
                selectedIndices = Set([0])
            }
            needsDisplay = true
        }
    }

    /// Set of selected cell indices
    var selectedIndices = Set<Int>() {
        didSet {
            needsDisplay = true
            sendAction(action, to: target)
        }
    }

    /// Minimum number of cells that must be selected (default: 1)
    var minimumSelection = 1

    /// Allow multiple selection (default: true)
    var allowsMultipleSelection = true

    private var isDragging = false
    private var dragSelecting = false
    private var lastTouchedIndex: Int?

    // Colors
    private var gridColor: NSColor {
        return isEnabled ? NSColor.gridColor : NSColor.disabledControlTextColor.withAlphaComponent(0.3)
    }

    private var selectedColor: NSColor {
        return isEnabled ? NSColor.controlAccentColor : NSColor.disabledControlTextColor
    }

    private var backgroundColor: NSColor {
        return NSColor.controlBackgroundColor
    }

    private var labelColor: NSColor {
        return isEnabled ? NSColor.controlTextColor : NSColor.disabledControlTextColor
    }

    private var selectedLabelColor: NSColor {
        return isEnabled ? NSColor.alternateSelectedControlTextColor : NSColor.disabledControlTextColor
    }

    // Other UI constants
    private let borderRadius: CGFloat = 6
    private let defaultFontSize: CGFloat = 13

    // MARK: - Initialization

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        setup()
    }

    required init?(coder: NSCoder) {
        super.init(coder: coder)
        setup()
    }

    private func setup() {
        wantsLayer = true
        // Default to first cell selected if none specified
        if selectedIndices.isEmpty && !cellLabels.isEmpty {
            selectedIndices.insert(0)
        }
    }

    // Provide intrinsic content size
    override var intrinsicContentSize: NSSize {
        return NSSize(width: NSView.noIntrinsicMetric, height: NSView.noIntrinsicMetric)
    }

    // MARK: - Drawing

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)

        guard !cellLabels.isEmpty else { return }

        // Draw background
        backgroundColor.setFill()
        bounds.fill()

        gridColor.setStroke()

        // Draw border
        let borderRect = NSRect(x: 0, y: 0, width: bounds.width, height: bounds.height)
        let border = NSBezierPath(roundedRect: borderRect, xRadius: borderRadius, yRadius: borderRadius)
        border.lineWidth = 0.75
        border.stroke()

        // Draw vertical lines between cells
        let cellWidth = bounds.width / CGFloat(cellLabels.count)
        for index in 1 ..< cellLabels.count {
            let x = CGFloat(index) * cellWidth
            let path = NSBezierPath()
            path.lineWidth = 0.75
            path.move(to: NSPoint(x: x, y: 0))
            path.line(to: NSPoint(x: x, y: bounds.height))
            path.stroke()
        }

        // Draw selected cells
        drawSelectedCells(cellWidth: cellWidth)

        // Draw cell labels
        drawCellLabels(cellWidth: cellWidth)
    }

    private func drawSelectedCells(cellWidth: CGFloat) {
        selectedColor.setFill()

        // Group consecutive selections for smoother appearance
        var index = 0
        while index < cellLabels.count {
            if selectedIndices.contains(index) {
                let startIndex = index
                var endIndex = index
                while endIndex + 1 < cellLabels.count, selectedIndices.contains(endIndex + 1) {
                    endIndex += 1
                }
                let selectionCount = CGFloat(endIndex - startIndex + 1)
                let x = CGFloat(startIndex) * cellWidth
                let rect = NSRect(x: x + 1, y: 1, width: cellWidth * selectionCount - 2, height: bounds.height - 2)
                let roundRect = NSBezierPath(roundedRect: rect, xRadius: borderRadius, yRadius: borderRadius)
                roundRect.fill()
                index = endIndex + 1
            } else {
                index += 1
            }
        }
    }

    private func drawCellLabels(cellWidth: CGFloat) {
        let fontSize = defaultFontSize
        let font = NSFont.systemFont(ofSize: fontSize)
        var attributes: [NSAttributedString.Key: Any] = [
            .font: font,
        ]

        for (index, label) in cellLabels.enumerated() {
            // Set text color based on selection state
            if selectedIndices.contains(index) {
                attributes[.foregroundColor] = selectedLabelColor
            } else {
                attributes[.foregroundColor] = labelColor
            }

            // Calculate label size and center it vertically, and left-justify
            let labelSize = (label as NSString).size(withAttributes: attributes)
            let cellRect = NSRect(x: CGFloat(index) * cellWidth, y: 0, width: cellWidth, height: bounds.height)
            let x = cellRect.minX + borderRadius - 1
            let y = cellRect.midY - labelSize.height / 2

            label.draw(at: NSPoint(x: x, y: y), withAttributes: attributes)
        }
    }

    // MARK: - Mouse Handling

    override func mouseDown(with event: NSEvent) {
        guard isEnabled else { return }
        guard !cellLabels.isEmpty else { return }

        let location = convert(event.locationInWindow, from: nil)
        let index = cellIndexFromPosition(location)

        if allowsMultipleSelection {
            // Toggle selection
            dragSelecting = !selectedIndices.contains(index)
            if dragSelecting {
                selectedIndices.insert(index)
                isDragging = true
                lastTouchedIndex = index
            } else if selectedIndices.count > minimumSelection {
                // Only deselect if we have more than minimum selected
                selectedIndices.remove(index)
                isDragging = true
                lastTouchedIndex = index
            }
        } else {
            // Single selection mode
            if !selectedIndices.contains(index) {
                selectedIndices.removeAll()
                selectedIndices.insert(index)
            }
        }
    }

    override func mouseDragged(with event: NSEvent) {
        guard isEnabled else { return }
        guard allowsMultipleSelection else { return }
        guard isDragging, let previousIndex = lastTouchedIndex else { return }
        guard !cellLabels.isEmpty else { return }

        let location = convert(event.locationInWindow, from: nil)
        let index = cellIndexFromPosition(location)

        if index == previousIndex || index == -1 { return }
        lastTouchedIndex = index

        if dragSelecting {
            selectedIndices.insert(index)
        } else if selectedIndices.count > minimumSelection {
            selectedIndices.remove(index)
        }
    }

    override func mouseUp(with _: NSEvent) {
        guard isEnabled else { return }

        isDragging = false
        lastTouchedIndex = nil
    }

    // MARK: - Helper Methods

    /// Returns the cell index based on the position of the mouse pointer
    private func cellIndexFromPosition(_ point: NSPoint) -> Int {
        let x = point.x
        let y = point.y
        // did they drag vertically outside of the control?
        if y < 0 || y > bounds.height { return -1 }
        guard !cellLabels.isEmpty else { return 0 }
        let cellWidth = bounds.width / CGFloat(cellLabels.count)
        let index = Int(x / cellWidth)
        return min(max(index, 0), cellLabels.count - 1)
    }

    // MARK: - Public API

    /// Returns an array of selected indices (sorted)
    func selectedIndicesList() -> [Int] {
        return selectedIndices.sorted()
    }

    /// Set the selected indices
    func setSelectedIndices(_ indices: Set<Int>) {
        let validIndices = indices.filter { $0 >= 0 && $0 < cellLabels.count }
        if validIndices.isEmpty {
            // Ensure at least minimum selection
            selectedIndices = Set([0])
        } else {
            selectedIndices = validIndices
        }
    }

    /// Select all cells
    func selectAll() {
        selectedIndices = Set(0..<cellLabels.count)
    }

    /// Clear selection (will maintain minimum selection)
    func clearSelection() {
        selectedIndices = Set([0])
    }
}
