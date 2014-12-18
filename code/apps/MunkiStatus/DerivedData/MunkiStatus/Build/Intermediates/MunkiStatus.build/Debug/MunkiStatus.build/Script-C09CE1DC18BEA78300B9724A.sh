#!/bin/bash
# add this number to Git revision index to get "build" number consistent with old SVN repo
MAGICNUMBER=482

BASEVERNUM=`/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "${INFOPLIST_FILE}"`

# Git isn't installed on 10.6 or earlier by default, so find it
GIT=`which git`
if [ "$GIT" == "" ] ; then
    # let's hope it's in /usr/local/bin
    if [ -x "/usr/local/bin/git" ] ; then
        GIT=/usr/local/bin/git
    fi
fi

if [ "$GIT" != "" ] ; then
    # generate a psuedo-svn revision number from the list of Git revisions
    GITREV=`$GIT log -n1 --format="%H" -- ./`
  GITREVINDEX=`$GIT rev-list --count $GITREV`
    REV=$(($GITREVINDEX + $MAGICNUMBER))

    /usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $BASEVERNUM.$REV" "${TARGET_BUILD_DIR}/${INFOPLIST_PATH}"
    /usr/libexec/PlistBuddy -c "Set :CFBundleVersion $REV" "${TARGET_BUILD_DIR}/${INFOPLIST_PATH}"
    /usr/libexec/PlistBuddy -c "Set :GitRevision string $GITREV" "${TARGET_BUILD_DIR}/${INFOPLIST_PATH}"
fi
