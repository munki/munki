#!/bin/sh

managedinstalldir="$(defaults read /Library/Preferences/ManagedInstalls ManagedInstallDir)"
plist_loc="$managedinstalldir/ConditionalItems"

IFS=$'\n'
for hardware_port in `networksetup -listallhardwareports | awk -F ": " '/Hardware Port/{print $2}'`; do
	hardware_ports+=( $hardware_port )
done

defaults write "$plist_loc" "hardware_ports" -array "${hardware_ports[@]}"
plutil -convert xml1 "$plist_loc".plist

exit 0
