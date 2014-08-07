# encoding: utf-8
#
# MSUStatusController.py
#
# Copyright 2009-2014 Greg Neagle.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


from objc import YES, NO, IBAction, IBOutlet, nil
import os
import time
import munki
import msulog
import FoundationPlist
from Foundation import *
from AppKit import *
from PyObjCTools import AppHelper

debug = False

class MSUStatusController(NSObject):
    '''
    Handles status messages from managedsoftwareupdate
    '''

    session_started = False
    got_status_update = False
    timer = None
    
    _status_stopBtnDisabled = False
    _status_stopBtnHidden = False
    _status_message = u''
    _status_detail = u''
    _status_percent = -1
    _status_stopBtnState = 0

    statusWindowController = IBOutlet()
    
    def registerForNotifications(self):
        '''Register for notification messages'''
        notification_center = NSDistributedNotificationCenter.defaultCenter()
        notification_center.addObserver_selector_name_object_suspensionBehavior_(
            self,
            self.updateStatus_,
            'com.googlecode.munki.managedsoftwareupdate.statusUpdate',
            None,
            NSNotificationSuspensionBehaviorDeliverImmediately)
        self.receiving_notifications = True

    def unregisterForNotifications(self):
        '''Tell the DistributedNotificationCenter to stop sending us notifications'''
        NSDistributedNotificationCenter.defaultCenter().removeObserver_(self)
        # set self.receiving_notifications to False so our process monitoring
        # thread will exit
        self.receiving_notifications = False
    
    def startMunkiStatusSession(self):
        '''Initialize things for monitoring a managedsoftwareupdate session'''
        self.initStatusSession()
        self.session_started = True
        # start our process monitor timer so we can be notified about
        # process failure
        self.timeout_counter = 6
        self.saw_process = False
        self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            5.0, self, self.checkProcess_, None, YES)
            
    def checkProcess_(self, timer):
        '''Monitors managedsoftwareupdate process for failure to start
        or unexpected exit, so we're not waiting around forever if
        managedsoftwareupdate isn't running.'''
        PYTHON_SCRIPT_NAME = u'managedsoftwareupdate'
        NEVER_STARTED = -2
        UNEXPECTEDLY_QUIT = -1
        
        if self.session_started:
            if self.got_status_update:
                # we got a status update since we last checked; no need to
                # check the process table
                self.timeout_counter = 6
                self.saw_process = True
                # clear the flag so we have to get another status update
                self.got_status_update = False
            elif munki.pythonScriptRunning(PYTHON_SCRIPT_NAME):
                self.timeout_counter = 6
                self.saw_process = True
            else:
                msulog.debug_log('managedsoftwareupdate not running...')
                self.timeout_counter -= 1
            if self.timeout_counter == 0:
                msulog.debug_log('Timed out waiting for managedsoftwareupdate.')
                if self.saw_process:
                    self.sessionEnded_(UNEXPECTEDLY_QUIT)
                else:
                    self.sessionEnded_(NEVER_STARTED)
    
    def sessionStarted(self):
        '''Accessor method'''
        return self.session_started

    def sessionEnded_(self, result):
        '''clean up after a managesoftwareupdate session ends'''
        if self.timer:
            self.timer.invalidate()
            self.timer = None
        self.cleanUpStatusSession()
        # tell the window controller the update session is done
        self.statusWindowController.munkiStatusSessionEnded_(result)
        
    def updateStatus_(self, notification):
        '''Got update status notification from managedsoftwareupdate'''
        self.got_status_update = True
        info = notification.userInfo()
        if 'message' in info:
            self.setMessage_(info['message'])
        if 'detail' in info:
            self.setDetail_(info['detail'])
        if 'percent' in info:
            self.setPercentageDone_(info['percent'])
        if 'stop_button_visible' in info:
            if info['stop_button_visible']:
                self.showStopButton()
            else:
                self.hideStopButton()
        if 'stop_button_enabled' in info:
            if info['stop_button_enabled']:
                self.enableStopButton()
            else:
                self.disableStopButton()

        command = info.get('command')
        if not self.session_started and command not in ['showRestartAlert', 'quit']:
            # we got a status message but we didn't start the session
            # so switch to the right mode
            self.startMunkiStatusSession()
        if command:
            msulog.debug_log('Received command: %s' % command)
        if command == 'activate':
            pass
            #NSApp.activateIgnoringOtherApps_(YES) #? do we really want to do this?
            #self.statusWindowController.window().orderFrontRegardless()
        elif command == 'showRestartAlert':
            self.doRestartAlert()
        elif command == 'quit':
            self.sessionEnded_(0)

##### required status methods #####

    def initStatusSession(self):
        '''Initialize the main window for update status'''
        self.statusWindowController._update_in_progress = True
        if self.statusWindowController.currentPageIsUpdatesPage():
            self.statusWindowController.webView.reload_(self)
            self.statusWindowController.displayUpdateCount()

    def cleanUpStatusSession(self):
        '''Clean up after status session ends'''
        self.session_started = False
        # reset all our status variables
        self.statusWindowController._update_in_progress = False
        self._status_stopBtnDisabled = False
        self._status_stopBtnHidden = False
        self._status_stopBtnState = 0
        self._status_message = u''
        self._status_detail = u''
        self._status_percent = -1

    def setPercentageDone_(self, percent):
        '''Display precentage done'''
        try:
            if float(percent) > 100.0:
                percent = 100
        except ValueError:
            percent = 0
        self._status_percent = percent
        document = self.statusWindowController.webView.mainFrameDocument()
        if document:
            spinner = document.getElementById_('updates-progress-spinner')
            if spinner: # we are displaying the updates status page
                progress = document.getElementById_('progress-bar')
                if progress:
                    if float(percent) < 0:
                        # indeterminate
                        progress.setClassName_('indeterminate')
                        progress.removeAttribute_('style')
                    else:
                        progress.setClassName_('')
                        progress.setAttribute__('style', 'width: %s%%' % percent)

    def doRestartAlert(self):
        '''Display a restart alert -- some item just installed or removed requires a restart'''
        self._status_restartAlertDismissed = 0
        alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(
            NSLocalizedString(u"Restart Required", u"Restart Required alert title"),
            NSLocalizedString(u"Restart", u"Restart button title"),
            nil,
            nil,
            u"%@", NSLocalizedString(
                u"Software installed or removed requires a restart. You will "
                "have a chance to save open documents.", u"Restart Required alert detail"))
        alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(
            self.statusWindowController.window(),
            self, self.restartAlertDidEnd_returnCode_contextInfo_, nil)

    @AppHelper.endSheetMethod
    def restartAlertDidEnd_returnCode_contextInfo_(
                                        self, alert, returncode, contextinfo):
        '''Called when restartAlert ends'''
        self._status_restartAlertDismissed = 1
        # TO-DO: initiate actual restart

    def setMessage_(self, messageText):
        '''Display main status message'''
        self._status_message = NSLocalizedString(messageText, None)
        document = self.statusWindowController.webView.mainFrameDocument()
        if document:
            spinner = document.getElementById_('updates-progress-spinner')
            if spinner: # we are displaying the updates status page
                textElement = document.getElementById_('primary-status-text')
                if textElement:
                    if messageText:
                        textElement.setInnerText_(messageText)
                    else:
                        textElement.setInnerHTML_('&nbsp;')

    def setDetail_(self, detailText):
        '''Display status detail'''
        self._status_detail = NSLocalizedString(detailText, None)
        document = self.statusWindowController.webView.mainFrameDocument()
        if document:
            spinner = document.getElementById_('updates-progress-spinner')
            if spinner: # we are displaying the updates status page
                textElement = document.getElementById_('secondary-status-text')
                if textElement:
                    if detailText:
                        textElement.setInnerText_(detailText)
                    else:
                        textElement.setInnerHTML_('&nbsp;')

    def getStopBtnState(self):
        '''Get the state (pressed or not) of the stop button'''
        return self._status_stopBtnState

    def hideStopButton(self):
        '''Hide the stop button'''
        if self._status_stopBtnState:
            return
        self._status_stopBtnHidden = True
        document = self.statusWindowController.webView.mainFrameDocument()
        if document:
            spinner = document.getElementById_('updates-progress-spinner')
            if spinner: # we are displaying the updates status page
                install_btn = document.getElementById_('install-all-button-text')
                if install_btn:
                    btn_classes = install_btn.className().split(' ')
                    if not 'hidden' in btn_classes:
                        btn_classes.append('hidden')
                        install_btn.setClassName_(' '.join(btn_classes))

    def showStopButton(self):
        '''Show the stop button'''
        if self._status_stopBtnState:
           return
        self._status_stopBtnHidden = False
        document = self.statusWindowController.webView.mainFrameDocument()
        if document:
            spinner = document.getElementById_('updates-progress-spinner')
            if spinner: # we are displaying the updates status page
                install_btn = document.getElementById_('install-all-button-text')
                if install_btn:
                    btn_classes = install_btn.className().split(' ')
                    if 'hidden' in btn_classes:
                        btn_classes.remove('hidden')
                        install_btn.setClassName_(' '.join(btn_classes))

    def enableStopButton(self):
        '''Enable the stop button'''
        if self._status_stopBtnState:
            return
        self._status_stopBtnDisabled = False
        document = self.statusWindowController.webView.mainFrameDocument()
        if document:
            spinner = document.getElementById_('updates-progress-spinner')
            if spinner: # we are displaying the updates status page
                install_btn = document.getElementById_('install-all-button-text')
                if install_btn:
                    btn_classes = install_btn.className().split(' ')
                    if 'disabled' in btn_classes:
                        btn_classes.remove('disabled')
                        install_btn.setClassName_(' '.join(btn_classes))

    def disableStopButton(self):
        '''Disable the stop button'''
        if self._status_stopBtnState:
            return
        self._status_stopBtnDisabled = True
        document = self.statusWindowController.webView.mainFrameDocument()
        if document:
            spinner = document.getElementById_('updates-progress-spinner')
            if spinner: # we are displaying the updates status page
                install_btn = document.getElementById_('install-all-button-text')
                if install_btn:
                    btn_classes = install_btn.className().split(' ')
                    if not 'disabled' in btn_classes:
                        btn_classes.append('disabled')
                        install_btn.setClassName_(' '.join(btn_classes))

    def getRestartAlertDismissed(self):
        '''Was the restart alert dimissed?'''
        return self._status_restartAlertDismissed
