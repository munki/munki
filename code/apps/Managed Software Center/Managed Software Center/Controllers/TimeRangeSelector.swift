//
//  TimeRangeSelector.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 5/6/26.
//  Copyright © 2026 The Munki Project. All rights reserved.
//

import Cocoa

class TimeRangeSelectorView: NSView {
    // MARK: - Properties

    var selectedHours = Array(repeating: false, count: 24) {
        didSet {
            needsDisplay = true
            onTimeSelectionChanged?()
        }
    }

    private var allowedHoursStart = -1
    private var allowedHoursEnd = -1

    var onTimeSelectionChanged: (() -> Void)?

    private var isDragging = false
    private var dragSelecting = false
    private var lastTouchedHour: Int?

    private var hours = [Int]()

    // Colors
    private let gridColor = NSColor.gridColor
    private let selectedColor = NSColor.selectedControlColor
    private let backgroundColor = NSColor.controlBackgroundColor

    // Other UI constants
    private let borderRadius: CGFloat = 6

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
        if allowedHoursStart == -1 || allowedHoursEnd == -1 {
            // default setup
            setAllowedHours(start: 8, end: 18)
        }
    }

    // Provide intrinsic content size
    override var intrinsicContentSize: NSSize {
        return NSSize(width: NSView.noIntrinsicMetric, height: NSView.noIntrinsicMetric)
    }

    // MARK: - Drawing

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)

        // Draw background
        backgroundColor.setFill()
        bounds.fill()

        gridColor.setStroke()

        // draw border
        let borderRect = NSRect(x: 0, y: 0, width: bounds.width, height: bounds.height)
        let border = NSBezierPath(roundedRect: borderRect, xRadius: borderRadius, yRadius: borderRadius)
        border.lineWidth = 0.75
        border.stroke()

        // Draw vertical lines between hours
        let hourWidth = bounds.width / CGFloat(hours.count)
        for index in 1 ..< hours.count {
            let x = CGFloat(index) * hourWidth
            let path = NSBezierPath()
            path.lineWidth = 0.75
            path.move(to: NSPoint(x: x, y: 0))
            path.line(to: NSPoint(x: x, y: bounds.height))
            path.stroke()
        }

        // Draw selected hours
        drawSelectedHours(hourWidth: hourWidth)

        // Draw hour labels
        drawHourLabels(hourWidth: hourWidth)
    }

    private func drawSelectedHours(hourWidth: CGFloat) {
        selectedColor.setFill()

        var hourIndex = 0
        while hourIndex < hours.count {
            if selectedHours[hours[hourIndex]] {
                let startIndex = hourIndex
                var endIndex = hourIndex
                while endIndex + 1 < hours.count, selectedHours[hours[endIndex + 1]] {
                    endIndex += 1
                }
                let selectionCount = CGFloat(endIndex - startIndex + 1)
                let x = CGFloat(startIndex) * hourWidth
                let rect = NSRect(x: x + 1, y: 1, width: hourWidth * selectionCount - 2, height: bounds.height - 2)
                let roundRect = NSBezierPath(roundedRect: rect, xRadius: borderRadius, yRadius: borderRadius)
                roundRect.fill()
                hourIndex = endIndex + 1
            } else {
                hourIndex = hourIndex + 1
            }
        }
    }

    private func drawHourLabels(hourWidth: CGFloat) {
        let fontSize: CGFloat = (hours.count > 12) ? 11 : 13
        let attributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: fontSize),
            .foregroundColor: NSColor.labelColor,
        ]

        for (index, hour) in hours.enumerated() {
            let hourString = labelHour(hour)
            let x = CGFloat(index) * hourWidth + borderRadius - 1
            let y = bounds.height / 2 - fontSize / 2 - 1
            hourString.draw(at: NSPoint(x: x, y: y), withAttributes: attributes)
        }
    }

    // MARK: - Mouse Handling

    override func mouseDown(with event: NSEvent) {
        let location = convert(event.locationInWindow, from: nil)
        let hour = hourFromPosition(location.x)
        if hour >= selectedHours.count { return }
        dragSelecting = !selectedHours[hour]
        if dragSelecting {
            selectedHours[hour] = true
            isDragging = true
            lastTouchedHour = hour
        } else if selectedHours.filter({ $0 }).count > 1 {
            // must have at least one selected hour;
            // disallow deselecting all hours
            selectedHours[hour] = false
            isDragging = true
            lastTouchedHour = hour
        }
    }

    override func mouseDragged(with event: NSEvent) {
        guard isDragging, let previousHour = lastTouchedHour else { return }

        let location = convert(event.locationInWindow, from: nil)
        let hour = hourFromPosition(location.x)
        if hour >= selectedHours.count { return }
        if hour == previousHour { return }
        lastTouchedHour = hour
        if dragSelecting {
            selectedHours[hour] = true
        } else if selectedHours.filter({ $0 }).count > 1 {
            selectedHours[hour] = false
        }
    }

    override func mouseUp(with _: NSEvent) {
        isDragging = false
        lastTouchedHour = nil
    }

    // MARK: - Helper Methods

    // return the hour based on the position of the mouse pointer
    private func hourFromPosition(_ x: CGFloat) -> Int {
        let hourWidth = bounds.width / CGFloat(hours.count)
        let hourIndex = Int(x / hourWidth)
        let constrainedHourIndex = min(max(hourIndex, 0), hours.count - 1)
        return hours[constrainedHourIndex]
    }

    /// Attempt to detect if user wants time in 24 hour format
    private func is24hourTime() -> Bool {
        let formatter = DateFormatter()
        formatter.locale = Locale.current
        formatter.setLocalizedDateFormatFromTemplate("j")
        return formatter.dateFormat?.contains("a") == false
    }

    /// Returns a compact string for hour labels in our time range selector.
    /// May not strictly adhere to local conventions for displaying the time
    /// For 12-hour time formats, adds a am/pm label for 12 and for the first
    /// displayed hour
    private func labelHour(_ hour: Int) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale.current
        let using24hTime = is24hourTime()
        if using24hTime {
            formatter.dateFormat = "HH"
        } else {
            formatter.dateFormat = "h"
        }

        var components = DateComponents()
        components.hour = hour
        components.minute = 0

        let calendar = Calendar.current
        guard let date = calendar.date(from: components) else {
            return "\(hour)"
        }
        var formattedStr = formatter.string(from: date)
        if !using24hTime {
            // append an 'a' for AM and a 'p' for PM to "12"
            if hour == 0 || (hour < 12 && hour == allowedHoursStart) {
                formattedStr += "a"
            }
            if hour == 12 || (hour > 12 && hour == allowedHoursStart) {
                formattedStr += "p"
            }
        }
        return formattedStr
    }

    /// Public function to return a list of selected hours
    func selectedHoursList() -> [Int] {
        var hourList = [Int]()
        for (hour, selected) in selectedHours.enumerated() {
            if selected {
                hourList.append(hour)
            }
        }
        return hourList
    }

    /// is the given hour within the start and end range (handles ranges that cross midnight)
    private func hourWithinRange(_ hour: Int, start: Int, end: Int) -> Bool {
        if start < end {
            return hour >= start && hour < end
        }
        return hour >= start || hour < end
    }

    /// Public function to set the selected hours
    func setSelectedHours(_ hours: [Int]) {
        selectedHours = Array(repeating: false, count: 24)
        let validHours = hours.filter {
            hourWithinRange($0, start: allowedHoursStart, end: allowedHoursEnd)
        }
        if !validHours.isEmpty {
            for hour in validHours {
                selectedHours[hour] = true
            }
        } else {
            // if there are no hours within the allowed range, then
            // select all hours within the allowed range
            // (we must not have no selected hours within the allowed range)
            for hour in 0 ..< selectedHours.count {
                selectedHours[hour] = hourWithinRange(
                    hour, start: allowedHoursStart, end: allowedHoursEnd
                )
            }
        }
    }

    /// Public function to set the allowed hour range
    func setAllowedHours(start: Int, end: Int) {
        // make sure start is in valid range (0-23)
        // reset to 0 if invalid
        if start < 0 || start > 23 {
            allowedHoursStart = 0
        } else {
            allowedHoursStart = start
        }
        // make sure end is in valid range (0-24)
        // reset to 24 if invalid
        if end < 0 || end > 24 {
            allowedHoursEnd = 24
        } else {
            allowedHoursEnd = end
        }
        // if start and end are the same then all 24 hours are valid
        if allowedHoursStart == allowedHoursEnd {
            allowedHoursStart = 0
            allowedHoursEnd = 24
        }
        if allowedHoursStart < allowedHoursEnd {
            // "normal" range
            hours = Array(allowedHoursStart ..< allowedHoursEnd)
        } else {
            // range crosses midnight
            hours = Array(allowedHoursStart ... 23)
            hours = hours + Array(0 ..< allowedHoursEnd)
        }
        needsDisplay = true
    }
}
