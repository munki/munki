#!/bin/sh

set -e

# remove old python symlink if it exists
if [ -f "/usr/local/munki/python" ]; then
    /bin/rm /usr/local/munki/python
fi

# sometimes old versions are left behind in the framework. remove them.
for OLDVERS in 3.7 3.8 3.9 ; do
    if [ -d "/usr/local/munki/Python.framework/Versions/${OLDVERS}" ]; then
        /bin/rm -r "/usr/local/munki/Python.framework/Versions/${OLDVERS}"
    fi
done

