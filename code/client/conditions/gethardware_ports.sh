#!/bin/sh
# This is an example of a bash conditional script which outputs a key with an array of values
# Please note how the array is created and used within the defaults statement for proper output

# Read the location of the ManagedInstallDir from ManagedInstall.plist
managedinstalldir="$(defaults read /Library/Preferences/ManagedInstalls ManagedInstallDir)"
# Make sure we're outputting our information to "ConditionalItems.plist" (plist is left off since defaults requires this)
plist_loc="$managedinstalldir/ConditionalItems"

IFS=$'\n' # Set our field spearator to newline since each unique item is on its own line
for hardware_port in `networksetup -listallhardwareports | awk -F ": " '/Hardware Port/{print $2}'`; do
	# build array of values from output of above command
	hardware_ports+=( $hardware_port )
done

# Note the key "hardware_ports" which becomes the condition that you would use in a predicate statement
defaults write "$plist_loc" "hardware_ports" -array "${hardware_ports[@]}"

# CRITICAL! Since 'defaults' outputs a binary plist, we need to ensure that munki can read it by converting it to xml
plutil -convert xml1 "$plist_loc".plist

exit 0
