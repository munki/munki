#!/bin/bash
#
# Check out Munki from git and build an mpkg distribution package.


# Defaults.
PKGTYPE="bundle"
PKGID="com.googlecode.munki"
OUTPUTDIR=`pwd`
CONFPKG=""
CHECKOUTREV="HEAD"
BRANCH="master"


usage() {
    cat <<EOF
Usage: `basename $0` [-i id] [-o dir] [-c package] [-r revision]"

    -i id       Set the base package bundle ID
    -o dir      Set the output directory
    -c package  Include a configuration package (NOT CURRENTLY IMPLEMENTED)
    -b branch   Git branch to clone (master is the default)
    -r revision Git revision to check out (HEAD is the default)

EOF
}


while getopts "i:r:o:b:c:h" option
do
    case $option in
        "i")
            PKGID="$OPTARG"
            ;;
        "o")
            OUTPUTDIR="$OPTARG"
            ;;
        "b")
            BRANCH="$OPTARG"
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

MUNKIDIR=`pwd`/"munki-git"

# Sanity checks.
GIT=`which git`
WHICH_GIT_RESULT="$?"
if [ "$WHICH_GIT_RESULT" != "0" ]; then
    echo "Could not find git in command path. Maybe it's not installed?" 1>&2
    echo "You can get a Git package here:" 1>&2
    echo "    https://git-scm.com/download/mac"
    exit 1
fi
if [ ! -x "/usr/bin/pkgbuild" ]; then
    echo "pkgbuild is not installed!"
    exit 1
fi
if [ ! -x "/usr/bin/productbuild" ]; then
    echo "productbuild is not installed!"
    exit 1
fi
if [ ! -x "/usr/bin/xcodebuild" ]; then
    echo "xcodebuild is not installed!"
    exit 1
fi

echo "Cloning munki repo branch $BRANCH from github..."
git clone --branch "$BRANCH" --no-checkout -- https://github.com/munki/munki.git "$MUNKIDIR"
CLONE_RESULT="$?"
if [ "$CLONE_RESULT" != "0" ]; then
    echo "Error cloning munki repo: $CLONE_RESULT" 1>&2
    exit 1
fi

echo "Checking out revision $CHECKOUTREV..."
cd "$MUNKIDIR"
git checkout "$CHECKOUTREV"
CHECKOUT_RESULT="$?"
if [ "$CHECKOUT_RESULT" != "0" ]; then
    echo "Error checking out $CHECKOUTREV: $CHECKOUT_RESULT" 1>&2
    exit 1
fi

if [ ! -z "$CONFPKG" ]; then
    CONFPKGARG="-c $CONFPKG"
else
    CONFPKGARG=""
fi

# now use the version of the make_munki_mpkg.sh script in the Git repo.
"$MUNKIDIR/code/tools/make_munki_mpkg.sh" -i "$PKGID" -r "$MUNKIDIR" -o "$OUTPUTDIR" $CONFPKGARG

exit $?
