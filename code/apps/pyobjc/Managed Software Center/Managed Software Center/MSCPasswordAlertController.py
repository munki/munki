# -*- coding: utf-8 -*-
#
#  MSCPasswordAlertController.py
#  Managed Software Center
#
#  Created by Greg Neagle on 4/17/17.
#  Copyright (c) 2018-2019 The Munki Project. All rights reserved.
#
'''Controller for our custom alert that prompts for password'''

from objc import IBAction, IBOutlet, nil
from PyObjCTools import AppHelper
from Quartz import CAKeyframeAnimation, CGPathCreateMutable
from Quartz import CGPathAddLineToPoint, CGPathMoveToPoint
from Quartz import CGPathCloseSubpath
#from Foundation import *
#from AppKit import *

# pylint: disable=wildcard-import
from CocoaWrapper import *
# pylint: enable=wildcard-import


import authrestart
import msclog
import munki
import passwdutil


# Disable PyLint complaining about 'invalid' camelCase names
# pylint: disable=C0103

class MSCPasswordAlertController(NSObject):
    '''An object that handles our password alert'''

    # Cocoa UI binding properties
    passwordView = IBOutlet()
    passwordLabel = IBOutlet()
    passwordField = IBOutlet()

    def promptForPasswordForAuthRestart(self):
        '''Set up and display our alert that prompts for password'''
        # Set up all the fields and buttons with localized text
        alert = NSAlert.alloc().init()
        alert.addButtonWithTitle_(
            NSLocalizedString(u"Allow", u"Allow button text"))
        alert.addButtonWithTitle_(
            NSLocalizedString(u"Deny", u"Deny button text"))
        alert.setMessageText_(NSLocalizedString(
            u"Managed Software Center wants to unlock the startup disk after "
            "restarting to complete all pending updates.",
            u"Password prompt title"))
        alert.setInformativeText_(NSLocalizedString(
            u"To allow this, enter your login password.",
            u"Password explanation"))
        alert.setAccessoryView_(self.passwordView)
        self.passwordLabel.setStringValue_(NSLocalizedString(
            u"Password:",u"Password label"))
        self.passwordField.setStringValue_(u"")
        # resize label to fit the text
        self.passwordLabel.sizeToFit()
        # resize the password field to use the rest of the available space
        viewWidth = self.passwordView.frame().size.width
        labelWidth = self.passwordLabel.frame().size.width
        fieldFrame = self.passwordField.frame()
        fieldFrame.origin.x = labelWidth + 8
        fieldFrame.size.width = viewWidth - labelWidth - 8
        self.passwordField.setFrame_(fieldFrame)
        # add esc as a key equivalent for the Deny button
        alert.buttons().objectAtIndex_(1).setKeyEquivalent_(chr(27))
        # change the Allow button to call our password validation method
        allowButton = alert.buttons().objectAtIndex_(0)
        allowButton.setTarget_(self)
        allowButton.setAction_(self.verifyPassword_)
        # make sure our password field is ready to accept input
        alert.window().setInitialFirstResponder_(self.passwordField)
        # we can finally run the alert!
        result = alert.runModal()
        if result == NSAlertFirstButtonReturn:
            # they clicked "Allow". We handled it in the verifyPassword method
            msclog.log("user", "stored password for auth restart")
        if result == NSAlertSecondButtonReturn:
            # they clicked "Deny"
            msclog.log("user", "denied password for auth restart")

    def verifyPassword_(self, alert):
        username = NSUserName()
        password = self.passwordField.stringValue()
        if passwdutil.verifyPassword(username, password):
            # store username and password and end modal alert
            authrestart.store_password(password, username=username)
            code = NSAlertFirstButtonReturn
            NSApplication.sharedApplication().stopModalWithCode_(code)
            NSApplication.sharedApplication().endSheet_returnCode_(
                alert, code)
            alert.window().orderOut_(None)
        else:
            # wrong password, shake the alert window
            self.shake(alert.window())

    def shake(self, the_window):
        '''Uses CoreAnimation to "shake" the alert window'''
        # adapted from here:
        # http://stackoverflow.com/questions/10517386/how-to-give-nswindow-a-shake-effect-as-saying-no-as-in-login-failure-window/23491643#23491643

        numberOfShakes = 3
        durationOfShake = 0.5
        vigourOfShake = 0.05

        frame = the_window.frame()
        shakeAnimation = CAKeyframeAnimation.animation()

        shakePath = CGPathCreateMutable()
        CGPathMoveToPoint(shakePath, None, NSMinX(frame), NSMinY(frame))
        for index in range(numberOfShakes):
            CGPathAddLineToPoint(
                shakePath, None,
                NSMinX(frame) - frame.size.width * vigourOfShake, NSMinY(frame))
            CGPathAddLineToPoint(
                shakePath, None,
                NSMinX(frame) + frame.size.width * vigourOfShake, NSMinY(frame))
        CGPathCloseSubpath(shakePath)
        shakeAnimation.setPath_(shakePath)
        shakeAnimation.setDuration_(durationOfShake)

        the_window.setAnimations_({'frameOrigin': shakeAnimation})
        the_window.animator().setFrameOrigin_(frame.origin)