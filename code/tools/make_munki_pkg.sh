#!/bin/sh
#
# Build script for munki tools package
# Builds an installer package for munki tools
#

# if you are building your own version of munki, you might
# want to change the pkgid to reflect your organization
PKGID=com.googlecode.munki

# set munkiroot to the root dir of your munki 'source'
munkiroot="/Users/Shared/munki/munki"
if [ ! -d "$munkiroot" ]; then
    echo "Please set your munkiroot" 1>&2
    exit -1
fi
# set packagedir to whereever you'd like the final package to be created
packagedir="/Users/Shared/pkgs"
if [ ! -d "$packagedir" ]; then
    echo "Please set your packagedir" 1>&2
    exit -1
fi


# get the version for the package
pushd "$munkiroot/code/client/munkilib" >/dev/null
munkivers=`python -c "import munkicommon; print munkicommon.get_version()" | cut -d" " -f1`
popd >/dev/null
svnrev=`svnversion | tr -cd '[:digit:]'`
VERS=$munkivers.$svnrev.0


usage() {
    echo "Usage: `basename \"$0\"` [Applications|Library|usr]"
    echo
    echo "By default all components are included in the package."
}


if [ $# -eq 0 ]; then
    BUILD_APP=YES
    BUILD_LIB=YES
    BUILD_USR=YES
else
    BUILD_APP=
    BUILD_LIB=
    BUILD_USR=
    while [ $# -gt 0 ]; do 
        case "$1" in
            "Applications")
                BUILD_APP=YES
                ;;
            "Library")
                BUILD_LIB=YES
                ;;
            "usr")
                BUILD_USR=YES
                ;;
            *)
                usage
                exit -1
                ;;
        esac
        shift
    done
fi


if [ ! -x "/Developer/usr/bin/packagemaker" ]; then
    echo "PackageMaker is not installed!"
    exit -1
fi

if [ $(id -u) -ne 0 ]; then
    echo "Please enter your sudo password if prompted."
fi


if [ "$BUILD_APP" == "YES" ]; then
    if [ ! -x "/usr/bin/xcodebuild" ]; then
        echo "Xcode is not installed!"
        exit -1
    fi    
    
    (
        cd "$munkiroot/code/Managed Software Update"
        /usr/bin/xcodebuild -project "Managed Software Update.xcodeproj" -alltargets
        XCODEBUILD_RESULT="$?"
        if [ "$XCODEBUILD_RESULT" -ne 0 ]; then
            echo "Error building Managed Software Update.app: $XCODEBUILD_RESULT"
            exit -1
        fi
    )
    
    if [ ! -e "$munkiroot/code/Managed Software Update/build/Release/Managed Software Update.app" ]; then
        echo "Need a release build of Managed Software Update.app!"
        echo "Open the Xcode project $munkiroot/code/Managed Software Update/Managed Software Update.xcodeproj and build it."
        exit -1
    fi
fi


if [ ! -d "$packagedir" ]; then
    mkdir -p "$packagedir"
fi

# prerun cleanup
rm -rf "$packagedir/munkitools-$VERS.pkg"
if [ -d /tmp/munkitools ]; then
    sudo rm -rf /tmp/munkitools
fi
mkdir /tmp/munkitools
cd /tmp/munkitools

if [ "$BUILD_USR" == "YES" ]; then
    mkdir -p ./usr/local/munki/munkilib
    chmod -R 755 ./usr
    cp "$munkiroot/code/client/"* ./usr/local/munki/ 2>&1 | grep -v "munkilib is a directory"
    cp "$munkiroot"/code/client/munkilib/*.py ./usr/local/munki/munkilib/
    # no pre/postflight scripts in the package, please
    rm -f ./usr/local/munki/preflight
    rm -f ./usr/local/munki/postflight
fi

if [ "$BUILD_APP" == "YES" ]; then
    mkdir -p ./Applications/Utilities
    chmod -R 775 ./Applications
    cp -R "$munkiroot/code/Managed Software Update/build/Release/Managed Software Update.app" ./Applications/Utilities/
    chmod -R o-w ./Applications/Utilities/Managed\ Software\ Update.app
fi

if [ "$BUILD_LIB" == "YES" ]; then
    mkdir -m 1775 ./Library
    mkdir -m 755 ./Library/LaunchAgents
    cp "$munkiroot/launchd/LaunchAgents/"*.plist ./Library/LaunchAgents/
    chmod 644 ./Library/LaunchAgents/*
    
    mkdir -m 755 ./Library/LaunchDaemons
    cp "$munkiroot/launchd/LaunchDaemons/"*.plist ./Library/LaunchDaemons/
    chmod 644 ./Library/LaunchDaemons/*

    # create these directories in the package so we have a record
    # and they can be removed later
    mkdir -m 755 -p ./Library/Managed\ Installs
    mkdir -m 750 -p ./Library/Managed\ Installs/Cache
    mkdir -m 750 -p ./Library/Managed\ Installs/catalogs
    mkdir -m 755 -p ./Library/Managed\ Installs/manifests
fi

chmod 1775 /tmp/munkitools
sudo chown root:admin /tmp/munkitools
sudo chown -hR root:wheel /tmp/munkitools
if [ -d ./Applications ]; then
    sudo chown -hR root:admin ./Applications
fi
if [ -d ./Library ]; then
    sudo chown root:admin ./Library
    sudo chown -hR root:admin ./Library/Managed\ Installs
fi

# Update Info.plist
MAJOR=`echo $VERS | cut -d. -f1`
MINOR=`echo $VERS | cut -d. -f2`
SIZE=`du -sk /tmp/munkitools | cut -f1`
INFO="$munkiroot/code/pkgtemplate/Info.plist"
/usr/libexec/PlistBuddy -c "set :CFBundleShortVersionString $VERS" "$INFO"
/usr/libexec/PlistBuddy -c "set :IFMajorVersion $MAJOR" "$INFO"
/usr/libexec/PlistBuddy -c "set :IFMinorVersion $MINOR" "$INFO"
/usr/libexec/PlistBuddy -c "set :IFPkgFlagInstalledSize $SIZE" "$INFO"
/usr/libexec/PlistBuddy -c "set :IFPkgFlagRestartAction RequiredRestart" "$INFO"

/Developer/usr/bin/packagemaker \
    --root . \
    --info "$INFO" \
    --resources "$munkiroot/code/pkgtemplate/Resources" \
    --id "$PKGID" \
    --version "$VERS" \
    --no-recommend \
    --no-relocate \
    --target 10.4 \
    --out "$packagedir/munkitools-$VERS.pkg" \
    --verbose
sudo rm -rf /tmp/munkitools
