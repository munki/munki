#!/bin/bash
#
# Check out Munki source from GitHub and build a distribution package.


# Defaults.
PKGID="com.googlecode.munki"
OUTPUTDIR="$(pwd)"
CHECKOUTREV="HEAD"
BRANCH="main"


usage() {
    cat <<EOF
Usage: $(basename "$0") [-b branch ] [-r revision] [<make_munki_mpkg.sh options>]"

    -b branch   Git branch to clone (main is the default)
    -r revision Git revision to check out (HEAD is the default)

    The remaining options are passed to make_munki_pkg.sh:
    -i id       Specify the base package bundle ID
    -o dir      Specify the output directory
    -n orgname  Specify the name of the organization
    -p          Build Python.framework even if one exists
    -B          Include a package that sets Munki's bootstrap mode
    -A          Auto run managedsoftwareupdate immediately after install. This
                really should be used only with DEP/ADM enrollments.
    -c plist    Build a configuration package using the preferences defined in a
                plist file
    -R          Include a pkg to install Rosetta2 on ARM-based hardware.
    -s cert_cn  Sign distribution package with a Developer ID Installer
                certificate from keychain. Provide the certificate's Common
                Name. Ex: "Developer ID Installer: Munki (U8PN57A5N2)"
    -S cert_cn  Sign apps with a Developer ID Application certificate from
                keychain. Provide the certificate's Common Name.
                Ex: "Developer ID Application: Munki (U8PN57A5N2)"
    -T pemfile  Include a pkg to install a client certificate for server mTLS
                mutual authentication, at /Library/Managed Installs/certs/.

EOF
}

ADDITIONALARGS=""
while getopts "b:r:i:o:n:c:s:S:T:pBAhR" option
do
    case $option in
        "b")
            BRANCH="$OPTARG"
            ;;
        "r")
            CHECKOUTREV="$OPTARG"
            ;;
        "i")
            ADDITIONALARGS="${ADDITIONALARGS} -i \"$OPTARG\""
            ;;
        "o")
            ADDITIONALARGS="${ADDITIONALARGS} -o \"$OPTARG\""
            ;;
        "n")
            ADDITIONALARGS="${ADDITIONALARGS} -n \"$OPTARG\""
            ;;
        "c")
            ADDITIONALARGS="${ADDITIONALARGS} -c \"$OPTARG\""
            ;;
        "s")
            ADDITIONALARGS="${ADDITIONALARGS} -s \"$OPTARG\""
            ;;
        "S")
            ADDITIONALARGS="${ADDITIONALARGS} -S \"$OPTARG\""
            ;;
        "p")
            ADDITIONALARGS="${ADDITIONALARGS} -p"
            ;;
        "B")
            ADDITIONALARGS="${ADDITIONALARGS} -B"
            ;;
        "A")
            ADDITIONALARGS="${ADDITIONALARGS} -A"
            ;;
        "R")
            ADDITIONALARGS="${ADDITIONALARGS} -R"
            ;;
        "T")
            ADDITIONALARGS="${ADDITIONALARGS} -T \"$OPTARG\""
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

MUNKIDIR="$(pwd)/munki-git"

# Sanity checks.
if ! which git 1>/dev/null ; then
    echo "Could not find git in command path. Maybe it's not installed?" 1>&2
    echo "You can get a Git package here:" 1>&2
    echo "    https://git-scm.com/download/mac"
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

# now use the version of the make_munki_mpkg.sh script in the Git repo.
CMD="\"$MUNKIDIR/code/tools/make_munki_mpkg.sh\" -r \"$MUNKIDIR\" -o \"$OUTPUTDIR\" $ADDITIONALARGS"
eval $CMD

exit $?
