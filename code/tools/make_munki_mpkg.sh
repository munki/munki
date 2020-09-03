#!/bin/bash
#
# Build script for munki tools, builds a distribution package.


# Defaults.
PKGID="com.googlecode.munki"
MUNKIROOT="."
# Convert to absolute path.
MUNKIROOT=$(cd "$MUNKIROOT"; pwd)
OUTPUTDIR="."
# Convert to absolute path.
OUTPUTDIR=$(cd "$OUTPUTDIR"; pwd)
CONFPKG=""
# add this number to Git revision index to get "build" number
# consistent with old SVN repo
MAGICNUMBER=482
BUILDPYTHON=NO
PKGSIGNINGCERT=""
APPSIGNINGCERT=""
BOOTSTRAPPKG=NO
CONFPKG=NO
MDMSTYLE=NO
ORGNAME=macOS

# try to automagically find Munki source root
TOOLSDIR=$(dirname "$0")
# Convert to absolute path.
TOOLSDIR=$(cd "$TOOLSDIR"; pwd)
PARENTDIR=$(dirname "$TOOLSDIR")
PARENTDIRNAME=$(basename "$PARENTDIR")
if [ "$PARENTDIRNAME" == "code" ]; then
    GRANDPARENTDIR=$(dirname "$PARENTDIR")
    GRANDPARENTDIRNAME=$(basename "$GRANDPARENTDIR")
    if [ "$GRANDPARENTDIRNAME" == "Munki2" ]; then
        MUNKIROOT="$GRANDPARENTDIR"
    fi
fi

usage() {
    cat <<EOF
Usage: $(basename "$0") [-i id] [-r root] [-o dir] [-c package] [-s cert]

    -i id       Specify the base package bundle ID
    -r root     Specify the Munki source root
    -o dir      Specify the output directory
    -n orgname  Specify the name of the organization
    -p          Build Python.framework even if one exists
    -B          Include a package that sets Munki's bootstrap mode
    -m          Build the package in a manner suitable for install via MDM;
                specifically, attempt to start all the launchd agents and
                daemons without requiring a restart. Such a package is not
                suited for upgrade installs or install via Munki itself.
    -c plist    Build a configuration package using the preferences defined in a
                plist file. 
    -s cert_cn  Sign distribution package with a Developer ID Installer
                certificate from keychain. Provide the certificate's Common
                Name. Ex: "Developer ID Installer: Munki (U8PN57A5N2)"
    -S cert_cn  Sign apps with a Developer ID Application certificated from
                keychain. Provide the certificate's Common Name.
                Ex: "Developer ID Application: Munki (U8PN57A5N2)"

EOF
}


while getopts "i:r:o:n:c:s:S:pBmh" option
do
    case $option in
        "i")
            PKGID="$OPTARG"
            ;;
        "r")
            MUNKIROOT="$OPTARG"
            ;;
        "o")
            OUTPUTDIR="$OPTARG"
            ;;
        "n")
            ORGNAME="$OPTARG"
            ;;
        "c")
            CONFPLIST="$OPTARG"
            CONFPKG=YES
            ;;
        "s")
            PKGSIGNINGCERT="$OPTARG"
            ;;
        "S")
            APPSIGNINGCERT="$OPTARG"
            ;;
        "p")
            BUILDPYTHON=YES
            ;;
        "B")
            BOOTSTRAPPKG=YES
            ;;
        "m")
            MDMSTYLE=YES
            ;;
        "h" | *)
            usage
            exit 1
            ;;
    esac
done
shift $((OPTIND - 1))

if [ $# -ne 0 ]; then
    usage
    exit 1
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

# Sanity checks.
if ! which git 1>/dev/null ; then
    echo "Could not find git in command path. Maybe it's not installed?" 1>&2
    echo "You can get a Git package here:" 1>&2
    echo "    https://git-scm.com/download/mac"
    exit 1
fi
if [ ! -x "/usr/bin/pkgbuild" ]; then
    echo "pkgbuild is not installed!" 1>&2
    exit 1
fi
if [ ! -x "/usr/bin/productbuild" ]; then
    echo "productbuild is not installed!" 1>&2
    exit 1
fi
if [ ! -x "/usr/bin/xcodebuild" ]; then
    echo "xcodebuild is not installed!" 1>&2
    exit 1
fi
if [[ "$CONFPKG" == "YES" ]] ; then
    CONFDIRPATH="$(cd "$(dirname "$CONFPLIST")" ; pwd)"
    CONFPLISTNAME="$(basename "$CONFPLIST")"
    CONFFULLPATH="${CONFDIRPATH}/${CONFPLISTNAME}"
    if ! defaults read "$CONFFULLPATH" 1>/dev/null ; then
        echo "Could not read $CONFFULLPATH, or invalid plist!"
        exit 1
    fi
fi


# Get the munki version
MUNKIVERS=$(defaults read "$MUNKIROOT/code/client/munkilib/version" CFBundleShortVersionString)
if [ "$?" != "0" ]; then
    echo "$MUNKIROOT/code/client/munkilib/version is missing!" 1>&2
    echo "Perhaps $MUNKIROOT does not contain the munki source?" 1>&2
    exit 1
fi

# Build the Python framework if requested or missing
if [ "$BUILDPYTHON" == "YES" ] || [ ! -d "$MUNKIROOT/Python.framework" ]; then
    PYTHONBUILDTOOL="${TOOLSDIR}/build_python_framework.sh"
    if [ ! -x "${PYTHONBUILDTOOL}" ] ; then
        echo "${PYTHONBUILDTOOL} is missing!" 1>&2
        exit 1
    fi
    echo "Building Python.framework..."
    if ! "${PYTHONBUILDTOOL}" ; then
        echo "Building Python.framework failed!" 1>&2
        exit 1
    fi
fi

cd "$MUNKIROOT"
# generate a pseudo-svn revision number for the core tools (and admin tools)
# from the list of Git revisions
GITREV=$(git log -n1 --format="%H" -- code/client)
GITREVINDEX=$(git rev-list --count "$GITREV")
SVNREV=$((GITREVINDEX + MAGICNUMBER))
MPKGSVNREV=$SVNREV
VERSION=$MUNKIVERS.$SVNREV

# get a pseudo-svn revision number for the apps pkg
APPSGITREV=$(git log -n1 --format="%H" -- code/apps)
GITREVINDEX=$(git rev-list --count "$APPSGITREV")
APPSSVNREV=$((GITREVINDEX + MAGICNUMBER))
if [ $APPSSVNREV -gt $MPKGSVNREV ] ; then
    MPKGSVNREV=$APPSSVNREV
fi
# get base apps version from MSC.app
APPSVERSION=$(defaults read "$MUNKIROOT/code/apps/Managed Software Center/Managed Software Center/Info" CFBundleShortVersionString)
# append the APPSSVNREV
APPSVERSION=$APPSVERSION.$APPSSVNREV

# get a pseudo-svn revision number for the launchd pkg
LAUNCHDGITREV=$(git log -n1 --format="%H" -- launchd/LaunchDaemons launchd/LaunchAgents)
GITREVINDEX=$(git rev-list --count "$LAUNCHDGITREV")
LAUNCHDSVNREV=$((GITREVINDEX + MAGICNUMBER))
if [ $LAUNCHDSVNREV -gt $MPKGSVNREV ] ; then
    MPKGSVNREV=$LAUNCHDSVNREV
fi
# Get launchd version if different
LAUNCHDVERSION=$MUNKIVERS
if [ -e "$MUNKIROOT/launchd/version.plist" ]; then
    LAUNCHDVERSION=$(defaults read "$MUNKIROOT/launchd/version" CFBundleShortVersionString)
fi
LAUNCHDVERSION=$LAUNCHDVERSION.$LAUNCHDSVNREV
# get a pseudo-svn revision number for the Python pkg
PYTHONGITREV=$(git log -n1 --format="%H" -- code/tools/py3_requirements.txt code/tools/build_python_framework.sh)
GITREVINDEX=$(git rev-list --count "$PYTHONGITREV")
PYTHONSVNREV=$((GITREVINDEX + MAGICNUMBER))
if [ $PYTHONSVNREV -gt $MPKGSVNREV ] ; then
    MPKGSVNREV=$PYTHONSVNREV
fi
# Get Python version
PYTHONVERSION="NOT FOUND"
PYTHONINFOPLIST="$MUNKIROOT"/Python.framework/Versions/Current/Resources/Info.plist
if [ -f "$PYTHONINFOPLIST" ]; then
    PYTHONVERSION=$(defaults read "$PYTHONINFOPLIST" CFBundleVersion)
fi
PYTHONVERSION=$PYTHONVERSION.$PYTHONSVNREV


# get a pseudo-svn revision number for the metapackage
MPKGVERSION=$MUNKIVERS.$MPKGSVNREV

MPKG="$OUTPUTDIR/munkitools-$MPKGVERSION.pkg"


if [ "$(id -u)" -ne 0 ]; then
    cat <<EOF

            #####################################################
            ##  Please enter your sudo password when prompted  ##
            #####################################################

EOF
fi

echo "Build variables"
echo
echo "  munki core tools version: $VERSION"
echo "  LaunchAgents/LaunchDaemons version: $LAUNCHDVERSION"
echo "  Apps package version: $APPSVERSION"
echo "  Python package version: $PYTHONVERSION"
echo
echo "  metapackage version: $MPKGVERSION"
echo
echo "  Bundle ID: $PKGID"
echo "  Munki source root: $MUNKIROOT"
echo "  Output directory: $OUTPUTDIR"
echo "  Include bootstrap pkg: $BOOTSTRAPPKG"
if [ "$CONFPKG" == "YES" ] ; then
    echo "  Include config pkg built with plist: $CONFFULLPATH"
else
    echo "  Include config pkg: NO"
fi
echo "  MDM-style package: $MDMSTYLE"
echo
if [ "$APPSIGNINGCERT" != "" ] ; then
    echo "  Sign app with keychain cert: $APPSIGNINGCERT"
else
    echo "  Sign application: NO"
fi
if [ "$PKGSIGNINGCERT" != "" ] ; then
    echo "  Sign package with keychain cert: $PKGSIGNINGCERT"
else
    echo "  Sign package: NO"
fi
echo


# Build Managed Software Center.
echo "Building Managed Software Update.xcodeproj..."
pushd "$MUNKIROOT/code/apps/Managed Software Center" > /dev/null
/usr/bin/xcodebuild -project "Managed Software Center.xcodeproj" -alltargets clean > /dev/null
/usr/bin/xcodebuild -project "Managed Software Center.xcodeproj" -alltargets build > /dev/null
XCODEBUILD_RESULT="$?"
popd > /dev/null
if [ "$XCODEBUILD_RESULT" -ne 0 ]; then
    echo "Error building Managed Software Center.app: $XCODEBUILD_RESULT"
    exit 2
fi

MSCAPP="$MUNKIROOT/code/apps/Managed Software Center/build/Release/Managed Software Center.app"
if [ ! -e "$MSCAPP" ]; then
    echo "Need a release build of Managed Software Center.app!"
    echo "Open the Xcode project $MUNKIROOT/code/apps/Managed Software Center/Managed Software Center.xcodeproj and build it."
    exit 2
else
    MSCVERSION=$(defaults read "$MSCAPP/Contents/Info" CFBundleShortVersionString)
    echo "Managed Software Center.app version: $MSCVERSION"
fi

# Build MunkiStatus
echo "Building MunkiStatus.xcodeproj..."
pushd "$MUNKIROOT/code/apps/MunkiStatus" > /dev/null
/usr/bin/xcodebuild -project "MunkiStatus.xcodeproj" -alltargets clean > /dev/null
/usr/bin/xcodebuild -project "MunkiStatus.xcodeproj" -alltargets build > /dev/null
XCODEBUILD_RESULT="$?"
popd > /dev/null
if [ "$XCODEBUILD_RESULT" -ne 0 ]; then
    echo "Error building MunkiStatus.app: $XCODEBUILD_RESULT"
    exit 2
fi

MSAPP="$MUNKIROOT/code/apps/MunkiStatus/build/Release/MunkiStatus.app"
if [ ! -e  "$MSAPP" ]; then
    echo "Need a release build of MunkiStatus.app!"
    echo "Open the Xcode project $MUNKIROOT/code/apps/MunkiStatus/MunkiStatus.xcodeproj and build it."
    exit 2
else
    MSVERSION=$(defaults read "$MSAPP/Contents/Info" CFBundleShortVersionString)
    echo "MunkiStatus.app version: $MSVERSION"
fi

# Build munki-notifier
echo "Building munki-notifier.xcodeproj..."
pushd "$MUNKIROOT/code/apps/munki-notifier" > /dev/null
/usr/bin/xcodebuild -project "munki-notifier.xcodeproj" -alltargets clean > /dev/null
/usr/bin/xcodebuild -project "munki-notifier.xcodeproj" -alltargets build > /dev/null
XCODEBUILD_RESULT="$?"
popd > /dev/null
if [ "$XCODEBUILD_RESULT" -ne 0 ]; then
    echo "Error building munki-notifier.app: $XCODEBUILD_RESULT"
    exit 2
fi

NOTIFIERAPP="$MUNKIROOT/code/apps/munki-notifier/build/Release/munki-notifier.app"
if [ ! -e  "$NOTIFIERAPP" ]; then
    echo "Need a release build of munki-notifier.app!"
    echo "Open the Xcode project $MUNKIROOT/code/apps/notifier/munki-notifier.xcodeproj and build it."
    exit 2
else
    NOTIFIERVERSION=$(defaults read "$NOTIFIERAPP/Contents/Info" CFBundleShortVersionString)
    echo "munki-notifier.app version: $NOTIFIERVERSION"
fi

# Create a PackageInfo file.
makeinfo() {
    pkg="$1"
    out="$2_$pkg"
    if [ "$3" == "restart" ]; then
        restart='postinstall-action="restart"'
    else
        restart=""
    fi
    cat > "$out" <<EOF
<pkg-info format-version="2" install-location="/" auth="root" $restart>
</pkg-info>
EOF
}


# Pre-build cleanup.

if ! rm -rf "$MPKG" ; then
    echo "Error removing $MPKG before rebuilding it."
    exit 2
fi


# Create temporary directory
PKGTMP=$(mktemp -d -t munkipkg)


#########################################
## core munki tools                    ##
## /usr/local/munki, minus admin tools ##
## plus /Library/Managed Installs      ##
#########################################
echo
echo "Creating core package template..."

# Create directory structure.
COREROOT="$PKGTMP/munki_core"
mkdir -m 1775 "$COREROOT"
mkdir -p "$COREROOT/usr/local/munki/munkilib"
chmod -R 755 "$COREROOT/usr"
# Copy command line utilities.
# edit this if list of tools changes!
for TOOL in authrestartd launchapp logouthelper managedsoftwareupdate supervisor precache_agent ptyexec removepackages
do
    cp -X "$MUNKIROOT/code/client/$TOOL" "$COREROOT/usr/local/munki/" 2>&1
done
# Copy python libraries.
#cp -X "$MUNKIROOT/code/client/munkilib/"*.py "$COREROOT/usr/local/munki/munkilib/"
rsync -a --exclude '*.pyc' --exclude '.DS_Store' "$MUNKIROOT/code/client/munkilib/" "$COREROOT/usr/local/munki/munkilib/"
# Copy munki version.
cp -X "$MUNKIROOT/code/client/munkilib/version.plist" "$COREROOT/usr/local/munki/munkilib/"
# svnversion file was used when we were using subversion
# we don't need this file if we have an updated get_version method in munkicommon.py
if [ "$SVNREV" -lt "1302" ]; then
    echo $SVNREV > "$COREROOT/usr/local/munki/munkilib/svnversion"
fi

# add Build Number and Git Revision to version.plist
/usr/libexec/PlistBuddy -c "Delete :BuildNumber" "$COREROOT/usr/local/munki/munkilib/version.plist" 2>/dev/null
/usr/libexec/PlistBuddy -c "Add :BuildNumber string $SVNREV" "$COREROOT/usr/local/munki/munkilib/version.plist"
/usr/libexec/PlistBuddy -c "Delete :GitRevision" "$COREROOT/usr/local/munki/munkilib/version.plist" 2>/dev/null
/usr/libexec/PlistBuddy -c "Add :GitRevision string $GITREV" "$COREROOT/usr/local/munki/munkilib/version.plist"
# Set permissions.
chmod -R go-w "$COREROOT/usr/local/munki"
chmod +x "$COREROOT/usr/local/munki"

# make paths.d file
mkdir -p "$COREROOT/private/etc/paths.d"
echo "/usr/local/munki" > "$COREROOT/private/etc/paths.d/munki"
chmod -R 755 "$COREROOT/private"
chmod 644 "$COREROOT/private/etc/paths.d/munki"

# Create directory structure for /Library/Managed Installs.
mkdir -m 1775 "$COREROOT/Library"
mkdir -m 755 -p "$COREROOT/Library/Managed Installs"
mkdir -m 750 -p "$COREROOT/Library/Managed Installs/Cache"
mkdir -m 750 -p "$COREROOT/Library/Managed Installs/catalogs"
mkdir -m 755 -p "$COREROOT/Library/Managed Installs/manifests"

# Create package info file.
makeinfo core "$PKGTMP/info" norestart


#########################################
## admin munki tools                   ##
## /usr/local/munki admin tools        ##
#########################################

echo "Creating admin package source..."

# Create directory structure.
ADMINROOT="$PKGTMP/munki_admin"
mkdir -m 1775 "$ADMINROOT"
mkdir -p "$ADMINROOT/usr/local/munki"
chmod -R 755 "$ADMINROOT/usr"
# Copy command line admin utilities.
# edit this if list of tools changes!
for TOOL in makecatalogs makepkginfo manifestutil munkiimport iconimporter repoclean
do
	cp -X "$MUNKIROOT/code/client/$TOOL" "$ADMINROOT/usr/local/munki/" 2>&1
done
# Set permissions.
chmod -R go-w "$ADMINROOT/usr/local/munki"
chmod +x "$ADMINROOT/usr/local/munki"

# make paths.d file
mkdir -p "$ADMINROOT/private/etc/paths.d"
echo "/usr/local/munki" > "$ADMINROOT/private/etc/paths.d/munki"
chmod -R 755 "$ADMINROOT/private"
chmod 644 "$ADMINROOT/private/etc/paths.d/munki"

# Create package info file.
makeinfo admin "$PKGTMP/info" norestart


###################
## /Applications ##
###################

echo "Creating applications package source..."

# Create directory structure.
APPROOT="$PKGTMP/munki_app"
mkdir -m 1775 "$APPROOT"
mkdir -m 775 "$APPROOT/Applications"
# Copy Managed Software Center application.
cp -R "$MSCAPP" "$APPROOT/Applications/"
# Copy MunkiStatus helper app
cp -R "$MSAPP" "$APPROOT/Applications/Managed Software Center.app/Contents/Resources/"
# Copy notifier helper app
cp -R "$NOTIFIERAPP" "$APPROOT/Applications/Managed Software Center.app/Contents/Resources/"
# make sure not writeable by group or other
chmod -R go-w "$APPROOT/Applications/Managed Software Center.app"

# sign MSC app
if [ "$APPSIGNINGCERT" != "" ]; then
    echo "Signing Managed Software Center.app..."
    /usr/bin/codesign -s "$APPSIGNINGCERT" --options runtime --verbose \
        "$APPROOT/Applications/Managed Software Center.app/Contents/PlugIns/MSCDockTilePlugin.docktileplugin" \
        "$APPROOT/Applications/Managed Software Center.app/Contents/Resources/MunkiStatus.app" \
        "$APPROOT/Applications/Managed Software Center.app/Contents/Resources/munki-notifier.app" \
        "$APPROOT/Applications/Managed Software Center.app"
    SIGNING_RESULT="$?"
    if [ "$SIGNING_RESULT" -ne 0 ]; then
        echo "Error signing Managed Software Center.app: $SIGNING_RESULT"
        exit 2
    fi
fi

# Create package info file.
makeinfo app "$PKGTMP/info" norestart


##############
## launchd ##
##############

echo "Creating launchd package source..."

# Create directory structure.
LAUNCHDROOT="$PKGTMP/munki_launchd"
mkdir -m 1775 "$LAUNCHDROOT"
mkdir -m 1775 "$LAUNCHDROOT/Library"
mkdir -m 755 "$LAUNCHDROOT/Library/LaunchAgents"
mkdir -m 755 "$LAUNCHDROOT/Library/LaunchDaemons"
# Copy launch daemons and launch agents.
cp -X "$MUNKIROOT/launchd/LaunchAgents/"*.plist "$LAUNCHDROOT/Library/LaunchAgents/"
chmod 644 "$LAUNCHDROOT/Library/LaunchAgents/"*
cp -X "$MUNKIROOT/launchd/LaunchDaemons/"*.plist "$LAUNCHDROOT/Library/LaunchDaemons/"
chmod 644 "$LAUNCHDROOT/Library/LaunchDaemons/"*
# Create package info file.
RESTARTFLAG=restart
if [ "$MDMSTYLE" == "YES" ] ; then
    RESTARTFLAG=norestart
fi
makeinfo launchd "$PKGTMP/info" "$RESTARTFLAG"


#######################
## app_usage_monitor ##
#######################

echo "Creating app_usage package source..."

# Create directory structure.
APPUSAGEROOT="$PKGTMP/munki_app_usage"
mkdir -m 1775 "$APPUSAGEROOT"
mkdir -m 1775 "$APPUSAGEROOT/Library"
mkdir -m 755 "$APPUSAGEROOT/Library/LaunchAgents"
mkdir -m 755 "$APPUSAGEROOT/Library/LaunchDaemons"
mkdir -p "$APPUSAGEROOT/usr/local/munki"
chmod -R 755 "$APPUSAGEROOT/usr"
# Copy launch agent, launch daemon, daemon, and agent
# LaunchAgent
cp -X "$MUNKIROOT/launchd/app_usage_LaunchAgent/"*.plist "$APPUSAGEROOT/Library/LaunchAgents/"
chmod 644 "$APPUSAGEROOT/Library/LaunchAgents/"*
# LaunchDaemon
cp -X "$MUNKIROOT/launchd/app_usage_LaunchDaemon/"*.plist "$APPUSAGEROOT/Library/LaunchDaemons/"
chmod 644 "$APPUSAGEROOT/Library/LaunchDaemons/"*
# Copy tools.
# edit this if list of tools changes!
for TOOL in appusaged app_usage_monitor
do
	cp -X "$MUNKIROOT/code/client/$TOOL" "$APPUSAGEROOT/usr/local/munki/" 2>&1
done
# Set permissions.
chmod -R go-w "$APPUSAGEROOT/usr/local/munki"
chmod +x "$APPUSAGEROOT/usr/local/munki"
# Create package info file.
makeinfo app_usage "$PKGTMP/info" norestart


############
## python ##
############

echo "Creating python package source..."

# Create directory structure.
PYTHONROOT="$PKGTMP/munki_python"
mkdir -m 1775 "$PYTHONROOT"
mkdir -p "$PYTHONROOT/usr/local/munki"
chmod -R 755 "$PYTHONROOT/usr"
# Copy framework
cp -R "$MUNKIROOT/Python.framework" "$PYTHONROOT/usr/local/munki/"
# Create symlink
ln -s Python.framework/Versions/Current/bin/python3 "$PYTHONROOT/usr/local/munki/munki-python"
# Set permissions.
chmod -R go-w "$PYTHONROOT/usr/local/munki"
chmod +x "$PYTHONROOT/usr/local/munki"
# Create package info file.
makeinfo python "$PKGTMP/info" norestart

#######################
## no python choice  ##
#######################

echo "Creating no-python package source..."

# Create directory structure.
NOPYTHONROOT="$PKGTMP/munki_no_python"
mkdir -m 1775 "$NOPYTHONROOT"
mkdir -p "$NOPYTHONROOT/usr/local/munki"
chmod -R 755 "$NOPYTHONROOT/usr"
# Create symlink
ln -s /usr/bin/python "$NOPYTHONROOT/usr/local/munki/munki-python"
# Set permissions.
chmod -R go-w "$NOPYTHONROOT/usr/local/munki"
chmod +x "$NOPYTHONROOT/usr/local/munki"
# Create package info file.
makeinfo no_python "$PKGTMP/info" norestart


###############
## bootstrap ##
###############
if [ "$BOOTSTRAPPKG" == "YES" ] ;  then

    echo "Creating bootstrap package source..."

    # Create directory structure.
    BOOTSTRAPROOT="$PKGTMP/munki_bootstrap"
    mkdir -m 1775 "$BOOTSTRAPROOT"
    mkdir -p "$BOOTSTRAPROOT/Users/Shared"
    # Create bootstrap flag file
    touch "$BOOTSTRAPROOT/Users/Shared/.com.googlecode.munki.checkandinstallatstartup"
    # Create package info file.
    makeinfo bootstrap "$PKGTMP/info" norestart
fi


############
## config ##
############
if [ "$CONFPKG" == "YES" ] ; then

    echo "Creating configuration package souce..."

    # Create directory structure.
    CONFROOT="$PKGTMP/munki_config"
    mkdir -m 1775 "$CONFROOT"
    mkdir -p "$CONFROOT/Library/Preferences"
    # Copy prefs file
    cp "$CONFFULLPATH" "$CONFROOT/Library/Preferences/ManagedInstalls.plist"
    # Create package info file.
    makeinfo config "$PKGTMP/info" norestart
fi

#############################
## Create metapackage root ##
#############################

echo "Creating metapackage source..."

# Create root for productbuild.
METAROOT="$PKGTMP/munki_mpkg"
mkdir -p "$METAROOT/Resources"
# Configure Distribution
DISTFILE="$METAROOT/Distribution"
PKGPREFIX="#"
# Package destination directory.
PKGDEST="$METAROOT"

# Create Distribution file.
CORETITLE="Munki core tools"
COREDESC="Core command-line tools used by Munki."
ADMINTITLE="Munki admin tools"
ADMINDESC="Command-line munki admin tools."
APPTITLE="Managed Software Center"
APPDESC="Managed Software Center application."
LAUNCHDTITLE="Munki launchd files"
LAUNCHDDESC="Core Munki launch daemons and launch agents."
APPUSAGETITLE="Munki app usage monitoring tool"
APPUSAGEDESC="Munki app usage monitoring tool and launchdaemon. Optional install; if installed Munki can use data collected by this tool to automatically remove unused software."
PYTHONTITLE="Munki embedded Python"
PYTHONDESC="Embedded Python 3 framework for Munki."
NOPYTHONTITLE="System Python link"
NOPYTHONDESC="Creates symlink to system Python at /usr/local/munki/munki-python. Available for install if you choose not to install Munki's embedded Python."
BOOTSTRAPTITLE="Munki bootstrap setup"
BOOTSTRAPDESC="Enables bootstrap mode for the Munki tools."
CONFTITLE="Munki tools configuration"
CONFDESC="Sets initial preferences for Munki tools."

LAUNCHDPOSTINSTALLACTION="onConclusion=\"RequireRestart\""
if [ "$MDMSTYLE" == "YES" ] ;  then
    LAUNCHDPOSTINSTALLACTION=""
fi

BOOTSTRAPOUTLINE=""
BOOTSTRAPCHOICE=""
BOOTSTRAPREF=""
if [ "$BOOTSTRAPPKG" == "YES" ] ; then
    BOOTSTRAPOUTLINE="<line choice=\"bootstrap\"/>"
    BOOTSTRAPCHOICE="<choice id=\"bootstrap\" title=\"$BOOTSTRAPTITLE\" description=\"$BOOTSTRAPDESC\">
        <pkg-ref id=\"$PKGID.bootstrap\"/>
    </choice>"
    BOOTSTRAPREF="<pkg-ref id=\"$PKGID.bootstrap\" auth=\"Root\">${PKGPREFIX}munkitools_bootstrap.pkg</pkg-ref>"
fi

CONFOUTLINE=""
CONFCHOICE=""
CONFREF=""
if [ "$CONFPKG" == "YES" ]; then
    CONFOUTLINE="<line choice=\"config\"/>"
    CONFCHOICE="<choice id=\"config\" title=\"$CONFTITLE\" description=\"$CONFDESC\">
        <pkg-ref id=\"$PKGID.config\"/>
    </choice>"
    CONFREF="<pkg-ref id=\"$PKGID.config\" auth=\"Root\">${PKGPREFIX}munkitools_config.pkg</pkg-ref>"
fi

cat > "$DISTFILE" <<EOF
<?xml version="1.0" encoding="utf-8"?>
<installer-script minSpecVersion="1.000000">
    <title>Munki - Software Management for $ORGNAME</title>
    <volume-check>
        <allowed-os-versions>
            <os-version min="10.10"/>
        </allowed-os-versions>
    </volume-check>
    <options customize="allow" allow-external-scripts="no"/>
    <domains enable_anywhere="true"/>
    <choices-outline>
        <line choice="core"/>
        <line choice="admin"/>
        <line choice="app"/>
        <line choice="launchd"/>
        <line choice="app_usage"/>
        <line choice="python"/>
        <line choice="no_python"/>
        $BOOTSTRAPOUTLINE
        $CONFOUTLINE
    </choices-outline>
    <choice id="core" title="$CORETITLE" description="$COREDESC">
        <pkg-ref id="$PKGID.core"/>
    </choice>
    <choice id="admin" title="$ADMINTITLE" description="$ADMINDESC">
        <pkg-ref id="$PKGID.admin"/>
    </choice>
    <choice id="app" title="$APPTITLE" description="$APPDESC">
        <pkg-ref id="$PKGID.app"/>
    </choice>
    <choice id="launchd" title="$LAUNCHDTITLE" description="$LAUNCHDDESC" start_selected='my.choice.packageUpgradeAction != "installed"'>
        <pkg-ref id="$PKGID.launchd"/>
    </choice>
    <choice id="app_usage" title="$APPUSAGETITLE" description="$APPUSAGEDESC">
        <pkg-ref id="$PKGID.app_usage"/>
    </choice>
    <choice id="python" title="$PYTHONTITLE" description="$PYTHONDESC">
        <pkg-ref id="$PKGID.python"/>
    </choice>
    <choice id="no_python" title="$NOPYTHONTITLE" description="$NOPYTHONDESC" selected='choices["python"].selected == false' enabled='choices["python"].selected == false'>
        <pkg-ref id="$PKGID.no_python"/>
    </choice>
    $BOOTSTRAPCHOICE
    $CONFCHOICE
    <pkg-ref id="$PKGID.core" auth="Root">${PKGPREFIX}munkitools_core.pkg</pkg-ref>
    <pkg-ref id="$PKGID.admin" auth="Root">${PKGPREFIX}munkitools_admin.pkg</pkg-ref>
    <pkg-ref id="$PKGID.app" auth="Root">${PKGPREFIX}munkitools_app.pkg</pkg-ref>
    <pkg-ref id="$PKGID.launchd" auth="Root" $LAUNCHDPOSTINSTALLACTION>${PKGPREFIX}munkitools_launchd.pkg</pkg-ref>
    <pkg-ref id="$PKGID.app_usage" auth="Root">${PKGPREFIX}munkitools_app_usage.pkg</pkg-ref>
    <pkg-ref id="$PKGID.python" auth="Root">${PKGPREFIX}munkitools_python.pkg</pkg-ref>
    <pkg-ref id="$PKGID.no_python" auth="Root">${PKGPREFIX}munkitools_no_python.pkg</pkg-ref>
    $BOOTSTRAPREF
    $CONFREF
    <product id="$PKGID" version="$VERSION" />
</installer-script>
EOF

###################
## Set ownership ##
###################

echo "Setting ownership to root..."

sudo chown root:admin "$COREROOT" "$ADMINROOT" "$APPROOT" "$LAUNCHDROOT"
sudo chown -hR root:wheel "$COREROOT/usr"
sudo chown -hR root:admin "$COREROOT/Library"
sudo chown -hR root:wheel "$COREROOT/private"

sudo chown -hR root:wheel "$ADMINROOT/usr"
sudo chown -hR root:wheel "$ADMINROOT/private"

sudo chown -hR root:admin "$APPROOT/Applications"

sudo chown root:admin "$LAUNCHDROOT/Library"
sudo chown -hR root:wheel "$LAUNCHDROOT/Library/LaunchDaemons"
sudo chown -hR root:wheel "$LAUNCHDROOT/Library/LaunchAgents"

sudo chown root:admin "$APPUSAGEROOT/Library"
sudo chown -hR root:wheel "$APPUSAGEROOT/Library/LaunchDaemons"
sudo chown -hR root:wheel "$APPUSAGEROOT/Library/LaunchAgents"
sudo chown -hR root:wheel "$APPUSAGEROOT/usr"

sudo chown -hR root:wheel "$PYTHONROOT/usr"
sudo chown -hR root:wheel "$NOPYTHONROOT/usr"

if [ "$BOOTSTRAPPKG" == "YES" ] ; then
    sudo chown -hR root:admin "$BOOTSTRAPROOT"
fi

if [ "$CONFPKG" == "YES" ] ; then
    sudo chown -hR root:admin "$CONFROOT"
fi

ALLPKGS="core admin app launchd app_usage python no_python"
if [ "$BOOTSTRAPPKG" == "YES" ] ; then
    ALLPKGS="${ALLPKGS} bootstrap"
fi
if [ "$CONFPKG" == "YES" ] ; then
    ALLPKGS="${ALLPKGS} config"
fi

######################
## Run pkgbuild ##
######################
CURRENTUSER=$(whoami)
for pkg in $ALLPKGS ; do
    case $pkg in
        "app")
            ver="$APPSVERSION"
            SCRIPTS="${MUNKIROOT}/code/tools/pkgresources/Scripts_app"
            ;;
        "launchd")
            ver="$LAUNCHDVERSION"
            SCRIPTS=""
            if [ "$MDMSTYLE" == "YES" ] ; then
                SCRIPTS="${MUNKIROOT}/code/tools/pkgresources/Scripts_launchd"
            fi
            ;;
        "app_usage")
            ver="$VERSION"
            SCRIPTS="${MUNKIROOT}/code/tools/pkgresources/Scripts_app_usage"
            ;;
        "python")
            ver="$PYTHONVERSION"
            SCRIPTS="${MUNKIROOT}/code/tools/pkgresources/Scripts_python"
            ;;
        "bootstrap")
            ver="1.0"
            ;;
        "config")
            ver="1.0"
            ;;
        *)
            ver="$VERSION"
            SCRIPTS=""
            ;;
    esac
    echo
    echo "Packaging munkitools_$pkg.pkg"
    
    # use sudo here so pkgutil doesn't complain when it tries to
    # descend into root/Library/Managed Installs/*

    # Use pkgutil --analyze to build a component property list
    # then turn off bundle relocation
    sudo /usr/bin/pkgbuild \
        --analyze \
        --root "$PKGTMP/munki_$pkg" \
        "${PKGTMP}/munki_${pkg}_component.plist"
    if [ "$pkg" == "app" ]; then
        # change BundleIsRelocatable from true to false
        sudo /usr/libexec/PlistBuddy \
            -c 'Set :0:BundleIsRelocatable false' \
            "${PKGTMP}/munki_${pkg}_component.plist"
    fi

    if [ "$SCRIPTS" != "" ]; then
        sudo /usr/bin/pkgbuild \
            --root "$PKGTMP/munki_$pkg" \
            --identifier "$PKGID.$pkg" \
            --version "$ver" \
            --ownership preserve \
            --info "$PKGTMP/info_$pkg" \
            --component-plist "${PKGTMP}/munki_${pkg}_component.plist" \
            --scripts "$SCRIPTS" \
            "$PKGDEST/munkitools_$pkg.pkg"
    else
        sudo /usr/bin/pkgbuild \
            --root "$PKGTMP/munki_$pkg" \
            --identifier "$PKGID.$pkg" \
            --version "$ver" \
            --ownership preserve \
            --info "$PKGTMP/info_$pkg" \
            --component-plist "${PKGTMP}/munki_${pkg}_component.plist" \
            "$PKGDEST/munkitools_$pkg.pkg"
    fi

    if [ "$?" -ne 0 ]; then
        echo "Error building munkitools_$pkg.pkg."
        echo "Attempting to clean up temporary files..."
        sudo rm -rf "$PKGTMP"
        exit 2
    else
        # set ownership of package back to current user
        sudo chown -R "$CURRENTUSER" "$PKGDEST/munkitools_$pkg.pkg"
    fi
done

echo
# build distribution pkg from the components
# Sign package if specified with options.
if [ "$PKGSIGNINGCERT" != "" ]; then
     /usr/bin/productbuild \
        --distribution "$DISTFILE" \
        --package-path "$METAROOT" \
        --resources "$METAROOT/Resources" \
        --sign "$PKGSIGNINGCERT" \
        "$MPKG"
else
    /usr/bin/productbuild \
        --distribution "$DISTFILE" \
        --package-path "$METAROOT" \
        --resources "$METAROOT/Resources" \
        "$MPKG"
fi

if [ "$?" -ne 0 ]; then
    echo "Error creating $MPKG."
    echo "Attempting to clean up temporary files..."
    sudo rm -rf "$PKGTMP"
    exit 2
fi

echo "Distribution package created at $MPKG."
echo
echo "Removing temporary files..."
sudo rm -rf "$PKGTMP"

echo "Done."
