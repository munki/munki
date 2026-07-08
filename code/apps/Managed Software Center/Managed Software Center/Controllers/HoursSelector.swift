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
            // Recreate accessibility children when labels change
            _accessibilityChildren = createAccessibilityChildren()
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
    private var firstClickedIndex: Int = -1
    private var lastTouchedIndex: Int = -1
    private var previouslySelectedIndices = Set<Int>()

    /// Currently focused cell index for keyboard navigation
    fileprivate var focusedIndex: Int = 0

    /// Store accessibility children
    private var _accessibilityChildren: [HourCellAccessibilityElement] = []

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
    private let defaultFontSize: CGFloat = NSFont.systemFontSize // 13
    private let smallFontSize: CGFloat = NSFont.smallSystemFontSize // 11
    private let dragSlopFactor: CGFloat = 8

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
        if selectedIndices.isEmpty, !cellLabels.isEmpty {
            selectedIndices.insert(0)
        }
        setupAccessibility()
    }

    private func setupAccessibility() {
        // Configure the main control
        setAccessibilityRole(.group)
        setAccessibilityLabel(NSLocalizedString("Hours", comment: "Accessibility label for hour selector"))
        setAccessibilityHelp(NSLocalizedString(
            "Use arrow keys to navigate hours, space to toggle selection",
            comment: "Accessibility help for hour selector"
        ))

        // Create accessibility children for each cell
        _accessibilityChildren = createAccessibilityChildren()
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

        // Draw focus ring for keyboard navigation
        if window?.firstResponder == self {
            drawFocusRing(cellWidth: cellWidth)
        }

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

    private func drawFocusRing(cellWidth: CGFloat) {
        guard focusedIndex >= 0, focusedIndex < cellLabels.count else { return }

        NSGraphicsContext.saveGraphicsState()
        NSFocusRingPlacement.only.set()

        let x = CGFloat(focusedIndex) * cellWidth
        let focusRect = NSRect(x: x + 2, y: 2, width: cellWidth - 4, height: bounds.height - 4)
        let focusPath = NSBezierPath(roundedRect: focusRect, xRadius: borderRadius - 1, yRadius: borderRadius - 1)
        focusPath.fill()

        NSGraphicsContext.restoreGraphicsState()
    }

    private func drawCellLabels(cellWidth: CGFloat) {
        let fontSize: CGFloat = (cellLabels.count > 12) ? smallFontSize : defaultFontSize
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
        if index == -1 { return }
        firstClickedIndex = index
        focusedIndex = index
        previouslySelectedIndices = selectedIndices

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
        guard isDragging, lastTouchedIndex != -1 else { return }
        guard !cellLabels.isEmpty else { return }

        let location = convert(event.locationInWindow, from: nil)
        let index = cellIndexFromPosition(location)

        if index == lastTouchedIndex || index == -1 { return }
        lastTouchedIndex = index
        focusedIndex = index

        if dragSelecting {
            if index >= firstClickedIndex {
                let newSelection = Set(firstClickedIndex ... index)
                selectedIndices = previouslySelectedIndices.union(newSelection)
            } else {
                let newSelection = Set(index ... firstClickedIndex)
                selectedIndices = previouslySelectedIndices.union(newSelection)
            }
        } else { // deselecting
            var deselectedRange = Set<Int>()
            if index >= firstClickedIndex {
                deselectedRange = Set(firstClickedIndex ... index)
            } else {
                deselectedRange = Set(index ... firstClickedIndex)
            }
            let newSelection = previouslySelectedIndices.subtracting(deselectedRange)
            if newSelection.count >= minimumSelection {
                selectedIndices = newSelection
            }
        }
    }

    override func mouseUp(with _: NSEvent) {
        guard isEnabled else { return }

        isDragging = false
        lastTouchedIndex = -1
        firstClickedIndex = -1
    }

    // MARK: - Helper Methods

    /// Returns the cell index based on the position of the mouse pointer
    private func cellIndexFromPosition(_ point: NSPoint) -> Int {
        let x = point.x
        let y = point.y
        // did they drag vertically outside of the control?
        if y < -dragSlopFactor || y > bounds.height + dragSlopFactor { return -1 }
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
        selectedIndices = Set(0 ..< cellLabels.count)
    }

    /// Clear selection (will maintain minimum selection)
    func clearSelection() {
        selectedIndices = Set([0])
    }

    // MARK: - Keyboard Navigation

    override var acceptsFirstResponder: Bool {
        return isEnabled
    }

    override func becomeFirstResponder() -> Bool {
        needsDisplay = true
        return super.becomeFirstResponder()
    }

    override func resignFirstResponder() -> Bool {
        needsDisplay = true
        return super.resignFirstResponder()
    }

    override func keyDown(with event: NSEvent) {
        guard isEnabled else {
            super.keyDown(with: event)
            return
        }

        switch event.keyCode {
        case 123: // Left arrow
            moveFocus(by: -1)
        case 124: // Right arrow
            moveFocus(by: 1)
        case 49: // Space
            toggleFocusedCell()
        case 36, 76: // Return or Enter
            // Activate the control (send action)
            sendAction(action, to: target)
        default:
            super.keyDown(with: event)
        }
    }

    private func moveFocus(by delta: Int) {
        guard !cellLabels.isEmpty else { return }

        let newIndex = focusedIndex + delta
        if newIndex >= 0, newIndex < cellLabels.count {
            focusedIndex = newIndex
            needsDisplay = true

            // Announce the focused cell to VoiceOver
            if focusedIndex < _accessibilityChildren.count {
                let child = _accessibilityChildren[focusedIndex]

                // Post focused element changed - VoiceOver will read the element's label
                NSAccessibility.post(element: child, notification: .focusedUIElementChanged)
            }
        }
    }

    private func toggleFocusedCell() {
        guard !cellLabels.isEmpty else { return }
        if selectedIndices.contains(focusedIndex) {
            // Try to deselect
            if selectedIndices.count > minimumSelection {
                selectedIndices.remove(focusedIndex)
                notifySelectionChange(index: focusedIndex, selected: false)
            }
        } else {
            // Select
            if allowsMultipleSelection {
                selectedIndices.insert(focusedIndex)
            } else {
                selectedIndices = [focusedIndex]
            }
            notifySelectionChange(index: focusedIndex, selected: true)
        }
    }

    fileprivate func notifySelectionChange(index _: Int, selected _: Bool) {
        // Post selected children changed notification
        NSAccessibility.post(element: self, notification: .selectedChildrenChanged)
    }

    // MARK: - Accessibility Support

    override func isAccessibilityElement() -> Bool {
        return true
    }

    override func accessibilityRole() -> NSAccessibility.Role? {
        return .group
    }

    override func accessibilityLabel() -> String? {
        return NSLocalizedString("Hours", comment: "Accessibility label for hour selector")
    }

    override func accessibilityValue() -> Any? {
        let selectedLabels = selectedIndices.sorted().map { cellLabels[$0] }
        return selectedLabels.joined(separator: ", ")
    }

    private func createAccessibilityChildren() -> [HourCellAccessibilityElement] {
        return cellLabels.enumerated().map { index, label in
            let element = HourCellAccessibilityElement(index: index, parent: self)
            element.setAccessibilityLabel(label)
            return element
        }
    }

    override func accessibilityChildren() -> [Any]? {
        return _accessibilityChildren
    }

    override func accessibilitySelectedChildren() -> [Any]? {
        return _accessibilityChildren.filter { selectedIndices.contains($0.index) }
    }

    override func accessibilityPerformPress() -> Bool {
        // Toggle the focused cell
        if isEnabled {
            toggleFocusedCell()
            return true
        }
        return false
    }
}

// MARK: - HourCellAccessibilityElement

/// Accessibility element representing a single hour cell
class HourCellAccessibilityElement: NSAccessibilityElement {
    let index: Int
    weak var parent: HoursSelector?
    private var isSelected: Bool {
        parent?.selectedIndices.contains(index) ?? false
    }

    init(index: Int, parent: HoursSelector) {
        self.index = index
        self.parent = parent
        super.init()
        setAccessibilityRole(.button)
        setAccessibilityParent(parent)
    }

    override func accessibilityLabel() -> String? {
        guard let parent, index < parent.cellLabels.count else { return nil }
        return parent.cellLabels[index]
    }

    override func accessibilityValue() -> Any? {
        return isSelected ? 1 : 0
    }

    override func isAccessibilitySelected() -> Bool {
        return isSelected
    }

    override func accessibilityFrame() -> NSRect {
        guard let parent, let window = parent.window else { return .zero }
        let cellWidth = parent.bounds.width / CGFloat(parent.cellLabels.count)
        let cellRect = NSRect(x: CGFloat(index) * cellWidth, y: 0, width: cellWidth, height: parent.bounds.height)
        let frameInWindow = parent.convert(cellRect, to: nil)
        let frameInScreen = window.convertToScreen(frameInWindow)
        return frameInScreen
    }

    override func isAccessibilityElement() -> Bool {
        return true
    }

    override func isAccessibilityEnabled() -> Bool {
        return parent?.isEnabled ?? false
    }

    override func isAccessibilityFocused() -> Bool {
        guard let parent else { return false }
        return parent.focusedIndex == index && parent.window?.firstResponder == parent
    }

    override func accessibilityHelp() -> String? {
        return NSLocalizedString("Press to toggle hour selection", comment: "Accessibility help for hour cell")
    }
}
