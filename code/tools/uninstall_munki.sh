#!/bin/bash
#
# Merciless uninstall of munki.


if [ `id -u` -ne 0 ]; then
    echo "Munki uninstallation must be run by root"
    exit 1
fi

launchctl unload /Library/LaunchDaemons/com.googlecode.munki.*
rm -rf "/Applications/Utilities/Managed Software Update.app"
rm -f /Library/LaunchDaemons/com.googlecode.munki.*
rm -f /Library/LaunchAgents/com.googlecode.munki.*
rm -rf "/Library/Managed Installs"
rm -rf /usr/local/munki
pkgutil --forget com.googlecode.munki.core
pkgutil --forget com.googlecode.munki.admin
pkgutil --forget com.googlecode.munki.app
pkgutil --forget com.googlecode.munki.launchd
pkgutil --forget com.googlecode.munki