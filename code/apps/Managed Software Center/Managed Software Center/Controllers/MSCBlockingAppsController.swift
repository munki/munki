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

/// A struct to track UI elements that correspond to blockind apps
private struct BlockingAppRowData {
    var displayName: String
    var rowView: NSView?
    var spinner: NSProgressIndicator?
    var manualQuitField: NSTextField?
    var forceQuitButton: NSButton?
    var forceQuitButtonWidthConstraint: NSLayoutConstraint?
    var quitInitiatedTime: Date?
}

/// Controller that manages the blocking apps sheet UI.
/// Presents a sheet listing running applications that must be quit before updates can proceed.
class MSCBlockingAppsController: NSObject {
    // MARK: - Properties

    private weak var parentWindow: NSWindow?
    private var sheet: NSWindow?
    private var appsToQuit: [(displayName: String, path: String)] = []
    private var nonBlockedItemsPending = false
    private var quitAppsButton: NSButton?
    private var updateOtherItemsButton: NSButton?
    private var monitorTimer: Timer?
    private var appsToCheck: [String] = []
    private var currentUser: String = ""

    // UI elements for dynamic updates
    private var blockingAppsStackView: NSStackView?
    private var closedApps: Set<String> = [] // paths of closed apps
    private var appRowDataForPath: [String: BlockingAppRowData] = [:]

    private var repoIcons: [String: String] = [:] // keyed by app name

    // Force quit tracking
    private let forceQuitDelay: TimeInterval = 5.0

    // Manual quit tracking - apps that cannot/should not be quit by us
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
    private var sheetWidth: CGFloat = 320 // can be adjusted
    private let rowHeight: CGFloat = 32
    private let stackViewSpacing: CGFloat = 4
    private let iconSize: CGFloat = 32
    private let maxVisibleRows = 6
    private let sheetMargin: CGFloat = 24

    // MARK: - Initialization

    init(parentWindow: NSWindow) {
        self.parentWindow = parentWindow
        super.init()
    }

    // MARK: - Public Methods

    /// Presents an interactive sheet listing blocking applications so the user can close them.
    ///
    /// - Returns: `false` if blocking apps are running and user cancelled;
    ///            `true` if no blocking apps or all were closed,
    ///            `true` if user clicks "Update others"
    ///
    /// The sheet is dismissed automatically when all apps are closed or when the user cancels/ignores it.
    /// This method blocks further progress until the user has handled the apps or dismissed the sheet.
    func canContinueAfterPresentingBlockingAppsSheet() -> Bool {
        guard let mainWindow = parentWindow else {
            msc_debug_log("Could not get main window in canContinueAfterPresentingBlockingAppsSheet")
            return false
        }

        // Gather apps to check from update list
        appsToCheck = []
        manualQuitAppNames = []
        appQuitScripts = [:]
        appsBeingRemovedNames = []

        var running_apps: [BlockingAppInfo] = []
        for update_item in getUpdateList() {
            let manualQuit = update_item["blocking_applications_manual_quit_only"] as? Bool ?? false
            let isBeingRemoved = update_item["status"] as? String == "will-be-removed"
            let itemBlockingApps = blockingApplicationsForItem(update_item.my)
            if itemBlockingApps.count == 1 {
                // track the repo icons by app name in case we need them
                let appName = itemBlockingApps.first!
                repoIcons[appName] = update_item["icon"] as? String
            }

            appsToCheck += itemBlockingApps
            let runningBlockingApps = getRunningBlockingApps(itemBlockingApps)
            if runningBlockingApps.isEmpty {
                // this item has no blocking apps or none are running
                nonBlockedItemsPending = true
            } else {
                running_apps += runningBlockingApps
            }

            // Track apps that require manual quit
            if manualQuit {
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
            if let quitScript = update_item["blocking_applications_quit_script"] as? String {
                for appName in itemBlockingApps {
                    appQuitScripts[appName] = quitScript
                    msc_debug_log("Found blocking_applications_quit_script for \(appName)")
                }
            }
        }

        if running_apps.isEmpty {
            return true
        }

        guard let user = getconsoleuser() else {
            return false
        }
        currentUser = user

        let other_users_apps = running_apps
            .filter { $0.user != currentUser }
            .map(\.display_name)

        if !other_users_apps.isEmpty {
            showOtherUsersAlert(apps: other_users_apps, in: mainWindow)
            return false
        }

        // Get apps for current user only
        let my_apps = running_apps.filter { $0.user == currentUser }

        // Build a set of unique apps with their paths for icon lookup
        var uniqueApps = [(displayName: String, path: String)]()
        var seenNames = Set<String>()
        manualQuitAppPaths = []
        appsBeingRemovedPaths = []
        for app in my_apps {
            let displayName = (app.display_name as NSString).deletingPathExtension
            if !displayName.isEmpty, !seenNames.contains(displayName) {
                seenNames.insert(displayName)
                var appPath = app.pathname
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
        closedApps = []
        appRowDataForPath = [:]

        // Check if all blocking apps are being removed (uninstalled)
        // If so, we shouldn't offer to reopen them
        let allAppsBeingRemoved = !uniqueApps.isEmpty && uniqueApps.allSatisfy { app in
            !app.path.isEmpty && appsBeingRemovedPaths.contains(app.path)
        }

        // Create and configure the sheet
        let sheetWindow = createSheet(for: uniqueApps, hideReopenCheckbox: allAppsBeingRemoved)

        /*
         let sheetWindow = createSheet(
             for: [
                 (displayName: "Adobe Photoshop 2026", path: "/Applications/Adobe Photoshop 2026/Adobe Photoshop 2026.app"),
                 (displayName: "Geführte Softwareaktualisierung", path: "/Applications/Managed Software Center.app"),
                 (displayName: "Workspace ONE Intelligent Hub", path: "/Applications/Workspace ONE Intelligent Hub.app"),
             ])
         */

        sheet = sheetWindow

        // Track result
        var canContinue = false

        // Start monitoring for app closures
        startMonitoring(mainWindow: mainWindow)

        // Show the sheet and wait for it to complete
        mainWindow.beginSheet(sheetWindow) { [weak self] response in
            self?.monitorTimer?.invalidate()
            if response == .cancel {
                canContinue = false
            } else if response == .OK {
                canContinue = true
            }
            NSApp.stopModal()
        }

        // Run modal to block until sheet is dismissed
        NSApp.runModal(for: sheetWindow)
        monitorTimer?.invalidate()

        // Save apps to reopen if checkbox is checked, visible, and user didn't cancel
        // Exclude apps that are being removed as they won't exist after the update
        if canContinue, reopenCheckbox?.state == .on, reopenCheckbox?.isHidden == false {
            appsToReopenAfterUpdate = closedApps.filter { !appsBeingRemovedPaths.contains($0) }
        } else {
            appsToReopenAfterUpdate = []
        }

        // Cleanup
        cleanup()

        return canContinue
    }

    // MARK: - Private Methods

    /// Shows an alert informing the user that there are blocking processes running as other users
    /// (which might include root)
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
        alert.beginSheetModal(for: window)
    }

    /// Creates a sheet that lists blocking applications, and allows users to quit them
    private func createSheet(
        for apps: [(displayName: String, path: String)],
        hideReopenCheckbox: Bool = false
    ) -> NSWindow {
        let stackViewHeight = min(CGFloat(apps.count), CGFloat(maxVisibleRows)) * (rowHeight + stackViewSpacing)
        // Adjust height based on whether checkbox is shown
        let checkboxHeight: CGFloat = hideReopenCheckbox ? 0 : 28 // checkbox height + spacing
        let sheetHeight: CGFloat = stackViewHeight + 232 + checkboxHeight // Extra height for UI elements

        let sheetWindow = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: sheetWidth, height: sheetHeight),
            styleMask: [.titled, .docModalWindow],
            backing: .buffered,
            defer: true
        )

        let contentView = NSView(frame: NSRect(x: 0, y: 0, width: sheetWidth, height: sheetHeight))

        // Title label
        let titleLabel = NSTextField(
            labelWithString: NSLocalizedString(
                "Conflicting applications running",
                comment: "Blocking Apps Running title"
            )
        )
        titleLabel.font = NSFont.boldSystemFont(ofSize: NSFont.systemFontSize)
        titleLabel.translatesAutoresizingMaskIntoConstraints = false
        contentView.addSubview(titleLabel)

        // Message label
        let messageLabel = NSTextField(
            wrappingLabelWithString: NSLocalizedString(
                "You must quit these applications before proceeding with installation or removal:",
                comment: "Blocking Apps Running detail for auto-quit sheet"
            )
        )
        messageLabel.font = NSFont.systemFont(ofSize: NSFont.smallSystemFontSize)
        messageLabel.textColor = .secondaryLabelColor
        messageLabel.translatesAutoresizingMaskIntoConstraints = false
        contentView.addSubview(messageLabel)

        // Reopen apps checkbox (hidden if all apps are being removed)
        let checkbox = NSButton(checkboxWithTitle: NSLocalizedString(
            "Reopen applications after update",
            comment: "Reopen apps after update checkbox"
        ), target: nil, action: nil)
        checkbox.translatesAutoresizingMaskIntoConstraints = false
        checkbox.state = .on
        checkbox.isHidden = hideReopenCheckbox
        contentView.addSubview(checkbox)
        reopenCheckbox = checkbox
        
        // create a stack view for our action buttons
        let buttonStackView = NSStackView()
        buttonStackView.orientation = .vertical
        buttonStackView.alignment = .centerX
        //buttonStackView.spacing = stackViewSpacing
        buttonStackView.translatesAutoresizingMaskIntoConstraints = false

        // Quit Apps button
        let quitButton = NSButton(
            title: NSLocalizedString("Quit Apps and Update", comment: "Quit Apps and Update button title"),
            target: self, action: #selector(quitApps(_:))
        )
        quitButton.translatesAutoresizingMaskIntoConstraints = false
        quitButton.bezelStyle = .rounded
        if #available(macOS 11.0, *) {
            quitButton.controlSize = .large
        }
        quitButton.keyEquivalent = "\r"
        //contentView.addSubview(quitButton)
        buttonStackView.addArrangedSubview(quitButton)
        quitAppsButton = quitButton
        
        // Update others button
        if pythonishBool(pref("MSCOfferToUpdateOthers")) {
            let updateOthersButton = NSButton(
                title: NSLocalizedString("Skip and Update Others", comment: "Skip and Update Others button title"),
                target: self, action: #selector(updateOthers(_:))
            )
            updateOthersButton.translatesAutoresizingMaskIntoConstraints = false
            updateOthersButton.bezelStyle = .rounded
            if #available(macOS 11.0, *) {
                updateOthersButton.controlSize = .large
            }
            updateOthersButton.isEnabled = nonBlockedItemsPending
            //contentView.addSubview(updateOthersButton)
            buttonStackView.addArrangedSubview(updateOthersButton)
            NSLayoutConstraint.activate([
                updateOthersButton.widthAnchor.constraint(
                    equalTo: buttonStackView.widthAnchor),
            ])
            updateOtherItemsButton = updateOthersButton
        }
        
        // Cancel button
        let cancelButton = NSButton(
            title: NSLocalizedString("Cancel", comment: "Cancel button title/short action text"),
            target: self, action: #selector(cancelSheet(_:))
        )
        cancelButton.translatesAutoresizingMaskIntoConstraints = false
        cancelButton.bezelStyle = .rounded
        if #available(macOS 11.0, *) {
            cancelButton.controlSize = .large
        }
        cancelButton.keyEquivalent = "\u{1B}"
        //contentView.addSubview(cancelButton)
        buttonStackView.addArrangedSubview(cancelButton)
        
        NSLayoutConstraint.activate([
            cancelButton.widthAnchor.constraint(
                equalTo: buttonStackView.widthAnchor),
            quitButton.widthAnchor.constraint(
                equalTo: buttonStackView.widthAnchor),
        ])
        
        contentView.addSubview(buttonStackView)

        let actionButtonWidth = if let updateOtherItemsButton {
            max(
                quitButton.intrinsicContentSize.width,
                updateOtherItemsButton.intrinsicContentSize.width,
                228
            )
        } else {
            max(
                quitButton.intrinsicContentSize.width,
                228
            )
        }
        
        let adjustedSheetWidth = max(
            sheetWidth,
            actionButtonWidth + 2 * sheetMargin,
            titleLabel.intrinsicContentSize.width + 2 * sheetMargin,
            checkbox.intrinsicContentSize.width + 2 * sheetMargin
        )
        
        if adjustedSheetWidth > sheetWidth {
            var frame = sheetWindow.frame
            frame.size.width = adjustedSheetWidth
            sheetWindow.setFrame(frame,  display: true)
            sheetWidth = adjustedSheetWidth
        }
        
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
        
        // Layout constraints
        NSLayoutConstraint.activate([
            titleLabel.topAnchor.constraint(
                equalTo: contentView.topAnchor, constant: sheetMargin
            ),
            titleLabel.leadingAnchor.constraint(
                equalTo: contentView.leadingAnchor, constant: sheetMargin
            ),
            titleLabel.trailingAnchor.constraint(
                equalTo: contentView.trailingAnchor, constant: -sheetMargin
            ),

            messageLabel.topAnchor.constraint(
                equalTo: titleLabel.bottomAnchor, constant: 8
            ),
            messageLabel.leadingAnchor.constraint(
                equalTo: contentView.leadingAnchor, constant: sheetMargin
            ),
            messageLabel.trailingAnchor.constraint(
                equalTo: contentView.trailingAnchor, constant: -sheetMargin
            ),

            blockingScrollView.topAnchor.constraint(
                equalTo: messageLabel.bottomAnchor, constant: 12
            ),
            blockingScrollView.leadingAnchor.constraint(
                equalTo: contentView.leadingAnchor, constant: sheetMargin
            ),
            blockingScrollView.trailingAnchor.constraint(
                equalTo: contentView.trailingAnchor, constant: -sheetMargin
            ),
            blockingScrollView.heightAnchor.constraint(
                equalToConstant: stackViewHeight + 8),

            blockingStackView.topAnchor.constraint(
                equalTo: blockingScrollView.contentView.topAnchor),
            blockingStackView.leadingAnchor.constraint(
                equalTo: blockingScrollView.contentView.leadingAnchor, constant: 4
            ),
            blockingStackView.trailingAnchor.constraint(
                equalTo: blockingScrollView.contentView.trailingAnchor, constant: -4
            ),

            checkbox.topAnchor.constraint(
                equalTo: blockingScrollView.bottomAnchor, constant: 12
            ),
            checkbox.leadingAnchor.constraint(
                equalTo: contentView.leadingAnchor, constant: sheetMargin
            ),

            buttonStackView.centerXAnchor.constraint(
                equalTo: contentView.centerXAnchor),
            buttonStackView.widthAnchor.constraint(equalToConstant: actionButtonWidth),
            buttonStackView.bottomAnchor.constraint(
                equalTo: contentView.bottomAnchor, constant: -24
            ),
        ])

        sheetWindow.contentView = contentView
        return sheetWindow
    }

    /// Create the list of blocking apps
    private func createBlockingAppsStackView(
        apps: [(displayName: String, path: String)]
    ) -> NSStackView {
        appRowDataForPath.removeAll()
        let stackView = NSStackView()
        stackView.orientation = .vertical
        stackView.alignment = .leading
        stackView.spacing = stackViewSpacing
        stackView.translatesAutoresizingMaskIntoConstraints = false

        let spinnerSize: CGFloat = 16

        let sortedApps = apps.sorted {
            $0.displayName.lowercased() < $1.displayName.lowercased()
        }
        for app in sortedApps {
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
            nameLabel.font = NSFont.systemFont(ofSize: NSFont.systemFontSize)
            nameLabel.lineBreakMode = .byTruncatingTail

            rowView.addSubview(iconView)
            rowView.addSubview(nameLabel)

            let manualQuitLabel = createManualQuitLabel(for: app.path)
            rowView.addSubview(manualQuitLabel)

            if isManualQuit {
                // Show "Manual quit required" label for apps that can't be quit by us
                manualQuitLabel.isHidden = false
            }

            let forceQuitButton = createForceQuitButton(for: app.path)
            rowView.addSubview(forceQuitButton)
            let forceQuitButtonWidthConstraint = forceQuitButton.widthAnchor.constraint(
                equalToConstant: 0)

            // Progress spinner (hidden by default) for apps that can be quit by us
            let spinner = NSProgressIndicator()
            spinner.translatesAutoresizingMaskIntoConstraints = false
            spinner.style = .spinning
            spinner.controlSize = .small
            spinner.isHidden = true
            spinner.isDisplayedWhenStopped = false
            rowView.addSubview(spinner)

            // record things for later use
            if !app.path.isEmpty {
                appRowDataForPath[app.path] = BlockingAppRowData(
                    displayName: app.displayName,
                    rowView: rowView,
                    spinner: spinner,
                    manualQuitField: manualQuitLabel,
                    forceQuitButton: forceQuitButton,
                    forceQuitButtonWidthConstraint: forceQuitButtonWidthConstraint
                )
            }

            // Layout constraints
            NSLayoutConstraint.activate([
                // row
                rowView.heightAnchor.constraint(equalToConstant: rowHeight),
                rowView.widthAnchor.constraint(equalToConstant: sheetWidth - 40),

                // icon
                iconView.leadingAnchor.constraint(
                    equalTo: rowView.leadingAnchor, constant: 4
                ),
                iconView.centerYAnchor.constraint(
                    equalTo: rowView.centerYAnchor
                ),
                iconView.widthAnchor.constraint(equalToConstant: iconSize),
                iconView.heightAnchor.constraint(equalToConstant: iconSize),

                // name
                nameLabel.leadingAnchor.constraint(
                    equalTo: iconView.trailingAnchor, constant: 8
                ),
                nameLabel.trailingAnchor.constraint(
                    lessThanOrEqualTo: forceQuitButton.leadingAnchor,
                    constant: -8
                ),
                nameLabel.centerYAnchor.constraint(
                    equalTo: rowView.centerYAnchor
                ),

                // manual quit text
                manualQuitLabel.leadingAnchor.constraint(
                    equalTo: iconView.trailingAnchor, constant: 8
                ),
                manualQuitLabel.trailingAnchor.constraint(
                    lessThanOrEqualTo: spinner.leadingAnchor, constant: -8
                ),
                manualQuitLabel.topAnchor.constraint(
                    equalTo: nameLabel.bottomAnchor),

                // force quit button
                forceQuitButton.trailingAnchor.constraint(
                    equalTo: rowView.trailingAnchor, constant: -4
                ),
                forceQuitButton.centerYAnchor.constraint(
                    equalTo: rowView.centerYAnchor
                ),
                forceQuitButtonWidthConstraint,

                // progress spinner
                spinner.trailingAnchor.constraint(
                    equalTo: rowView.trailingAnchor, constant: -4
                ),
                spinner.centerYAnchor.constraint(equalTo: rowView.centerYAnchor),
                spinner.widthAnchor.constraint(equalToConstant: spinnerSize),
                spinner.heightAnchor.constraint(equalToConstant: spinnerSize),
            ])

            stackView.addArrangedSubview(rowView)
        }

        return stackView
    }

    /// Removes a closed app from the list of blocking apps and adds it to a list of closed apps
    private func moveAppToClosedApps(path: String) {
        guard !closedApps.contains(path),
              let rowView = appRowDataForPath[path]?.rowView,
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

    private func startMonitoring(mainWindow: NSWindow) {
        let appsToCheckCopy = appsToCheck
        let currentUserCopy = currentUser

        let timer = Timer(timeInterval: 1.0, repeats: true) { [weak self, weak mainWindow] timer in
            guard let self, let mainWindow else {
                timer.invalidate()
                return
            }

            let stillRunning = getRunningBlockingApps(appsToCheckCopy)
            let myStillRunning = stillRunning.filter { $0.user == currentUserCopy }

            // Get the paths of still-running apps (extract the executable paths)
            var stillRunningPaths = Set<String>()
            for app in myStillRunning {
                let appPath = app.pathname
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
            // Timer is already on main RunLoop with .common mode, so we're on the main thread
            let now = Date()

            for app in appsToQuit {
                msc_debug_log("Checking app: \(app.displayName) path=\(app.path) isEmpty=\(app.path.isEmpty) isStillRunning=\(isAppStillRunning(app.path)) inClosedList=\(closedApps.contains(app.path))")
                if !app.path.isEmpty, !isAppStillRunning(app.path), !closedApps.contains(app.path) {
                    msc_debug_log("Moving app to closed apps: \(app.displayName) at \(app.path)")
                    moveAppToClosedApps(path: app.path)
                    if pythonishBool(pref("MSCOfferToUpdateOthers")),
                       let updateOthersButton = updateOtherItemsButton
                    {
                        updateOthersButton.isHidden = false
                    }
                }

                // Check if app has exceeded force quit delay and is still running
                if let quitTime = appRowDataForPath[app.path]?.quitInitiatedTime,
                   now.timeIntervalSince(quitTime) >= self.forceQuitDelay,
                   isAppStillRunning(app.path),
                   !self.closedApps.contains(app.path)
                {
                    // Show force quit button for this app
                    showForceQuitButton(for: app.path)
                }
            }

            if myStillRunning.isEmpty {
                // All apps have been closed
                timer.invalidate()
                if let sheetWindow = sheet {
                    mainWindow.endSheet(sheetWindow, returnCode: .OK)
                }
            }
        }

        // Add timer to common run loop modes so it fires during modal sessions
        RunLoop.main.add(timer, forMode: .common)
        monitorTimer = timer
    }

    private func createManualQuitLabel(for _: String) -> NSTextField {
        let manualQuitLabel = NSTextField(labelWithString: NSLocalizedString(
            "Manual quit required",
            comment: "Manual quit required label"
        ))
        manualQuitLabel.translatesAutoresizingMaskIntoConstraints = false
        manualQuitLabel.font = NSFont.systemFont(ofSize: 10)
        manualQuitLabel.textColor = .systemOrange
        manualQuitLabel.alignment = .right
        manualQuitLabel.isHidden = true

        return manualQuitLabel
    }

    private func showManualQuitLabel(for appPath: String) {
        guard let manualQuitLabel = appRowDataForPath[appPath]?.manualQuitField
        else {
            return
        }
        manualQuitLabel.isHidden = false
    }

    private func createForceQuitButton(for appPath: String) -> NSButton {
        // Create the Force Quit button
        let forceQuitButton = NSButton(
            title: NSLocalizedString(
                "Force Quit", comment: "Force Quit button title"
            ),
            target: self,
            action: #selector(forceQuitButtonClicked(_:))
        )
        forceQuitButton.translatesAutoresizingMaskIntoConstraints = false
        forceQuitButton.bezelStyle = .rounded
        forceQuitButton.controlSize = .small
        forceQuitButton.font = NSFont.systemFont(ofSize: 10)
        forceQuitButton.isHidden = true

        // Store the app path in the button's identifier for later retrieval
        forceQuitButton.identifier = NSUserInterfaceItemIdentifier(appPath)

        return forceQuitButton
    }

    private func showForceQuitButton(for appPath: String) {
        guard let appRowData = appRowDataForPath[appPath],
              let spinner = appRowData.spinner,
              let forceQuitButton = appRowData.forceQuitButton,
              let widthConstraint = appRowData.forceQuitButtonWidthConstraint
        else {
            return
        }
        // Hide and stop the spinner
        spinner.stopAnimation(nil)
        spinner.isHidden = true

        // Check if MSCOfferToForceQuitBlockingApps is enabled
        let offerToForceQuitEnabled = pythonishBool(pref("MSCOfferToForceQuitBlockingApps"))
        if !offerToForceQuitEnabled {
            // Show "Manual quit required" label instead of Force Quit button
            showManualQuitLabel(for: appPath)
            return
        }
        forceQuitButton.isHidden = false
        NSLayoutConstraint.deactivate([widthConstraint])
        NSLayoutConstraint.activate([
            forceQuitButton.widthAnchor.constraint(
                equalToConstant: forceQuitButton.intrinsicContentSize.width),
        ])
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
        let bundlePrefix = appPath + "/"
        // NSRunningApplication.bundleURL.path always ends with a /
        // so build our comparison URL with a path ending with a /
        let bundleURL = URL(fileURLWithPath: bundlePrefix)

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

        // Hide the force quit button and show spinner while we wait for it to close
        if var appRowData = appRowDataForPath[appPath],
           let button = appRowData.forceQuitButton,
           let spinner = appRowData.spinner
        {
            button.isHidden = true
            spinner.isHidden = false
            spinner.startAnimation(nil)
            // Reset the quit initiation time so we don't immediately show the force quit button again
            appRowData.quitInitiatedTime = Date()
            appRowDataForPath[appPath] = appRowData
        }
    }

    private func cleanup() {
        sheet = nil
        appRowDataForPath = [:]
        appsToQuit = []
        quitAppsButton = nil
        monitorTimer = nil
        appsToCheck = []
        blockingAppsStackView = nil
        closedApps = []
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

    /// Action when clicking the Update others button;
    /// closes the sheet and allows update to continue
    @objc private func updateOthers(_: Any?) {
        guard let sheetWindow = sheet,
              let mainWindow = parentWindow
        else {
            return
        }
        mainWindow.endSheet(sheetWindow, returnCode: .OK)
    }

    /// Action when clicking Cancel button;
    /// closes the sheet and does not allow the update to continue
    @objc private func cancelSheet(_: Any?) {
        guard let sheetWindow = sheet,
              let mainWindow = parentWindow
        else {
            return
        }
        mainWindow.endSheet(sheetWindow, returnCode: .cancel)
    }

    /// Action when clicking Quit Apps button;
    /// Begins attempts to quit the blocking apps
    @objc private func quitApps(_: Any?) {
        quitAppsButton?.isEnabled = false

        for app in appsToQuit {
            guard !app.path.isEmpty else { continue }

            // Skip apps that require manual quit
            if manualQuitAppPaths.contains(app.path) {
                msc_debug_log("Skipping quit attempt for manual quit app: \(app.displayName)")
                continue
            }

            // Only show spinner for apps that haven't been closed yet
            if !closedApps.contains(app.path) {
                if let spinner = appRowDataForPath[app.path]?.spinner {
                    spinner.isHidden = false
                    spinner.startAnimation(nil)
                }

                // Record quit initiation time for force quit tracking
                if var appRowData = appRowDataForPath[app.path] {
                    appRowData.quitInitiatedTime = Date()
                    appRowDataForPath[app.path] = appRowData
                }

                // Check for custom quit script
                let appFileName = (app.path as NSString).lastPathComponent
                if let quitScript = appQuitScripts[appFileName] {
                    // Run the custom quit script instead of default termination
                    msc_debug_log("Running blocking_applications_quit_script for \(app.displayName)")
                    DispatchQueue.global(qos: .userInitiated).async {
                        let result = runEmbeddedScript(quitScript, scriptName: "blocking_applications_quit_script")
                        DispatchQueue.main.async {
                            if result.exitcode != 0 {
                                msc_debug_log("blocking_applications_quit_script for \(app.displayName) failed with exit code \(result.exitcode)")
                            } else {
                                msc_debug_log("blocking_applications_quit_script for \(app.displayName) completed successfully")
                            }
                        }
                    }
                } else {
                    // Use default termination logic
                    // Find the running application by its bundle URL and terminate it
                    let bundlePrefix = app.path + "/"
                    // NSRunningApplication.bundleURL.path always ends with a /
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
    }
}
