//
//  BlurredBackgroundController.swift
//
//  Heavily based on code by Bart Reardon in CocoaDialog
//

import Cocoa
import Foundation

class BlurWindow: NSWindow {
    override init(contentRect: NSRect, styleMask _: NSWindow.StyleMask, backing _: NSWindow.BackingStoreType, defer _: Bool) {
        super.init(contentRect: contentRect, styleMask: [.fullSizeContentView], backing: .buffered, defer: true)
    }
}

class BlurWindowController: NSWindowController {
    var screen: CGDirectDisplayID? = nil

    func updateWindowRect() {
        if let screen {
            let bounds = appKitDisplayBounds(screen)
            if let window = window {
                window.setFrame(bounds, display: true)
                window.setFrameOrigin(bounds.origin)
            }
        }
    }

    override func loadWindow() {
        window = BlurWindow(
            contentRect: CGRect(x: 0, y: 0, width: 100, height: 100),
            styleMask: [],
            backing: .buffered,
            defer: true
        )
        window?.contentViewController = BlurViewController()
        window?.collectionBehavior = [.canJoinAllSpaces]
        if atLoginWindow() {
            window?.canBecomeVisibleWithoutLogin = true
        }
        updateWindowRect()
    }
}

class BlurViewController: NSViewController {
    init() {
        super.init(nibName: nil, bundle: nil)
    }

    @available(*, unavailable)
    required init?(coder _: NSCoder) {
        fatalError()
    }

    override func loadView() {
        super.viewDidLoad()
        view = NSView()
    }

    override func viewWillAppear() {
        super.viewWillAppear()
        view.window?.isOpaque = false
        view.window?.level = backdropWindowLevel

        let blurView = NSVisualEffectView(frame: view.bounds)
        blurView.blendingMode = .behindWindow
        if #available(macOS 10.14, *) {
            blurView.material = .fullScreenUI
        } else {
            // Fallback on earlier versions
            blurView.material = .sidebar
        }
        blurView.state = .active
        view.window?.contentView?.addSubview(blurView)
    }

    override func viewWillDisappear() {
        super.viewWillDisappear()
        view.window?.contentView?.removeFromSuperview()
    }
}

func getCGDisplayIds() -> [CGDirectDisplayID] {
    var displayCount: UInt32 = 0
    let err = CGGetActiveDisplayList(0, nil, &displayCount)
    if err == .success {
        var displayIDs: [CGDirectDisplayID] = Array(repeating: 0, count: Int(displayCount))
        let err = CGGetActiveDisplayList(displayCount, &displayIDs, nil)
        if err == .success {
            return displayIDs
        }
    }
    return []
}

/// Converts CGDisplayBounds to NSScreen.frame coordinates
func appKitDisplayBounds(_ display: CGDirectDisplayID) -> CGRect {
    let bounds = CGDisplayBounds(display)
    let mainDisplayHeight = CGDisplayBounds(CGMainDisplayID()).size.height
    return CGRect(x: bounds.origin.x,
                  y: mainDisplayHeight - bounds.origin.y - bounds.size.height,
                  width: bounds.size.width,
                  height: bounds.size.height)
}

class BackgroundBlurrer {
    var blurWindows = [BlurWindowController]()

    init() {
        for screen in getCGDisplayIds() {
            let blurWindow = BlurWindowController()
            blurWindow.screen = screen
            blurWindow.close()
            blurWindow.loadWindow()
            blurWindow.showWindow(self)
            blurWindows.append(blurWindow)
        }
        // React to display connected / disconnected / resized events
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(updateBlur),
            name: NSApplication.didChangeScreenParametersNotification,
            object: nil
        )
    }

    @objc func updateBlur() {
        let currentScreens = getCGDisplayIds()
        var existingScreens: Set<CGDirectDisplayID> = []
        for blurWindow in blurWindows {
            if let screen = blurWindow.screen {
                if !currentScreens.contains(screen) {
                    // a screen was detached/deactivated
                    blurWindow.close()
                    blurWindow.screen = nil
                } else {
                    existingScreens.insert(screen)
                    let screenRect = appKitDisplayBounds(screen)
                    let windowRect = blurWindow.window?.frame ?? .zero
                    if screenRect != windowRect {
                        // screen changed location or size
                        // we tried just resizing the window to match, but that
                        // did not work consistently at the loginwindow
                        // so just close the current window and open a new one
                        DispatchQueue.main.async {
                            blurWindow.close()
                            blurWindow.loadWindow()
                            blurWindow.showWindow(self)
                        }
                    }
                }
            }
        }
        // remove any controllers that don't have screens
        blurWindows.removeAll { $0.screen == nil }
        // now look for new screens
        for screen in currentScreens {
            if !existingScreens.contains(screen) {
                // a screen was attached
                let blurWindow = BlurWindowController()
                blurWindow.screen = screen
                DispatchQueue.main.async {
                    blurWindow.close()
                    blurWindow.loadWindow()
                    blurWindow.showWindow(self)
                }
                blurWindows.append(blurWindow)
            }
        }
    }

    deinit {
        for blurWindow in blurWindows {
            blurWindow.close()
        }
        blurWindows = [BlurWindowController]()
    }
}
