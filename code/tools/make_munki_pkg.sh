#!/bin/sh
#
# Build script for munki tools package
# Builds an installer package for munki tools
#


PKGID=com.googlecode.munki
VERS=0.6.0.640.0

# set munkiroot to the root dir of your munki 'source'
munkiroot="/Users/Shared/munki/munki"
# set packagedir to whereever you'd like the final package to be created
packagedir="/Users/Shared/pkgs"

if [ ! -e "$munkiroot/code/Managed Software Update/build/Release/Managed Software Update.app" ]; then
    echo "Need a release build of Managed Software Update.app!"
    echo "Open the Xcode project $munkiroot/code/Managed Software Update/Managed Software Update.xcodeproj and build it."
    exit -1
fi

if [ ! -d "$packagedir" ]; then
    mkdir -p "$packagedir"
fi

# prerun cleanup
rm -rf "$packagedir/munkitools-$VERS.pkg"
rm -rf /tmp/munkitools
mkdir /tmp/munkitools
chown root:wheel /tmp/munkitools
chmod 755 /tmp/munkitools
cd /tmp/munkitools

mkdir -p ./usr/local/munki/munkilib
chown -R root:wheel ./usr
chmod -R 755 ./usr
cp "$munkiroot/code/client/"* ./usr/local/munki/
cp "$munkiroot"/code/client/munkilib/*.py ./usr/local/munki/munkilib/
# no pre/postflight scripts in the package, please
rm -f ./usr/local/munki/preflight
rm -f ./usr/local/munki/postflight

mkdir -p ./Applications/Utilities
chown -R root:admin ./Applications
chmod -R 775 ./Applications
cp -R "$munkiroot/code/Managed Software Update/build/Release/Managed Software Update.app" ./Applications/Utilities/
chmod -R o-w ./Applications/Utilities/Managed\ Software\ Update.app

mkdir -m 755 ./Library
mkdir -m 755 ./Library/LaunchAgents
chown root:wheel ./Library/LaunchAgents
cp "$munkiroot/launchd/LaunchAgents/"*.plist ./Library/LaunchAgents/
chmod 644 ./Library/LaunchAgents/*

mkdir -m 755 ./Library/LaunchDaemons
chown root:wheel ./Library/LaunchDaemons
cp "$munkiroot/launchd/LaunchDaemons/"*.plist ./Library/LaunchDaemons/
chmod 644 ./Library/LaunchDaemons/*

# create these directories in the package so we have a record
# and they can be removed later
mkdir -m 755 -p ./Library/Managed\ Installs
mkdir -m 750 -p ./Library/Managed\ Installs/Cache
mkdir -m 750 -p ./Library/Managed\ Installs/catalogs
mkdir -m 755 -p ./Library/Managed\ Installs/manifests
chown -R root:admin ./Library/Managed\ Installs

/Developer/usr/bin/packagemaker --root . --id "$PKGID" --version "$VERS"  --no-recommend --out "$packagedir/munkitools-$VERS.pkg" --verbose --scripts "$munkiroot/code/other/munkipkgscripts"
rm -f "$packagedir/munkitools-$VERS.pkg/Contents/Resources/TokenDefinitions.plist"
defaults delete "$packagedir/munkitools-$VERS.pkg/Contents/Info" IFPkgPathMappings
defaults write "$packagedir/munkitools-$VERS.pkg/Contents/Info" IFPkgFlagRestartAction "RequiredRestart"
plutil -convert xml1 "$packagedir/munkitools-$VERS.pkg/Contents/Info.plist"
chmod 664 "$packagedir/munkitools-$VERS.pkg/Contents/Info.plist"
cat > "$packagedir/munkitools-$VERS.pkg/Contents/Resources/en.lproj/Description.plist" <<EOF
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
 
