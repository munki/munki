# encoding: utf-8
#
# Copyright 2009-2019 Greg Neagle.
#
# Licensed under the Apache License, Version 2.0 (the 'License');
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an 'AS IS' BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
pkgutils.py

Created by Greg Neagle on 2016-12-14.

Common pkg/receipt functions and classes used by the munki tools.
"""

import os
import re
import shutil
import subprocess
import tempfile
import urllib2

from distutils import version
from types import StringType
from xml.dom import minidom

from . import display
from . import osutils
from . import utils
from . import FoundationPlist

# we use lots of camelCase-style names. Deal with it.
# pylint: disable=C0103


#####################################################
# Apple package utilities
#####################################################

def getPkgRestartInfo(filename):
    """Uses Apple's installer tool to get RestartAction
    from an installer item."""
    installerinfo = {}
    proc = subprocess.Popen(['/usr/sbin/installer',
                             '-query', 'RestartAction',
                             '-pkg', filename],
                            bufsize=-1,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    (out, err) = proc.communicate()
    if proc.returncode:
        display.display_error("installer -query failed: %s %s", out, err)
        return {}

    if out:
        restartAction = str(out).rstrip('\n')
        if restartAction != 'None':
            installerinfo['RestartAction'] = restartAction

    return installerinfo


class MunkiLooseVersion(version.LooseVersion):
    '''Subclass version.LooseVersion to compare things like
    "10.6" and "10.6.0" as equal'''

    def __init__(self, vstring=None):
        if vstring is None:
            # treat None like an empty string
            self.parse('')
        if vstring is not None:
            if isinstance(vstring, unicode):
                # unicode string! Why? Oh well...
                # convert to string so version.LooseVersion doesn't choke
                vstring = vstring.encode('UTF-8')
            self.parse(str(vstring))

    def _pad(self, version_list, max_length):
        """Pad a version list by adding extra 0
        components to the end if needed"""
        # copy the version_list so we don't modify it
        cmp_list = list(version_list)
        while len(cmp_list) < max_length:
            cmp_list.append(0)
        return cmp_list

    def __cmp__(self, other):
        if isinstance(other, StringType):
            other = MunkiLooseVersion(other)

        max_length = max(len(self.version), len(other.version))
        self_cmp_version = self._pad(self.version, max_length)
        other_cmp_version = self._pad(other.version, max_length)

        return cmp(self_cmp_version, other_cmp_version)


def padVersionString(versString, tupleCount):
    """Normalize the format of a version string"""
    if versString is None:
        versString = '0'
    components = str(versString).split('.')
    if len(components) > tupleCount:
        components = components[0:tupleCount]
    else:
        while len(components) < tupleCount:
            components.append('0')
    return '.'.join(components)


def getVersionString(plist, key=None):
    """Gets a version string from the plist.

    If a key is explicitly specified, the value of that key is
    returned without modification, or an empty string if the
    key does not exist.

    If key is not specified:
    if there's a valid CFBundleShortVersionString, returns that.
    else if there's a CFBundleVersion, returns that
    else returns an empty string.

    """
    VersionString = ''
    if key:
        # admin has specified a specific key
        # return value verbatim or empty string
        return plist.get(key, '')

    # default to CFBundleShortVersionString plus magic
    # and workarounds and edge case cleanups
    key = 'CFBundleShortVersionString'
    if not 'CFBundleShortVersionString' in plist:
        if 'Bundle versions string, short' in plist:
            # workaround for broken Composer packages
            # where the key is actually named
            # 'Bundle versions string, short' instead of
            # 'CFBundleShortVersionString'
            key = 'Bundle versions string, short'
    if plist.get(key):
        # return key value up to first space
        # lets us use crappy values like '1.0 (100)'
        VersionString = plist[key].split()[0]
    if VersionString:
        if VersionString[0] in '0123456789':
            # starts with a number; that's good
            # now for another edge case thanks to Adobe:
            # replace commas with periods
            VersionString = VersionString.replace(',', '.')
            return VersionString
    if plist.get('CFBundleVersion'):
        # no CFBundleShortVersionString, or bad one
        # a future version of the Munki tools may drop this magic
        # and require admins to explicitly choose the CFBundleVersion
        # but for now Munki does some magic
        VersionString = plist['CFBundleVersion'].encode('utf-8').split()[0]
        if VersionString[0] in '0123456789':
            # starts with a number; that's good
            # now for another edge case thanks to Adobe:
            # replace commas with periods
            VersionString = VersionString.replace(',', '.')
            return VersionString

    return ''


def getBundleInfo(path):
    """
    Returns Info.plist data if available
    for bundle at path
    """
    infopath = os.path.join(path, "Contents", "Info.plist")
    if not os.path.exists(infopath):
        infopath = os.path.join(path, "Resources", "Info.plist")

    if os.path.exists(infopath):
        try:
            plist = FoundationPlist.readPlist(infopath)
            return plist
        except FoundationPlist.NSPropertyListSerializationException:
            pass

    return None


def getAppBundleExecutable(bundlepath):
    """Returns path to the actual executable in an app bundle or None"""
    plist = getBundleInfo(bundlepath)
    if plist:
        if 'CFBundleExecutable' in plist:
            executable = plist['CFBundleExecutable']
        elif 'CFBundleName' in plist:
            executable = plist['CFBundleName']
        else:
            executable = os.path.splitext(os.path.basename(bundlepath))[0]
        executable_path = os.path.join(bundlepath, 'Contents/MacOS', executable)
        if os.path.exists(executable_path):
            return executable_path
    return None


def getBundleVersion(bundlepath, key=None):
    """
    Returns version number from a bundle.
    Some extra code to deal with very old-style bundle packages

    Specify key to use a specific key in the Info.plist for
    the version string.
    """
    plist = getBundleInfo(bundlepath)
    if plist:
        versionstring = getVersionString(plist, key)
        if versionstring:
            return versionstring

    # no version number in Info.plist. Maybe old-style package?
    infopath = os.path.join(
        bundlepath, 'Contents', 'Resources', 'English.lproj')
    if os.path.exists(infopath):
        for item in osutils.listdir(infopath):
            if os.path.join(infopath, item).endswith('.info'):
                infofile = os.path.join(infopath, item)
                fileobj = open(infofile, mode='r')
                info = fileobj.read()
                fileobj.close()
                infolines = info.splitlines()
                for line in infolines:
                    parts = line.split(None, 1)
                    if len(parts) == 2:
                        label = parts[0]
                        if label == 'Version':
                            return parts[1]

    # didn't find a version number, so return 0...
    return '0.0.0.0.0'


def parsePkgRefs(filename, path_to_pkg=None):
    """Parses a .dist or PackageInfo file looking for pkg-ref or pkg-info tags
    to get info on included sub-packages"""
    info = []
    dom = minidom.parse(filename)
    pkgrefs = dom.getElementsByTagName('pkg-info')
    if pkgrefs:
        # this is a PackageInfo file
        for ref in pkgrefs:
            keys = ref.attributes.keys()
            if 'identifier' in keys and 'version' in keys:
                pkginfo = {}
                pkginfo['packageid'] = \
                       ref.attributes['identifier'].value.encode('UTF-8')
                pkginfo['version'] = \
                    ref.attributes['version'].value.encode('UTF-8')
                payloads = ref.getElementsByTagName('payload')
                if payloads:
                    keys = payloads[0].attributes.keys()
                    if 'installKBytes' in keys:
                        pkginfo['installed_size'] = int(float(
                            payloads[0].attributes[
                                'installKBytes'].value.encode('UTF-8')))
                    if pkginfo not in info:
                        info.append(pkginfo)
                # if there isn't a payload, no receipt is left by a flat
                # pkg, so don't add this to the info array
    else:
        pkgrefs = dom.getElementsByTagName('pkg-ref')
        if pkgrefs:
            # this is a Distribution or .dist file
            pkgref_dict = {}
            for ref in pkgrefs:
                keys = ref.attributes.keys()
                if 'id' in keys:
                    pkgid = ref.attributes['id'].value.encode('UTF-8')
                    if not pkgid in pkgref_dict:
                        pkgref_dict[pkgid] = {'packageid': pkgid}
                    if 'version' in keys:
                        pkgref_dict[pkgid]['version'] = \
                            ref.attributes['version'].value.encode('UTF-8')
                    if 'installKBytes' in keys:
                        pkgref_dict[pkgid]['installed_size'] = int(float(
                            ref.attributes['installKBytes'].value.encode(
                                'UTF-8')))
                    if ref.firstChild:
                        text = ref.firstChild.wholeText
                        if text.endswith('.pkg'):
                            if text.startswith('file:'):
                                relativepath = urllib2.unquote(
                                    text[5:].encode('UTF-8'))
                                pkgdir = os.path.dirname(
                                    path_to_pkg or filename)
                                pkgref_dict[pkgid]['file'] = os.path.join(
                                    pkgdir, relativepath)
                            else:
                                if text.startswith('#'):
                                    text = text[1:]
                                relativepath = urllib2.unquote(
                                    text.encode('UTF-8'))
                                thisdir = os.path.dirname(filename)
                                pkgref_dict[pkgid]['file'] = os.path.join(
                                    thisdir, relativepath)

            for key in pkgref_dict.keys():
                pkgref = pkgref_dict[key]
                if 'file' in pkgref:
                    if os.path.exists(pkgref['file']):
                        info.extend(getReceiptInfo(pkgref['file']))
                        continue
                if 'version' in pkgref:
                    if 'file' in pkgref:
                        del pkgref['file']
                    info.append(pkgref_dict[key])

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
    pkgtmp = tempfile.mkdtemp(dir=osutils.tmpdir())
    # record our current working dir
    cwd = os.getcwd()
    # change into our tmpdir so we can use xar to unarchive the flat package
    os.chdir(pkgtmp)
    # Get the TOC of the flat pkg so we can search it later
    cmd_toc = ['/usr/bin/xar', '-tf', abspkgpath]
    proc = subprocess.Popen(cmd_toc, bufsize=-1, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    (toc, err) = proc.communicate()
    toc = toc.strip().split('\n')
    if proc.returncode == 0:
        # Walk trough the TOC entries
        for toc_entry in toc:
            # If the TOC entry is a top-level PackageInfo, extract it
            if toc_entry.startswith('PackageInfo') and len(infoarray) == 0:
                cmd_extract = ['/usr/bin/xar', '-xf', abspkgpath, toc_entry]
                result = subprocess.call(cmd_extract)
                if result == 0:
                    packageinfoabspath = os.path.abspath(
                        os.path.join(pkgtmp, toc_entry))
                    infoarray = parsePkgRefs(packageinfoabspath)
                    break
                else:
                    display.display_warning(
                        "An error occurred while extracting %s: %s",
                        toc_entry, err)
            # If there are PackageInfo files elsewhere, gather them up
            elif toc_entry.endswith('.pkg/PackageInfo'):
                cmd_extract = ['/usr/bin/xar', '-xf', abspkgpath, toc_entry]
                result = subprocess.call(cmd_extract)
                if result == 0:
                    packageinfoabspath = os.path.abspath(
                        os.path.join(pkgtmp, toc_entry))
                    infoarray.extend(parsePkgRefs(packageinfoabspath))
                else:
                    display.display_warning(
                        "An error occurred while extracting %s: %s",
                        toc_entry, err)
        if len(infoarray) == 0:
            for toc_entry in [item for item in toc
                              if item.startswith('Distribution')]:
                # Extract the Distribution file
                cmd_extract = ['/usr/bin/xar', '-xf', abspkgpath, toc_entry]
                result = subprocess.call(cmd_extract)
                if result == 0:
                    distributionabspath = os.path.abspath(
                        os.path.join(pkgtmp, toc_entry))
                    infoarray = parsePkgRefs(distributionabspath,
                                             path_to_pkg=pkgpath)
                    break
                else:
                    display.display_warning(
                        "An error occurred while extracting %s: %s",
                        toc_entry, err)

        if len(infoarray) == 0:
            display.display_warning(
                'No valid Distribution or PackageInfo found.')
    else:
        display.display_warning(err)

    # change back to original working dir
    os.chdir(cwd)
    shutil.rmtree(pkgtmp)
    return infoarray


def getBomList(pkgpath):
    '''Gets bom listing from pkgpath, which should be a path
    to a bundle-style package'''
    bompath = None
    for item in osutils.listdir(os.path.join(pkgpath, 'Contents')):
        if item.endswith('.bom'):
            bompath = os.path.join(pkgpath, 'Contents', item)
            break
    if not bompath:
        for item in osutils.listdir(os.path.join(pkgpath, 'Contents', 'Resources')):
            if item.endswith('.bom'):
                bompath = os.path.join(pkgpath, 'Contents', 'Resources', item)
                break
    if bompath:
        proc = subprocess.Popen(['/usr/bin/lsbom', '-s', bompath],
                                shell=False, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        (output, dummy_err) = proc.communicate()
        if proc.returncode == 0:
            return output.splitlines()
    return []


def getOnePackageInfo(pkgpath):
    """Gets receipt info for a single bundle-style package"""
    pkginfo = {}
    plist = getBundleInfo(pkgpath)
    if plist:
        pkginfo['filename'] = os.path.basename(pkgpath)
        try:
            if 'CFBundleIdentifier' in plist:
                pkginfo['packageid'] = plist['CFBundleIdentifier']
            elif 'Bundle identifier' in plist:
                # special case for JAMF Composer generated packages.
                pkginfo['packageid'] = plist['Bundle identifier']
            else:
                pkginfo['packageid'] = os.path.basename(pkgpath)

            if 'CFBundleName' in plist:
                pkginfo['name'] = plist['CFBundleName']

            if 'IFPkgFlagInstalledSize' in plist:
                pkginfo['installed_size'] = int(plist['IFPkgFlagInstalledSize'])

            pkginfo['version'] = getBundleVersion(pkgpath)
        except (AttributeError,
                FoundationPlist.NSPropertyListSerializationException):
            pkginfo['packageid'] = 'BAD PLIST in %s' % \
                                    os.path.basename(pkgpath)
            pkginfo['version'] = '0.0'
        ## now look for applications to suggest for blocking_applications
        #bomlist = getBomList(pkgpath)
        #if bomlist:
        #    pkginfo['apps'] = [os.path.basename(item) for item in bomlist
        #                        if item.endswith('.app')]

    else:
        # look for old-style .info files!
        infopath = os.path.join(
            pkgpath, 'Contents', 'Resources', 'English.lproj')
        if os.path.exists(infopath):
            for item in osutils.listdir(infopath):
                if os.path.join(infopath, item).endswith('.info'):
                    pkginfo['filename'] = os.path.basename(pkgpath)
                    pkginfo['packageid'] = os.path.basename(pkgpath)
                    infofile = os.path.join(infopath, item)
                    fileobj = open(infofile, mode='r')
                    info = fileobj.read()
                    fileobj.close()
                    infolines = info.splitlines()
                    pkginfo['version'] = '0.0'
                    pkginfo['name'] = 'UNKNOWN'
                    for line in infolines:
                        parts = line.split(None, 1)
                        if len(parts) == 2:
                            label = parts[0]
                            if label == 'Version':
                                pkginfo['version'] = parts[1]
                            if label == 'Title':
                                pkginfo['name'] = parts[1]
                    break
    return pkginfo


def getBundlePackageInfo(pkgpath):
    """Get metadata from a bundle-style package"""
    infoarray = []

    if pkgpath.endswith('.pkg'):
        pkginfo = getOnePackageInfo(pkgpath)
        if pkginfo:
            infoarray.append(pkginfo)
            return infoarray

    bundlecontents = os.path.join(pkgpath, 'Contents')
    if os.path.exists(bundlecontents):
        for item in osutils.listdir(bundlecontents):
            if item.endswith('.dist'):
                filename = os.path.join(bundlecontents, item)
                # return info using the distribution file
                return parsePkgRefs(filename, path_to_pkg=bundlecontents)

        # no .dist file found, look for packages in subdirs
        dirsToSearch = []
        plist = getBundleInfo(pkgpath)
        if plist:
            if 'IFPkgFlagComponentDirectory' in plist:
                componentdir = plist['IFPkgFlagComponentDirectory']
                dirsToSearch.append(componentdir)

        if dirsToSearch == []:
            dirsToSearch = ['', 'Contents', 'Contents/Installers',
                            'Contents/Packages', 'Contents/Resources',
                            'Contents/Resources/Packages']
        for subdir in dirsToSearch:
            searchdir = os.path.join(pkgpath, subdir)
            if os.path.exists(searchdir):
                for item in osutils.listdir(searchdir):
                    itempath = os.path.join(searchdir, item)
                    if os.path.isdir(itempath):
                        if itempath.endswith('.pkg'):
                            pkginfo = getOnePackageInfo(itempath)
                            if pkginfo:
                                infoarray.append(pkginfo)
                        elif itempath.endswith('.mpkg'):
                            pkginfo = getBundlePackageInfo(itempath)
                            if pkginfo:
                                infoarray.extend(pkginfo)

    return infoarray


def getReceiptInfo(pkgname):
    """Get receipt info from a package"""
    info = []
    if hasValidPackageExt(pkgname):
        display.display_debug2('Examining %s' % pkgname)
        if os.path.isfile(pkgname):       # new flat package
            info = getFlatPackageInfo(pkgname)

        if os.path.isdir(pkgname):        # bundle-style package?
            info = getBundlePackageInfo(pkgname)

    elif pkgname.endswith('.dist'):
        info = parsePkgRefs(pkgname)

    return info


def getInstalledPackageVersion(pkgid):
    """
    Checks a package id against the receipts to
    determine if a package is already installed.
    Returns the version string of the installed pkg
    if it exists, or an empty string if it does not
    """

    # First check (Leopard and later) package database
    proc = subprocess.Popen(['/usr/sbin/pkgutil',
                             '--pkg-info-plist', pkgid],
                            bufsize=1,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    (out, dummy_err) = proc.communicate()

    if out:
        try:
            plist = FoundationPlist.readPlistFromString(out)
        except FoundationPlist.NSPropertyListSerializationException:
            pass
        else:
            foundbundleid = plist.get('pkgid')
            foundvers = plist.get('pkg-version', '0.0.0.0.0')
            if pkgid == foundbundleid:
                display.display_debug2('\tThis machine has %s, version %s',
                                       pkgid, foundvers)
                return foundvers

    # If we got to this point, we haven't found the pkgid yet.
    # Check /Library/Receipts
    receiptsdir = '/Library/Receipts'
    if os.path.exists(receiptsdir):
        installitems = osutils.listdir(receiptsdir)
        highestversion = '0'
        for item in installitems:
            if item.endswith('.pkg'):
                info = getBundlePackageInfo(os.path.join(receiptsdir, item))
                if len(info):
                    infoitem = info[0]
                    foundbundleid = infoitem['packageid']
                    foundvers = infoitem['version']
                    if pkgid == foundbundleid:
                        if (MunkiLooseVersion(foundvers) >
                                MunkiLooseVersion(highestversion)):
                            highestversion = foundvers

        if highestversion != '0':
            display.display_debug2('\tThis machine has %s, version %s',
                                   pkgid, highestversion)
            return highestversion


    # This package does not appear to be currently installed
    display.display_debug2('\tThis machine does not have %s' % pkgid)
    return ""


def trim_version_string(version_string):
    """Trims all lone trailing zeros in the version string after major/minor.

    Examples:
      10.0.0.0 -> 10.0
      10.0.0.1 -> 10.0.0.1
      10.0.0-abc1 -> 10.0.0-abc1
      10.0.0-abc1.0 -> 10.0.0-abc1
    """
    if version_string is None or version_string == '':
        return ''
    version_parts = version_string.split('.')
    # strip off all trailing 0's in the version, while over 2 parts.
    while len(version_parts) > 2 and version_parts[-1] == '0':
        del version_parts[-1]
    return '.'.join(version_parts)


def nameAndVersion(aString):
    """
    Splits a string into the name and version numbers:
    'TextWrangler2.3b1' becomes ('TextWrangler', '2.3b1')
    'AdobePhotoshopCS3-11.2.1' becomes ('AdobePhotoshopCS3', '11.2.1')
    'MicrosoftOffice2008v12.2.1' becomes ('MicrosoftOffice2008', '12.2.1')
    """
    # first try regex
    m = re.search(r'[0-9]+(\.[0-9]+)((\.|a|b|d|v)[0-9]+)+', aString)
    if m:
        vers = m.group(0)
        name = aString[0:aString.find(vers)].rstrip(' .-_v')
        return (name, vers)

    # try another way
    index = 0
    for char in aString[::-1]:
        if char in '0123456789._':
            index -= 1
        elif char in 'abdv':
            partialVersion = aString[index:]
            if set(partialVersion).intersection(set('abdv')):
                # only one of 'abdv' allowed in the version
                break
            else:
                index -= 1
        else:
            break

    if index < 0:
        possibleVersion = aString[index:]
        # now check from the front of the possible version until we
        # reach a digit (because we might have characters in '._abdv'
        # at the start)
        for char in possibleVersion:
            if not char in '0123456789':
                index += 1
            else:
                break
        vers = aString[index:]
        return (aString[0:index].rstrip(' .-_v'), vers)
    else:
        # no version number found,
        # just return original string and empty string
        return (aString, '')


def hasValidConfigProfileExt(path):
    """Verifies a path ends in '.mobileconfig'"""
    ext = os.path.splitext(path)[1]
    return ext.lower() == '.mobileconfig'


def hasValidPackageExt(path):
    """Verifies a path ends in '.pkg' or '.mpkg'"""
    ext = os.path.splitext(path)[1]
    return ext.lower() in ['.pkg', '.mpkg']


def hasValidDiskImageExt(path):
    """Verifies a path ends in '.dmg' or '.iso'"""
    ext = os.path.splitext(path)[1]
    return ext.lower() in ['.dmg', '.iso']


def hasValidInstallerItemExt(path):
    """Verifies we have an installer item"""
    return (hasValidPackageExt(path) or hasValidDiskImageExt(path)
            or hasValidConfigProfileExt(path))


def getChoiceChangesXML(pkgitem):
    """Queries package for 'ChoiceChangesXML'"""
    choices = []
    try:
        proc = subprocess.Popen(
            ['/usr/sbin/installer', '-showChoiceChangesXML', '-pkg', pkgitem],
            bufsize=1, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        (out, dummy_err) = proc.communicate()
        if out:
            plist = FoundationPlist.readPlistFromString(out)

            # list comprehension to populate choices with those items
            # whose 'choiceAttribute' value is 'selected'
            choices = [item for item in plist
                       if 'selected' in item['choiceAttribute']]
    except BaseException:
        # No choices found or something went wrong
        pass
    return choices


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

    if not hasValidInstallerItemExt(pkgitem):
        return {}

    # first query /usr/sbin/installer for restartAction
    installerinfo = getPkgRestartInfo(pkgitem)
    # now look for receipt/subpkg info
    receiptinfo = getReceiptInfo(pkgitem)

    name = os.path.split(pkgitem)[1]
    shortname = os.path.splitext(name)[0]
    metaversion = getBundleVersion(pkgitem)
    if metaversion == '0.0.0.0.0':
        metaversion = nameAndVersion(shortname)[1]

    highestpkgversion = '0.0'
    installedsize = 0
    for infoitem in receiptinfo:
        if (MunkiLooseVersion(infoitem['version']) >
                MunkiLooseVersion(highestpkgversion)):
            highestpkgversion = infoitem['version']
        if 'installed_size' in infoitem:
            # note this is in KBytes
            installedsize += infoitem['installed_size']

    if metaversion == '0.0.0.0.0':
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
    elif installedsize:
        cataloginfo['installed_size'] = installedsize

    cataloginfo['receipts'] = receiptinfo

    if os.path.isfile(pkgitem) and not pkgitem.endswith('.dist'):
        # flat packages require 10.5.0+
        cataloginfo['minimum_os_version'] = "10.5.0"

    return cataloginfo


@utils.Memoize
def getInstalledPackages():
    """Builds a dictionary of installed receipts and their version number"""
    installedpkgs = {}

    # we use the --regexp option to pkgutil to get it to return receipt
    # info for all installed packages.  Huge speed up.
    proc = subprocess.Popen(['/usr/sbin/pkgutil', '--regexp',
                             '--pkg-info-plist', '.*'], bufsize=8192,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out, dummy_err) = proc.communicate()
    while out:
        (pliststr, out) = utils.getFirstPlist(out)
        if pliststr:
            plist = FoundationPlist.readPlistFromString(pliststr)
            if 'pkg-version' in plist and 'pkgid' in plist:
                installedpkgs[plist['pkgid']] = (
                    plist['pkg-version'] or '0.0.0.0.0')
        else:
            break

    # Now check /Library/Receipts
    receiptsdir = '/Library/Receipts'
    if os.path.exists(receiptsdir):
        installitems = osutils.listdir(receiptsdir)
        for item in installitems:
            if item.endswith('.pkg'):
                pkginfo = getOnePackageInfo(
                    os.path.join(receiptsdir, item))
                pkgid = pkginfo.get('packageid')
                thisversion = pkginfo.get('version')
                if pkgid:
                    if not pkgid in installedpkgs:
                        installedpkgs[pkgid] = thisversion
                    else:
                        # pkgid is already in our list. There must be
                        # multiple receipts with the same pkgid.
                        # in this case, we want the highest version
                        # number, since that's the one that's
                        # installed, since presumably
                        # the newer package replaced the older one
                        storedversion = installedpkgs[pkgid]
                        if (MunkiLooseVersion(thisversion) >
                                MunkiLooseVersion(storedversion)):
                            installedpkgs[pkgid] = thisversion
    return installedpkgs



# This function doesn't really have anything to do with packages or receipts
# but is used by makepkginfo, munkiimport, and installer.py, so it might as
# well live here for now
def isApplication(pathname):
    """Returns true if path appears to be an OS X application"""
    # No symlinks, please
    if os.path.islink(pathname):
        return False
    if pathname.endswith('.app'):
        return True
    if os.path.isdir(pathname):
        # look for app bundle structure
        # use Info.plist to determine the name of the executable
        plist = getBundleInfo(pathname)
        if plist:
            if 'CFBundlePackageType' in plist:
                if plist['CFBundlePackageType'] != 'APPL':
                    return False
            # get CFBundleExecutable,
            # falling back to bundle name if it's missing
            bundleexecutable = plist.get(
                'CFBundleExecutable', os.path.basename(pathname))
            bundleexecutablepath = os.path.join(
                pathname, 'Contents', 'MacOS', bundleexecutable)
            if os.path.exists(bundleexecutablepath):
                return True
    return False


if __name__ == '__main__':
    print 'This is a library of support tools for the Munki Suite.'
