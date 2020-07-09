#!/bin/bash
#
# Build script for getting the munki build version


# Defaults.
MUNKIROOT="."
# Convert to absolute path.
MUNKIROOT=$(cd "$MUNKIROOT"; pwd)
OUTPUTDIR="."
# add this number to Git revision index to get "build" number
# consistent with old SVN repo
MAGICNUMBER=482
BUILDPYTHON=NO


# Sanity checks.
GIT=$(which git)
WHICH_GIT_RESULT="$?"
if [ "$WHICH_GIT_RESULT" != "0" ]; then
    echo "Could not find git in command path. Maybe it's not installed?" 1>&2
    echo "You can get a Git package here:" 1>&2
    echo "    https://git-scm.com/download/mac"
    exit 1
fi


# Get the munki version
MUNKIVERS=$(defaults read "$MUNKIROOT/code/client/munkilib/version" CFBundleShortVersionString)
if [ "$?" != "0" ]; then
    echo "$MUNKIROOT/code/client/munkilib/version is missing!" 1>&2
    echo "Perhaps $MUNKIROOT does not contain the munki source?" 1>&2
    exit 1
fi

# generate a pseudo-svn revision number for the core tools (and admin tools)
# from the list of Git revisions
GITREV=$(git log -n1 --format="%H" -- code/client)
GITREVINDEX=$(git rev-list --count $GITREV)
SVNREV=$(($GITREVINDEX + $MAGICNUMBER))
MPKGSVNREV=$SVNREV
VERSION=$MUNKIVERS.$SVNREV

echo "$VERSION"
