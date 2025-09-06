#!/bin/bash
#
# Test script


# Defaults.
PKGID="com.googlecode.munki"
MUNKIROOT="."
# Convert to absolute path.
MUNKIROOT=$(cd "$MUNKIROOT"; pwd)
OUTPUTDIR="."
# Convert to absolute path.
OUTPUTDIR=$(cd "$OUTPUTDIR"; pwd)
CONFPKG=""

# try to automagically find Munki source root
TOOLSDIR=$(dirname "$0")
# Convert to absolute path.
TOOLSDIR=$(cd "$TOOLSDIR"; pwd)
PARENTDIR=$(dirname "$TOOLSDIR")
PARENTDIRNAME=$(basename "$PARENTDIR")
if [ "$PARENTDIRNAME" == "code" ]; then
    GRANDPARENTDIR=$(dirname "$PARENTDIR")
    GRANDPARENTDIRNAME=$(basename "$GRANDPARENTDIR")
    if [ "$GRANDPARENTDIRNAME" == "munki" ]; then
        MUNKIROOT="$GRANDPARENTDIR"
    fi
fi

if [ ! -d "$MUNKIROOT" ]; then
    echo "Please set the munki source root" 1>&2
    exit 1
else
    # Convert to absolute path.
    MUNKIROOT=$(cd "$MUNKIROOT"; pwd)
fi

if [ ! -d "$OUTPUTDIR" ]; then
    echo "Please set the output directory" 1>&2
    exit 1
fi


ACTOOL_OUTPUT="$OUTPUTDIR/actool_output"
mkdir -p "$ACTOOL_OUTPUT"
cd "$MUNKIROOT"

# run actool
echo "Running actool against Managed Software Center.xcodeproj..."
pushd "$MUNKIROOT/code/apps/Managed Software Center" > /dev/null

xcrun actool \
    Managed\ Software\ Center/Assets.xcassets \
    Managed\ Software\ Center/AppIcon.icon \
    --compile "$ACTOOL_OUTPUT" \
    --output-format human-readable-text --notices --warnings \
    --export-dependency-info "$ACTOOL_OUTPUT/assetcatalog_dependencies_thinned" \
    --output-partial-info-plist "$ACTOOL_OUTPUT/assetcatalog_generated_info.plist_thinned" \
    --app-icon AppIcon --skip-app-store-deployment \
    --enable-on-demand-resources NO --development-region en \
    --target-device mac --minimum-deployment-target 10.15 --platform macosx

RESULT="$?"
popd > /dev/null
if [ "$RESULT" -ne 0 ]; then
    echo "Error running actool against Managed Software Center.xcodeproj: $RESULT"
    exit 2
fi

echo "Done."
