#!/usr/bin/python
"""
Postinstall script to load munki's launchdaemons.
"""


def getconsoleuser():
    '''Uses Apple's SystemConfiguration framework to get the current
    console user'''
    from SystemConfiguration import SCDynamicStoreCopyConsoleUser
    cfuser = SCDynamicStoreCopyConsoleUser(None, None, None)
    return cfuser[0]


def main():
    # This returns the conditions on whether or not a restart is required
    # for the launchd pkg.
    consoleuser = getconsoleuser()
    if consoleuser is None or consoleuser == u"loginwindow" or consoleuser == u"_mbsetupuser":
        exit(0)
    else:
        exit(1)

if __name__ == '__main__':
    main()
