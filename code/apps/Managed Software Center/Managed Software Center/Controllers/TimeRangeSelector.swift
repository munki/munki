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

    private var allowedHoursStart = 8
    private var allowedHoursEnd = 18

    var onTimeSelectionChanged: (() -> Void)?

    private var isDragging = false
    private var dragSelecting = false
    private var lastTouchedHour: Int?

    private var hours = [Int]()

    // Colors
    private let gridColor = NSColor.gray.withAlphaComponent(0.3)
    private let selectedColor = NSColor.systemBlue.withAlphaComponent(0.3)
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
        if allowedHoursStart < allowedHoursEnd {
            hours  = Array(allowedHoursStart..<allowedHoursEnd)
        } else {
            hours = Array(allowedHoursStart...23)
            hours = hours + Array(0..<allowedHoursEnd)
        }
    }

    func setAllowedHours(start: Int, end: Int) {
        allowedHoursStart = start
        allowedHoursEnd = end
        if allowedHoursStart < allowedHoursEnd {
            hours  = Array(allowedHoursStart..<allowedHoursEnd)
        } else {
            hours = Array(allowedHoursStart...23)
            hours = hours + Array(0..<allowedHoursEnd)
        }
        needsDisplay = true
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
        for hour in 1...hours.count - 1 {
            let x = CGFloat(hour) * hourWidth
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
            .foregroundColor: NSColor.labelColor
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
        dragSelecting = !selectedHours[hour]
        if dragSelecting {
            selectedHours[hour] = true
            isDragging = true
            lastTouchedHour = hour
        } else if selectedHours.filter({ $0 }).count > 1 {
            selectedHours[hour] = false
            isDragging = true
            lastTouchedHour = hour
        }
    }

    override func mouseDragged(with event: NSEvent) {
        //guard isDragging, let dragStart = dragStartTime else { return }
        guard isDragging, let previousHour = lastTouchedHour else { return }

        let location = convert(event.locationInWindow, from: nil)
        let hour = hourFromPosition(location.x)
        if hour == previousHour { return }
        lastTouchedHour = hour
        if dragSelecting {
            selectedHours[hour] = true
        } else if selectedHours.filter({ $0 }).count > 1 {
            selectedHours[hour] = false
        }
    }

    override func mouseUp(with event: NSEvent) {
        isDragging = false
        lastTouchedHour = nil
    }

    // MARK: - Helper Methods

    private func indexForHour(_ hour: Int) -> Int {
        return hours.firstIndex(where: { $0 == hour }) ?? -1
    }

    // return the hour from the position of the mouse pointer
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
            if hour == 0 || hour == 24 || (hour < 12 && hour == allowedHoursStart) {
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

    /// Public function to set the selected hours
    func setSelectedHours(_ hours: [Int]) {
        selectedHours = Array(repeating: false, count: 24)
        for hour in hours {
            selectedHours[hour] = true
        }
    }
}

