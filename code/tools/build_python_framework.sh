#!/bin/bash
#
# Build script for universal Python 3 framework for Munki

TOOLSDIR=$(dirname "$0")
REQUIREMENTS="${TOOLSDIR}/py3_requirements.txt"
PYTHON_FRAMEWORK_VERSION=3.10
PYTHON_VERSION=3.10.11
PYTHON_PRERELEASE_VERSION=
PYTHON_BASEURL="https://www.python.org/ftp/python/%s/python-%s${PYTHON_PRERELEASE_VERSION}-macos%s.pkg"
MACOS_VERSION=11
CODEDIR=$(dirname "${TOOLSDIR}")
MUNKIROOT=$(dirname "${CODEDIR}")

# Sanity checks.
GIT=$(which git)
WHICH_GIT_RESULT="$?"
if [ "${WHICH_GIT_RESULT}" != "0" ]; then
    echo "Could not find git in command path. Maybe it's not installed?" 1>&2
    echo "You can get a Git package here:" 1>&2
    echo "    https://git-scm.com/download/mac"
    exit 1
fi
if [ ! -d "${MUNKIROOT}/code" ]; then
    echo "Does not look like you are running this script from a Munki git repo." 1>&2
    exit 1
fi
if [ ! -f "${REQUIREMENTS}" ]; then
    echo "Missing requirements file at ${REQUIREMENTS}." 1>&2
    exit 1
fi

# clone our relocatable-python tool
PYTHONTOOLDIR="/tmp/relocatable-python-git"
if [ -d "${PYTHONTOOLDIR}" ]; then
    rm -rf "${PYTHONTOOLDIR}"
fi
echo "Cloning relocatable-python tool from github..."
git clone https://github.com/gregneagle/relocatable-python.git "${PYTHONTOOLDIR}"
CLONE_RESULT="$?"
if [ "${CLONE_RESULT}" != "0" ]; then
    echo "Error cloning relocatable-python tool repo: ${CLONE_RESULT}" 1>&2
    exit 1
fi

# remove existing Python.framework if present
if [ -d "${MUNKIROOT}/Python.framework" ]; then
    rm -rf "${MUNKIROOT}/Python.framework"
fi

# build the framework
"${PYTHONTOOLDIR}/make_relocatable_python_framework.py" \
    --baseurl "${PYTHON_BASEURL}" \
    --python-version "${PYTHON_VERSION}" \
    --os-version "${MACOS_VERSION}" \
    --upgrade-pip \
    --pip-requirements "${REQUIREMENTS}" \
    --destination "${MUNKIROOT}"

# verify we actually have a universal build
echo "Verifying Universal2 builds..."
STATUS=0

# ensure all .so and .dylibs are universal
LIB_COUNT=$(find "${MUNKIROOT}/Python.framework" -name "*.so" -or -name "*.dylib" | wc -l)
UNIVERSAL_COUNT=$(find "${MUNKIROOT}/Python.framework" -name "*.so" -or -name "*.dylib" | xargs file | grep "2 architectures" | wc -l)
if [ "$LIB_COUNT" != "$UNIVERSAL_COUNT" ] ; then 
    echo "$LIB_COUNT libraries (*.so and *.dylib) found in the framework; only $UNIVERSAL_COUNT are universal!"
    echo "The following libraries are not universal:"
    find "${MUNKIROOT}"/Python.framework -name "*.so" -or -name "*.dylib" | xargs file | grep -v "2 architectures" | grep -v "(for architecture"
    STATUS=1
fi

# test some more files in the framework
MORE_FILES="Python.framework/Versions/${PYTHON_FRAMEWORK_VERSION}/Resources/Python.app/Contents/MacOS/Python
Python.framework/Versions/Current/Python
Python.framework/Versions/Current/bin/python${PYTHON_FRAMEWORK_VERSION}"

for TESTFILE in $MORE_FILES ; do
    ARCH_TEST=$(file "${MUNKIROOT}/$TESTFILE" | grep "2 architectures")
    if [ "$ARCH_TEST" == "" ]  ; then
        echo "${MUNKIROOT}/$TESTFILE is not universal!"
        STATUS=1
    fi
done

exit $STATUS

