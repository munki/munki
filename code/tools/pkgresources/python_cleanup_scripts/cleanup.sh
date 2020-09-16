#!/bin/sh

set -e

if [ -f "/usr/local/munki/python" ]; then
    /bin/rm /usr/local/munki/python
fi

if [ -d "/usr/local/munki/Python.framework/Versions/3.7" ]; then
    /bin/rm -r /usr/local/munki/Python.framework/Versions/3.7
fi
