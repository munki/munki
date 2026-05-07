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

    var startTime: Int = 9 {
        didSet {
            needsDisplay = true
            onTimeSelectionChanged?()
        }
    }

    var endTime: Int = 17 {
        didSet {
            needsDisplay = true
            onTimeSelectionChanged?()
        }
    }

    var okHours = [Int]()

    var allowedHoursStart = 8
    var allowedHoursEnd = 18

    var onTimeSelectionChanged: (() -> Void)?

    private var isDragging = false
    private var dragStartTime: Int?

    private var hours = [Int]()

    // Colors
    private let gridColor = NSColor.gray.withAlphaComponent(0.3)
    private let selectedColor = NSColor.systemBlue.withAlphaComponent(0.3)
    private let backgroundColor = NSColor.controlBackgroundColor

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
            hours = hours + Array(0...allowedHoursEnd)
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
        let border = NSBezierPath(roundedRect: borderRect, xRadius: 4, yRadius: 4)
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

        // Draw selected range
        drawSelectedRange(hourWidth: hourWidth)

        // Draw hour labels
        drawHourLabels(hourWidth: hourWidth)
    }

    private func indexForHour(_ hour: Int) -> Int {
        return hours.firstIndex(where: { $0 == hour }) ?? -1
    }

    private func drawSelectedRange(hourWidth: CGFloat) {
        selectedColor.setFill()

        if endTime >= startTime {
            // Normal range (doesn't cross midnight)
            let x = CGFloat(indexForHour(startTime)) * hourWidth
            let width = CGFloat(endTime - startTime) * hourWidth
            let rect = NSRect(x: x, y: 0, width: width, height: bounds.height)
            rect.fill()
        } else {
            // Range crosses midnight - draw two rectangles
            // From start to end of day
            let rect1 = NSRect(x: CGFloat(indexForHour(startTime)) * hourWidth,
                               y: 0,
                               width: CGFloat(hours.count + 1 - startTime) * hourWidth,
                               height: bounds.height)
            rect1.fill()

            // From start of day to end time
            let rect2 = NSRect(x: 0,
                               y: 0,
                               width: CGFloat(indexForHour(startTime)) * hourWidth,
                               height: bounds.height)
            rect2.fill()
        }
    }

    private func drawHourLabels(hourWidth: CGFloat) {
        let fontSize: CGFloat = 11
        let attributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: fontSize),
            .foregroundColor: NSColor.labelColor
        ]

        var hourIndex = 0
        for hour in hours {
            let hourString = labelHour(hour)
            let x = CGFloat(hourIndex) * hourWidth + 2
            let y = bounds.height / 2 - fontSize / 2 - 1
            hourString.draw(at: NSPoint(x: x, y: y), withAttributes: attributes)
            hourIndex += 1
        }
    }

    // MARK: - Mouse Handling

    override func mouseDown(with event: NSEvent) {
        let location = convert(event.locationInWindow, from: nil)
        let hour = hourFromPosition(location.x)

        isDragging = true
        dragStartTime = hour
        startTime = hour
        endTime = hour + 1
    }

    override func mouseDragged(with event: NSEvent) {
        guard isDragging, let dragStart = dragStartTime else { return }

        let location = convert(event.locationInWindow, from: nil)
        let hour = hourFromPosition(location.x)

        if hour >= dragStart {
            startTime = dragStart
            endTime = hour + 1
        } else {
            startTime = hour
            endTime = dragStart + 1
        }
    }

    override func mouseUp(with event: NSEvent) {
        isDragging = false
        dragStartTime = nil
    }

    // MARK: - Helper Methods

    private func hourInAllowedRange(_ hour: Int) -> Bool {
        if allowedHoursEnd > allowedHoursStart {
            // Normal case: range doesn't cross midnight
            // Example: 08:00 to 17:00
            return hour >= allowedHoursStart && hour < allowedHoursEnd
        } else {
            // Range crosses midnight
            // Example: 20:00 to 03:00
            return hour >= allowedHoursStart || hour < allowedHoursEnd
        }
    }

    private func hourFromPosition(_ x: CGFloat) -> Int {
        let hourWidth = bounds.width / CGFloat(hours.count)
        let hourIndex = Int(x / hourWidth)
        let constrainedHourIndex = min(max(hourIndex, 0), hours.count - 1)
        return hours[constrainedHourIndex]
    }

    /// Attempt to detect if user wants time in 24 hour format
    func is24hourTime() -> Bool {
        let formatter = DateFormatter()
        formatter.locale = Locale.current
        formatter.setLocalizedDateFormatFromTemplate("j")
        return formatter.dateFormat?.contains("a") == false
    }

    /// Returns a compact string for hour labels in our time range selector.
    /// May not strictly adhere to local conventions for displaying the time
    func labelHour(_ hour: Int) -> String {
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
            if hour == 0 || hour == 24 {
                formattedStr += "a"
            }
            if hour == 12 {
                formattedStr += "p"
            }
        }
        return formattedStr
    }

    func formatHour(_ hour: Int) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale.current
        formatter.dateStyle = .none
        formatter.timeStyle = .short

        var components = DateComponents()
        components.hour = hour
        components.minute = 0

        let calendar = Calendar.current
        guard let date = calendar.date(from: components) else {
            return "\(hour):00"
        }

        return formatter.string(from: date)
    }

    func crossesMidnight() -> Bool {
        return endTime < startTime
    }
}

// MARK: - View Controller

class TimeRangeSelectorViewController: NSViewController {

    private var timeRangeView: TimeRangeSelectorView!
    private var startLabel: NSTextField!
    private var endLabel: NSTextField!
    private var warningLabel: NSTextField!
    private var infoBox: NSBox!

    var startTime: Int {
        get { timeRangeView.startTime }
        set { timeRangeView.startTime = newValue }
    }

    var endTime: Int {
        get { timeRangeView.endTime }
        set { timeRangeView.endTime = newValue }
    }

    override func loadView() {
        //view = NSView(frame: NSRect(x: 0, y: 0, width: 600, height: 200))
        view.wantsLayer = true
    }

    override func viewDidLoad() {
        super.viewDidLoad()
        setupUI()
    }

    private func setupUI() {
        // Everything is a subview of our view, which should be a custom NSView
        let containerView = view

        // Info box for start/end times
        infoBox = NSBox()
        infoBox.boxType = .custom
        infoBox.cornerRadius = 6
        infoBox.borderColor = NSColor.separatorColor
        infoBox.fillColor = NSColor.controlBackgroundColor
        infoBox.translatesAutoresizingMaskIntoConstraints = false
        containerView.addSubview(infoBox)

        let infoContainer = NSView()
        infoContainer.translatesAutoresizingMaskIntoConstraints = false
        infoBox.contentView = infoContainer

        // Start time label
        startLabel = NSTextField(labelWithString: "Start: 9:00 AM")
        startLabel.translatesAutoresizingMaskIntoConstraints = false
        infoContainer.addSubview(startLabel)

        // End time label
        endLabel = NSTextField(labelWithString: "End: 5:00 PM")
        endLabel.translatesAutoresizingMaskIntoConstraints = false
        infoContainer.addSubview(endLabel)

        // Time range selector view
        timeRangeView = TimeRangeSelectorView()
        timeRangeView.translatesAutoresizingMaskIntoConstraints = false
        timeRangeView.onTimeSelectionChanged = { [weak self] in
            self?.updateLabels()
        }
        containerView.addSubview(timeRangeView)

        // Warning label
        warningLabel = NSTextField(labelWithString: "⚠️  Range crosses midnight")
        warningLabel.textColor = .systemOrange
        warningLabel.alignment = .center
        warningLabel.translatesAutoresizingMaskIntoConstraints = false
        warningLabel.isHidden = true
        containerView.addSubview(warningLabel)

        // Layout constraints
        NSLayoutConstraint.activate([

            // Info box at top
            infoBox.topAnchor.constraint(equalTo: containerView.topAnchor),
            infoBox.leadingAnchor.constraint(equalTo: containerView.leadingAnchor),
            infoBox.trailingAnchor.constraint(equalTo: containerView.trailingAnchor),
            infoBox.heightAnchor.constraint(equalToConstant: 40),

            // Start and end labels inside info box
            startLabel.leadingAnchor.constraint(equalTo: infoBox.leadingAnchor, constant: 12),
            startLabel.centerYAnchor.constraint(equalTo: infoBox.centerYAnchor),

            endLabel.trailingAnchor.constraint(equalTo: infoBox.trailingAnchor, constant: -12),
            endLabel.centerYAnchor.constraint(equalTo: infoBox.centerYAnchor),

            // Time range view below info box
            timeRangeView.topAnchor.constraint(equalTo: infoBox.bottomAnchor, constant: 16),
            timeRangeView.leadingAnchor.constraint(equalTo: containerView.leadingAnchor),
            timeRangeView.trailingAnchor.constraint(equalTo: containerView.trailingAnchor),
            timeRangeView.heightAnchor.constraint(equalToConstant: 20),

            // Warning label below time range view
            warningLabel.topAnchor.constraint(equalTo: timeRangeView.bottomAnchor, constant: 12),
            warningLabel.centerXAnchor.constraint(equalTo: containerView.centerXAnchor),
            warningLabel.bottomAnchor.constraint(equalTo: containerView.bottomAnchor)
        ])

        updateLabels()
    }

    private func updateLabels() {
        startLabel.stringValue = "Start: \(timeRangeView.formatHour(timeRangeView.startTime))"
        endLabel.stringValue = "End: \(timeRangeView.formatHour(timeRangeView.endTime))"
        warningLabel.isHidden = !timeRangeView.crossesMidnight()
    }
}
