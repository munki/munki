#!/bin/sh
#
# Build script for munki tools package
# Builds an installer package for munki tools
# using the source checked out from code.google.com
#

# set PKGDIR to whereever you'd like the final package to be created
PKGDIR="/Users/Shared/pkgs"

if [ $(whoami) != "root" ]; then
    echo "You must run this as root or via sudo!"
    exit -1
fi

if [ ! -x "/usr/bin/xcodebuild" ]; then
    echo "Xcode is not installed!"
    exit -1
fi    

if [ ! -x "/Developer/usr/bin/packagemaker" ]; then
    echo "PackageMaker is not installed!"
    exit -1
fi

# temporary storage for items from SVN
TMPDIR="/tmp"
MUNKIDIR="munki-SVN"
MUNKIROOT="$TMPDIR/$MUNKIDIR"

cd "$TMPDIR"
if [ -d "$MUNKIROOT" ] ; then
    rm -r "$MUNKIROOT"
fi

svn checkout http://munki.googlecode.com/svn/trunk/ "$MUNKIDIR"
CHECKOUT_RESULT="$?"
if [ "$CHECKOUT_RESULT" != "0" ]; then
    echo "Error checking out munki code from SVN: $CHECKOUT_RESULT"
    exit -1
fi

# get SVN revision number
SVN_REV=`svn info http://munki.googlecode.com/svn/trunk/ | grep Revision: | cut -d " " -f2`
# get version number from munkicommon

cd "$MUNKIROOT/code/client/munkilib"
MUNKIVERS=`python -c "import munkicommon; print munkicommon.get_version()" | cut -d" " -f1`
VERS="$MUNKIVERS.$SVN_REV.0"

echo "Starting build for munki tools version $VERS"

cd "$MUNKIROOT/code/Managed Software Update"
/usr/bin/xcodebuild -project Managed\ Software\ Update.xcodeproj -alltargets
XCODEBUILD_RESULT="$?"
if [ "$XCODEBUILD_RESULT" != "0" ]; then
    echo "Error building Managed Software Update.app: $XCODEBUILD_RESULT"
    exit -1
fi

if [ ! -e "$MUNKIROOT/code/Managed Software Update/build/Release/Managed Software Update.app" ]; then
    echo "Build of Managed Software Update.app not found at $MUNKIROOT/code/Managed Software Update/build/Release/"
    exit -1
fi

if [ ! -d "$PKGDIR" ]; then
    mkdir -p "$PKGDIR"
fi

# prerun cleanup
rm -rf "$PKGDIR/munkitools-$VERS.pkg"
rm -rf /tmp/munkitools
mkdir /tmp/munkitools
chown root:wheel /tmp/munkitools
chmod 755 /tmp/munkitools
cd /tmp/munkitools

mkdir -p ./usr/local/munki/munkilib
chown -R root:wheel ./usr
chmod -R 755 ./usr
cp "$MUNKIROOT/code/client/"* ./usr/local/munki/
cp "$MUNKIROOT"/code/client/munkilib/*.py ./usr/local/munki/munkilib/
# no pre/postflight scripts in the package, please
rm -f ./usr/local/munki/preflight
rm -f ./usr/local/munki/postflight

mkdir -p ./Applications/Utilities
chown -R root:admin ./Applications
chmod -R 775 ./Applications
cp -R "$MUNKIROOT/code/Managed Software Update/build/Release/Managed Software Update.app" ./Applications/Utilities/
chmod -R o-w ./Applications/Utilities/Managed\ Software\ Update.app

mkdir -m 755 ./Library
mkdir -m 755 ./Library/LaunchAgents
chown root:wheel ./Library/LaunchAgents
cp "$MUNKIROOT/launchd/LaunchAgents/"*.plist ./Library/LaunchAgents/
chmod 644 ./Library/LaunchAgents/*

mkdir -m 755 ./Library/LaunchDaemons
chown root:wheel ./Library/LaunchDaemons
cp "$MUNKIROOT/launchd/LaunchDaemons/"*.plist ./Library/LaunchDaemons/
chmod 644 ./Library/LaunchDaemons/*

# create these directories in the package so we have a record
# and they can be removed later
mkdir -m 755 -p ./Library/Managed\ Installs
mkdir -m 750 -p ./Library/Managed\ Installs/Cache
mkdir -m 750 -p ./Library/Managed\ Installs/catalogs
mkdir -m 755 -p ./Library/Managed\ Installs/manifests
chown -R root:admin ./Library/Managed\ Installs

PKGID=com.googlecode.munki
/Developer/usr/bin/packagemaker --root . --id "$PKGID" --version "$VERS"  --no-recommend --out "$PKGDIR/munkitools-$VERS.pkg" --verbose

rm -f "$PKGDIR/munkitools-$VERS.pkg/Contents/Resources/TokenDefinitions.plist"
defaults delete "$PKGDIR/munkitools-$VERS.pkg/Contents/Info" IFPkgPathMappings
defaults write "$PKGDIR/munkitools-$VERS.pkg/Contents/Info" IFPkgFlagRestartAction "RequiredRestart"
plutil -convert xml1 "$PKGDIR/munkitools-$VERS.pkg/Contents/Info.plist"
chmod 664 "$PKGDIR/munkitools-$VERS.pkg/Contents/Info.plist"

LPROJPATH="$PKGDIR/munkitools-$VERS.pkg/Contents/Resources/en.lproj"
if [ ! -d "$LPROJPATH" ]; then
    # insert your own local language here if needed
    LPROJPATH="$PKGDIR/munkitools-$VERS.pkg/Contents/Resources/English.lproj"
fi

cat > "$LPROJPATH/Description.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>IFPkgDescriptionDescription</key>
	<string>Managed software installation tools.</string>
	<key>IFPkgDescriptionTitle</key>
	<string>munki tools</string>
</dict>
</plist>
EOF

# now clean up
rm -r "$MUNKIROOT"
rm -r /tmp/munkitools
 
