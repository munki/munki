#!/bin/zsh

check_exit_code() {
    if [ "$1" != "0" ]; then
        echo "$2: $1" 1>&2
        exit 1
    fi
}

SWIFT_MUNKI_DIR="./cli/munki"

# Build makecatalogs
xcodebuild -project "$SWIFT_MUNKI_DIR/munki.xcodeproj" -scheme makecatalogs build
check_exit_code "$?" "Error building makecatalogs"

# Build makepkginfo
xcodebuild -project "$SWIFT_MUNKI_DIR/munki.xcodeproj" -scheme makepkginfo build
check_exit_code "$?" "Error building makepkginfo"
