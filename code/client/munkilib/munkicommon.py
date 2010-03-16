#!/usr/bin/python
# encoding: utf-8
#
# Copyright 2009 Greg Neagle.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# 
#      http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
munkicommon

Created by Greg Neagle on 2008-11-18.

Common functions used by the munki tools.
"""

import sys
import os
import re
import time
import subprocess
import tempfile
import shutil
import urllib2
from distutils import version
from xml.dom import minidom

#from Foundation import NSDictionary, NSDate
#from CoreFoundation import CFPreferencesCopyAppValue

import munkistatus
import FoundationPlist

def get_version():
    '''Returns version of munkitools'''
    return "0.5.0"


# output and logging functions
def getsteps(num_of_steps, limit):
    """
    Helper function for display_percent_done
    """
    steps = []
    current = 0.0
    for i in range(0,num_of_steps):
        if i == num_of_steps-1:
            steps.append(int(round(limit)))
        else:
            steps.append(int(round(current)))
        current += float(limit)/float(num_of_steps-1)
    return steps


def display_percent_done(current,maximum):
    """
    Mimics the command-line progress meter seen in some
    of Apple's tools (like softwareupdate), or tells
    MunkiStatus to display percent done via progress bar.
    """
    if munkistatusoutput:
        step = getsteps(21, maximum)
        if current in step:
            if current == maximum:
                percentdone = 100
            else:
                percentdone = int(float(current)/float(maximum)*100)
            munkistatus.percent(str(percentdone))
    elif verbose > 1:
        step = getsteps(16, maximum)
        output = ''
        indicator = ['\t0','.','.','20','.','.','40','.','.',
                    '60','.','.','80','.','.','100\n']
        for i in range(0,16):
            if current >= step[i]:
                output += indicator[i]
        if output:
            sys.stdout.write("\r" + output)
            sys.stdout.flush()


def display_status(msg):
    """
    Displays major status messages, formatting as needed
    for verbose/non-verbose and munkistatus-style output.
    """
    log(msg)
    if munkistatusoutput:
        munkistatus.detail(msg)
    elif verbose > 0:
        if msg.endswith(".") or msg.endswith(u"…"):
            print "%s" % msg.encode('UTF-8')
        else:
            print "%s..." % msg.encode('UTF-8')
        sys.stdout.flush()


def display_info(msg):
    """
    Displays info messages.
    Not displayed in MunkiStatus.
    """
    log(msg)
    if munkistatusoutput:
        pass
    elif verbose > 0:
        print msg.encode('UTF-8')
        sys.stdout.flush()
        
        
def display_detail(msg):
    """
    Displays minor info messages, formatting as needed
    for verbose/non-verbose and munkistatus-style output.
    These are usually logged only, but can be printed to
    stdout if verbose is set to 2 or higher
    """
    if munkistatusoutput:
        pass
    elif verbose > 1:
        print msg.encode('UTF-8')
        sys.stdout.flush()
    if pref('LoggingLevel') > 0:
        log(msg)
        
        
def display_debug1(msg):
    """
    Displays debug messages, formatting as needed
    for verbose/non-verbose and munkistatus-style output.
    """
    if munkistatusoutput:
        pass
    elif verbose > 2:
        print msg.encode('UTF-8')
        sys.stdout.flush()
    if pref('LoggingLevel') > 1:
        log("DEBUG1: %s" % msg)


def display_debug2(msg):
    """
    Displays debug messages, formatting as needed
    for verbose/non-verbose and munkistatus-style output.
    """
    if munkistatusoutput:
        pass
    elif verbose > 3:
        print msg.encode('UTF-8')
    if pref('LoggingLevel') > 2:
        log("DEBUG2: %s" % msg)
        
        
def reset_warnings():
    warningsfile = os.path.join(os.path.dirname(pref("LogFile")),
                                                "warnings.log")
    if os.path.exists(warningsfile):
        rotatelog(warningsfile)


def display_warning(msg):
    """
    Prints warning msgs to stderr and the log
    """
    global warnings
    warning = "WARNING: %s" % msg
    print >>sys.stderr, warning.encode('UTF-8')
    log(warning)
    # append this warning to our warnings log
    log(warning, "warnings.log")
    # collect the warning for later reporting
    report['Warnings'].append(msg)


def reset_errors():
    errorsfile = os.path.join(os.path.dirname(pref("LogFile")), "errors.log")
    if os.path.exists(errorsfile):
        rotatelog(errorsfile)


def display_error(msg):
    """
    Prints msg to stderr and the log
    """
    global errors
    errmsg = "ERROR: %s" % msg
    print >>sys.stderr, errmsg.encode('UTF-8')
    log(errmsg)
    # append this error to our errors log
    log(errmsg, "errors.log")
    # collect the errors for later reporting
    report['Errors'].append(msg)


def log(msg, logname=''):
    # date/time format string
    formatstr = "%b %d %H:%M:%S"
    if not logname:
        # use our regular logfile
        logpath = pref("LogFile")
    else:
        logpath = os.path.join(os.path.dirname(pref("LogFile")), logname)
    try:
        f = open(logpath, mode='a', buffering=1)
        print >>f, time.strftime(formatstr), msg.encode('UTF-8')
        f.close()
    except (OSError, IOError):
        pass
        
        
def rotatelog(logname=''):
    if not logname:
        # use our regular logfile
        logpath = pref("LogFile")
    else:
        logpath = os.path.join(os.path.dirname(pref("LogFile")), logname)
    if os.path.exists(logpath):
        for x in range(3,-1,-1):
            try:
                os.unlink(logpath+"."+str(x+1))
            except (OSError, IOError):
                pass
            try:
                os.rename(logpath+"."+str(x), logpath+"."+str(x+1))
            except (OSError, IOError):
                pass
        try:
            os.rename(logpath, logpath+".0")
        except (OSError, IOError):
            pass


def rotate_main_log():
    if os.path.exists(pref("LogFile")):
        if os.path.getsize(pref("LogFile")) > 1000000:
            rotatelog(pref("LogFile"))


def printreportitem(label, value, indent=0):
    indentspace = "    "
    if type(value) == type(None):
        print indentspace*indent, "%s: !NONE!" % label
    elif type(value) == list or type(value).__name__ == 'NSCFArray':
        if label:
            print indentspace*indent, "%s:" % label
        index = 0
        for item in value:
            index += 1
            printreportitem(index, item, indent+1)
    elif type(value) == dict or type(value).__name__ == 'NSCFDictionary':
        if label:
            print indentspace*indent, "%s:" % label
        for subkey in value.keys():
            printreportitem(subkey, value[subkey], indent+1)
    else:
        print indentspace*indent, "%s: %s" % (label, value)
        
            
def printreport(reportdict):
    """Prints the report dictionary in a pretty(?) way"""
    for key in reportdict.keys():
        printreportitem(key, reportdict[key])
        

def savereport():
    FoundationPlist.writePlist(report, 
        os.path.join(pref('ManagedInstallDir'), "ManagedInstallReport.plist"))
    

def archive_report():
    reportfile = os.path.join(pref('ManagedInstallDir'),              
                              "ManagedInstallReport.plist")
    if os.path.exists(reportfile):
        modtime = os.stat(reportfile).st_mtime
        formatstr = "%Y-%m-%d-%H%M%S"
        archivename = "ManagedInstallReport-" + \
                      time.strftime(formatstr,time.localtime(modtime)) + \
                       ".plist"
        archivepath = os.path.join(pref('ManagedInstallDir'), "Archives")
        if not os.path.exists(archivepath):
            try:
                os.mkdir(archivepath)
            except (OSError, IOError):
                display_warning("Could not create report archive path.")
        try:
            os.rename(reportfile, os.path.join(archivepath, archivename))
            # convert to binary format to compress
            #cmd = ['/usr/bin/plutil', '-convert', 'binary1', 
            #       os.path.join(archivepath, archivename)]
            #p = subprocess.Popen(cmd, shell=False, bufsize=1, 
            #                     stdin=subprocess.PIPE, 
            #                     stdout=subprocess.PIPE, 
            #                     stderr=subprocess.PIPE)
            #(out, err) = p.communicate()
        except (OSError, IOError):
            display_warning("Could not archive report.")
        # now keep number of archived reports to 100 or fewer
        p = subprocess.Popen(['/bin/ls', '-t1', archivepath], 
                             bufsize=1, stdout=subprocess.PIPE, 
                             stderr=subprocess.PIPE)
        (output, err) = p.communicate()
        if output:
            archiveitems = [item 
                            for item in output.splitlines() 
                            if item.startswith("ManagedInstallReport-")]
            if len(archiveitems) > 100:
                for item in archiveitems[100:]:
                    itempath = os.path.join(archivepath, item)
                    if os.path.isfile(itempath):
                        try:
                            os.unlink(itempath)
                        except (OSError, IOError):
                            display_warning("Could not remove archive item %s"                  
                                             % itempath)
            
        
        
# misc functions

def validPlist(path):
    '''Uses plutil to determine if path contains a valid plist.
    Returns True or False.'''
    cmd = ['/usr/bin/plutil', '-lint', '-s' , path]
    p = subprocess.Popen(cmd, shell=False, bufsize=1, stdin=subprocess.PIPE, 
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out, err) = p.communicate()
    if p.returncode == 0:
        return True
    else:
        return False


def stopRequested():
    """Allows user to cancel operations when 
    MunkiStatus is being used"""
    if munkistatusoutput:
        if munkistatus.getStopButtonState() == 1:
            log("### User stopped session ###")
            return True
    return False


def getconsoleuser():    
    from SystemConfiguration import SCDynamicStoreCopyConsoleUser
    cfuser = SCDynamicStoreCopyConsoleUser( None, None, None )
    return cfuser[0]


def currentGUIusers():
    '''Gets a list of GUI users by parsing the output of /usr/bin/who'''
    gui_users = []
    p = subprocess.Popen("/usr/bin/who", shell=False, stdin=subprocess.PIPE, 
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (output, err) = p.communicate()
    lines = output.splitlines()
    for line in lines:
        if "console" in line:
            parts = line.split()
            gui_users.append(parts[0])

    return gui_users


def pythonScriptRunning(scriptname):
    cmd = ['/bin/ps', '-eo', 'pid=,command=']
    p = subprocess.Popen(cmd, shell=False, bufsize=1, stdin=subprocess.PIPE, 
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out, err) = p.communicate()
    mypid = os.getpid()
    lines = out.splitlines()
    for line in lines:
        (pid, proc) = line.split(None,1)
        # first look for Python processes
        if proc.find("MacOS/Python ") != -1 or proc.find("python ") != -1:
            if proc.find(scriptname) != -1:
                if int(pid) != int(mypid):
                    return pid

    return 0
    
    
def osascript(osastring):
    '''Wrapper to run AppleScript commands'''
    cmd = ['/usr/bin/osascript', '-e', osastring]
    p = subprocess.Popen(cmd, shell=False, bufsize=1, stdin=subprocess.PIPE, 
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out, err) = p.communicate()
    if p.returncode != 0:
        print >>sys.stderr, "Error: ", err
    if out:
        return out.decode('UTF-8').rstrip("\n")
        
        
# dmg helpers

def mountdmg(dmgpath, use_shadow=False):
    """
    Attempts to mount the dmg at dmgpath
    and returns a list of mountpoints
    If use_shadow is true, mount image with shadow file
    """
    mountpoints = []
    dmgname = os.path.basename(dmgpath)
    cmd = ['/usr/bin/hdiutil', 'attach', dmgpath, 
                '-mountRandom', '/tmp', '-nobrowse', '-plist']
    if use_shadow:
        cmd.append('-shadow')
    p = subprocess.Popen(cmd,
                         bufsize=1, stdout=subprocess.PIPE, 
                         stderr=subprocess.PIPE)
    (plist, err) = p.communicate()
    if err:
        print >>sys.stderr, "Error %s mounting %s." % (err, dmgpath)
    if plist:
        pl = FoundationPlist.readPlistFromString(plist)
        for entity in pl['system-entities']:
            if 'mount-point' in entity:
                mountpoints.append(entity['mount-point'])

    return mountpoints


def unmountdmg(mountpoint):
    """
    Unmounts the dmg at mountpoint
    """
    p = subprocess.Popen(['/usr/bin/hdiutil', 'detach', mountpoint], 
                         bufsize=1, stdout=subprocess.PIPE, 
                         stderr=subprocess.PIPE)
    (output, err) = p.communicate()
    if err:
        print >>sys.stderr, err
        p = subprocess.Popen(['/usr/bin/hdiutil', 'detach', mountpoint, 
                             '-force'], 
                              bufsize=1, stdout=subprocess.PIPE, 
                              stderr=subprocess.PIPE)
        (output, err) = p.communicate()
        
        
def isApplication(pathname):
    '''Returns true if path appears to be an OS X application'''
    # No symlinks, please
    if os.path.islink(pathname):
        return False
    if pathname.endswith(".app"):
        return True
    if os.path.isdir(pathname):
        # look for app bundle structure
        # use Info.plist to determine the name of the executable
        infoplist = os.path.join(pathname, "Contents", "Info.plist")
        if os.path.exists(infoplist):
            pl = FoundationPlist.readPlist(infoplist)
            if 'CFBundlePackageType' in pl:
                if pl['CFBundlePackageType'] != 'APPL':
                    return False
            # get CFBundleExecutable, 
            # falling back to bundle name if it's missing
            bundleexecutable = pl.get('CFBundleExecutable',     
                                      os.path.basename(pathname))
            bundleexecutablepath = os.path.join(pathname, "Contents", 
                                                "MacOS", bundleexecutable)
            if os.path.exists(bundleexecutablepath):
                return True
    return False


#####################################################
# managed installs preferences/metadata
#####################################################


def prefs():
    # define default values
    global _prefs
    if not _prefs:
        _prefs['ManagedInstallDir'] = "/Library/Managed Installs"
        # convenience; to be replaced with CatalogURL and PackageURL
        _prefs['SoftwareRepoURL'] = "http://munki/repo"
        # effective defaults for the following three; though if they
        # are not in the prefs plist, they are calculated relative
        # to the SoftwareRepoURL (if it exists)
        #prefs['ManifestURL'] = "http://munki/repo/manifests/"
        #prefs['CatalogURL'] = "http://munki/repo/catalogs/"
        #prefs['PackageURL'] = "http://munki/repo/pkgs/"
        _prefs['ClientIdentifier'] = ''
        _prefs['LogFile'] = \
            "/Library/Managed Installs/Logs/ManagedSoftwareUpdate.log"
        _prefs['LoggingLevel'] = 1
        _prefs['InstallAppleSoftwareUpdates'] = False
        _prefs['SoftwareUpdateServerURL'] = ''
        _prefs['DaysBetweenNotifications'] = 1
        _prefs['LastNotifiedDate'] = '1970-01-01 00:00:00 -0000'
        # Added by bcw
        _prefs['UseClientCertificate'] = False
        
        prefsfile = "/Library/Preferences/ManagedInstalls.plist"
        pl = {}
        if os.path.exists(prefsfile):
            try:
                pl = FoundationPlist.readPlist(prefsfile)
            except FoundationPlist.NSPropertyListSerializationException:
                display_error("ERROR: Could not read preferences file %s." 
                               % prefsfile)
                raise Exception("Could not read preferences file %s." % 
                                                                prefsfile)
            try:
                for key in pl.keys():
                    if type(pl[key]).__name__ == "__NSCFDate":
                        # convert NSDate/CFDates to strings
                        _prefs[key] = str(pl[key])
                    else:
                        _prefs[key] = pl[key]
            except AttributeError:
                display_error("ERROR: Prefs file %s contains invalid data." 
                                                        % prefsfile)
                raise Exception("Preferences file %s invalid." % prefsfile)
        else:
            # no prefs file, so we'll write out a "default" prefs file
            del _prefs['LastNotifiedDate']
            FoundationPlist.writePlist(_prefs, prefsfile)
                            
    return _prefs


def pref(prefname):
    return prefs().get(prefname,'')
    
    
#####################################################    
# Apple package utilities
#####################################################

def getInstallerPkgInfo(filename):
    """Uses Apple's installer tool to get basic info 
    about an installer item."""
    installerinfo = {}
    p = subprocess.Popen(["/usr/sbin/installer", "-pkginfo", "-verbose",        
                          "-plist", "-pkg", filename], 
                          bufsize=1, stdout=subprocess.PIPE, 
                          stderr=subprocess.PIPE)
    (out, err) = p.communicate()

    if out:
        # discard any lines at the beginning that aren't part of the plist
        lines = out.splitlines()
        pl = ''
        for index in range(len(lines)):
            try:
                pl = FoundationPlist.readPlistFromString(
                                    '\n'.join(lines[index:]) )
            except FoundationPlist.NSPropertyListSerializationException:
                pass
            if pl:
                break
        if pl:            
            if 'Size' in pl:
                installerinfo['installed_size'] = int(pl['Size'])
            if 'Description' in pl:
                installerinfo['description'] = pl['Description']
            if 'Will Restart' in pl:
                if pl['Will Restart'] == "YES":
                    installerinfo['RestartAction'] = "RequireRestart"
            if "Title" in pl:
                installerinfo['display_name'] = pl['Title']
    
    p = subprocess.Popen(["/usr/sbin/installer", 
                          "-query", "RestartAction", 
                          "-pkg", filename], 
                          bufsize=1, 
                          stdout=subprocess.PIPE, 
                          stderr=subprocess.PIPE)
    (out, err) = p.communicate()
    if out:
        restartAction = out.rstrip('\n')
        if restartAction != 'None':
            installerinfo['RestartAction'] = restartAction
                
    return installerinfo
    

def padVersionString(versString,tupleCount):
    if versString == None:
        versString = "0"
    components = str(versString).split(".")
    if len(components) > tupleCount :
        components = components[0:tupleCount]
    else:
        while len(components) < tupleCount :
            components.append("0")
    return ".".join(components)
    

def getVersionString(pl):
    # Gets a version string from the plist.
    # if there's a valid CFBundleShortVersionString, returns that.
    # else if there's a CFBundleVersion, returns that
    # else returns an empty string.
    CFBundleShortVersionString = ''
    if pl.get('CFBundleShortVersionString'):
        CFBundleShortVersionString = \
            pl['CFBundleShortVersionString'].split()[0]
    if "Bundle versions string, short" in pl:
        CFBundleShortVersionString = \
            pl['Bundle versions string, short'].split()[0]
    if CFBundleShortVersionString:
        if CFBundleShortVersionString[0] in "0123456789":
            # starts with a number; that's good
            # now for another edge case thanks to Adobe:
            # replace commas with periods
            CFBundleShortVersionString = \
                CFBundleShortVersionString.replace(',','.')
            return CFBundleShortVersionString
    if pl.get('CFBundleVersion'):
        # no CFBundleShortVersionString, or bad one
        CFBundleVersion = str(pl['CFBundleVersion']).split()[0]
        if CFBundleVersion[0] in "0123456789":
            # starts with a number; that's good
            # now for another edge case thanks to Adobe:
            # replace commas with periods
            CFBundleVersion = CFBundleVersion.replace(',','.')
            return CFBundleVersion
            
    return ''


def getExtendedVersion(bundlepath):
    """
    Returns five-part version number like Apple uses in distribution
    and flat packages
    """
    infoPlist = os.path.join(bundlepath,"Contents","Info.plist")                    
    if os.path.exists(infoPlist):
        pl = FoundationPlist.readPlist(infoPlist)
        versionstring = getVersionString(pl)
        if versionstring:
            return padVersionString(versionstring, 5)
            
    # didn't find a version number, so return 0...
    return "0.0.0.0.0"
  
                
def parsePkgRefs(filename):
    """Parses a .dist or PackageInfo file looking for pkg-ref or pkg-info tags 
    to get info on included sub-packages"""
    info = []
    dom = minidom.parse(filename)
    pkgrefs = dom.getElementsByTagName("pkg-ref")
    if pkgrefs:
        for ref in pkgrefs:
            keys = ref.attributes.keys()
            if 'id' in keys and 'version' in keys:
                if debug:
                    for key in keys:
                        print key, "=>", \
                              ref.attributes[key].value.encode('UTF-8')

                pkginfo = {}
                pkginfo['packageid'] = \
                             ref.attributes['id'].value.encode('UTF-8')
                pkginfo['version'] = \
                    padVersionString(
                        ref.attributes['version'].value.encode('UTF-8'), 5)
                if 'installKBytes' in keys:
                    pkginfo['installed_size'] = \
                        int(
                         ref.attributes['installKBytes'].value.encode('UTF-8')
                        )
                if not pkginfo['packageid'].startswith('manual'):
                    if not pkginfo in info:
                        info.append(pkginfo)
    else:
        pkgrefs = dom.getElementsByTagName("pkg-info")
        if pkgrefs:
            for ref in pkgrefs:
                keys = ref.attributes.keys()
                if 'identifier' in keys and 'version' in keys:
                    if debug:
                        for key in keys:
                            print key, "=>", \
                                  ref.attributes[key].value.encode('UTF-8')

                    pkginfo = {}
                    pkginfo['packageid'] = \
                           ref.attributes['identifier'].value.encode('UTF-8')
                    pkginfo['version'] = \
                           padVersionString(
                            ref.attributes['version'].value.encode('UTF-8'),5)
                    if not pkginfo in info:
                        info.append(pkginfo)
    return info


def getFlatPackageInfo(pkgpath):
    """
    returns array of dictionaries with info on subpackages
    contained in the flat package
    """

    infoarray = []
    # get the absolute path to the pkg because we need to do a chdir later
    abspkgpath = os.path.abspath(pkgpath)
    # make a tmp dir to expand the flat package into
    pkgtmp = tempfile.mkdtemp(dir=tmpdir)
    # record our current working dir
    cwd = os.getcwd()
    # change into our tmpdir so we can use xar to unarchive the flat package
    os.chdir(pkgtmp)
    p = subprocess.Popen(["/usr/bin/xar", "-xf", abspkgpath, 
                          "--exclude", "Payload"])
    returncode = p.wait()
    if returncode == 0:
        currentdir = pkgtmp
        packageinfofile = os.path.join(currentdir, "PackageInfo")
        if os.path.exists(packageinfofile):
            infoarray = parsePkgRefs(packageinfofile)
                
        if not infoarray:
            # didn't get any packageid info or no PackageInfo file
            # look for subpackages at the top level
            for item in os.listdir(currentdir):
                itempath = os.path.join(currentdir, item)
                if itempath.endswith(".pkg") and os.path.isdir(itempath):
                    packageinfofile = os.path.join(itempath, "PackageInfo")
                    if os.path.exists(packageinfofile):
                        infoarray.extend(parsePkgRefs(packageinfofile))
                        
        if not infoarray:
            # found no PackageInfo files and no subpackages,
            # so let's look at the Distribution file
            distributionfile = os.path.join(currentdir, "Distribution")
            if os.path.exists(distributionfile):
                infoarray = parsePkgRefs(distributionfile)
                
    # change back to original working dir
    os.chdir(cwd)
    shutil.rmtree(pkgtmp)
    return infoarray


def getOnePackageInfo(pkgpath):
    """Gets receipt info for a single bundle-style package"""
    pkginfo = {}
    plistpath = os.path.join(pkgpath, "Contents", "Info.plist")
    if os.path.exists(plistpath):
        pkginfo['filename'] = os.path.basename(pkgpath)
        try:
            pl = FoundationPlist.readPlist(plistpath)
            if "CFBundleIdentifier" in pl:
                pkginfo['packageid'] = pl["CFBundleIdentifier"]
            elif "Bundle identifier" in pl:
                # special case for JAMF Composer generated packages.
                pkginfo['packageid'] = pl["Bundle identifier"]
            else:
                pkginfo['packageid'] = os.path.basename(pkgpath)
            
            if "CFBundleName" in pl:
                pkginfo['name'] = pl["CFBundleName"]
        
            if "IFPkgFlagInstalledSize" in pl:
                pkginfo['installed_size'] = pl["IFPkgFlagInstalledSize"]
        
            pkginfo['version'] = getExtendedVersion(pkgpath)
        except (AttributeError, 
                FoundationPlist.NSPropertyListSerializationException):
            pkginfo['packageid'] = "BAD PLIST in %s" % \
                                    os.path.basename(pkgpath)
            pkginfo['version'] = "0.0.0.0.0"
    return pkginfo
    

def getText(nodelist):
    '''Helper function to get text from XML child nodes'''
    rc = ""
    for node in nodelist:
        if node.nodeType == node.TEXT_NODE:
            rc = rc + node.data
    return rc


def getBundlePackageInfo(pkgpath):
    infoarray = []
    
    if pkgpath.endswith(".pkg"):
        pkginfo = getOnePackageInfo(pkgpath)
        if pkginfo:
            infoarray.append(pkginfo)
            return infoarray

    bundlecontents = os.path.join(pkgpath, "Contents")
    if os.path.exists(bundlecontents):
        for item in os.listdir(bundlecontents):
            if item.endswith(".dist"):
                filename = os.path.join(bundlecontents, item)                
                dom = minidom.parse(filename)
                pkgrefs = dom.getElementsByTagName("pkg-ref")
                if pkgrefs:
                    # try to find subpackages from the file: references
                    for ref in pkgrefs:
                        fileref = getText(ref.childNodes)
                        if fileref.startswith("file:"):
                            relativepath = urllib2.unquote(fileref[5:])
                            subpkgpath = os.path.join(pkgpath, relativepath)
                            if os.path.exists(subpkgpath):
                                pkginfo = getBundlePackageInfo(subpkgpath)
                                if pkginfo:
                                    infoarray.extend(pkginfo)
            
                    if infoarray:
                        return infoarray
                
        # no .dist file found, look for packages in subdirs
        dirsToSearch = []
        plistpath = os.path.join(pkgpath, "Contents", "Info.plist")
        if os.path.exists(plistpath):
            pl = FoundationPlist.readPlist(plistpath)
            if 'IFPkgFlagComponentDirectory' in pl:
                componentdir = pl['IFPkgFlagComponentDirectory']
                dirsToSearch.append(componentdir)
            
        if dirsToSearch == []:     
            dirsToSearch = ['Contents', 'Contents/Installers',
                            'Contents/Packages', 'Contents/Resources',
                            'Contents/Resources/Packages']
        for subdir in dirsToSearch:
            searchdir = os.path.join(pkgpath, subdir)
            if os.path.exists(searchdir):
                for item in os.listdir(searchdir):
                    itempath = os.path.join(searchdir, item)
                    if os.path.isdir(itempath):
                        if itempath.endswith(".pkg"):
                            pkginfo = getOnePackageInfo(itempath)
                            if pkginfo:
                                infoarray.append(pkginfo)
                        elif itempath.endswith(".mpkg"):
                            pkginfo = getBundlePackageInfo(itempath)
                            if pkginfo:
                                infoarray.extend(pkginfo)
                    
        if infoarray:
            return infoarray
        else:
            # couldn't find any subpackages, 
            # just return info from the .dist file
            # if it exists
            for item in os.listdir(bundlecontents):
                if item.endswith(".dist"):
                    distfile = os.path.join(bundlecontents, item)
                    infoarray.extend(parsePkgRefs(distfile))
                    
    return infoarray


def getReceiptInfo(p):
    info = []
    if p.endswith(".pkg") or p.endswith(".mpkg"):
        if debug:
            print "Examining %s" % p
        if os.path.isfile(p):             # new flat package
            info = getFlatPackageInfo(p)

        if os.path.isdir(p):              # bundle-style package?
            info = getBundlePackageInfo(p)
            
    elif p.endswith('.dist'):
        info = parsePkgRefs(p)
            
    return info


def getInstalledPackageVersion(pkgid):
    """
    Checks a package id against the receipts to
    determine if a package is already installed.
    Returns the version string of the installed pkg
    if it exists, or an empty string if it does not
    """
        
    # First check (Leopard and later) package database
   
    p = subprocess.Popen(["/usr/sbin/pkgutil", 
                            "--pkg-info-plist", pkgid], 
                            bufsize=1, 
                            stdout=subprocess.PIPE, 
                            stderr=subprocess.PIPE)
    (out, err) = p.communicate()

    if out:
        try:
            pl = FoundationPlist.readPlistFromString(out)

            if "pkgid" in pl:
                foundbundleid = pl["pkgid"]
            if "pkg-version" in pl:
                foundvers = pl["pkg-version"]
            
            if pkgid == foundbundleid:
                display_debug2("\tThis machine has %s, version %s" % 
                                (pkgid, foundvers))
            return padVersionString(foundvers,5)
        except (AttributeError,
                FoundationPlist.NSPropertyListSerializationException):
            pass
            
    # If we got to this point, we haven't found the pkgid yet. 
    # Check /Library/Receipts
    receiptsdir = "/Library/Receipts"
    if os.path.exists(receiptsdir):
        installitems = os.listdir(receiptsdir)
        highestversion = "0"
        for item in installitems:
            if item.endswith(".pkg"):
                info = getBundlePackageInfo(os.path.join(receiptsdir, item))
                if len(info):
                    infoitem = info[0]
                    foundbundleid = infoitem['packageid']
                    foundvers = infoitem['version']
                    if pkgid == foundbundleid:
                        if version.LooseVersion(foundvers) > \
                           version.LooseVersion(highestversion):
                            highestversion = foundvers

        if highestversion != "0":
            display_debug2("\tThis machine has %s, version %s" % 
                            (pkgid, highestversion))
            return highestversion
   
    
    # This package does not appear to be currently installed
    display_debug2("\tThis machine does not have %s" % pkgid)
    return ""
    
    
def nameAndVersion(s):
    """
    Splits a string into the name and version numbers:
    'TextWrangler2.3b1' becomes ('TextWrangler', '2.3b1')
    'AdobePhotoshopCS3-11.2.1' becomes ('AdobePhotoshopCS3', '11.2.1')
    'MicrosoftOffice2008v12.2.1' becomes ('MicrosoftOffice2008', '12.2.1')
    """
    index = 0
    for char in s:
        if char in "0123456789":
            possibleVersion = s[index:]
            if not (" " in possibleVersion or "_" in possibleVersion or \
                    "-" in possibleVersion or "v" in possibleVersion):
                 return (s[0:index].rstrip(" .-_v"), possibleVersion)
        index += 1
    # no version number found, just return original string and empty string
    return (s, '')


def findInstallerItem(path):
    if path.endswith('.pkg') or path.endswith('.mpkg') or \
       path.endswith('.dmg'):
        return path
    else:
        # Apple Software Updates download as directories
        # with .dist files and .pkgs
        if os.path.exists(path) and os.path.isdir(path):
            for item in os.listdir(path):
                if item.endswith('.pkg'):
                    return path
                    
            # we didn't find a pkg at this level
            # look for a Packages dir
            path = os.path.join(path,"Packages")
            if os.path.exists(path) and os.path.isdir(path):
                for item in os.listdir(path):
                    if item.endswith('.pkg'):
                        return path
    # found nothing!
    return ''


def getPackageMetaData(pkgitem):
    """
    Queries an installer item (.pkg, .mpkg, .dist)
    and gets metadata. There are a lot of valid Apple package formats
    and this function may not deal with them all equally well.
    Standard bundle packages are probably the best understood and documented,
    so this code deals with those pretty well.

    metadata items include:
    installer_item_size:  size of the installer item (.dmg, .pkg, etc)
    installed_size: size of items that will be installed
    RestartAction: will a restart be needed after installation?
    name
    version
    description
    receipts: an array of packageids that may be installed 
              (some may not be installed on some machines)
    """
    
    installedsize = 0
    pkgitem = findInstallerItem(pkgitem)
    if pkgitem == None:
        return {}
    
    # first get the data /usr/sbin/installer will give us   
    installerinfo = getInstallerPkgInfo(pkgitem)
    # now look for receipt/subpkg info
    receiptinfo = getReceiptInfo(pkgitem)
    
    name = os.path.split(pkgitem)[1]
    shortname = os.path.splitext(name)[0]
    metaversion = getExtendedVersion(pkgitem)
    if metaversion == "0.0.0.0.0":
        metaversion = nameAndVersion(shortname)[1]

    highestpkgversion = "0.0"
    for infoitem in receiptinfo:
        if version.LooseVersion(infoitem['version']) > \
           version.LooseVersion(highestpkgversion):
            highestpkgversion = infoitem['version']
            if "installed_size" in infoitem:
                # note this is in KBytes
                installedsize += infoitem['installed_size']
    
    if metaversion == "0.0.0.0.0":
        metaversion = highestpkgversion
    elif len(receiptinfo) == 1:
        # there is only one package in this item
        metaversion = highestpkgversion
    elif highestpkgversion.startswith(metaversion):
        # for example, highestpkgversion is 2.0.3124.0, 
        # version in filename is 2.0
        metaversion = highestpkgversion
            
    cataloginfo = {}
    cataloginfo['name'] = nameAndVersion(shortname)[0]
    cataloginfo['version'] = metaversion
    for key in ('display_name', 'RestartAction', 'description'):
        if key in installerinfo:
            cataloginfo[key] = installerinfo[key]
    
    if 'installed_size' in installerinfo:
           if installerinfo['installed_size'] > 0:
               cataloginfo['installed_size'] = installerinfo['installed_size']
           
    cataloginfo['receipts'] = receiptinfo        
           
    return cataloginfo
    
    
# some utility functions

def getAvailableDiskSpace(volumepath="/"):
    # returns available diskspace in KBytes.
    p = subprocess.Popen(["/usr/sbin/diskutil", "info", "-plist", volumepath], 
                         bufsize=1,
                         stdout=subprocess.PIPE, 
                         stderr=subprocess.PIPE)
    (out, err) = p.communicate()
    if out:
        try:
            pl = FoundationPlist.readPlistFromString(out)

            if "FreeSpace" in pl:
                # pl["FreeSpace"] is in bytes
                return int(pl["FreeSpace"]/1024)
                
        except (AttributeError,
                FoundationPlist.NSPropertyListSerializationException):
            pass

    # Yikes
    return 0


def cleanUpTmpDir():
    global tmpdir
    if tmpdir:
        try:
            shutil.rmtree(tmpdir) 
        except (OSError, IOError):
            pass
        tmpdir = None
    
    
# module globals
debug = False
verbose = 1
munkistatusoutput = False
tmpdir = tempfile.mkdtemp()
_prefs = {}
report = {}
report['Errors'] = []
report['Warnings'] = []


def main():
    print "This is a library of support tools for the Munki Suite."

if __name__ == '__main__':
    main()

