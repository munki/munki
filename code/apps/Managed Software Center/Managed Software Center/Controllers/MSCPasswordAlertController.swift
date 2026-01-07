//
//  MSCPasswordAlertController.swift
//  Managed Software Center
//
//  Created by Greg Neagle on 7/17/18.
//  Copyright © 2018-2026 The Munki Project. All rights reserved.
//

import Cocoa

class MSCPasswordAlertController: NSObject {
    // An object that handles our password alert
    
    // Cocoa UI binding properties
    @IBOutlet weak var passwordView: NSView!
    @IBOutlet weak var passwordLabel: NSTextField!
    @IBOutlet weak var passwordField: NSSecureTextField!
    
    func promptForPasswordForAuthRestart() {
        // Set up and display our alert that prompts for password
        let alert = NSAlert()
        alert.addButton(withTitle: NSLocalizedString("Allow", comment: "Allow button text"))
        alert.addButton(withTitle: NSLocalizedString("Deny", comment: "Deny button text"))
        alert.messageText = NSLocalizedString(
            "Managed Software Center wants to unlock the startup disk after " +
            "restarting to complete all pending updates.",
            comment: "Password prompt title")
        alert.informativeText = NSLocalizedString(
            "To allow this, enter your login password.",
            comment: "Password explanation")
        alert.accessoryView = passwordView
        passwordLabel.stringValue = NSLocalizedString(
            "Password:", comment: "Password label")
        passwordField.stringValue = ""
        passwordLabel.sizeToFit()
        // resize the password field to use the rest of the available space
        let viewWidth = passwordView.frame.size.width
        let labelWidth = passwordLabel.frame.size.width
        var fieldFrame = passwordField.frame
        fieldFrame.origin.x = labelWidth + 8
        fieldFrame.size.width = viewWidth - labelWidth - 8
        passwordField.frame = fieldFrame
        // add esc as a key equivalent for the Deny button
        alert.buttons[1].keyEquivalent = "\u{1B}"
        // change the Allow button to call our password validation method
        let allowButton = alert.buttons[0]
        allowButton.target = self
        allowButton.action = #selector(self.verifyPassword)
        // make sure our password field is ready to accept input
        alert.window.initialFirstResponder = passwordField
        // we can finally run the alert!
        let result = alert.runModal()
        alert.window.orderOut(nil)
        if result == .alertFirstButtonReturn {
            // they clicked "Allow". We handled it in the verifyPassword method
            msc_log("user", "stored password for auth restart")
        } else if result == .alertSecondButtonReturn {
            // they clicked "Deny"
            msc_log("user", "denied password for auth restart")
        }
    }
    
    @objc func verifyPassword(_ alert: NSAlert) {
        // verify the password entered; if it verifies, store it for authrestart
        // otherwise shake the window and let the user try again or cancel/deny
        let username = NSUserName()
        let password = passwordField.stringValue
        if verifyODPassword(username: username, password: password) {
            // store username and password and end modal alert
            _ = storePassword(password, forUserName: username)
            NSApplication.shared.stopModal(withCode: .alertFirstButtonReturn)
        } else {
            // wrong password, shake the alert window
            shake(alert.window)
        }
    }
    
    func shake(_ the_window: NSWindow) {
        // Uses CoreAnimation to "shake" the alert window
        // adapted from here:
        // http://stackoverflow.com/questions/10517386/how-to-give-nswindow-a-shake-effect-as-saying-no-as-in-login-failure-window/23491643#23491643
        
        let numberOfShakes = 3
        let durationOfShake = 0.5
        let vigourOfShake = 0.05
        
        let frame = the_window.frame
        let shakeAnimation = CAKeyframeAnimation()
        
        let shakePath = CGMutablePath()
        shakePath.move(to: CGPoint(x: NSMinX(frame), y: NSMinY(frame)))
        for _ in 1...numberOfShakes {
            shakePath.addLine(to: CGPoint(x: NSMinX(frame) - frame.size.width * CGFloat(vigourOfShake), y: NSMinY(frame)))
            shakePath.addLine(to: CGPoint(x: NSMinX(frame) + frame.size.width * CGFloat(vigourOfShake), y: NSMinY(frame)))
        }
        shakePath.closeSubpath()
        shakeAnimation.path = shakePath
        shakeAnimation.duration = durationOfShake
        
        let frameOriginKey = "frameOrigin"
        the_window.animations = [frameOriginKey: shakeAnimation]
        the_window.animator().setFrameOrigin(frame.origin)
    }
}
