#!/bin/sh

/bin/rm /Users/Shared/.com.googlecode.munki.autorunmanagedsoftwarecenter

/usr/local/munki/supervisor -- /usr/local/munki/managedsoftwareupdate --auto

exit 0
