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
    
    _status_stopBtnDisabled = False
    _status_stopBtnHidden = False
    _status_message = ''
    _status_detail = ''
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
        self.initStatusSession()
        #self.registerForNotifications()
        self.session_started = True
        # start our process monitor thread so we can be notified about
        # process failure
        NSThread.detachNewThreadSelector_toTarget_withObject_(
                                                self.monitorProcess, self, None)
            
    def monitorProcess(self):
        '''Monitors managedsoftwareupdate process for failure to start
        or unexpected exit, so we're not waiting around forever if
        managedsoftwareupdate isn't running.'''
        PYTHON_SCRIPT_NAME = 'managedsoftwareupdate'
        NEVER_STARTED = -2
        UNEXPECTEDLY_QUIT = -1
        
        timeout_counter = 6
        saw_process = False
        
        NSLog('monitorProcess thread started')
        
        # Autorelease pool for memory management
        pool = NSAutoreleasePool.alloc().init()
        while self.session_started:
            if self.got_status_update:
                # we got a status update since we last checked; no need to
                # check the process table
                timeout_counter = 6
                saw_process = True
                # clear the flag so we have to get another status update
                self.got_status_update = False
            elif munki.pythonScriptRunning(PYTHON_SCRIPT_NAME):
                timeout_counter = 6
                saw_process = True
            else:
                NSLog('managedsoftwareupdate not running...')
                timeout_counter -= 1
            if timeout_counter == 0:
                NSLog('Timed out waiting for managedsoftwareupdate.')
                if saw_process:
                    sessionResult = UNEXPECTEDLY_QUIT
                else:
                    sessionResult = NEVER_STARTED
                self.performSelectorOnMainThread_withObject_waitUntilDone_(
                                            self.sessionEnded_, sessionResult, NO)
                break
            time.sleep(5)
        
        # Clean up autorelease pool
        del pool
        NSLog('monitorProcess thread ended')
    
    def sessionStarted(self):
        return self.session_started

    def sessionEnded_(self, result):
        # clean up if needed
        self.cleanUpStatusSession()
        # tell the app the update session is done
        NSApp.delegate().munkiStatusSessionEnded_(result)
        
    def updateStatus_(self, notification):
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
            NSLog('Received command: %s' % command)
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
        self.statusWindowController._update_in_progress = True
        if self.statusWindowController.currentPageIsUpdatesPage():
            self.statusWindowController.webView.reload_(self)
            self.statusWindowController.displayUpdateCount()

    def cleanUpStatusSession(self):
        self.session_started = False
        # reset all our status variables
        self.statusWindowController._update_in_progress = False
        self._status_stopBtnDisabled = False
        self._status_stopBtnHidden = False
        self._status_stopBtnState = 0
        self._status_message = ''
        self._status_detail = ''
        self._status_percent = -1

    def setPercentageDone_(self, percent):
        try:
            if float(percent) > 100.0:
                percent = 100
        except ValueError:
            percent = 0
        self._status_percent = percent
        document = self.statusWindowController.webView.mainFrameDocument()
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

    @AppHelper.endSheetMethod
    def restartAlertDidEnd_returnCode_contextInfo_(
                                        self, alert, returncode, contextinfo):
        self._status_restartAlertDismissed = 1
        # TO-DO: initiate actual restart

    def doRestartAlert(self):
        self._status_restartAlertDismissed = 0
        alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(
            NSLocalizedString(u"Restart Required", None),
            NSLocalizedString(u"Restart", None),
            nil,
            nil,
            NSLocalizedString(
                u"Software installed or removed requires a restart. You will "
                "have a chance to save open documents.", None))
        alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(
            self.statusWindowController.window(),
            self, self.restartAlertDidEnd_returnCode_contextInfo_, nil)

    def setMessage_(self, messageText):
        self._status_message = messageText
        document = self.statusWindowController.webView.mainFrameDocument()
        spinner = document.getElementById_('updates-progress-spinner')
        if spinner: # we are displaying the updates status page
            textElement = document.getElementById_('primary-status-text')
            if textElement:
                if messageText:
                    textElement.setInnerText_(messageText.encode('utf-8'))
                else:
                    textElement.setInnerHTML_('&nbsp;')

    def setDetail_(self, detailText):
        self._status_detail = detailText
        document = self.statusWindowController.webView.mainFrameDocument()
        spinner = document.getElementById_('updates-progress-spinner')
        if spinner: # we are displaying the updates status page
            textElement = document.getElementById_('secondary-status-text')
            if textElement:
                if detailText:
                    textElement.setInnerText_(detailText.encode('utf-8'))
                else:
                    textElement.setInnerHTML_('&nbsp;')

    def getStopBtnState(self):
        return self._status_stopBtnState

    def hideStopButton(self):
        if self._status_stopBtnState:
            return
        self._status_stopBtnHidden = True
        document = self.statusWindowController.webView.mainFrameDocument()
        spinner = document.getElementById_('updates-progress-spinner')
        if spinner: # we are displaying the updates status page
            install_btn = document.getElementById_('install-all-button-text')
            if install_btn:
                btn_classes = install_btn.className().split(' ')
                if not 'hidden' in btn_classes:
                    btn_classes.append('hidden')
                    install_btn.setClassName_(' '.join(btn_classes))

    def showStopButton(self):
        if self._status_stopBtnState:
           return
        self._status_stopBtnHidden = False
        document = self.statusWindowController.webView.mainFrameDocument()
        spinner = document.getElementById_('updates-progress-spinner')
        if spinner: # we are displaying the updates status page
            install_btn = document.getElementById_('install-all-button-text')
            if install_btn:
                btn_classes = install_btn.className().split(' ')
                if 'hidden' in btn_classes:
                    btn_classes.remove('hidden')
                    install_btn.setClassName_(' '.join(btn_classes))

    def enableStopButton(self):
        if self._status_stopBtnState:
            return
        self._status_stopBtnDisabled = False
        document = self.statusWindowController.webView.mainFrameDocument()
        spinner = document.getElementById_('updates-progress-spinner')
        if spinner: # we are displaying the updates status page
            install_btn = document.getElementById_('install-all-button-text')
            if install_btn:
                btn_classes = install_btn.className().split(' ')
                if 'disabled' in btn_classes:
                    btn_classes.remove('disabled')
                    install_btn.setClassName_(' '.join(btn_classes))

    def disableStopButton(self):
        if self._status_stopBtnState:
            return
        self._status_stopBtnDisabled = True
        document = self.statusWindowController.webView.mainFrameDocument()
        spinner = document.getElementById_('updates-progress-spinner')
        if spinner: # we are displaying the updates status page
            install_btn = document.getElementById_('install-all-button-text')
            if install_btn:
                btn_classes = install_btn.className().split(' ')
                if not 'disabled' in btn_classes:
                    btn_classes.append('disabled')
                    install_btn.setClassName_(' '.join(btn_classes))

    def getRestartAlertDismissed(self):
        return self._status_restartAlertDismissed
