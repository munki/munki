#!/bin/bash
#
# runtests.sh
#
# Invoke selected or all unit tests under the tests/ subdir structure.
# run with "-h" for help.
#
# Author: John Randolph (jrand@google.com)
#

TESTSDIR="tests"
PYTHON=""
TOPDIR=""
VERBOSE=""
declare -a TESTS

function die() {
    echo error: "$@" >&2
    exit 1
}

function printVerbose() {
    if [ ! -z "$VERBOSE" ]; then
        echo "$@" >&2
    fi
}

function printUsageExit() {
    cat <<EOM >&2

Usage: $0 [-v] [-h] [test targets ...]

    -v verbose
    -h this help

    test targets are supplied (relative paths to test binaries) they
    will be run,

    otherwise all *_test.py binaries will be run under the tests dir.

EOM
    exit 0
}

function detectPython() {
    case `sw_vers -productVersion 2>/dev/null` in
        10.11*) PYTHON="python2.7" ;;
        10.10*) PYTHON="python2.7" ;;
        10.9*) PYTHON="python2.7" ;;
        10.8*) PYTHON="python2.7" ;;
        10.7*) PYTHON="python2.7" ;;
        10.6*) PYTHON="python2.6" ;;
        10.5*) PYTHON="python2.5" ;;
        10.4*) PYTHON="python2.4" ;;
        *) die "Could not detect OS X version."
    esac
}

function detectTopDir() {
    scriptname=`basename "$0"`
    if [ ! -x "./${scriptname}" ]; then
        die "Run $0 from the top of the munki distribution."
    fi
    TOPDIR=`pwd`
}

function detectTestsDir() {
    if [ ! -d "${TOPDIR}/${TESTSDIR}" ]; then
        die "No tests to run."
    fi
}

function parseArgs() {
    while getopts "vh" opt "$@" ; do
        case "$opt" in
            v) VERBOSE="1" ;;
            h) printUsageExit ;;
            *) printUsageExit ;;
        esac
         shift
    done

    if [[ $# -gt 0 ]]; then
        TESTS=("$@")
    fi
}

# main

parseArgs "$@"
detectPython
detectTopDir
detectTestsDir

cd "${TESTSDIR}"

# output a list of tests to run in format DIR\tFILENAME\n
# whether they are received from arguments or found with find.
(
    # find specific tests
    if [[ "$TESTS" ]]; then
        n=0
        while [[ $n -lt ${#TESTS[@]} ]]; do
            file="${TESTS[$n]}" 
            if [[ ! -f "${file}" ]]; then
              die "Test ${file} does not exist."
            fi
            dir=`dirname "${file}"`
            echo -e "${dir}\t${file}"
            n=$[$n+1]
        done
    # find all tests
    else
        find . -type f -name '*_test.py' -print0 | \
        xargs -0 -n 1 dirname | uniq | \
        while read dir ; do
            printVerbose ====== Directory "$dir"
            for file in ${dir}/*_test.py; do
                echo -e "${dir}\t${file}"
            done
        done
    fi
) | \
# process the list to run each test
(

final_status=0

while read dir file ; do
    printVerbose === File "${file}"
    env PYTHONPATH="${TOPDIR}/${dir}" ${PYTHON} "${file}"
    rc="$?"
    if [[ "${rc}" != "0" ]]; then
        printVerbose === Exit status "${rc}"
        final_status=1
    fi
done ;

exit "${final_status}"

)

exit $?
