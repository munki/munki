-- ManagedSoftwareUpdate.applescript
-- ManagedSoftwareUpdate

--  Created by Greg Neagle on 5/7/09.
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

property managedInstallDir : ""

on itemstoinstall()
	set installlist to {}
	set ManagedInstallPrefs to "/Library/Preferences/ManagedInstalls.plist"
	try
		tell application "System Events"
			set managedInstallDir to value of property list item "ManagedInstallDir" of property list file ManagedInstallPrefs
			set InstallInfo to managedInstallDir & "/InstallInfo.plist"
			set managedinstalllist to value of property list item "managed_installs" of property list file InstallInfo
			repeat with installitem in managedinstalllist
				if (installed of installitem) is false then
					set end of installlist to (installitem as item)
				end if
			end repeat
			try
				set appleupdatelist to value of property list item "apple_updates" of property list file InstallInfo
				repeat with installitem in appleupdatelist
					set end of installlist to (installitem as item)
				end repeat
			end try
		end tell
	end try
	return installlist as list
end itemstoinstall

on restartRequired()
	copy itemstoinstall() to installitems
	repeat with installitem in installitems
		try
			if |RestartAction| of installitem is "RequireRestart" then
				return true
			end if
		end try
	end repeat
	return false
end restartRequired


on awake from nib theObject
	if name of theObject is "table" then
		set theDataSource to make new data source at end
		
		make new data column at end of data columns of theDataSource with properties {name:"image"}
		make new data column at end of data columns of theDataSource with properties {name:"name"}
		make new data column at end of data columns of theDataSource with properties {name:"version"}
		make new data column at end of data columns of theDataSource with properties {name:"description"}
		make new data column at end of data columns of theDataSource with properties {name:"restartaction"}
		
		copy my itemstoinstall() to installitems
		set EmptyImage to load image "Empty"
		set RestartImage to load image "RestartReq"
		
		if (count of installitems) is 0 then
			display alert "Your software is up to date." message ¬
				"There is no new software for your computer at this time." default button ¬
				"OK" as informational attached to window 1
			return
		end if
		
		repeat with installitem in installitems
			
			set theDataRow to make new data row at end of data rows of theDataSource
			try
				if |RestartAction| of installitem is "RequireRestart" then
					set contents of data cell "image" of theDataRow to RestartImage
				end if
			on error
				set contents of data cell "image" of theDataRow to EmptyImage
			end try
			try
				set contents of data cell "name" of theDataRow to display_name of installitem
			end try
			if contents of data cell "name" of theDataRow is "" then
				set contents of data cell "name" of theDataRow to |name| of installitem
			end if
			set contents of data cell "version" of theDataRow to version_to_install of installitem
			set contents of data cell "description" of theDataRow to |description| of installitem
			try
				set contents of data cell "restartaction" of theDataRow to |RestartAction| of installitem
			end try
		end repeat
		
		set data source of theObject to theDataSource
	end if
end awake from nib

on clicked theObject
	if the name of theObject is "laterBtn" then
		quit
	end if
	
	if the name of theObject is "installBtn" then
		copy my restartRequired() to restartNeeded
		if restartNeeded then
			display alert "Restart Required" message ¬
				"A restart is required after installation. Log out and install now?" alternate button "Cancel" default button ¬
				"Log out and install" as warning attached to window 1
		else
			display alert "Logout Recommeded" message ¬
				"A logout is recommeded before installation. Log out and install now?" alternate button "Install without logging out" default button ¬
				"Log out and install" as warning attached to window 1
		end if
	end if
end clicked

on will close theObject
	if the name of theObject is "mainWindow" then
		quit
	end if
end will close

on selection changed theObject
	if the name of theObject is "table" then
		set theDataRow to selected data row of theObject
		set theDescription to the contents of data cell "description" of theDataRow
		set theRestartAction to the contents of data cell "restartaction" of theDataRow
		if theRestartAction is "RequireRestart" then
			set theRestartAction to "Restart required after install."
		end if
		set theText to theDescription & return & theRestartAction
		set contents of text field "descriptionFld" of view "descriptionFldView" of scroll view ¬
			"descriptionScrollView" of view "splitViewBottom" of split view "splitView" of window id 1 to theText
	end if
end selection changed

on alert ended theObject with reply withReply
	if button returned of withReply is "Log out and install" then
		tell application "System Events"
			log out
		end tell
		quit
	end if
	if button returned of withReply is "Install without logging out" then
		--trigger managedinstaller
		set triggerpath to quoted form of (managedInstallDir & "/.run_managedinstaller")
		do shell script "/usr/bin/touch " & triggerpath
		quit
	end if
	if button returned of withReply is "OK" then
		-- acknowleged no new software available
		quit
	end if
end alert ended
