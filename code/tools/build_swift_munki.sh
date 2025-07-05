#!/bin/sh
export PATH=/usr/bin:/bin:/usr/sbin:/sbin

check_exit_code() {
    if [ "$1" != "0" ]; then
        echo "$2: $1" 1>&2
        exit 1
    fi
}

TOOLS="managedsoftwareupdate makecatalogs makepkginfo munkiimport removepackages app_usage_monitor appusaged authrestartd launchapp logouthelper iconimporter repoclean manifestutil precache_agent supervisor installhelper"

TOOLSDIR=$(dirname "$0")
# Convert to absolute path.
TOOLSDIR=$(cd "${TOOLSDIR}" ; pwd)
CODEDIR=$(dirname "${TOOLSDIR}")

MUNKI_PROJ="${CODEDIR}/cli/munki/munki.xcodeproj"
if [ ! -e "${MUNKI_PROJ}" ] ; then
    check_exit_code 1 "${MUNKI_PROJ} doesn't exist"
fi

BUILD_DIR="${CODEDIR}/build"
BINARIES_DIR="${CODEDIR}/build/binaries"

if [ ! -d "${BUILD_DIR}" ] ; then
    mkdir "${BUILD_DIR}"
fi

if [ ! -d "${BINARIES_DIR}" ] ; then
    mkdir "${BINARIES_DIR}"
fi

for TOOL in ${TOOLS} ; do
    xcodebuild \
        -project "${MUNKI_PROJ}" \
        -configuration Release \
        -scheme "${TOOL}" \
        -destination "generic/platform=macOS" \
        -derivedDataPath "${BUILD_DIR}" \
        build
    check_exit_code "$?" "Error building ${TOOL}"
    cp "${BUILD_DIR}/Build/Products/Release/${TOOL}" "${BINARIES_DIR}/"
done
