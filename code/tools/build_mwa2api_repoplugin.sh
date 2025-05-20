#!/bin/sh
export PATH=/usr/bin:/bin:/usr/sbin:/sbin

check_exit_code() {
    if [ "$1" != "0" ]; then
        echo "$2: $1" 1>&2
        exit 1
    fi
}

TOOL="MWA2APIRepo"
VERSION="2.0.0"

# find the Xcode project
TOOLSDIR=$(dirname "$0")
# Convert to absolute path.
TOOLSDIR=$(cd "${TOOLSDIR}" ; pwd)
CODEDIR=$(dirname "${TOOLSDIR}")
MUNKIROOT=$(dirname "${CODEDIR}")

PLUGIN_PROJ_PARENT="${CODEDIR}/cli/MWA2APIRepo"
PLUGIN_PROJ="${PLUGIN_PROJ_PARENT}/MWA2APIRepo.xcodeproj"
if [ ! -e "${PLUGIN_PROJ}" ] ; then
    check_exit_code 1 "${PLUGIN_PROJ} doesn't exist"
fi

# generate a revision number for from the list of Git revisions
GITREV=$(git log -n1 --format="%H" -- "${PLUGIN_PROJ_PARENT}")
GITREVINDEX=$(git rev-list --count "$GITREV")
VERSION="${VERSION}.${GITREVINDEX}"

# make sure we have a build directory to use
BUILD_DIR="${CODEDIR}/build"
if [ ! -d "${BUILD_DIR}" ] ; then
    mkdir "${BUILD_DIR}"
fi

# build the dylib
xcodebuild \
    -project "${PLUGIN_PROJ}" \
    -configuration Release \
    -scheme "${TOOL}" \
    -destination "generic/platform=macOS" \
    -derivedDataPath "${BUILD_DIR}" \
    build 1>/dev/null

check_exit_code "$?" "Error building ${TOOL}.plugin"

# build a pkg (component pkg for now)

# make the payload (package root) dir
PKG_ROOT="${CODEDIR}/${TOOL}_payload"
mkdir -p "${PKG_ROOT}/usr/local/munki/repoplugins"
chmod -R 755 "${PKG_ROOT}"

# copy the dylib into the payload
cp "${BUILD_DIR}/Build/Products/Release/${TOOL}.plugin" "${PKG_ROOT}/usr/local/munki/repoplugins/"

# build the pkg!
pkgbuild \
    --root "${PKG_ROOT}" \
    --identifier "com.googlecode.munki.${TOOL}" \
    --version "${VERSION}" \
    --ownership recommended \
    "${MUNKIROOT}/${TOOL}-${VERSION}.pkg"

#if [ $? -eq 0 ] ; then
#    # clean up!
#    rm -r "$BUILD_DIR"
#    rm -r "$PKG_ROOT"
#fi
