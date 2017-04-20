# -*- coding: utf-8 -*-
#
#  PasswordSheetController.py
#  Managed Software Center
#
#  Created by Greg Neagle on 4/17/17.
#  Copyright (c) 2017 The Munki Project. All rights reserved.
#
'''Controller for our custom restart alert that prompts for password'''

from objc import IBAction, IBOutlet, nil
from AppKit import *
from Foundation import *
from PyObjCTools import AppHelper
from Quartz import CAKeyframeAnimation, CATransaction

import authrestart
import msclog
import munki
import passwdutil


# Disable PyLint complaining about 'invalid' camelCase names
# pylint: disable=C0103

class MSCPasswordSheetController(NSWindowController):
    '''An object that handles our password sheet'''

    # instance variables
    alert_controller = None

    # Cocoa UI binding properties
    passwordSheet = IBOutlet()
    sheetTitleLabel = IBOutlet()
    sheetDetailLabel = IBOutlet()
    sheetPasswordDetailLabel = IBOutlet()
    sheetPasswordLabel = IBOutlet()
    sheetPasswordField = IBOutlet()
    okButton = IBOutlet()
    cancelButton = IBOutlet()

    def promptForPasswordForAuthRestart(self, alert_controller):
        '''Set up and display our restart alert that prompts for password'''
        self.alert_controller = alert_controller
        self.sheetTitleLabel.setStringValue_(NSLocalizedString(
            u"Restart Required", u"Restart Required title"))
        self.sheetDetailLabel.setStringValue_(NSLocalizedString(
            u"A restart is required after updating. Log out and update now?",
            u"Restart Required detail, shorter"))
        self.sheetPasswordDetailLabel.setStringValue_(NSLocalizedString(
            u"This computer is protected by FileVault. "
            "A password is required to unlock the startup disk after restart. "
            "Enter your password to allow this.",
            u"Restart Password explanation"))
        self.sheetPasswordLabel.setStringValue_(NSLocalizedString(
            u"Password:", u"Password label"))
        self.okButton.setTitle_(NSLocalizedString(
            u"Log out and update", u"Log out and Update button text"))
        self.cancelButton.setTitle_(NSLocalizedString(
            u"Cancel", u"Cancel button title/short action text"))

        self.sheetPasswordField.setStringValue_("")
        NSApp.beginSheet_modalForWindow_modalDelegate_didEndSelector_contextInfo_(
            self.passwordSheet, alert_controller.window, self,
            self.promptForPasswordSheetDidEnd_returnCode_contextInfo_, nil)

    @AppHelper.endSheetMethod
    def promptForPasswordSheetDidEnd_returnCode_contextInfo_(
            self, sheet, returncode, contextinfo):
        '''Called when promptForPasswordSheet ends'''
        sheet.orderOut_(self)

    @IBAction
    def cancelPasswordSheet_(self, sender):
        '''React to user clicking Cancel in the sheet'''
        NSApp.endSheet_(self.passwordSheet)
        msclog.log("user", "cancelled")

    @IBAction
    def okClickedForPasswordSheet_(self, sender):
        '''React to user clicking the "Logout and install" button in the
        sheet'''
        username = NSUserName()
        password = self.sheetPasswordField.stringValue()
        if len(password) and not passwdutil.verifyPassword(username, password):
            self.badPasswordField_(self.sheetPasswordField)
        else:
            NSApp.endSheet_(self.passwordSheet)
            if self.alert_controller.alertedToFirmwareUpdatesAndCancelled():
                msclog.log("user", "alerted_to_firmware_updates_and_cancelled")
                return
            elif self.alert_controller.alertedToRunningOnBatteryAndCancelled():
                msclog.log("user", "alerted_on_battery_power_and_cancelled")
                return
            msclog.log("user", "install_with_logout")
            # store the password for auth restart
            authrestart.store_password(password)
            result = munki.logoutAndUpdate()
            if result:
                self.alert_controller.installSessionErrorAlert()


    def badPasswordField_(self, textField):
        '''Uses CoreAnimation to "shake" the password field, then clears it'''
        # adapted from tburgin's work here:
        # https://github.com/google/macops-keychainminder/blob/master/KeychainMinderGUI/PasswordViewController.m

        def makeShakeAnimation():
            '''CoreAnimation Keyframe "shake" animation'''
            animation = CAKeyframeAnimation.animation()
            animation.setKeyPath_("position.x")
            animation.setValues_([0, 10, -10, 10, -10, 10, 0])
            animation.setKeyTimes_(
                [0, 1.0/6.0, 2.0/6.0, 3.0/6.0, 4.0/6.0, 5.0/6.0, 1])
            animation.setDuration_(0.6)
            animation.setAdditive_(True)
            return animation

        def animationComplete():
            '''Used as a completion block for CATransaction'''
            textField.setStringValue_("")
            textField.setEnabled_(True)

        # attach and run our animation
        CATransaction.begin()
        CATransaction.setCompletionBlock_(animationComplete)
        textField.layer().addAnimation_forKey_(makeShakeAnimation(), 'shake')
        CATransaction.commit()
