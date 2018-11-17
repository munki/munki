# encoding: utf-8
#
#  AlertController.py
#  Managed Software Center
#
#  Created by Greg Neagle on 2/25/14.
#

import os

import authrestart
import munki
import msclog
import MunkiItems

from objc import nil
from AppKit import *
from Foundation import *
from PyObjCTools import AppHelper

# Disable PyLint complaining about 'invalid' camelCase names
# pylint: disable=C0103

class AlertController(NSObject):
    '''An object that handles some of our alerts, if for no other reason
    than to move a giant bunch of ugly code out of the WindowController'''

    def setWindow_(self, the_window):
        '''Store our parent window'''
        self.window = the_window

    def handlePossibleAuthRestart(self):
        '''Ask for and store a password for auth restart if needed/possible'''
        username = NSUserName()
        if (MunkiItems.updatesRequireRestart() and
                authrestart.verify_user(username) and
                not authrestart.verify_recovery_key_present()):
            # FV is on and user is in list of FV users, so they can
            # authrestart, and we do not have a stored FV recovery
            # key/password. So we should prompt the user for a password
            # we can use for fdesetup authrestart
            NSApp.delegate(
                ).passwordAlertController.promptForPasswordForAuthRestart()

    def forcedLogoutWarning(self, notification_obj):
        '''Display a forced logout warning'''
        NSApp.activateIgnoringOtherApps_(True)
        info = notification_obj.userInfo()
        moreText = NSLocalizedString(
            u"All pending updates will be installed. Unsaved work will be lost."
            "\nYou may avoid the forced logout by logging out now.",
            u"Forced Logout warning detail")
        logout_time = None
        if info:
            logout_time = info.get('logout_time')
        elif munki.thereAreUpdatesToBeForcedSoon():
            logout_time = munki.earliestForceInstallDate()
        if not logout_time:
            return
        time_til_logout = int(logout_time.timeIntervalSinceNow() / 60)
        if time_til_logout > 55:
            deadline_str = munki.stringFromDate(logout_time)
            msclog.log("user", "forced_logout_warning_initial")
            formatString = NSLocalizedString(
                u"A logout will be forced at approximately %s.",
                u"Logout warning string when logout is an hour or more away")
            infoText = formatString % deadline_str + u"\n" + moreText
        elif time_til_logout > 0:
            msclog.log("user", "forced_logout_warning_%s" % time_til_logout)
            formatString = NSLocalizedString(
                u"A logout will be forced in less than %s minutes.",
                u"Logout warning string when logout is in < 60 minutes")
            infoText = formatString % time_til_logout + u"\n" + moreText
        else:
            msclog.log("user", "forced_logout_warning_final")
            infoText = NSLocalizedString(
                u"A logout will be forced in less than a minute.\nAll pending "
                "updates will be installed. Unsaved work will be lost.",
                u"Logout warning string when logout is in less than a minute")

        # Set the OK button to default, unless less than 5 minutes to logout
        # in which case only the Logout button should be displayed.
        self._force_warning_logout_btn = NSLocalizedString(
            u"Log out and update now", u"Logout and Update Now button text")
        self._force_warning_ok_btn = NSLocalizedString(u"OK",
                                                       u"OK button title")
        if time_til_logout > 5:
            self._force_warning_btns = {
                NSAlertDefaultReturn: self._force_warning_ok_btn,
                NSAlertAlternateReturn: self._force_warning_logout_btn,
            }
        else:
            self._force_warning_btns = {
                NSAlertDefaultReturn: self._force_warning_logout_btn,
                NSAlertAlternateReturn: nil,
            }

        if self.window.attachedSheet():
            # there's an existing sheet open
            NSApp.endSheet_(self.window.attachedSheet())

        alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(
            NSLocalizedString(
                u"Forced Logout for Mandatory Install",
                u"Forced Logout title text"),
            self._force_warning_btns[NSAlertDefaultReturn],
            self._force_warning_btns[NSAlertAlternateReturn],
            nil,
            u"%@", infoText)
        alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(
            self.window, self,
            self.forceLogoutWarningDidEnd_returnCode_contextInfo_, nil)

    @AppHelper.endSheetMethod
    def forceLogoutWarningDidEnd_returnCode_contextInfo_(
            self, alert, returncode, contextinfo):
        '''Called when the forced logout warning alert ends'''
        btn_pressed = self._force_warning_btns.get(returncode)
        if btn_pressed == self._force_warning_logout_btn:
            msclog.log("user", "install_with_logout")
            self.handlePossibleAuthRestart()
            try:
                munki.logoutAndUpdate()
            except munki.ProcessStartError, err:
                self.installSessionErrorAlert_(err)
        elif btn_pressed == self._force_warning_ok_btn:
            msclog.log("user", "dismissed_forced_logout_warning")

    def alertToExtraUpdates(self):
        '''Notify user of additional pending updates'''
        msclog.log("user", "extra_updates_pending")
        alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(
            NSLocalizedString(
                u"Additional Pending Updates",
                u"Additional Pending Updates title"),
            NSLocalizedString(u"OK", u"OK button title"),
            nil,
            nil,
            u"%@", NSLocalizedString(
                u"There are additional pending updates to install or remove.",
                u"Additional Pending Updates detail")
            )
        alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(
            self.window, self,
            self.extraUpdatesAlertDidEnd_returnCode_contextInfo_, nil)

    @AppHelper.endSheetMethod
    def extraUpdatesAlertDidEnd_returnCode_contextInfo_(
            self, alert, returncode, contextinfo):
        '''Called when the extra updates alert ends'''
        pass

    def confirmUpdatesAndInstall(self):
        '''Make sure it's OK to proceed with installing if logout or restart is
        required'''
        if self.alertedToMultipleUsers():
            return
        elif MunkiItems.updatesRequireRestart():
            alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(
                NSLocalizedString(u"Restart Required",
                                  u"Restart Required title"),
                NSLocalizedString(u"Log out and update",
                                  u"Log out and Update button text"),
                NSLocalizedString(u"Cancel",
                                  u"Cancel button title/short action text"),
                nil,
                u"%@", NSLocalizedString(
                    u"A restart is required after updating. Please be patient "
                    "as there may be a short delay at the login window. Log "
                    "out and update now?", u"Restart Required detail")
                )
            alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(
                self.window, self,
                self.logoutAlertDidEnd_returnCode_contextInfo_, nil)
        elif MunkiItems.updatesRequireLogout() or munki.installRequiresLogout():
            alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(
                NSLocalizedString(u"Logout Required", u"Logout Required title"),
                NSLocalizedString(u"Log out and update",
                                  u"Log out and Update button text"),
                NSLocalizedString(u"Cancel",
                                  u"Cancel button title/short action text"),
                nil,
                u"%@", NSLocalizedString(
                    u"A logout is required before updating. Please be patient "
                    "as there may be a short delay at the login window. Log "
                    "out and update now?", u"Logout Required detail")
                )
            alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(
                self.window, self,
                self.logoutAlertDidEnd_returnCode_contextInfo_, nil)
        else:
            # we shouldn't have been invoked if neither a restart or logout was
            # required
            msclog.debug_log(
                'confirmUpdatesAndInstall was called but no restart or logout '
                'was needed')

    @AppHelper.endSheetMethod
    def logoutAlertDidEnd_returnCode_contextInfo_(
            self, alert, returncode, contextinfo):
        '''Called when logout alert ends'''
        if returncode == NSAlertDefaultReturn:
            # make sure this alert panel is gone before we proceed, which
            # might involve opening another alert sheet
            alert.window().orderOut_(self)
            if self.alertedToFirmwareUpdatesAndCancelled():
                msclog.log("user", "alerted_to_firmware_updates_and_cancelled")
                return
            elif self.alertedToRunningOnBatteryAndCancelled():
                msclog.log("user", "alerted_on_battery_power_and_cancelled")
                return
            msclog.log("user", "install_with_logout")
            self.handlePossibleAuthRestart()
            try:
                munki.logoutAndUpdate()
            except munki.ProcessStartError, err:
                self.installSessionErrorAlert_(err)
        elif returncode == NSAlertAlternateReturn:
            msclog.log("user", "cancelled")

    def installSessionErrorAlert_(self, errmsg):
        '''Something has gone wrong and we can't trigger an install at logout'''
        msclog.log("user", "install_session_failed")
        alertMessageText = NSLocalizedString(
            u"Install session failed", u"Install Session Failed title")
        detailText = NSLocalizedString(
            u"There is a configuration problem with the managed software "
            "installer. Could not start the process. Contact your systems "
            "administrator.", u"Could Not Start Session message")
        detailText += u"\n\n" + unicode(errmsg)
        OKButtonTitle = NSLocalizedString(u"OK", u"OK button title")
        alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(
            alertMessageText, OKButtonTitle, nil, nil, u"%@", detailText)
        alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(
            self.window, self,
            self.installSessionErrorAlertDidEnd_returnCode_contextInfo_, nil)

    @AppHelper.endSheetMethod
    def installSessionErrorAlertDidEnd_returnCode_contextInfo_(
            self, alert, returncode, contextinfo):
        '''Called when installSessionErrorAlert ends'''
        pass

    def alertedToMultipleUsers(self):
        '''Returns True if there are multiple GUI logins; alerts as a side
        effect'''
        if len(munki.currentGUIusers()) > 1:
            msclog.log("MSC", "multiple_gui_users_update_cancelled")
            alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(
                NSLocalizedString(u"Other users logged in",
                                  u"Other Users Logged In title"),
                NSLocalizedString(u"Cancel",
                                  u"Cancel button title/short action text"),
                nil,
                nil,
                u"%@", NSLocalizedString(
                    u"There are other users logged into this computer.\n"
                    "Updating now could cause other users to lose their "
                    "work.\n\nPlease try again later after the other users "
                    "have logged out.", u"Other Users Logged In detail")
                )
            alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(
                self.window, self,
                self.multipleUserAlertDidEnd_returnCode_contextInfo_, nil)
            return True
        else:
            return False

    @AppHelper.endSheetMethod
    def multipleUserAlertDidEnd_returnCode_contextInfo_(
            self, alert, returncode, contextinfo):
        '''Called when multiple users alert ends'''
        pass

    def alertedToBlockingAppsRunning(self):
        '''Returns True if blocking_apps are running; alerts as a side-effect'''
        apps_to_check = []
        for update_item in MunkiItems.getUpdateList():
            if 'blocking_applications' in update_item:
                apps_to_check.extend(update_item['blocking_applications'])
            else:
                apps_to_check.extend(
                    [os.path.basename(item.get('path'))
                     for item in update_item.get('installs', [])
                     if item['type'] == 'application']
                )

        running_apps = munki.getRunningBlockingApps(apps_to_check)
        if running_apps:
            current_user = munki.getconsoleuser()
            other_users_apps = [item['display_name'] for item in running_apps
                                if item['user'] != current_user]
            my_apps = [item['display_name'] for item in running_apps
                       if item['user'] == current_user]
            msclog.log(
                "MSC", "conflicting_apps", ','.join(other_users_apps + my_apps))
            if other_users_apps:
                detailText = NSLocalizedString(
                    u"Other logged in users are using the following "
                    "applications. Try updating later when they are no longer "
                    "in use:\n\n%s",
                    u"Other Users Blocking Apps Running detail")
                alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(
                    NSLocalizedString(
                        u"Applications in use by others",
                        u"Other Users Blocking Apps Running title"),
                    NSLocalizedString(u"OK", u'OKButtonText'),
                    nil,
                    nil,
                    u"%@", detailText % u'\n'.join(set(other_users_apps))
                    )
            else:
                detailText = NSLocalizedString(
                    u"You must quit the following applications before "
                    "proceeding with installation or removal:\n\n%s",
                    u"Blocking Apps Running detail")
                alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(
                    NSLocalizedString(
                        u"Conflicting applications running",
                        u"Blocking Apps Running title"),
                    NSLocalizedString(u"OK", u"OK button title"),
                    nil,
                    nil,
                    u"%@", detailText % u'\n'.join(set(my_apps))
                    )
            alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(
                self.window, self,
                self.blockingAppsRunningAlertDidEnd_returnCode_contextInfo_,
                nil)
            return True
        else:
            return False

    @AppHelper.endSheetMethod
    def blockingAppsRunningAlertDidEnd_returnCode_contextInfo_(
            self, alert, returncode, contextinfo):
        '''Called when blocking apps alert ends'''
        pass

    def getFirmwareAlertInfo(self):
        '''Get detail about a firmware update'''
        info = []
        for update_item in MunkiItems.getUpdateList():
            if 'firmware_alert_text' in update_item:
                info_item = {}
                info_item['name'] = update_item.get('display_name', 'name')
                alert_text = update_item['firmware_alert_text']
                if alert_text == u'_DEFAULT_FIRMWARE_ALERT_TEXT_':
                    # substitute localized default alert text
                    alert_text = NSLocalizedString(
                        (u"Firmware will be updated on your computer. "
                         "Your computer's power cord must be connected "
                         "and plugged into a working power source. "
                         "It may take several minutes for the update to "
                         "complete. Do not disturb or shut off the power "
                         "on your computer during this update."),
                        u"Firmware Alert Default detail")
                info_item['alert_text'] = alert_text
                info.append(info_item)
        return info

    def alertedToFirmwareUpdatesAndCancelled(self):
        '''Returns True if we have one or more firmware updates and
        the user clicks the Cancel button'''
        firmware_alert_info = self.getFirmwareAlertInfo()
        if not firmware_alert_info:
            return False
        on_battery_power = munki.onBatteryPower()
        for item in firmware_alert_info:
            alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(
                item['name'],
                NSLocalizedString(u"Continue", u"Continue button text"),
                NSLocalizedString(
                    u"Cancel", u"Cancel button title/short action text"),
                nil,
                u"")
            if on_battery_power:
                alert_text = NSLocalizedString(
                    u"Your computer is not connected to a power source.",
                    u"No Power Source Warning text")
                alert_text += "\n\n" + item['alert_text']
            else:
                alert_text = item['alert_text']
            alert.setInformativeText_(alert_text)
            alert.setAlertStyle_(NSCriticalAlertStyle)
            if on_battery_power:
                # set Cancel button to be activated by return key
                alert.buttons()[1].setKeyEquivalent_('\r')
                # set Continue button to be activated by Escape key
                alert.buttons()[0].setKeyEquivalent_(chr(27))
            buttonPressed = alert.runModal()
            if buttonPressed == NSAlertAlternateReturn:
                return True
        return False

    def alertedToRunningOnBatteryAndCancelled(self):
        '''Returns True if we are running on battery and user clicks
        the Cancel button'''
        if munki.onBatteryPower() and munki.getBatteryPercentage() < 50:
            alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(
                NSLocalizedString(
                    u"Your computer is not connected to a power source.",
                    u"No Power Source Warning text"),
                NSLocalizedString(u"Continue", u"Continue button text"),
                NSLocalizedString(u"Cancel",
                                  u"Cancel button title/short action text"),
                nil,
                u"%@", NSLocalizedString(
                    u"For best results, you should connect your computer to a "
                    "power source before updating. Are you sure you want to "
                    "continue the update?", u"No Power Source Warning detail")
                )
            msclog.log("MSU", "alert_on_battery_power")
            # making UI consistent with Apple Software Update...
            # set Cancel button to be activated by return key
            alert.buttons()[1].setKeyEquivalent_('\r')
            # set Continue button to be activated by Escape key
            alert.buttons()[0].setKeyEquivalent_(chr(27))
            buttonPressed = alert.runModal()
            if buttonPressed == NSAlertAlternateReturn:
                return True
        return False
