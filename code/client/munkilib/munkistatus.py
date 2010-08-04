#!/usr/bin/python
# encoding: utf-8
#
# Copyright 2009-2010 Greg Neagle.
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

Created by Greg Neagle on 2009-09-24.

Utility functions for using MunkiStatus.app
to display status and progress.
"""

import os
import subprocess
import socket
import time

# module socket variable
SOCK = None


def launchMunkiStatus():
    '''Uses launchd KeepAlive path so it launches from a launchd agent
    in the correct context.
    This is more complicated to set up, but makes Apple (and launchservices)
    happier.
    There needs to be a launch agent that is triggered when the launchfile
    is created; and that launch agent then runs MunkiStatus.app.'''
    launchfile = "/var/run/com.googlecode.munki.MunkiStatus"
    cmd = ['/usr/bin/touch', launchfile]
    retcode = subprocess.call(cmd)
    time.sleep(0.1)
    if os.path.exists(launchfile):
        os.unlink(launchfile)


def launchAndConnectToMunkiStatus():
    '''Connects to the MunkiStatus socket, launching MunkiStatus if needed'''
    global SOCK
    if not getMunkiStatusPID():
        launchMunkiStatus()
    socketpath = getMunkiStatusSocket()
    if socketpath:
        try:
            SOCK = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            SOCK.connect(socketpath)
        except IOError:
            # some problem; kill the socket
            SOCK = None
    #else:
        #raise Exception("Could not open connection to MunkiStatus.app")


def sendCommand(command_text):
    '''Send a command to MunkiStatus'''
    global SOCK
    if SOCK == None:
        launchAndConnectToMunkiStatus()
    if SOCK:        
        try:
            # we can send only a single line.
            messagelines = command_text.splitlines(True)
            SOCK.send(messagelines[0].encode('UTF-8'))
        except socket.error, (err, errmsg):
            if err == 32 or err == 9:
                # broken pipe
                SOCK.close()
                SOCK = None


def readResponse():
    '''Read a response from MunkiStatsu'''
    global SOCK
    if SOCK:
        try:
            # our responses are really short
            data = SOCK.recv(256)
            return int(data.rstrip('\n'))
        except (ValueError, TypeError):
            # MunkiStatus returned an illegal value
            # ignore for now
            return 0
        except socket.error, (err, errmsg):
            print err, errmsg
            SOCK.close()
            SOCK = None
            
    return ''


def getPIDforProcessName(processname):
    '''Returns a process ID for processname'''
    cmd = ['/bin/ps', '-eo', 'pid=,command=']
    proc = subprocess.Popen(cmd, shell=False, bufsize=1, 
                            stdin=subprocess.PIPE, 
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    while True: 
        line =  proc.stdout.readline().decode('UTF-8')
        if not line and (proc.poll() != None):
            break
        line = line.rstrip('\n')
        if line:
            (pid, process) = line.split(None, 1)
            if process.find(processname) != -1:
                return str(pid)
                
    return 0


def getMunkiStatusPID():
    '''Gets the process ID for Managed Software Update'''
    return getPIDforProcessName(
      "Managed Software Update.app/Contents/MacOS/Managed Software Update") \
      or getPIDforProcessName("MunkiStatus.app/Contents/MacOS/MunkiStatus")


def getMunkiStatusSocket():
    '''Returns the path to the MunkiStatus socket'''
    pid = None
    for i in range(8):
        pid = getMunkiStatusPID()
        if pid:
            break
        else:
            # sleep and try again
            time.sleep(.25)
    if pid:
        for i in range(12):
            socketpath = "/tmp/com.googlecode.munki.munkistatus.%s" % pid
            if os.path.exists(socketpath):
                return socketpath
            
            # sleep and try again
            time.sleep(.25)
    return ""


def activate():
    '''Brings MunkiStatus window to the front.'''
    sendCommand(u"ACTIVATE: \n")


def hide():
    '''Hides MunkiStatus window.'''
    sendCommand(u"HIDE: \n")


def show():
    '''Shows MunkiStatus window.'''
    sendCommand(u"SHOW: \n")


def title(titleText):
    '''Sets the window title.'''
    sendCommand(u"TITLE: %s\n" % titleText)


def message(messageText):
    '''Sets the status message.'''
    sendCommand(u"MESSAGE: %s\n" % messageText)


def detail(detailsText):
    '''Sets the detail text.'''
    sendCommand(u"DETAIL: %s\n" % detailsText)


def percent(percentage):
    '''Sets the progress indicator to 0-100 percent done.
    If you pass a negative number, the progress indicator
    is shown as an indeterminate indicator (barber pole).'''
    sendCommand(u"PERCENT: %s\n" % percentage)


def hideStopButton():
    '''Hides the stop button.'''
    sendCommand(u"HIDESTOPBUTTON: \n")


def showStopButton():
    '''Shows the stop button.'''
    sendCommand(u"SHOWSTOPBUTTON: \n")


def disableStopButton():
    '''Disables (grays out) the stop button.'''
    sendCommand(u"DISABLESTOPBUTTON: \n")       


def enableStopButton():
    '''Enables the stop button.'''
    sendCommand(u"ENABLESTOPBUTTON: \n")


def restartAlert():
    '''Tells MunkiStatus to display a restart alert.'''
    try:
        sendCommand(u"ACTIVATE: \n")
        sendCommand(u"RESTARTALERT: \n")
        return readResponse()
    except IOError:
        return 0


def getStopButtonState():
    '''Returns 1 if the stop button has been clicked, 0 otherwise.'''
    if not SOCK:
        return 0
    try:
        SOCK.send(u"GETSTOPBUTTONSTATE: \n")
        state = readResponse()
        if state:
            return state
        else:
            return 0
    except IOError:
        return 0


def quit():
    '''Tells the status app that we're done.'''
    global SOCK
    try:
        SOCK.send(u"QUIT: \n")
        SOCK.close()
        SOCK = None
    except (AttributeError, IOError):
        pass
