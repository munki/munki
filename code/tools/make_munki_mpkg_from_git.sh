#!/bin/bash
#
# Check out Munki from svn and build an mpkg distribution package.


# Defaults.
PKGTYPE="bundle"
PKGID="com.googlecode.munki"
OUTPUTDIR=`pwd`
CONFPKG=""
CHECKOUTREV="HEAD"


usage() {
    cat <<EOF
Usage: `basename $0` [-f] [-i id] [-o dir] [-c package] [-r revision]"

    -f          Build a flat package (bundle is the default)
    -i id       Set the base package bundle ID
    -o dir      Set the output directory
    -c package  Include a configuration package
    -r revision SVN revision to check out (latest is the default)

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
        "o")
            OUTPUTDIR="$OPTARG"
            ;;
        "c")
            CONFPKG="$OPTARG"
            ;;
        "r")
            CHECKOUTREV="$OPTARG"
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


MUNKIDIR=`pwd`/"munki-SVN"

echo "Checking out munki from SVN..."
svn checkout -r "$CHECKOUTREV" http://munki.googlecode.com/svn/trunk/ "$MUNKIDIR"
CHECKOUT_RESULT="$?"
if [ "$CHECKOUT_RESULT" != "0" ]; then
    echo "Error checking out munki code from SVN: $CHECKOUT_RESULT"
    exit 1
fi

if [ ! -z "$CONFPKG" ]; then
    CONFPKGARG="-c $CONFPKG"
else
    CONFPKGARG=""
fi

"$MUNKIDIR/code/tools/make_munki_mpkg.sh" -i "$PKGID" -r "$MUNKIDIR" -o "$OUTPUTDIR" $CONFPKGARG

exit $?
