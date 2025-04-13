#!/bin/sh
export PATH=/usr/bin:/bin:/usr/sbin:/sbin

check_exit_code() {
    if [ "$1" != "0" ]; then
        echo "$2: $1" 1>&2
        exit 1
    fi
}

SWIFT_MUNKI_DIR="./cli/munki"
BUILD_DIR="./build"
BINARIES_DIR="./binaries"

if [ ! -d "${BUILD_DIR}" ] ; then
    mkdir "${BUILD_DIR}"
fi

if [ ! -d "${BINARIES_DIR}" ] ; then
    mkdir "${BINARIES_DIR}"
fi

xcodebuild \
    -project "${SWIFT_MUNKI_DIR}/munki.xcodeproj" \
    -alltargets \
    -derivedDataPath "${BUILD_DIR}" \
    build

for TOOL in managedsoftwareupdate makecatalogs makepkginfo munkiimport removepackages app_usage_monitor appusaged authrestartd launchapp logouthelper iconimporter repoclean ; do
    xcodebuild \
        -project "${SWIFT_MUNKI_DIR}/munki.xcodeproj" \
        -configuration Release \
        -scheme ${TOOL} \
        -destination "generic/platform=macOS" \
        -derivedDataPath "${BUILD_DIR}" \
        build
    check_exit_code "$?" "Error building ${TOOL}"
    cp "$BUILD_DIR/Build/Products/Release/${TOOL}" "${BINARIES_DIR}/"
done
