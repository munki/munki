//
//  MSCBlockingAppsController.swift
//  Managed Software Center
//
//  Created by Jordan Calhoun on 1/12/26.
//  Copyright © 2026 The Munki Project. All rights reserved.
//

import Cocoa

/// A flipped NSClipView that positions content from top to bottom.
/// Used in scroll views to ensure content aligns to the top rather than the bottom.
private class FlippedClipView: NSClipView {
    override var isFlipped: Bool { true }
}

/// Controller that manages the blocking apps sheet UI.
/// Presents a sheet listing running applications that must be quit before updates can proceed.
class MSCBlockingAppsController: NSObject {
    // MARK: - Properties

    private weak var parentWindow: NSWindow?
    private var sheet: NSWindow?
    private var spinners: [String: NSProgressIndicator] = [:]
    private var appsToQuit: [(displayName: String, path: String)] = []
    private var quitAppsButton: NSButton?
    private var monitorTimer: Timer?
    private var appsToCheck: [String] = []
    private var currentUser: String = ""

    // UI elements for dynamic updates
    private var blockingAppsStackView: NSStackView?
    // private var closedAppsStackView: NSStackView?
    // private var closedAppsSectionView: NSView?
    private var appRowViews: [String: NSView] = [:] // keyed by app path
    private var closedApps: Set<String> = [] // paths of closed apps
    private var sheetHeightConstraint: NSLayoutConstraint?
    // private var closedScrollHeightConstraint: NSLayoutConstraint?

    private var repoIcons: [String: String] = [:] // keyed by app name

    // Force quit tracking
    private var quitInitiatedTimes: [String: Date] = [:] // keyed by app path
    private var forceQuitButtons: [String: NSButton] = [:] // keyed by app path
    private let forceQuitDelay: TimeInterval = 5.0

    // Manual quit tracking - apps that cannot be auto-quit
    private var manualQuitAppNames: Set<String> = [] // app names that require manual quit
    private var manualQuitAppPaths: Set<String> = [] // app paths that require manual quit

    // Custom quit script tracking - maps app names to their quit scripts
    private var appQuitScripts: [String: String] = [:] // keyed by app name (e.g. "Safari.app")

    // Removal tracking - apps being removed shouldn't be reopened
    private var appsBeingRemovedNames: Set<String> = [] // app names being removed
    private var appsBeingRemovedPaths: Set<String> = [] // app paths being removed

    // Reopen apps after update
    private var reopenCheckbox: NSButton?
    private(set) var appsToReopenAfterUpdate: [String] = []

    // Layout constants
    private let sheetWidth: CGFloat = 400
    private let rowHeight: CGFloat = 24
    private let stackViewSpacing: CGFloat = 4
    private let iconSize: CGFloat = 24
    private let maxVisibleRows = 6

    // MARK: - Initialization

    init(parentWindow: NSWindow) {
        self.parentWindow = parentWindow
        super.init()
    }

    // MARK: - Public Methods

    /// Presents an interactive sheet listing blocking applications so the user can close them.
    ///
    /// - Returns: `true` if blocking apps are running and user cancelled; `false` if no blocking apps or all were closed.
    ///
    /// The sheet is dismissed automatically when all apps are closed or when the user cancels/ignores it.
    /// This method blocks further progress until the user has handled the apps or dismissed the sheet.
    func presentBlockingAppsSheet() -> Bool {
        guard let mainWindow = parentWindow else {
            msc_debug_log("Could not get main window in presentBlockingAppsSheet")
            return false
        }

        // Gather apps to check from update list
        appsToCheck = []
        manualQuitAppNames = []
        appQuitScripts = [:]
        appsBeingRemovedNames = []
        for update_item in getUpdateList() {
            let preventAutoQuit = update_item["prevent_auto_quit_on_update"] as? Bool ?? false
            let isBeingRemoved = update_item["status"] as? String == "will-be-removed"
            var itemBlockingApps = [String]()

            if let blocking_apps = update_item["blocking_applications"] as? [String] {
                itemBlockingApps = blocking_apps
            } else if let installs_items = update_item["installs"] as? [PlistDict] {
                itemBlockingApps = installs_items.filter { ($0["type"] as? String ?? "" == "application" &&
                        !($0["path"] as? String ?? "").isEmpty) }.map { ($0["path"] as? NSString ?? "").lastPathComponent }
            }

            if itemBlockingApps.count == 1 {
                // track the repo icons by app name in case we need them
                let appName = itemBlockingApps.first!
                repoIcons[appName] = update_item["icon"] as? String
            }

            appsToCheck += itemBlockingApps

            // Track apps that require manual quit
            if preventAutoQuit {
                for appName in itemBlockingApps {
                    manualQuitAppNames.insert(appName)
                }
            }

            // Track apps that are being removed (shouldn't be reopened)
            if isBeingRemoved {
                for appName in itemBlockingApps {
                    appsBeingRemovedNames.insert(appName)
                    msc_debug_log("App is being removed, won't reopen: \(appName)")
                }
            }

            // Track custom quit scripts for blocking apps
            if let quitScript = update_item["application_quit_script"] as? String {
                for appName in itemBlockingApps {
                    appQuitScripts[appName] = quitScript
                    msc_debug_log("Found application_quit_script for \(appName)")
                }
            }
        }

        let running_apps = getRunningBlockingApps(appsToCheck)

        if running_apps.isEmpty {
            return false
        }

        guard let user = getconsoleuser() else {
            return false
        }
        currentUser = user

        let other_users_apps = running_apps
            .filter { $0["user"] ?? "" != currentUser }
            .map { $0["display_name"] ?? "" }

        if !other_users_apps.isEmpty {
            showOtherUsersAlert(apps: other_users_apps, in: mainWindow)
            return true
        }

        // Get apps for current user only
        let my_apps = running_apps.filter { $0["user"] ?? "" == currentUser }

        // Build a set of unique apps with their paths for icon lookup
        var uniqueApps = [(displayName: String, path: String)]()
        var seenNames = Set<String>()
        manualQuitAppPaths = []
        appsBeingRemovedPaths = []
        for app in my_apps {
            let displayName = app["display_name"] ?? ""
            if !displayName.isEmpty, !seenNames.contains(displayName) {
                seenNames.insert(displayName)
                var appPath = app["pathname"] ?? ""
                if !appPath.isEmpty {
                    while !appPath.isEmpty, !appPath.hasSuffix(".app") {
                        appPath = (appPath as NSString).deletingLastPathComponent
                    }
                }
                uniqueApps.append((displayName: displayName, path: appPath))

                // Check if this app requires manual quit or is being removed
                if !appPath.isEmpty {
                    let appFileName = (appPath as NSString).lastPathComponent
                    if manualQuitAppNames.contains(appFileName) {
                        manualQuitAppPaths.insert(appPath)
                        msc_debug_log("App requires manual quit: \(displayName) at \(appPath)")
                    }
                    if appsBeingRemovedNames.contains(appFileName) {
                        appsBeingRemovedPaths.insert(appPath)
                        msc_debug_log("App is being removed: \(displayName) at \(appPath)")
                    }
                }
            }
        }

        appsToQuit = uniqueApps
        spinners = [:]
        appRowViews = [:]
        closedApps = []

        // Create and configure the sheet
        let sheetWindow = createSheet(for: uniqueApps)
        sheet = sheetWindow

        // Track result
        var userCancelled = true

        // Start monitoring for app closures
        startMonitoring(mainWindow: mainWindow, userCancelled: &userCancelled)

        // Show the sheet and wait for it to complete
        mainWindow.beginSheet(sheetWindow) { [weak self] response in
            self?.monitorTimer?.invalidate()
            if response == .cancel {
                userCancelled = true
            } else if response == .OK {
                userCancelled = false
            }
            NSApp.stopModal()
        }

        // Run modal to block until sheet is dismissed
        NSApp.runModal(for: sheetWindow)
        monitorTimer?.invalidate()

        // Save apps to reopen if checkbox is checked and user didn't cancel
        // Exclude apps that are being removed as they won't exist after the update
        if !userCancelled, reopenCheckbox?.state == .on {
            appsToReopenAfterUpdate = closedApps.filter { !appsBeingRemovedPaths.contains($0) }
        } else {
            appsToReopenAfterUpdate = []
        }

        // Cleanup
        cleanup()

        return userCancelled
    }

    // MARK: - Private Methods

    private func showOtherUsersAlert(apps: [String], in window: NSWindow) {
        let alert = NSAlert()
        alert.messageText = NSLocalizedString(
            "Applications in use by others",
            comment: "Other Users Blocking Apps Running title"
        )
        let formatString = NSLocalizedString(
            "Other logged in users are using the following " +
                "applications. Try updating later when they are no longer " +
                "in use:\n\n%@",
            comment: "Other Users Blocking Apps Running detail"
        )
        alert.informativeText = String(
            format: formatString, Array(Set(apps)).joined(separator: "\n")
        )
        alert.addButton(withTitle: NSLocalizedString("OK", comment: "OK button title"))
        alert.beginSheetModal(for: window, completionHandler: { _ in })
    }

    private func createSheet(for apps: [(displayName: String, path: String)]) -> NSWindow {
        let visibleHeight = min(CGFloat(apps.count), CGFloat(maxVisibleRows)) * (rowHeight + stackViewSpacing)
        let sheetHeight: CGFloat = visibleHeight + 170 // Extra height for checkbox

        let sheetWindow = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: sheetWidth, height: sheetHeight),
            styleMask: [.titled, .docModalWindow],
            backing: .buffered,
            defer: true
        )

        let contentView = NSView(frame: NSRect(x: 0, y: 0, width: sheetWidth, height: sheetHeight))

        // Title label
        let titleLabel = NSTextField(labelWithString: NSLocalizedString(
            "Conflicting applications running",
            comment: "Blocking Apps Running title"
        ))
        titleLabel.font = NSFont.boldSystemFont(ofSize: 13)
        titleLabel.translatesAutoresizingMaskIntoConstraints = false
        contentView.addSubview(titleLabel)

        // Message label
        let messageLabel = NSTextField(wrappingLabelWithString: NSLocalizedString(
            "Please quit the following applications to continue with the update:",
            comment: "Blocking Apps Running detail for auto-quit sheet"
        ))
        messageLabel.font = NSFont.systemFont(ofSize: 11)
        messageLabel.textColor = .secondaryLabelColor
        messageLabel.translatesAutoresizingMaskIntoConstraints = false
        contentView.addSubview(messageLabel)

        // Create stack view for blocking app rows
        let blockingStackView = createBlockingAppsStackView(apps: apps)
        blockingAppsStackView = blockingStackView

        // Create scroll view for blocking apps
        let blockingScrollView = NSScrollView()
        blockingScrollView.translatesAutoresizingMaskIntoConstraints = false
        blockingScrollView.contentView = FlippedClipView()
        blockingScrollView.hasVerticalScroller = (apps.count > maxVisibleRows)
        if apps.count > maxVisibleRows {
            blockingScrollView.hasVerticalScroller = true
            blockingScrollView.borderType = .lineBorder
            blockingScrollView.autohidesScrollers = true
        } else {
            blockingScrollView.hasVerticalScroller = false
            blockingScrollView.verticalScrollElasticity = .none
            blockingScrollView.borderType = .noBorder
        }
        blockingScrollView.hasHorizontalScroller = false
        blockingScrollView.automaticallyAdjustsContentInsets = false
        blockingScrollView.contentInsets = NSEdgeInsets(top: 4, left: 0, bottom: 4, right: 0)
        blockingScrollView.wantsLayer = true
        blockingScrollView.layer?.cornerRadius = 6
        blockingScrollView.layer?.masksToBounds = true
        blockingScrollView.layer?.borderWidth = 1
        blockingScrollView.layer?.borderColor = NSColor.separatorColor.cgColor
        blockingScrollView.documentView = blockingStackView
        contentView.addSubview(blockingScrollView)

        /*
         // Create closed apps section (initially hidden)
         let closedSection = createClosedAppsSection()
         closedAppsSectionView = closedSection
         closedSection.isHidden = true
         contentView.addSubview(closedSection)
         */

        // Reopen apps checkbox
        let checkbox = NSButton(checkboxWithTitle: NSLocalizedString(
            "Reopen applications after update",
            comment: "Reopen apps after update checkbox"
        ), target: nil, action: nil)
        checkbox.translatesAutoresizingMaskIntoConstraints = false
        checkbox.state = .on
        contentView.addSubview(checkbox)
        reopenCheckbox = checkbox

        // Quit Apps button
        let quitButton = NSButton(title: NSLocalizedString("Quit Apps", comment: "Quit Apps button title"), target: self, action: #selector(quitApps(_:)))
        quitButton.translatesAutoresizingMaskIntoConstraints = false
        quitButton.bezelStyle = .rounded
        quitButton.keyEquivalent = "\r"
        contentView.addSubview(quitButton)
        quitAppsButton = quitButton

        // Cancel button
        let cancelButton = NSButton(title: NSLocalizedString("Cancel", comment: "Cancel button title/short action text"), target: self, action: #selector(cancelSheet(_:)))
        cancelButton.translatesAutoresizingMaskIntoConstraints = false
        cancelButton.bezelStyle = .rounded
        cancelButton.keyEquivalent = "\u{1B}"
        contentView.addSubview(cancelButton)

        // Layout constraints
        NSLayoutConstraint.activate([
            titleLabel.topAnchor.constraint(equalTo: contentView.topAnchor, constant: 16),
            titleLabel.leadingAnchor.constraint(equalTo: contentView.leadingAnchor, constant: 20),
            titleLabel.trailingAnchor.constraint(equalTo: contentView.trailingAnchor, constant: -20),

            messageLabel.topAnchor.constraint(equalTo: titleLabel.bottomAnchor, constant: 8),
            messageLabel.leadingAnchor.constraint(equalTo: contentView.leadingAnchor, constant: 20),
            messageLabel.trailingAnchor.constraint(equalTo: contentView.trailingAnchor, constant: -20),

            blockingScrollView.topAnchor.constraint(equalTo: messageLabel.bottomAnchor, constant: 12),
            blockingScrollView.leadingAnchor.constraint(equalTo: contentView.leadingAnchor, constant: 20),
            blockingScrollView.trailingAnchor.constraint(equalTo: contentView.trailingAnchor, constant: -20),
            blockingScrollView.heightAnchor.constraint(equalToConstant: visibleHeight + 8),

            blockingStackView.topAnchor.constraint(equalTo: blockingScrollView.contentView.topAnchor),
            blockingStackView.leadingAnchor.constraint(equalTo: blockingScrollView.contentView.leadingAnchor, constant: 4),
            blockingStackView.trailingAnchor.constraint(equalTo: blockingScrollView.contentView.trailingAnchor, constant: -4),
            /*
                closedSection.topAnchor.constraint(equalTo: blockingScrollView.bottomAnchor, constant: 12),
                closedSection.leadingAnchor.constraint(equalTo: contentView.leadingAnchor, constant: 20),
                closedSection.trailingAnchor.constraint(equalTo: contentView.trailingAnchor, constant: -20),
                 */
            // checkbox.topAnchor.constraint(equalTo: closedSection.bottomAnchor, // constant: 12),
            checkbox.topAnchor.constraint(equalTo: blockingScrollView.bottomAnchor, constant: 12),
            checkbox.leadingAnchor.constraint(equalTo: contentView.leadingAnchor, constant: 20),

            quitButton.topAnchor.constraint(equalTo: checkbox.bottomAnchor, constant: 16),
            quitButton.trailingAnchor.constraint(equalTo: contentView.trailingAnchor, constant: -20),
            quitButton.bottomAnchor.constraint(equalTo: contentView.bottomAnchor, constant: -16),

            cancelButton.topAnchor.constraint(equalTo: checkbox.bottomAnchor, constant: 16),
            cancelButton.trailingAnchor.constraint(equalTo: quitButton.leadingAnchor, constant: -12),
        ])

        sheetWindow.contentView = contentView
        return sheetWindow
    }

    private func createBlockingAppsStackView(apps: [(displayName: String, path: String)]) -> NSStackView {
        let stackView = NSStackView()
        stackView.orientation = .vertical
        stackView.alignment = .leading
        stackView.spacing = stackViewSpacing
        stackView.translatesAutoresizingMaskIntoConstraints = false

        let spinnerSize: CGFloat = 16

        for app in apps {
            let rowView = NSView()
            rowView.translatesAutoresizingMaskIntoConstraints = false

            let isManualQuit = manualQuitAppPaths.contains(app.path)

            // App icon
            let iconView = NSImageView()
            iconView.translatesAutoresizingMaskIntoConstraints = false
            iconView.imageScaling = .scaleProportionallyUpOrDown
            if !app.path.isEmpty {
                // grab icon from app bundle if possible
                if FileManager.default.fileExists(atPath: app.path) {
                    iconView.image = NSWorkspace.shared.icon(forFile: app.path)
                } else {
                    // use the icon from the repo
                    let appName = (app.path as NSString).lastPathComponent
                    if let iconPath = repoIcons[appName] {
                        let fullIconPath = NSString.path(withComponents: [html_dir(), iconPath])
                        iconView.image = NSImage(contentsOf: URL(fileURLWithPath: fullIconPath))
                    }
                }
            }
            // if no icon, use generic app icon
            if iconView.image == nil {
                iconView.image = NSImage(named: NSImage.applicationIconName)
            }

            // App name label
            let nameLabel = NSTextField(labelWithString: app.displayName)
            nameLabel.translatesAutoresizingMaskIntoConstraints = false
            nameLabel.font = NSFont.systemFont(ofSize: 13)
            nameLabel.lineBreakMode = .byTruncatingTail

            rowView.addSubview(iconView)
            rowView.addSubview(nameLabel)

            if !app.path.isEmpty {
                appRowViews[app.path] = rowView
            }

            if isManualQuit {
                // Show "Manual quit required" label for apps that can't be auto-quit
                let manualQuitLabel = showManualQuitLabel(for: app.path, in: rowView)

                NSLayoutConstraint.activate([
                    rowView.heightAnchor.constraint(equalToConstant: rowHeight),
                    rowView.widthAnchor.constraint(equalToConstant: sheetWidth - 40),

                    iconView.leadingAnchor.constraint(equalTo: rowView.leadingAnchor, constant: 4),
                    iconView.centerYAnchor.constraint(equalTo: rowView.centerYAnchor),
                    iconView.widthAnchor.constraint(equalToConstant: iconSize),
                    iconView.heightAnchor.constraint(equalToConstant: iconSize),

                    nameLabel.leadingAnchor.constraint(equalTo: iconView.trailingAnchor, constant: 8),
                    nameLabel.trailingAnchor.constraint(lessThanOrEqualTo: manualQuitLabel.leadingAnchor, constant: -8),
                    nameLabel.centerYAnchor.constraint(equalTo: rowView.centerYAnchor),
                ])
            } else {
                // Progress spinner (hidden by default) for apps that can be auto-quit
                let spinner = NSProgressIndicator()
                spinner.translatesAutoresizingMaskIntoConstraints = false
                spinner.style = .spinning
                spinner.controlSize = .small
                spinner.isHidden = true
                spinner.isDisplayedWhenStopped = false

                if !app.path.isEmpty {
                    spinners[app.path] = spinner
                }

                rowView.addSubview(spinner)

                NSLayoutConstraint.activate([
                    rowView.heightAnchor.constraint(equalToConstant: rowHeight),
                    rowView.widthAnchor.constraint(equalToConstant: sheetWidth - 40),

                    iconView.leadingAnchor.constraint(equalTo: rowView.leadingAnchor, constant: 4),
                    iconView.centerYAnchor.constraint(equalTo: rowView.centerYAnchor),
                    iconView.widthAnchor.constraint(equalToConstant: iconSize),
                    iconView.heightAnchor.constraint(equalToConstant: iconSize),

                    nameLabel.leadingAnchor.constraint(equalTo: iconView.trailingAnchor, constant: 8),
                    nameLabel.trailingAnchor.constraint(lessThanOrEqualTo: spinner.leadingAnchor, constant: -8),
                    nameLabel.centerYAnchor.constraint(equalTo: rowView.centerYAnchor),

                    spinner.trailingAnchor.constraint(equalTo: rowView.trailingAnchor, constant: -4),
                    spinner.centerYAnchor.constraint(equalTo: rowView.centerYAnchor),
                    spinner.widthAnchor.constraint(equalToConstant: spinnerSize),
                    spinner.heightAnchor.constraint(equalToConstant: spinnerSize),
                ])
            }

            stackView.addArrangedSubview(rowView)
        }

        return stackView
    }

    /*
     private func createClosedAppsSection() -> NSView {
         let containerView = NSView()
         containerView.translatesAutoresizingMaskIntoConstraints = false

         // "Closed Applications" label
         let closedLabel = NSTextField(labelWithString: NSLocalizedString(
             "Closed Applications",
             comment: "Closed Applications section title"
         ))
         closedLabel.font = NSFont.boldSystemFont(ofSize: 11)
         closedLabel.textColor = .secondaryLabelColor
         closedLabel.translatesAutoresizingMaskIntoConstraints = false
         containerView.addSubview(closedLabel)

         // Stack view for closed apps
         let closedStackView = NSStackView()
         closedStackView.orientation = .vertical
         closedStackView.alignment = .leading
         closedStackView.spacing = 4
         closedStackView.translatesAutoresizingMaskIntoConstraints = false
         closedAppsStackView = closedStackView

         // Scroll view for closed apps
         let closedScrollView = NSScrollView()
         closedScrollView.translatesAutoresizingMaskIntoConstraints = false
         closedScrollView.contentView = FlippedClipView()
         closedScrollView.hasVerticalScroller = true
         closedScrollView.hasHorizontalScroller = false
         closedScrollView.autohidesScrollers = true
         closedScrollView.borderType = .lineBorder
         closedScrollView.automaticallyAdjustsContentInsets = false
         closedScrollView.contentInsets = NSEdgeInsets(top: 4, left: 0, bottom: 4, right: 0)
         closedScrollView.wantsLayer = true
         closedScrollView.layer?.cornerRadius = 6
         closedScrollView.layer?.masksToBounds = true
         closedScrollView.layer?.borderWidth = 1
         closedScrollView.layer?.borderColor = NSColor.separatorColor.cgColor
         closedScrollView.documentView = closedStackView
         containerView.addSubview(closedScrollView)

         // Initial height constraint (will be updated as apps are added)
         let scrollHeightConstraint = closedScrollView.heightAnchor.constraint(equalToConstant: rowHeight + 8)
         closedScrollHeightConstraint = scrollHeightConstraint

         NSLayoutConstraint.activate([
             closedLabel.topAnchor.constraint(equalTo: containerView.topAnchor),
             closedLabel.leadingAnchor.constraint(equalTo: containerView.leadingAnchor),
             closedLabel.trailingAnchor.constraint(equalTo: containerView.trailingAnchor),

             closedScrollView.topAnchor.constraint(equalTo: closedLabel.bottomAnchor, constant: 6),
             closedScrollView.leadingAnchor.constraint(equalTo: containerView.leadingAnchor),
             closedScrollView.trailingAnchor.constraint(equalTo: containerView.trailingAnchor),
             closedScrollView.bottomAnchor.constraint(equalTo: containerView.bottomAnchor),
             scrollHeightConstraint,

             closedStackView.topAnchor.constraint(equalTo: closedScrollView.contentView.topAnchor),
             closedStackView.leadingAnchor.constraint(equalTo: closedScrollView.contentView.leadingAnchor, constant: 4),
             closedStackView.trailingAnchor.constraint(equalTo: closedScrollView.contentView.trailingAnchor, constant: -4),
         ])

         return containerView
     }

     private func createClosedAppRow(displayName: String, path: String) -> NSView {
         let rowView = NSView()
         rowView.translatesAutoresizingMaskIntoConstraints = false

         // App icon
         let iconView = NSImageView()
         iconView.translatesAutoresizingMaskIntoConstraints = false
         iconView.imageScaling = .scaleProportionallyUpOrDown
         if !path.isEmpty {
             iconView.image = NSWorkspace.shared.icon(forFile: path)
         } else {
             iconView.image = NSImage(named: NSImage.applicationIconName)
         }

         // App name label
         let nameLabel = NSTextField(labelWithString: displayName)
         nameLabel.translatesAutoresizingMaskIntoConstraints = false
         nameLabel.font = NSFont.systemFont(ofSize: 13)
         nameLabel.textColor = .secondaryLabelColor
         nameLabel.lineBreakMode = .byTruncatingTail

         // Checkmark image
         let checkmarkView = NSImageView()
         checkmarkView.translatesAutoresizingMaskIntoConstraints = false
         checkmarkView.imageScaling = .scaleProportionallyUpOrDown
         if #available(macOS 11.0, *) {
             if let checkmarkImage = NSImage(systemSymbolName: "checkmark.circle.fill", accessibilityDescription: "Closed") {
                 checkmarkView.image = checkmarkImage
                 checkmarkView.contentTintColor = .systemGreen
             }
         } else {
             // Fallback for older macOS versions
             checkmarkView.image = NSImage(named: NSImage.statusAvailableName)
         }

         rowView.addSubview(iconView)
         rowView.addSubview(nameLabel)
         rowView.addSubview(checkmarkView)

         let checkmarkSize: CGFloat = 16

         NSLayoutConstraint.activate([
             rowView.heightAnchor.constraint(equalToConstant: rowHeight),
             rowView.widthAnchor.constraint(equalToConstant: sheetWidth - 40),

             iconView.leadingAnchor.constraint(equalTo: rowView.leadingAnchor, constant: 4),
             iconView.centerYAnchor.constraint(equalTo: rowView.centerYAnchor),
             iconView.widthAnchor.constraint(equalToConstant: iconSize),
             iconView.heightAnchor.constraint(equalToConstant: iconSize),

             nameLabel.leadingAnchor.constraint(equalTo: iconView.trailingAnchor, constant: 8),
             nameLabel.trailingAnchor.constraint(lessThanOrEqualTo: checkmarkView.leadingAnchor, constant: -8),
             nameLabel.centerYAnchor.constraint(equalTo: rowView.centerYAnchor),

             checkmarkView.trailingAnchor.constraint(equalTo: rowView.trailingAnchor, constant: -4),
             checkmarkView.centerYAnchor.constraint(equalTo: rowView.centerYAnchor),
             checkmarkView.widthAnchor.constraint(equalToConstant: checkmarkSize),
             checkmarkView.heightAnchor.constraint(equalToConstant: checkmarkSize),
         ])

         return rowView
     }

     private func moveAppToClosedSection(path: String) {
         guard !closedApps.contains(path),
               let rowView = appRowViews[path],
               let blockingStack = blockingAppsStackView,
               let closedStack = closedAppsStackView
         else {
             return
         }

         // Find the app info
         guard let appInfo = appsToQuit.first(where: { $0.path == path }) else {
             return
         }

         // Mark as closed
         closedApps.insert(path)

         // Stop and hide the spinner
         if let spinner = spinners[path] {
             spinner.stopAnimation(nil)
             spinner.isHidden = true
         }

         // Remove from blocking apps stack view
         blockingStack.removeArrangedSubview(rowView)
         rowView.removeFromSuperview()

         // Create a new row for the closed apps section with checkmark
         let closedRow = createClosedAppRow(displayName: appInfo.displayName, path: path)
         closedStack.addArrangedSubview(closedRow)

         // Show the closed apps section if this is the first closed app
         if closedAppsSectionView?.isHidden == true {
             closedAppsSectionView?.isHidden = false

             // Animate the sheet height change
             if let sheetWindow = sheet {
                 var frame = sheetWindow.frame
                 let additionalHeight: CGFloat = rowHeight + 40 // section title + scroll view + padding
                 frame.size.height += additionalHeight
                 frame.origin.y -= additionalHeight
                 sheetWindow.setFrame(frame, display: true, animate: true)
             }
         }

         // Update the closed scroll view height based on number of closed apps
         let closedCount = closedApps.count
         let newHeight = min(CGFloat(closedCount), CGFloat(maxVisibleRows)) * rowHeight + 8
         if let heightConstraint = closedScrollHeightConstraint, heightConstraint.constant != newHeight {
             let heightDiff = newHeight - heightConstraint.constant
             heightConstraint.constant = newHeight

             // Adjust sheet height if needed
             if closedCount > 1, let sheetWindow = sheet {
                 var frame = sheetWindow.frame
                 frame.size.height += heightDiff
                 frame.origin.y -= heightDiff
                 sheetWindow.setFrame(frame, display: true, animate: true)
             }
         }
     }
     */

    private func moveAppToClosedSection(path: String) {
        guard !closedApps.contains(path),
              let rowView = appRowViews[path],
              let blockingStack = blockingAppsStackView
        else {
            return
        }

        // Mark as closed
        closedApps.insert(path)

        // Remove from blocking apps stack view
        blockingStack.removeArrangedSubview(rowView)
        rowView.removeFromSuperview()
    }

    private func startMonitoring(mainWindow: NSWindow, userCancelled _: inout Bool) {
        let appsToCheckCopy = appsToCheck
        let currentUserCopy = currentUser

        let timer = Timer(timeInterval: 1.0, repeats: true) { [weak self, weak mainWindow] timer in
            guard let self, let mainWindow else {
                timer.invalidate()
                return
            }

            let stillRunning = getRunningBlockingApps(appsToCheckCopy)
            let myStillRunning = stillRunning.filter { $0["user"] ?? "" == currentUserCopy }

            // Get the paths of still-running apps (extract the executable paths)
            var stillRunningPaths = Set<String>()
            for app in myStillRunning {
                let appPath = app["pathname"] ?? ""
                if !appPath.isEmpty {
                    stillRunningPaths.insert(appPath)
                }
            }

            msc_debug_log("Still running paths: \(stillRunningPaths)")
            msc_debug_log("Apps to quit paths: \(appsToQuit.map(\.path))")
            msc_debug_log("Already closed: \(closedApps)")

            // Helper function to check if any running process is part of an app bundle
            func isAppStillRunning(_ appBundlePath: String) -> Bool {
                // Check if any running process path contains this app bundle path
                // This handles nested .app bundles (e.g., Docker.app contains Docker Desktop.app)
                let bundlePrefix = appBundlePath + "/"
                for runningPath in stillRunningPaths {
                    if runningPath.hasPrefix(bundlePrefix) || runningPath == appBundlePath {
                        return true
                    }
                }
                return false
            }

            // Check for newly closed apps and move them to the closed section
            // Must be done on main thread for UI updates
            DispatchQueue.main.async {
                let now = Date()

                for app in self.appsToQuit {
                    if !app.path.isEmpty, !isAppStillRunning(app.path), !self.closedApps.contains(app.path) {
                        msc_debug_log("Moving app to closed section: \(app.displayName) at \(app.path)")
                        self.moveAppToClosedSection(path: app.path)
                    }

                    // Check if app has exceeded force quit delay and is still running
                    if let quitTime = self.quitInitiatedTimes[app.path],
                       now.timeIntervalSince(quitTime) >= self.forceQuitDelay,
                       isAppStillRunning(app.path),
                       !self.closedApps.contains(app.path),
                       self.forceQuitButtons[app.path] == nil
                    {
                        // Show force quit button for this app
                        self.showForceQuitButton(for: app.path)
                    }
                }

                if myStillRunning.isEmpty {
                    // All apps have been closed
                    timer.invalidate()
                    if let sheetWindow = self.sheet {
                        mainWindow.endSheet(sheetWindow, returnCode: .OK)
                    }
                }
            }
        }

        // Add timer to common run loop modes so it fires during modal sessions
        RunLoop.main.add(timer, forMode: .common)
        monitorTimer = timer
    }

    private func showForceQuitButton(for appPath: String) {
        guard let rowView = appRowViews[appPath],
              let spinner = spinners[appPath]
        else {
            return
        }

        // Hide and stop the spinner
        spinner.stopAnimation(nil)
        spinner.isHidden = true

        // Check if AutoForceQuitAppsOnUpdates is disabled
        let autoForceQuitEnabled = pythonishBool(pref("AutoForceQuitAppsOnUpdate"))
        if !autoForceQuitEnabled {
            // Show "Manual quit required" label instead of Force Quit button
            showManualQuitLabel(for: appPath, in: rowView)
            return
        }

        // Create the Force Quit button
        let forceQuitButton = NSButton(title: NSLocalizedString("Force Quit", comment: "Force Quit button title"), target: self, action: #selector(forceQuitButtonClicked(_:)))
        forceQuitButton.translatesAutoresizingMaskIntoConstraints = false
        forceQuitButton.bezelStyle = .rounded
        forceQuitButton.controlSize = .small
        forceQuitButton.font = NSFont.systemFont(ofSize: 10)

        // Store the app path in the button's identifier for later retrieval
        forceQuitButton.identifier = NSUserInterfaceItemIdentifier(appPath)

        rowView.addSubview(forceQuitButton)

        NSLayoutConstraint.activate([
            forceQuitButton.trailingAnchor.constraint(equalTo: rowView.trailingAnchor, constant: -4),
            forceQuitButton.centerYAnchor.constraint(equalTo: rowView.centerYAnchor),
        ])

        forceQuitButtons[appPath] = forceQuitButton

        msc_debug_log("Showing Force Quit button for: \(appPath)")
    }

    @discardableResult
    private func showManualQuitLabel(for appPath: String, in rowView: NSView) -> NSTextField {
        let manualQuitLabel = NSTextField(labelWithString: NSLocalizedString(
            "Manual quit required",
            comment: "Manual quit required label"
        ))
        manualQuitLabel.translatesAutoresizingMaskIntoConstraints = false
        manualQuitLabel.font = NSFont.systemFont(ofSize: 10)
        manualQuitLabel.textColor = .systemOrange
        manualQuitLabel.alignment = .right

        rowView.addSubview(manualQuitLabel)

        NSLayoutConstraint.activate([
            manualQuitLabel.trailingAnchor.constraint(equalTo: rowView.trailingAnchor, constant: -4),
            manualQuitLabel.centerYAnchor.constraint(equalTo: rowView.centerYAnchor),
        ])

        msc_debug_log("Showing Manual quit required label for: \(appPath)")

        return manualQuitLabel
    }

    @objc private func forceQuitButtonClicked(_ sender: NSButton) {
        guard let appPath = sender.identifier?.rawValue,
              let appInfo = appsToQuit.first(where: { $0.path == appPath }),
              let mainWindow = parentWindow
        else {
            return
        }

        // Show confirmation alert
        let alert = NSAlert()
        alert.messageText = NSLocalizedString(
            "Force Quit Application?",
            comment: "Force Quit confirmation title"
        )
        let formatString = NSLocalizedString(
            "Are you sure you want to force quit \"%@\"? Any unsaved changes may be lost.",
            comment: "Force Quit confirmation message"
        )
        alert.informativeText = String(format: formatString, appInfo.displayName)
        alert.alertStyle = .warning
        alert.addButton(withTitle: NSLocalizedString("Force Quit", comment: "Force Quit button title"))
        alert.addButton(withTitle: NSLocalizedString("Cancel", comment: "Cancel button title/short action text"))

        alert.beginSheetModal(for: sheet ?? mainWindow) { [weak self] response in
            if response == .alertFirstButtonReturn {
                self?.performForceQuit(for: appPath)
            }
        }
    }

    private func performForceQuit(for appPath: String) {
        let bundleURL = URL(fileURLWithPath: appPath)
        let bundlePrefix = appPath + "/"

        // Find all running apps that match this bundle or are nested inside it
        let runningApps = NSWorkspace.shared.runningApplications.filter { runningApp in
            guard let runningBundleURL = runningApp.bundleURL else { return false }
            let runningPath = runningBundleURL.path
            return runningBundleURL == bundleURL ||
                runningPath.hasPrefix(bundlePrefix)
        }

        msc_debug_log("Force terminating \(runningApps.count) app(s) for bundle: \(appPath)")
        for runningApp in runningApps {
            msc_debug_log("  - Force terminating: \(runningApp.bundleURL?.path ?? "unknown")")
            _ = runningApp.forceTerminate()
        }

        // Remove the force quit button and show spinner while we wait for it to close
        if let button = forceQuitButtons[appPath] {
            button.removeFromSuperview()
            forceQuitButtons.removeValue(forKey: appPath)
        }

        if let spinner = spinners[appPath] {
            spinner.isHidden = false
            spinner.startAnimation(nil)
        }

        // Reset the quit initiation time so we don't immediately show the force quit button again
        quitInitiatedTimes[appPath] = Date()
    }

    private func cleanup() {
        sheet = nil
        spinners = [:]
        appsToQuit = []
        quitAppsButton = nil
        monitorTimer = nil
        appsToCheck = []
        blockingAppsStackView = nil
        // closedAppsStackView = nil
        // closedAppsSectionView = nil
        appRowViews = [:]
        closedApps = []
        sheetHeightConstraint = nil
        // closedScrollHeightConstraint = nil
        quitInitiatedTimes = [:]
        forceQuitButtons = [:]
        manualQuitAppNames = []
        manualQuitAppPaths = []
        appQuitScripts = [:]
        appsBeingRemovedNames = []
        appsBeingRemovedPaths = []
        reopenCheckbox = nil
        // Note: appsToReopenAfterUpdate is intentionally NOT cleared here
        // so the caller can access it after the sheet is dismissed
    }

    // MARK: - Public Methods for Reopening Apps

    /// Reopens all applications that were closed during the blocking apps sheet.
    /// Call this method after the update has completed.
    /// Clears the list of apps to reopen after attempting to open them.
    func reopenApps() {
        let config = NSWorkspace.OpenConfiguration()
        config.activates = false // Open apps in background without bringing to foreground

        for appPath in appsToReopenAfterUpdate {
            msc_debug_log("Reopening app in background: \(appPath)")
            NSWorkspace.shared.openApplication(
                at: URL(fileURLWithPath: appPath),
                configuration: config
            ) { _, error in
                if let error {
                    msc_debug_log("Failed to reopen app at \(appPath): \(error.localizedDescription)")
                }
            }
        }
        appsToReopenAfterUpdate = []
    }

    /// Clears the list of apps to reopen without reopening them.
    func clearAppsToReopen() {
        appsToReopenAfterUpdate = []
    }

    // MARK: - Actions

    @objc private func cancelSheet(_: Any?) {
        guard let sheetWindow = sheet,
              let mainWindow = parentWindow
        else {
            return
        }
        mainWindow.endSheet(sheetWindow, returnCode: .cancel)
    }

    @objc private func quitApps(_: Any?) {
        quitAppsButton?.isEnabled = false

        for app in appsToQuit {
            guard !app.path.isEmpty else { continue }

            // Skip apps that require manual quit
            if manualQuitAppPaths.contains(app.path) {
                msc_debug_log("Skipping auto-quit for manual quit app: \(app.displayName)")
                continue
            }

            // Only show spinner for apps that haven't been closed yet
            if !closedApps.contains(app.path) {
                if let spinner = spinners[app.path] {
                    spinner.isHidden = false
                    spinner.startAnimation(nil)
                }

                // Record quit initiation time for force quit tracking
                quitInitiatedTimes[app.path] = Date()

                // Check for custom quit script
                let appFileName = (app.path as NSString).lastPathComponent
                if let quitScript = appQuitScripts[appFileName] {
                    // Run the custom quit script instead of default termination
                    msc_debug_log("Running application_quit_script for \(app.displayName)")
                    DispatchQueue.global(qos: .userInitiated).async {
                        let result = runEmbeddedScript(quitScript, scriptName: "application_quit_script")
                        DispatchQueue.main.async {
                            if result.exitcode != 0 {
                                msc_debug_log("application_quit_script for \(app.displayName) failed with exit code \(result.exitcode)")
                            } else {
                                msc_debug_log("application_quit_script for \(app.displayName) completed successfully")
                            }
                        }
                    }
                } else {
                    // Use default termination logic
                    // Find the running application by its bundle URL and terminate it
                    let bundlePrefix = app.path + "/"
                    // NSRunningApplication.bundleURL.papth always ends with a /
                    // so build our comparison URL with a path ending with a /
                    let bundleURL = URL(fileURLWithPath: bundlePrefix)

                    // Find all running apps that match this bundle or are nested inside it
                    // This handles apps like Docker that contain nested .app bundles
                    let runningApps = NSWorkspace.shared.runningApplications.filter { runningApp in
                        guard let runningBundleURL = runningApp.bundleURL else { return false }
                        let runningPath = runningBundleURL.path
                        return runningBundleURL == bundleURL ||
                            runningPath.hasPrefix(bundlePrefix)
                    }

                    msc_debug_log("Terminating \(runningApps.count) app(s) for bundle: \(app.path)")
                    for runningApp in runningApps {
                        msc_debug_log("  - Terminating: \(runningApp.bundleURL?.path ?? "unknown")")
                        _ = runningApp.terminate()
                    }
                }
            }
        }

        // Re-enable the button after a delay in case some apps don't quit
        DispatchQueue.main.asyncAfter(deadline: .now() + 3.0) { [weak self] in
            self?.quitAppsButton?.isEnabled = true
        }
    }
}
