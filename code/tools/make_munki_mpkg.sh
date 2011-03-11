#!/bin/bash
#
# Build script for munki tools, builds an mpkg distribution package.


# Defaults.
PKGTYPE="bundle"
PKGID="com.googlecode.munki"
MUNKIROOT="/Users/Shared/munki/munki"
OUTPUTDIR="/Users/Shared/pkgs"
CONFPKG=""


usage() {
    cat <<EOF
Usage: `basename $0` [-f] [-i id] [-r root] [-o dir] [-c package]"

    -f          Build a flat package (bundle is the default)
    -i id       Set the base package bundle ID
    -r root     Set the munki source root
    -o dir      Set the output directory
    -c package  Include a configuration package

EOF
}


while getopts "fi:r:o:c:h" option
do
    case $option in
        "f")
            echo "Flat metapackage creation is not yet implemented."
            exit 1
            PKGTYPE="flat"
            ;;
        "i")
            PKGID="$OPTARG"
            ;;
        "r")
            MUNKIROOT="$OPTARG"
            ;;
        "o")
            OUTPUTDIR="$OPTARG"
            ;;
        "c")
            CONFPKG="$OPTARG"
            ;;
        "h" | *)
            usage
            exit 1
            ;;
    esac
done
shift $(($OPTIND - 1))

if [ $# -ne 0 ]; then
    usage
    exit 1
fi

if [ ! -d "$MUNKIROOT" ]; then
    echo "Please set the munki root" 1>&2
    exit 1
fi

if [ ! -d "$OUTPUTDIR" ]; then
    echo "Please set the output directory" 1>&2
    exit 1
fi


# Get the munki version.
MUNKIVERS=`defaults read "$MUNKIROOT/code/client/munkilib/version" CFBundleShortVersionString`
SVNREV=`svnversion $MUNKIROOT | cut -d: -f2 | tr -cd '[:digit:]'`
VERSION=$MUNKIVERS.$SVNREV.0


# Configure flat or bundle package.
if [ "$PKGTYPE" == "flat" ]; then
    TARGET="10.5"
    MPKG="$OUTPUTDIR/munkitools-$VERSION.pkg"
else
    TARGET="10.4"
    MPKG="$OUTPUTDIR/munkitools-$VERSION.mpkg"
fi


# Sanity checks.
if [ ! -x "/Developer/usr/bin/packagemaker" ]; then
    echo "PackageMaker is not installed!"
    exit 1
fi
if [ ! -x "/usr/bin/xcodebuild" ]; then
    echo "Xcode is not installed!"
    exit 1
fi

if [ $(id -u) -ne 0 ]; then
    cat <<EOF

            #####################################################
            ##  Please enter your sudo password when prompted  ##
            #####################################################

EOF
fi


echo "Build variables"
echo
echo "  Package type: $PKGTYPE"
echo "  Bundle ID: $PKGID"
echo "  Munki root: $MUNKIROOT"
echo "  Output directory: $OUTPUTDIR"
echo "  Version: $VERSION"
echo


# Build Xcode project.
echo "Building Managed Software Update.xcodeproj..."
pushd "$MUNKIROOT/code/Managed Software Update" > /dev/null
/usr/bin/xcodebuild -project "Managed Software Update.xcodeproj" -alltargets clean > /dev/null
/usr/bin/xcodebuild -project "Managed Software Update.xcodeproj" -alltargets build > /dev/null
XCODEBUILD_RESULT="$?"
popd > /dev/null
if [ "$XCODEBUILD_RESULT" -ne 0 ]; then
    echo "Error building Managed Software Update.app: $XCODEBUILD_RESULT"
    exit 2
fi

if [ ! -e "$MUNKIROOT/code/Managed Software Update/build/Release/Managed Software Update.app" ]; then
    echo "Need a release build of Managed Software Update.app!"
    echo "Open the Xcode project $MUNKIROOT/code/Managed Software Update/Managed Software Update.xcodeproj and build it."
    exit 2
fi


# Create a PackageInfo or Info.plist.
makeinfo() {
    pkg="$1"
    out="$2_$pkg"
    id="$3.$pkg"
    ver="$4"
    size="$5"
    nfiles="$6"
    restart="$7"
    major=`echo $ver | cut -d. -f1`
    minor=`echo $ver | cut -d. -f2`
    if [ "$PKGTYPE" == "bundle" ]; then
        # Bundle packages want an Info.plist.
        echo "Creating Info.plist for $id-$ver"
        if [ "$restart" == "restart" ]; then
            restart="RequiredRestart"
        else
            restart=""
        fi
        cat > "$out" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleIdentifier</key>
	<string>$id</string>
	<key>CFBundleShortVersionString</key>
	<string>$ver</string>
	<key>IFMajorVersion</key>
	<integer>$major</integer>
	<key>IFMinorVersion</key>
	<integer>$minor</integer>
	<key>IFPkgFlagAllowBackRev</key>
	<false/>
	<key>IFPkgFlagAuthorizationAction</key>
	<string>RootAuthorization</string>
	<key>IFPkgFlagDefaultLocation</key>
	<string>/</string>
	<key>IFPkgFlagFollowLinks</key>
	<true/>
	<key>IFPkgFlagInstallFat</key>
	<false/>
	<key>IFPkgFlagInstalledSize</key>
	<integer>$size</integer>
	<key>IFPkgFlagIsRequired</key>
	<false/>
	<key>IFPkgFlagOverwritePermissions</key>
	<false/>
	<key>IFPkgFlagRelocatable</key>
	<false/>
	<key>IFPkgFlagRestartAction</key>
	<string>$restart</string>
	<key>IFPkgFlagRootVolumeOnly</key>
	<false/>
	<key>IFPkgFlagUpdateInstalledLanguages</key>
	<false/>
	<key>IFPkgFormatVersion</key>
	<real>0.1</real>
</dict>
</plist>
EOF
    else
        # Flat packages want a PackageInfo.
        if [ "$restart" == "restart" ]; then
            restart=' postinstall-action="restart"' # Leading space is important.
        else
            restart=""
        fi
        MSUID=`defaults read "$MUNKIROOT/code/Managed Software Update/build/Release/Managed Software Update.app/Contents/Info" CFBundleIdentifier`
        if [ "$pkg" == "app" ]; then
            app="<bundle id=\"$MSUID\"
            CFBundleIdentifier=\"$MSUID\"
            path=\"./Applications/Utilities/Managed Software Update.app\"
            CFBundleVersion=\"$ver\"/>
    <bundle-version>
        <bundle id=\"$MSUID\"/>
    </bundle-version>"
        else
            app=""
        fi
        cat > "$out" <<EOF
<pkg-info format-version="2" identifier="$id" version="$ver" install-location="/" auth="root"$restart>
    <payload installKBytes="$size" numberOfFiles="$nfiles"/>
    $app
</pkg-info>
EOF
    fi
}


# Pre-build cleanup.
rm -rf "$MPKG"


# Create temporary directory
PKGTMP=`mktemp -d -t munkipkg`


######################
## /usr/local/munki ##
######################

echo "Creating /usr package template..."

# Create directory structure.
USRROOT="$PKGTMP/munki_usr"
mkdir -m 1775 "$USRROOT"
mkdir -p "$USRROOT/usr/local/munki/munkilib"
chmod -R 755 "$USRROOT/usr"
# Copy command line utilities.
cp -X "$MUNKIROOT/code/client/"* "$USRROOT/usr/local/munki/" 2>&1 | grep -v "munkilib is a directory"
# Copy python library.
cp -X "$MUNKIROOT/code/client/munkilib/"*.py "$USRROOT/usr/local/munki/munkilib/"
# Copy munki version.
cp -X "$MUNKIROOT/code/client/munkilib/version.plist" "$USRROOT/usr/local/munki/munkilib/"
echo $SVNREV > "$USRROOT/usr/local/munki/munkilib/svnversion"
# Don't include scripts in the package.
rm -f "$USRROOT/usr/local/munki/preflight"
rm -f "$USRROOT/usr/local/munki/postflight"
rm -f "$USRROOT/usr/local/munki/report_broken_client"
# Set permissions.
chmod -R go-w "$USRROOT/usr/local/munki"
chmod +x "$USRROOT/usr/local/munki"
chmod +x "$USRROOT/usr/local/munki/munkilib/"*.py
# Create package info file.
USRSIZE=`du -sk $USRROOT | cut -f1`
NFILES=$(echo `find $USRROOT/ | wc -l`)
makeinfo usr "$PKGTMP/info" "$PKGID" "$VERSION" $USRSIZE $NFILES norestart


###################
## /Applications ##
###################

echo "Creating /Applications package template..."

# Create directory structure.
APPROOT="$PKGTMP/munki_app"
mkdir -m 1775 "$APPROOT"
mkdir -p "$APPROOT/Applications/Utilities"
chmod -R 775 "$APPROOT/Applications"
# Copy Application.
cp -R "$MUNKIROOT/code/Managed Software Update/build/Release/Managed Software Update.app" "$APPROOT/Applications/Utilities/"
chmod -R go-w "$APPROOT/Applications/Utilities/Managed Software Update.app"
# Create package info file.
APPSIZE=`du -sk $APPROOT | cut -f1`
NFILES=$(echo `find $APPROOT/ | wc -l`)
MSUVERSION=`defaults read "$MUNKIROOT/code/Managed Software Update/build/Release/Managed Software Update.app/Contents/Info" CFBundleShortVersionString`
makeinfo app "$PKGTMP/info" "$PKGID" "$MSUVERSION" $APPSIZE $NFILES norestart


##############
## /Library ##
##############

echo "Creating /Library package template..."

# Create directory structure.
LIBROOT="$PKGTMP/munki_lib"
mkdir -m 1775 "$LIBROOT"
mkdir -m 1775 "$LIBROOT/Library"
mkdir -m 755 "$LIBROOT/Library/LaunchAgents"
mkdir -m 755 "$LIBROOT/Library/LaunchDaemons"
mkdir -m 755 -p "$LIBROOT/Library/Managed Installs"
mkdir -m 750 -p "$LIBROOT/Library/Managed Installs/Cache"
mkdir -m 750 -p "$LIBROOT/Library/Managed Installs/catalogs"
mkdir -m 755 -p "$LIBROOT/Library/Managed Installs/manifests"
# Copy launch daemons and launch agents.
cp -X "$MUNKIROOT/launchd/LaunchAgents/"*.plist "$LIBROOT/Library/LaunchAgents/"
chmod 644 "$LIBROOT/Library/LaunchAgents/"*
cp -X "$MUNKIROOT/launchd/LaunchDaemons/"*.plist "$LIBROOT/Library/LaunchDaemons/"
chmod 644 "$LIBROOT/Library/LaunchDaemons/"*
# Create package info file.
LIBSIZE=`du -sk $LIBROOT | cut -f1`
NFILES=$(echo `find $LIBROOT/ | wc -l`)
makeinfo lib "$PKGTMP/info" "$PKGID" "$VERSION" $LIBSIZE $NFILES restart


#############################
## Create metapackage root ##
#############################

echo "Creating meta package template..."

if [ "$PKGTYPE" == "flat" ]; then
    # Create root for xar.
    METAROOT="$PKGTMP/munki_mpkg"
    # Copy Resources.
    cp -R "$MUNKIROOT/code/pkgtemplate/Resources" "$METAROOT/"
    # Configure Distribution
    DISTFILE="$METAROOT/Distribution"
    PKGPREFIX="#"
    # Package destination directory.
    PKGDEST="$METAROOT"
else
    # Create meta package directory structure.
    METAROOT="$MPKG"
    mkdir -p "$METAROOT/Contents/Packages"
    # Copy Resources.
    cp -R "$MUNKIROOT/code/pkgtemplate/Resources" "$METAROOT/Contents/"
    find -d "$METAROOT" -name .svn -exec rm -rf {} \;
    # Configure Distribution.dist.
    DISTFILE="$METAROOT/Contents/distribution.dist"
    PKGPREFIX="file:./Contents/Packages/"
    # Package destination directory.
    PKGDEST="$METAROOT/Contents/Packages"
fi
# Create Distribution file.
USRTITLE=`defaults read "$MUNKIROOT/code/pkgtemplate/Resources_usr/English.lproj/Description" IFPkgDescriptionTitle`
APPTITLE=`defaults read "$MUNKIROOT/code/pkgtemplate/Resources_app/English.lproj/Description" IFPkgDescriptionTitle`
LIBTITLE=`defaults read "$MUNKIROOT/code/pkgtemplate/Resources_lib/English.lproj/Description" IFPkgDescriptionTitle`
USRDESC=`defaults read "$MUNKIROOT/code/pkgtemplate/Resources_usr/English.lproj/Description" IFPkgDescriptionDescription`
APPDESC=`defaults read "$MUNKIROOT/code/pkgtemplate/Resources_app/English.lproj/Description" IFPkgDescriptionDescription`
LIBDESC=`defaults read "$MUNKIROOT/code/pkgtemplate/Resources_lib/English.lproj/Description" IFPkgDescriptionDescription`
CONFOUTLINE=""
CONFCHOICE=""
CONFREF=""
if [ ! -z "$CONFPKG" ]; then
    if [ $PKGTYPE == "flag" ]; then
        echo "Flat configuration package not implemented"
        exit 1
    else
        if [ -d "$CONFPKG/Contents/Resources/English.lproj" ]; then
            eng_resources="$CONFPKG/Contents/Resources/English.lproj"
        elif [ -d "$CONFPKG/Contents/Resources/en.lproj" ]; then
            eng_resources="$CONFPKG/Contents/Resources/en.lproj"
        else
            echo "Can't find English.lproj or en.lproj in $CONFPKG/Contents/Resources"
            exit 1
        fi
        CONFTITLE=`defaults read "$eng_resources/Description" IFPkgDescriptionTitle`
        CONFDESC=`defaults read "$eng_resources/Description" IFPkgDescriptionDescription`
        CONFID=`defaults read "$CONFPKG/Contents/Info" CFBundleIdentifier`
        CONFSIZE=`defaults read "$CONFPKG/Contents/Info" IFPkgFlagInstalledSize`
        CONFVERSION=`defaults read "$CONFPKG/Contents/Info" CFBundleShortVersionString`
        CONFBASENAME=`basename "$CONFPKG"`
    fi
    CONFOUTLINE="<line choice=\"choice3\"/>"
    CONFCHOICE="<choice id=\"choice3\" title=\"$CONFTITLE\" description=\"$CONFDESC\">
        <pkg-ref id=\"$CONFID\"/>
    </choice>"
    CONFREF="<pkg-ref id=\"$CONFID\" installKBytes=\"$CONFSIZE\" version=\"$CONFVERSION\" auth=\"Root\">${PKGPREFIX}$CONFBASENAME</pkg-ref>"
fi
cat > "$DISTFILE" <<EOF
<?xml version="1.0" encoding="utf-8"?>
<installer-script minSpecVersion="1.000000" authoringTool="com.apple.PackageMaker" authoringToolVersion="3.0.4" authoringToolBuild="179">
    <title>Munki - Managed software installation for OS X</title>
    <options customize="allow" allow-external-scripts="no"/>
    <domains enable_anywhere="true"/>
    <choices-outline>
        <line choice="choice0"/>
        <line choice="choice1"/>
        <line choice="choice2"/>
        $CONFOUTLINE
    </choices-outline>
    <choice id="choice0" title="$USRTITLE" description="$USRDESC">
        <pkg-ref id="$PKGID.usr"/>
    </choice>
    <choice id="choice1" title="$APPTITLE" description="$APPDESC">
        <pkg-ref id="$PKGID.app"/>
    </choice>
    <choice id="choice2" title="$LIBTITLE" description="$LIBDESC">
        <pkg-ref id="$PKGID.lib"/>
    </choice>
    $CONFCHOICE
    <pkg-ref id="$PKGID.usr" installKBytes="$USRSIZE" version="$VERSION" auth="Root">${PKGPREFIX}munkitools_usr-$VERSION.pkg</pkg-ref>
    <pkg-ref id="$PKGID.app" installKBytes="$APPSIZE" version="$MSUVERSION" auth="Root">${PKGPREFIX}munkitools_app-$MSUVERSION.pkg</pkg-ref>
    <pkg-ref id="$PKGID.lib" installKBytes="$LIBSIZE" version="$VERSION" auth="Root" onConclusion="RequireRestart">${PKGPREFIX}munkitools_lib-$VERSION.pkg</pkg-ref>
    $CONFREF
</installer-script>
EOF


###################
## Set ownership ##
###################

echo "Setting ownership to root..."

sudo chown root:admin "$USRROOT" "$APPROOT" "$LIBROOT"
sudo chown -hR root:wheel "$USRROOT/usr"
sudo chown -hR root:admin "$APPROOT/Applications"
sudo chown root:admin "$LIBROOT/Library"
sudo chown -hR root:wheel "$LIBROOT/Library/LaunchDaemons"
sudo chown -hR root:wheel "$LIBROOT/Library/LaunchAgents"
sudo chown -hR root:admin "$LIBROOT/Library/Managed Installs"


######################
## Run PackageMaker ##
######################

for pkg in usr app lib; do
    if [ "$pkg" == "app" ]; then
        ver="$MSUVERSION"
    else
        ver="$VERSION"
    fi
    echo "Packaging munkitools_$pkg-$ver.pkg"
    /Developer/usr/bin/packagemaker \
        --root "$PKGTMP/munki_$pkg" \
        --info "$PKGTMP/info_$pkg" \
        --resources "$MUNKIROOT/code/pkgtemplate/Resources_$pkg" \
        --id "$PKGID.$pkg" \
        --version "$ver" \
        --no-recommend \
        --no-relocate \
        --target $TARGET \
        --out "$PKGDEST/munkitools_$pkg-$ver.pkg" \
        #--verbose
done


if [ "$PKGTYPE" == "flat" ]; then
    # FIXME: we should call packagemaker here
    echo "No flat package creation yet!"
else
    if [ ! -z "$CONFPKG" ]; then
        echo Copying `basename "$CONFPKG"`
        cp -rp "$CONFPKG" "$PKGDEST"
    fi
    echo "Metapackage created at $MPKG"
fi

echo "Removing temporary files..."
sudo rm -rf "$PKGTMP"

echo "Done."
