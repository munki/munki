//
//  BlurredBackgroundController.swift
//
//  Heavily based on code by Bart Reardon in CocoaDialog
//  Copyright © 2024-2026 The Munki Project

import Foundation
import Cocoa


class BlurWindow: NSWindow {
    override init(contentRect: NSRect, styleMask style: NSWindow.StyleMask, backing backingStoreType: NSWindow.BackingStoreType, defer flag: Bool) {
        super.init(contentRect: contentRect, styleMask: [.fullSizeContentView],  backing: .buffered, defer: true)
     }
}

class BlurWindowController: NSWindowController {
    
    var screen = NSScreen.main

    override func loadWindow() {
        window = BlurWindow(contentRect: CGRect(x: 0, y: 0, width: 100, height: 100), styleMask: [], backing: .buffered, defer: true)
        self.window?.contentViewController = BlurViewController()
        if let screen {
            self.window?.setFrame((screen.frame), display: true)
            self.window?.setFrameOrigin(screen.frame.origin)
        }
        self.window?.collectionBehavior = [.canJoinAllSpaces]
        /*if atLoginWindow() {
            self.window?.canBecomeVisibleWithoutLogin = true
        }*/
    }
}

class BlurViewController: NSViewController {

    init() {
         super.init(nibName: nil, bundle: nil)
     }

    required init?(coder: NSCoder) {
         fatalError()
     }

    override func loadView() {
        super.viewDidLoad()
        self.view = NSView()
    }

    override func viewWillAppear() {
        super.viewWillAppear()
        view.window?.isOpaque = false
        view.window?.level = NSWindow.Level(rawValue: Int(CGWindowLevelForKey(.maximumWindow) - 1 ))

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

class BackgroundBlurrer {
    
    var blurredScreen = [BlurWindowController]()
    
    init() {
        let screens = NSScreen.screens
        for (index, screen) in screens.enumerated() {
            blurredScreen.append(BlurWindowController())
            blurredScreen[index].screen = screen
            blurredScreen[index].close()
            blurredScreen[index].loadWindow()
            blurredScreen[index].showWindow(self)
        }
    }

    deinit {
        for controller in blurredScreen {
            controller.close()
        }
        blurredScreen = [BlurWindowController]()
    }

    func lowerWindowLevels() {
        for controller in blurredScreen {
            controller.window?.level = .normal
        }
    }

    
}
