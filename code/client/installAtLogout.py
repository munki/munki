#!/usr/bin/env python
"""
installomatic
Tool to automatically install pkgs, mpkgs, and dmgs
(containing pkgs and mpkgs) from a defined folder. Intended
to be run as part of a logout hook, but can be run manually
"""

import os
import subprocess
import sys
import time
import plistlib
import optparse
import managedinstalls


def log(message):
    global logdir
    logfile = os.path.join(logdir,'install.log')
    f = open(logfile, mode='a', buffering=1)
    if f:
        print >>f, time.ctime(), message
        f.close()


def countinstallcandidates(dirpath):
    """
    Counts the number of pkgs, mpkgs, and dmgs
    in dirpath
    """
    candidatecount = 0
    items = os.listdir(dirpath)
    for item in items:
        if (item.endswith(".pkg") or item.endswith(".mpkg") or item.endswith(".dmg")):
            candidatecount += 1
    return candidatecount


def install(pkgpath):
    """
    Uses the apple installer to install the package or metapackage
    at pkgpath. Prints status messages to STDOUT.
    Returns the installer return code and true if a restart is needed.
    """
    global installablecount
    global currentinstallable
    global options
    
    currentinstallable += 1
    restartneeded = False
    installeroutput = []

    cmd = ['/usr/sbin/installer', '-pkginfo', '-pkg', pkgpath]
    p = subprocess.Popen(cmd, shell=False, bufsize=1, stdin=subprocess.PIPE, 
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (output, err) = p.communicate()
    packagename = output.splitlines()[0]
    print >>sys.stderr, "Package name is", packagename
    if options.ihookoutput:
        print "%TITLE Installing " + packagename + "..."
        print "%%%s Item %s of %s" % (0, currentinstallable, installablecount)
    log("Installing %s from %s" % (packagename, os.path.basename(pkgpath)))
    cmd = ['/usr/sbin/installer', '-query', 'RestartAction', '-pkg', pkgpath]
    p = subprocess.Popen(cmd, shell=False, bufsize=1, stdin=subprocess.PIPE, 
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (output, err) = p.communicate()
    restartaction = output.rstrip("\n")
    if restartaction == "RequireRestart":
        message = "%s requires a restart after installation." % packagename
        print message
        sys.stdout.flush()
        log(message)
        restartneeded = True

    cmd = ['/usr/sbin/installer', '-verboseR', '-pkg', pkgpath, '-target', '/']
    p = subprocess.Popen(cmd, shell=False, bufsize=1, stdin=subprocess.PIPE, 
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    while (p.poll() == None): 
        installinfo =  p.stdout.readline()
        if installinfo.startswith("installer:"):
            # save all installer output in case there is
            # an error so we can dump it to the log
            installeroutput.append(installinfo)
            msg = installinfo[10:].rstrip("\n")
            if msg.startswith("PHASE:"):
                phase = msg[6:]
                if phase:
                    print phase
                    sys.stdout.flush()
            elif msg.startswith("STATUS:"):
                status = msg[7:]
                if status:
                    print status 
                    sys.stdout.flush()
            elif msg.startswith("%"):
                if options.ihookoutput:
                    percent = float(msg[1:])
                    percent = int(percent * 100)
                    print "%%%s Item %s of %s" % (percent, currentinstallable, installablecount)
                    if percent == 100:
                        overallpercentage = min(100,int(currentinstallable/installablecount * 100))
                        print "%%%s Item %s of %s" % (overallpercentage, currentinstallable, installablecount)
                    sys.stdout.flush()
            elif msg.startswith(" Error"):
                print msg
                sys.stdout.flush()
                print >>sys.stderr, msg
                log(msg)
            elif msg.startswith(" Cannot install"):
                print msg
                sys.stdout.flush()
                print >>sys.stderr, msg
                log(msg)
            else:
                print >>sys.stderr, msg

    retcode = p.poll()
    if retcode:
        message = "Install of %s failed." % packagename
        print >>sys.stderr, message
        log(message)
        message = "-------------------------------------------------"
        print >>sys.stderr, message
        log(message)
        for line in installeroutput:
            print >>sys.stderr, "     ", line.rstrip("\n")
            log(line.rstrip("\n"))
        message = "-------------------------------------------------"
        print >>sys.stderr, message
        log(message)
        restartneeded = False
    else:
        log("Install of %s was successful." % packagename)

    return (retcode, restartneeded)


def installall(dirpath):
    """
    Attempts to install all pkgs and mpkgs in a given directory.
    Will mount dmg files and install pkgs and mpkgs found at the
    root of any mountpoints.
    """
    restartflag = False
    installitems = os.listdir(dirpath)
    for item in installitems:
        itempath = os.path.join(dirpath, item)
        if (item.endswith(".pkg") or item.endswith(".mpkg")):
            (retcode, needsrestart) = install(itempath)
            if needsrestart:
                restartflag = True
        if item.endswith(".dmg"):
            mountpoints = mountdmg(itempath)
            for mountpoint in mountpoints:
                # install all the pkgs and mpkgs at the root
                # of the mountpoint -- call us recursively!
                needtorestart = installall(mountpoint)
                if needtorestart:
                    restartflag = True
                unmountdmg(mountpoint)
                
    return restartflag
    
    
def installWithInfo(dirpath, installlist):
    """
    Uses the installlist to install items in the
    correct order.
    """
    restartflag = False
    for item in installlist:
        itempath = os.path.join(dirpath, item)
        if not os.path.exists(itempath):
            #can't install, so we should stop
            return restartFlag
        if (item.endswith(".pkg") or item.endswith(".mpkg")):
            (retcode, needsrestart) = install(itempath)
            if needsrestart:
                restartflag = True
        if item.endswith(".dmg"):
            mountpoints = mountdmg(itempath)
            for mountpoint in mountpoints:
                # install all the pkgs and mpkgs at the root
                # of the mountpoint -- call us recursively!
                needtorestart = installall(mountpoint)
                if needtorestart:
                    restartflag = True
                unmountdmg(mountpoint)
                
        # now remove the item from the install cache
        # (using rm -f in case it's a bundle pkg)
        retcode = subprocess.call(["/bin/rm", "-rf", itempath])

    return restartflag



def mountdmg(dmgpath):
    """
    Attempts to mount the dmg at dmgpath
    and returns a list of mountpoints
    """
    mountpoints = []
    dmgname = os.path.basename(dmgpath)
    print "Mounting disk image %s" % dmgname
    log("Mounting disk image %s" % dmgname)
    p = subprocess.Popen(['/usr/bin/hdiutil', 'attach', dmgpath, '-mountRandom', '/tmp', '-nobrowse', '-plist'],
            bufsize=1, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (plist, err) = p.communicate()
    if plist:
        pl = plistlib.readPlistFromString(plist)
        for entity in pl['system-entities']:
            if 'mount-point' in entity:
                mountpoints.append(entity['mount-point'])

    return mountpoints


def unmountdmg(mountpoint):
    """
    Unmounts the dmg at mountpoint
    """
    p = subprocess.Popen(['/usr/bin/hdiutil', 'detach', mountpoint], 
        bufsize=1, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (output, err) = p.communicate()
    if err:
        print >>sys.stderr, err
        p = subprocess.Popen(['/usr/bin/hdiutil', 'detach', mountpoint, '-force'], 
            bufsize=1, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        (output, err) = p.communicate()
        
        
# module (global) variables
managedinstallbase = managedinstalls.managed_install_dir()
installdir = os.path.join(managedinstallbase , 'Cache')
logdir = os.path.join(managedinstallbase, 'Logs')
installablecount = 0
currentinstallable = 0

p = optparse.OptionParser()
p.add_option('--ihookoutput', '-i', action='store_true')
options, arguments = p.parse_args()


def main():
    global installdir
    global installablecount

    if options.ihookoutput:
        print '%WINDOWSIZE 512 232'
        print '%BACKGROUND /Users/Shared/Installer.png'
        print '%BECOMEKEY'
        print '%BEGINPOLE'
        sys.stdout.flush()
    
    needtorestart = False

    installablecount = countinstallcandidates(installdir)
    if installablecount:
        log("### Beginning automated install session ###")
        if os.path.exists(installdir):
            installinfo = os.path.join(managedinstallbase, 'InstallInfo.plist')
            if os.path.exists(installinfo):
                try:
                    pl = plistlib.readPlist(installinfo)
                except:
                    print >>sys.stderr, "Invalid %s" % installinfo
                    exit(0)
                if "install" in pl:
                    needtorestart = installWithInfo(installdir, pl['install'])
                    # remove the install info
                    os.unlink(installinfo)
            else:
                print "No %s found." % installinfo
                # install all pkgs and mpkgs
                needtorestart = installall(installdir)
            
            if needtorestart:
                print "Software installed requires a restart."
                log("Software installed requires a restart.")
                sys.stdout.flush()
        
        log("### End automated install session ###")
        if needtorestart:
            time.sleep(5)
            # uncomment this when testing is done so it will restart.
            #retcode = subprocess.call(["/sbin/shutdown", "-r", "now"]) 


if __name__ == '__main__':
    main()

