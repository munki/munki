-- MunkiStatus.applescript
-- MunkiStatus

--  Created by Greg Neagle on 4/17/09.

--
-- Copyright 2009 Greg Neagle.
--
-- Licensed under the Apache License, Version 2.0 (the "License");
-- you may not use this file except in compliance with the License.
-- You may obtain a copy of the License at
-- 
--      http://www.apache.org/licenses/LICENSE-2.0
-- 
-- Unless required by applicable law or agreed to in writing, software
-- distributed under the License is distributed on an "AS IS" BASIS,
-- WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
-- See the License for the specific language governing permissions and
-- limitations under the License.


on clicked theObject
	if the name of theObject is "stopBtn" then
		set the state of theObject to 1
		set enabled of theObject to false
	end if
end clicked

--#define kCGNormalWindowLevel 0
--#define kCGStatusWindowLevel 25
--#define kCGScreenSaverWindowLevel 1000

property kCGNormalWindowLevel : 0
property kCGStatusWindowLevel : 25
property kCGScreenSaverWindowLevel : 1000

on awake from nib theObject
	if name of theObject is "backdropWindow" then
		copy "" to cfuser
		copy (call method "consoleUser") to cfuser
		if cfuser is "" then
			call method "setCanBecomeVisibleWithoutLogin:" of theObject with parameter 1
			call method "setLevel:" of theObject with parameter (kCGStatusWindowLevel)
			copy (call method "mainScreenRect") to screenRect
			call method "setFrame:display:" of theObject with parameters {screenRect, true}
			try
				--first check if a custom desktop picture has been set
				set DesktopPicture to do shell script "/usr/bin/defaults read /Library/Preferences/com.apple.loginwindow DesktopPicture"
			on error
				-- no DesktopPicture set for loginwindow, let's use some defaults
				set DesktopPicture to "/System/Library/CoreServices/DefaultDesktop.jpg"
			end try
			
			-- now we have a DesktopPicture, try to load the image
			try
				set bgPicture to load image DesktopPicture
				-- did it work?
				get bgPicture
			on error
				-- failed. just use our internal solid blue background
				set bgPicture to load image "Solid Aqua Blue"
			end try
			set contents of image view "imageFld" of theObject to bgPicture
			show theObject
		end if
	end if
	if name of theObject is "mainWindow" then
		-- Leopard is picky about what we can display over the loginwindow
		call method "setCanBecomeVisibleWithoutLogin:" of theObject with parameter 1
		
		--if we are in the loginwindow context, we need to set the window level so
		--it displays above the loginwindow
		copy "" to cfuser
		copy (call method "consoleUser") to cfuser
		if cfuser is "" then
			call method "setLevel:" of theObject with parameter (kCGScreenSaverWindowLevel - 1)
		end if
		call method "center" of theObject
		set visible of theObject to true
		activate
	end if
end awake from nib

on resigned active theObject
	(*copy "" to cfuser
	copy (call method "consoleUser") to cfuser
	if cfuser is "" then
		tell me to activate
	end if*)
end resigned active



