#!/usr/bin/env python

import os
import subprocess
import managedinstalls

managedinstalldir = managedinstalls.managed_install_dir()
installinfo = os.path.join(managedinstalldir, "InstallInfo.plist")
ihook = "/Applications/Utilities/radmind/iHook.app/Contents/MacOS/iHook"
script = "/Users/gneagle/Documents/managedinstalls/code/client/ManagedInstaller"
args = "-i"

if os.path.exists(installinfo):
    retcode = subprocess.call([ihook, "--script=" + script, args])
