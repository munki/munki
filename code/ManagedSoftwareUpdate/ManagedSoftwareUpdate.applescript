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
property restartRequired : false
property installitems : {}
property activationCount : 0
property ManagedInstallPrefs : "/Library/Preferences/ManagedInstalls.plist"

on getRemovalDetailPrefs()
	set ShowRemovalDetail to false
	try
		tell application "System Events"
			set ShowRemovalDetail to value of property list item "ShowRemovalDetail" of property list file ManagedInstallPrefs
		end tell
	end try
	return ShowRemovalDetail
end getRemovalDetailPrefs

on getInstallInfoFile()
	try
		tell application "System Events"
			set managedInstallDir to value of property list item "ManagedInstallDir" of property list file ManagedInstallPrefs
		end tell
	on error
		set managedInstallDir to "/Library/Managed Installs"
	end try
	try
		set InstallInfo to managedInstallDir & "/InstallInfo.plist"
		copy (do shell script "test -e " & quoted form of InstallInfo) to result
		return InstallInfo
	on error
		return ""
	end try
end getInstallInfoFile


on itemstoinstall()
	set installlist to {}
	copy getInstallInfoFile() to InstallInfo
	if InstallInfo is not "" then
		try
			tell application "System Events"
				set InstallInfo to managedInstallDir & "/InstallInfo.plist"
				set managedinstalllist to value of property list item "managed_installs" of property list file InstallInfo
			end tell
			repeat with installitem in managedinstalllist
				try
					if exists (installer_item of installitem) then
						set end of installlist to (installitem as item)
						try
							if |RestartAction| of installitem is "RequireRestart" then
								set restartRequired to true
							end if
						end try
					end if
				end try
			end repeat
		end try
		
		set ShowRemovalDetail to getRemovalDetailPrefs()
		try
			tell application "System Events"
				set removallist to value of property list item "removals" of property list file InstallInfo
			end tell
			set removalcount to 0
			repeat with removalitem in removallist
				if (installed of removalitem) is true then
					set removalcount to removalcount + 1
					try
						if |RestartAction| of removalitem is "RequireRestart" then
							set restartRequired to true
						end if
					end try
					if ShowRemovalDetail then
						set display_name of removalitem to display_name of removalitem & " (will be removed)"
						set end of installlist to (removalitem as item)
					end if
				end if
			end repeat
			if not ShowRemovalDetail then
				if removalcount > 0 then
					if restartRequired then
						try
							set |RestartAction| of removalitem to "RequireRestart"
						on error
							set removalitem to removalitem & {|RestartAction|:"RequireRestart"}
						end try
					end if
					set display_name of removalitem to "Software removals"
					set |description| of removalitem to "Scheduled removal of managed software."
					set end of installlist to (removalitem as item)
				end if
			end if
		end try
		try
			tell application "System Events"
				set AppleUpdates to managedInstallDir & "/AppleUpdates.plist"
				set appleupdatelist to value of property list item "AppleUpdates" of property list file AppleUpdates
			end tell
			--set AppleUpdatesHeader to {display_name:"Apple Software Updates", version_to_install:"", |description|:"", |RestartAction|:""}
			--set end of installlist to AppleUpdatesHeader
			repeat with installitem in appleupdatelist
				set end of installlist to (installitem as item)
			end repeat
		end try
	end if
	return installlist as list
end itemstoinstall


on updateTable()
	set datasource to data source of table view "table" of scroll view ¬
		"tableScrollView" of view "splitViewTop" of split view "splitView" of window "MainWindow"
	set EmptyImage to load image "Empty"
	set RestartImage to load image "RestartReq"
	set installitems to my itemstoinstall()
	delete every data row of datasource
	repeat with installitem in installitems
		
		set theDataRow to make new data row at end of data rows of datasource
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
		
		set shortVersion to ""
		set oldDelims to AppleScript's text item delimiters
		try
			if version_to_install of installitem is not "" then
				set AppleScript's text item delimiters to "."
				if (count of text items of version_to_install of installitem) > 3 then
					set shortVersion to text items 1 through 3 of version_to_install of installitem as text
				else
					set shortVersion to version_to_install of installitem
				end if
			end if
		end try
		set AppleScript's text item delimiters to oldDelims
		
		set contents of data cell "version" of theDataRow to shortVersion
		set contents of data cell "description" of theDataRow to |description| of installitem
		try
			set contents of data cell "restartaction" of theDataRow to |RestartAction| of installitem
		end try
	end repeat
end updateTable

on initTable()
	set theTable to table view "table" of scroll view ¬
		"tableScrollView" of view "splitViewTop" of split view "splitView" of window "MainWindow"
	set theDataSource to make new data source at end
	make new data column at end of data columns of theDataSource with properties {name:"image"}
	make new data column at end of data columns of theDataSource with properties {name:"name"}
	make new data column at end of data columns of theDataSource with properties {name:"version"}
	make new data column at end of data columns of theDataSource with properties {name:"description"}
	make new data column at end of data columns of theDataSource with properties {name:"restartaction"}
	
	set data source of theTable to theDataSource
end initTable

on installAll()
	if restartRequired then
		display alert "Restart Required" message ¬
			"A restart is required after updating. Log out and update now?" alternate button "Cancel" default button ¬
			"Log out and update" as warning attached to window 1
	else
		display alert "Logout Recommeded" message ¬
			"A logout is recommeded before updating. Log out and update now?" alternate button "Cancel" other button "Update without logging out" default button ¬
			"Log out and update" as warning attached to window 1
	end if
end installAll

on awake from nib
	-- nothing
end awake from nib


on clicked theObject
	if the name of theObject is "laterBtn" then
		quit
	end if
	
	if the name of theObject is "installBtn" then
		my installAll()
	end if
end clicked

on will close theObject
	if the name of theObject is "mainWindow" then
		quit
	end if
end will close

on selection changed theObject
	if the name of theObject is "table" then
		if selected data rows of theObject is not {} then
			set theDataRow to selected data row of theObject
			set theDescription to the contents of data cell "description" of theDataRow
			set theRestartAction to the contents of data cell "restartaction" of theDataRow
			if theRestartAction is "RequireRestart" then
				set theRestartAction to return & "Restart required after install."
			end if
			set theText to theDescription & return & theRestartAction
		else
			set theText to ""
		end if
		set contents of text view "description" of scroll view ¬
			"descriptionScrollView" of view "splitViewBottom" of split view "splitView" of window id 1 to theText
	end if
end selection changed

on alert ended theObject with reply withReply
	if button returned of withReply is "Log out and update" then
		-- touch a flag so the process that runs after
		-- logout knows it's OK to install everything
		do shell script "/usr/bin/touch /private/tmp/com.googlecode.munki.installatlogout"
		ignoring application responses
			tell application "loginwindow"
				-- "really log out"
				«event aevtrlgo»
			end tell
		end ignoring
	end if
	if button returned of withReply is "Update without logging out" then
		-- trigger managedinstaller via launchd WatchPath
		-- we touch a file that launchd is is watching
		-- launchd, in turn, launches managedsoftwareupdate --installonly as root
		set triggerpath to quoted form of (managedInstallDir & "/.managedinstall.launchd")
		do shell script "/usr/bin/touch " & triggerpath
		quit
	end if
	if button returned of withReply is "Quit" then
		-- acknowleged no new software available, or installing later
		quit
	end if
	
end alert ended

on activated theObject
	set activationCount to activationCount + 1
	set installitems to my itemstoinstall()
	if (count of installitems) > 0 then
		show window "mainWindow"
		set enabled of (menu item "installAllMenuItem" of menu "updateMenu" of menu 1) to true
	else
		if activationCount is 1 then
			-- trigger manual update check, but only on launch
			-- we touch a file that launchd is is watching
			-- launchd, in turn, launches managedsoftwareupdate --manualcheck as root
			set triggerpath to quoted form of (managedInstallDir & "/.updatecheck.launchd")
			do shell script "/usr/bin/touch " & triggerpath
			-- when it's done, it sends an activate message to us again
		else
			show window "mainWindow"
			display alert "Your software is up to date." message ¬
				"There is no new software for your computer at this time." default button "Quit" as informational attached to window 1
		end if
	end if
end activated


on opened theObject
	if the name of theObject is "mainWindow" then
		my initTable()
		my updateTable()
	end if
end opened

on choose menu item theObject
	if the name of theObject is "installAllMenuItem" then
		my installAll()
	end if
end choose menu item
