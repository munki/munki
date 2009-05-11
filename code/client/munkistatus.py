#!/usr/bin/env python
# encoding: utf-8
#
# Copyright 2009 Greg Neagle.
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
"""
munkistatus.py

Created by Greg Neagle on 2009-04-17.

Utility functions for using MunkiStatus.app.
Can be called as a standalone script with options,
or as a Python library
"""

import sys
import os
import optparse
import subprocess


def osascript(osastring):
    cmd = ['osascript', '-e', osastring]
    p = subprocess.Popen(cmd, shell=False, bufsize=1, stdin=subprocess.PIPE, 
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out, err) = p.communicate()
    if p.returncode != 0:
        print >>sys.stderr, "Error: ", err
    if out:
        return out.rstrip("\n")


def quit():
    # see if MunkiStatus is running first
    cmd = ['/usr/bin/killall', '-s', 'MunkiStatus']
    p = subprocess.Popen(cmd, shell=False, bufsize=1, stdin=subprocess.PIPE, 
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out, err) = p.communicate()
    if p.returncode == 0:
        # it's running, send it a quit message
        result = osascript('tell application "MunkiStatus" to quit')
    

def activate():
    osascript('tell application "MunkiStatus" to activate')

    
def title(titleText):
    result = osascript('tell application "MunkiStatus" to set title of window "mainWindow" to "%s"' % titleText)
    
    
def message(messageText):
    result = osascript('tell application "MunkiStatus" to set contents of text field "mainTextFld" of window "mainWindow" to "%s"' % messageText)


def detail(detailsText):
    result = osascript('tell application "MunkiStatus" to set contents of text field "minorTextFld" of window "mainWindow" to "%s"' % detailsText)


def percent(percentage):
    # Note:  this is a relatively slow operation.
    # If you are calling this on every iteration of a loop, 
    # you may find it slows the loop down unacceptibly, as 
    # Your loop spends more time waiting for this operation
    # than actually doing its work. You might
    # instead try calling it once at the beginning of the loop,
    # once every X iterations, then once at the end to speed things up.
    # X might equal (number of iterations / 10 or even 20)
    percent = int(float(percentage))
    if percent > 100:
        percent = 100
    if percent < 0:
        # set an indeterminate progress bar
        result = osascript('tell application "MunkiStatus" to set indeterminate of progress indicator "progressBar" of window "mainWindow" to true')
        result = osascript('tell application "MunkiStatus" to tell window "mainWindow" to tell progress indicator "progressBar" to start')
    elif percent == 0:
        # we only clear the indeterminate status when we set the percentage to 0;
        # we tried always doing it, but it really slows down response times such
        # that a script spends way more time updating MunkiStatus than it does
        # actually performing its task
        result = osascript('tell application "MunkiStatus" to set indeterminate of progress indicator "progressBar" of window "mainWindow" to false')
        result = osascript('tell application "MunkiStatus" to set contents of progress indicator "progressBar" of window "mainWindow" to 0')
    else:
        percentStr = str(percent)
        result = osascript('tell application "MunkiStatus" to set contents of progress indicator "progressBar" of window "mainWindow" to %s' % percentStr)
    
    
def getStopButtonState():
    # see if MunkiStatus is running first
    cmd = ['/usr/bin/killall', '-s', 'MunkiStatus']
    p = subprocess.Popen(cmd, shell=False, bufsize=1, stdin=subprocess.PIPE, 
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out, err) = p.communicate()
    if p.returncode == 0:
        # it's running, ask it for the button state
        result = osascript('tell application "MunkiStatus" to get the state of button "stopBtn" of window "mainWindow"')    
        return int(result)
    else:
        return 0
    
    
def hideStopButton():
    result = osascript('tell application "MunkiStatus" to set visible of button "stopBtn" of window "mainWindow" to false')
   
   
def showStopButton():
    result = osascript('tell application "MunkiStatus" to set visible of button "stopBtn" of window "mainWindow" to true')
    

def disableStopButton():
    result = osascript('tell application "MunkiStatus" to set enabled of button "stopBtn" of window "mainWindow" to false')


def enableStopButton():
    result = osascript('tell application "MunkiStatus" to set enabled of button "stopBtn" of window "mainWindow" to true')


def main():
    p = optparse.OptionParser()
    p.add_option('--activate', '-a', action='store_true',
                    help='Bring MunkiStatus to the front.')
    p.add_option('--title', '-t', default='',
                    help='Window title.')                    
    p.add_option('--message', '-m', default='',
                    help='Main message text.')
    p.add_option('--detail', '-d',
                    help='Minor message text.')
    p.add_option('--percent', '-p', default='',
                    help='Update progress bar to show percent done. Negative values show an indeterminate progress bar.')
    p.add_option('--quit', '-q', action='store_true',
                    help='Tell MunkiStatus to quit.')
    p.add_option('--getStopButtonState', '-g', action='store_true',
                    help='Returns 1 if stop button has been clicked.')
    p.add_option('--hideStopButton', action='store_true',
                    help='Hide the stop button.')
    p.add_option('--showStopButton', action='store_true',
                    help='Show the stop button.')
    p.add_option('--disableStopButton', action='store_true',
                    help='Disable the stop button.')
    p.add_option('--enableStopButton', action='store_true',
                    help='Enable the stop button.')
    
    
    options, arguments = p.parse_args()
    
    if options.quit:
        quit()
        exit()           
    if options.activate:
        activate()
    if options.title:
        title(options.title)
    if options.message:
        message(options.message)        
    if options.detail:
        detail(options.detail)
    if options.percent:
        percent(options.percent)
    if options.getStopButtonState:
        print getStopButtonState()
    if options.hideStopButton:
        hideStopButton()        
    if options.showStopButton:
        showStopButton()
    if options.disableStopButton:
        disableStopButton()        
    if options.enableStopButton:
        enableStopButton()
    
                        
if __name__ == '__main__':
	main()

