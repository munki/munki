#!/bin/sh

check_exit_code() {
    if [ "$1" != "0" ]; then
        echo "$2: $1" 1>&2
        exit 1
    fi
}

SWIFT_MUNKI_DIR="./cli/munki"

for TOOL in managedsoftwareupdate makecatalogs makepkginfo munkiimport removepackages app_usage_monitor appusaged authrestartd launchapp logouthelper iconimporter repoclean ; do
    xcodebuild -project "$SWIFT_MUNKI_DIR/munki.xcodeproj" -configuration Release -scheme $TOOL build
    check_exit_code "$?" "Error building $TOOL"
done
