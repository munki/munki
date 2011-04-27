#!/usr/bin/env python
# encoding: utf-8
"""
appleupdates.py

Utilities for dealing with Apple Software Update.

"""
# Copyright 2009-2011 Greg Neagle.
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


import os
import stat
import subprocess
from xml.dom import minidom
from xml.parsers.expat import ExpatError

from Foundation import NSDate

import FoundationPlist
import munkicommon
import munkistatus
import installer


def softwareUpdatePrefs():
    """Returns a dictionary of prefs from
    /Library/Preferences/com.apple.SoftwareUpdate.plist"""
    try:
        return FoundationPlist.readPlist(
                   '/Library/Preferences/com.apple.SoftwareUpdate.plist')
    except FoundationPlist.NSPropertyListSerializationException:
        return {}


def getCurrentSoftwareUpdateServer():
    '''Returns the current Apple SUS CatalogURL'''
    return softwareUpdatePrefs().get('CatalogURL','')


def selectSoftwareUpdateServer():
    '''Switch to our preferred Software Update Server if supplied'''
    localCatalogURL = munkicommon.pref('SoftwareUpdateServerURL')
    if localCatalogURL:
        munkicommon.display_detail('Setting Apple Software Update '
                                   'CatalogURL to %s' % localCatalogURL)
        cmd = ['/usr/bin/defaults', 'write',
               '/Library/Preferences/com.apple.SoftwareUpdate',
               'CatalogURL', localCatalogURL]
        unused_retcode = subprocess.call(cmd)


def restoreSoftwareUpdateServer(theurl):
    '''Switch back to original Software Update server (if there was one)'''
    if munkicommon.pref('SoftwareUpdateServerURL'):
        if theurl:
            munkicommon.display_detail('Resetting Apple Software Update '
                                       'CatalogURL to %s' % theurl)
            cmd = ['/usr/bin/defaults', 'write',
                   '/Library/Preferences/com.apple.SoftwareUpdate',
                   'CatalogURL', theurl]
        else:
            munkicommon.display_detail('Resetting Apple Software Update '
                                       'CatalogURL to the default')
            cmd = ['/usr/bin/defaults', 'delete',
                   '/Library/Preferences/com.apple.SoftwareUpdate',
                   'CatalogURL']
        unused_retcode = subprocess.call(cmd)


def setupSoftwareUpdateCheck():
    '''Set defaults for root user and current host.
    Needed for Leopard.'''
    cmd = ['/usr/bin/defaults', '-currentHost', 'write',
           'com.apple.SoftwareUpdate', 'AgreedToLicenseAgreement',
           '-bool', 'YES']
    unused_retcode = subprocess.call(cmd)
    cmd = ['/usr/bin/defaults', '-currentHost', 'write',
           'com.apple.SoftwareUpdate', 'AutomaticDownload',
           '-bool', 'YES']
    unused_retcode = subprocess.call(cmd)
    cmd = ['/usr/bin/defaults', '-currentHost', 'write',
           'com.apple.SoftwareUpdate', 'LaunchAppInBackground',
           '-bool', 'YES']
    unused_retcode = subprocess.call(cmd)


CACHEDUPDATELIST = None
def softwareUpdateList():
    '''Returns a list of available updates
    using `/usr/sbin/softwareupdate -l`'''

    global CACHEDUPDATELIST
    if CACHEDUPDATELIST != None:
        return CACHEDUPDATELIST

    updates = []
    munkicommon.display_detail(
        'Getting list of available Apple Software Updates')
    cmd = ['/usr/sbin/softwareupdate', '-l']
    proc = subprocess.Popen(cmd, shell=False, bufsize=1,
                           stdin=subprocess.PIPE,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (output, unused_err) = proc.communicate()
    if proc.returncode == 0:
        updates = [str(item)[5:] for item in output.splitlines()
                       if str(item).startswith('   * ')]
    munkicommon.display_detail(
        'softwareupdate returned %s updates' % len(updates))
    CACHEDUPDATELIST = updates
    return CACHEDUPDATELIST


def checkForSoftwareUpdates():
    '''Does our Apple Software Update check'''
    msg = "Checking for available Apple Software Updates..."
    if munkicommon.munkistatusoutput:
        munkistatus.message(msg)
        munkistatus.detail("")
        munkistatus.percent(-1)
        munkicommon.log(msg)
    else:
        munkicommon.display_status(msg)
    # save the current SUS URL
    original_url = getCurrentSoftwareUpdateServer()
    # switch to a different SUS server if specified
    selectSoftwareUpdateServer()
    # get the OS version
    osvers = int(os.uname()[2].split('.')[0])
    if osvers == 9:
        setupSoftwareUpdateCheck()
        softwareupdateapp = "/System/Library/CoreServices/Software Update.app"
        softwareupdatecheck = os.path.join(softwareupdateapp,
                                "Contents/Resources/SoftwareUpdateCheck")

        try:
            # record mode of Software Update.app
            rawmode = os.stat(softwareupdateapp).st_mode
            oldmode = stat.S_IMODE(rawmode)
            # set mode of Software Update.app so it won't launch
            # yes, this is a hack.  So sue me.
            newmode = stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR
            os.chmod(softwareupdateapp, newmode)
        except OSError, e:
            munkicommon.display_warning(
                'Error with os.stat(Softare Update.app): %s', str(e))
            munkicommon.display_warning('Skipping Apple SUS check.')
            return -2

        cmd = [ softwareupdatecheck ]
    elif osvers > 9:
        # in Snow Leopard we can just use /usr/sbin/softwareupdate, since it
        # now downloads updates the same way as SoftwareUpdateCheck
        cmd = ['/usr/sbin/softwareupdate', '-v', '-d', '-a']
    else:
        # unsupported os version
        return -1

    # bump up verboseness so we get download percentage done feedback.
    oldverbose = munkicommon.verbose
    munkicommon.verbose = oldverbose + 1

    try:
        # now check for updates
        proc = subprocess.Popen(cmd, shell=False, bufsize=-1,
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT)
    except OSError, e:
        munkicommon.display_warning('Error with Popen(%s): %s', cmd, str(e))
        munkicommon.display_warning('Skipping Apple SUS check.')
        # if 10.5.x, safely revert the chmod from above.
        if osvers == 9:
            try:
                # put mode back for Software Update.app
                os.chmod(softwareupdateapp, oldmode)
            except OSError:
                pass
        return -3

    while True:
        output = proc.stdout.readline().decode('UTF-8')
        if munkicommon.munkistatusoutput:
            if munkicommon.stopRequested():
                os.kill(proc.pid, 15) #15 is SIGTERM
                break
        if not output and (proc.poll() != None):
            break
        # send the output to STDOUT or MunkiStatus as applicable
        if output.startswith('Downloading '):
            munkicommon.display_status(output.rstrip('\n'))
        elif output.startswith('   Progress: '):
            try:
                percent = int(output[13:].rstrip('\n%'))
            except ValueError:
                percent = -1
            munkicommon.display_percent_done(percent, 100)
        elif output.startswith('Installed '):
            # don't display this, it's just confusing
            pass
        elif output.startswith('x '):
            # don't display this, it's just confusing
            pass
        elif 'Missing bundle identifier' in output:
            # don't display this, it's noise
            pass
        elif output.rstrip() == '':
            pass
        else:
            munkicommon.display_status(output.rstrip('\n'))

    retcode = proc.poll()
    if retcode:
        if osvers == 9:
            # there's always an error on Leopard
            # because we prevent the app from launching
            # so let's just ignore them
            retcode = 0

    if retcode == 0:
        # get SoftwareUpdate's LastResultCode
        LastResultCode = softwareUpdatePrefs().get('LastResultCode', 0)
        if LastResultCode > 2:
            retcode = LastResultCode

    if retcode:
        # there was an error
        munkicommon.display_error("softwareupdate error: %s" % retcode)

    if osvers == 9:
        # put mode back for Software Update.app
        os.chmod(softwareupdateapp, oldmode)

    # set verboseness back.
    munkicommon.verbose = oldverbose

    # switch back to the original SUS server
    restoreSoftwareUpdateServer(original_url)
    return retcode


#
# Apple information on Distribution ('.dist') files:
#
# http://developer.apple.com/library/mac/#documentation/DeveloperTools/
# Reference/DistributionDefinitionRef/200-Distribution_XML_Ref/
# Distribution_XML_Ref.html
#
# Referred to elsewhere in this code as 'Distribution_XML_Ref.html'
#

def get_pkgrefs(xml_element):
    '''Gets all the pkg-refs that are children of the xml_element
       Returns a list of dictionaries.'''
    pkgs = []
    pkgrefs = xml_element.getElementsByTagName('pkg-ref')
    if pkgrefs:
        for ref in pkgrefs:
            keys = ref.attributes.keys()
            if 'id' in keys:
                pkgid = ref.attributes['id'].value
                pkg = {}
                pkg['id'] = pkgid
                if 'installKBytes' in keys:
                    pkg['installKBytes'] = \
                        ref.attributes['installKBytes'].value
                # Distribution_XML_Ref.html
                # says either 'installKBytes' or 'archiveKBytes' is valid
                if 'archiveKBytes' in keys:
                    pkg['installKBytes'] = \
                        ref.attributes['archiveKBytes'].value
                if 'version' in keys:
                    pkg['version'] = \
                        ref.attributes['version'].value
                if 'auth' in keys:
                    pkg['auth'] = \
                        ref.attributes['auth'].value
                if 'onConclusion' in keys:
                    pkg['onConclusion'] = \
                        ref.attributes['onConclusion'].value
                if ref.firstChild:
                    pkgfile = ref.firstChild.nodeValue
                    pkgfile = os.path.basename(pkgfile).lstrip('#./')
                    if pkgfile:
                        pkg['package_file'] = pkgfile
                pkgs.append(pkg)
    return pkgs


def parseDist(filename):
    '''Parses a dist file, looking for infomation of interest to
       munki. Returns a dictionary.'''
    su_name = ""
    title = ""

    dom = minidom.parse(filename)

    title_elements = dom.getElementsByTagName('title')
    if title_elements and title_elements[0].firstChild:
        title = title_elements[0].firstChild.nodeValue

    outlines = {}
    choices_outlines = dom.getElementsByTagName('choices-outline')
    if choices_outlines:
        for outline in choices_outlines:
            if 'ui' in outline.attributes.keys():
                # I wonder if we should convert to all lowercase...
                ui_name = outline.attributes['ui'].value
            else:
                ui_name = u'Installer'
            if not ui_name in outlines:
                outlines[ui_name] = []
                # this gets all lines, even children of lines
                # so we get a flattened list, which is fine
                # for our purposes for now.
                # may need to rework if we need tree-style
                # data in the future
                lines = outline.getElementsByTagName('line')
                for line in lines:
                    if 'choice' in line.attributes.keys():
                        outlines[ui_name].append(
                            line.attributes['choice'].value)
            else:
                # more than one choices-outline with the same ui-name.
                # we should throw an exception until we understand how to deal
                # with this.
                # Maybe we can safely merge them, but we'll play it
                # conversative for now
                raise AppleUpdateParseError(
                    'More than one choices-outline with ui=%s in %s'
                    % (ui_name, filename))

    choices = {}
    choice_elements = dom.getElementsByTagName("choice")
    if choice_elements:
        for choice in choice_elements:
            keys = choice.attributes.keys()
            if 'id' in keys:
                choice_id = choice.attributes['id'].value
                if not choice_id in choices:
                    choices[choice_id] = {}
                pkgrefs = get_pkgrefs(choice)
                if pkgrefs:
                    choices[choice_id]['pkg-refs'] = pkgrefs
            if 'suDisabledGroupID' in keys:
                # this is the name as displayed from
                # /usr/sbin/softwareupdate -l
                su_name = choice.attributes[
                    'suDisabledGroupID'].value

    # now look in top-level of xml for more pkg-ref info
    # this gets pkg-refs in child choice elements, too
    root_pkgrefs = get_pkgrefs(dom)
    # so remove the ones that we already found in choice elements
    already_seen_pkgrefs = []
    for key in choices.keys():
        for pkgref in choices[key].get('pkg-refs', []):
            already_seen_pkgrefs.append(pkgref)
    root_pkgrefs = [item for item in root_pkgrefs
                    if item not in already_seen_pkgrefs]

    text = ""
    localizations = dom.getElementsByTagName('localization')
    if localizations:
        string_elements = localizations[0].getElementsByTagName('strings')
        if string_elements:
            strings = string_elements[0]
            if strings.firstChild:
                text = strings.firstChild.wholeText

    # get title, version and description as displayed in Software Update
    title = vers = description = ""
    keep = False
    for line in text.split('\n'):
        if line.startswith('"SU_TITLE"'):
            title = line[10:]
            title = title[title.find('"')+1:-2]
        if line.startswith('"SU_VERS"'):
            vers = line[9:]
            vers = vers[vers.find('"')+1:-2]
        if line.startswith('"SU_VERSION"'):
            vers = line[12:]
            vers = vers[vers.find('"')+1:-2]
        if line.startswith('"SU_DESCRIPTION"'):
            description = ""
            keep = True
            # lop off "SU_DESCRIPTION"
            line = line[16:]
            # lop off everything up through '
            line = line[line.find("'")+1:]

        if keep:
            # replace escaped single quotes
            line = line.replace("\\'","'")
            if line == "';":
                # we're done
                break
            elif line.endswith("';"):
                # done
                description += line[0:-2]
                break
            else:
                # append the line to the description
                description += line + "\n"

    # now try to determine the total installed size
    itemsize = 0
    for pkgref in root_pkgrefs:
        if 'installKBytes' in pkgref:
            itemsize += int(pkgref['installKBytes'])

    if itemsize == 0:
        # just add up the size of the files in this directory
        for (path, unused_dirs, files) in os.walk(os.path.dirname(filename)):
            for name in files:
                pathname = os.path.join(path, name)
                # use os.lstat so we don't follow symlinks
                itemsize += int(os.lstat(pathname).st_size)
        # convert to kbytes
        itemsize = int(itemsize/1024)

    dist = {}
    dist['su_name'] = su_name
    dist['title'] = title
    dist['version'] = vers
    dist['installed_size'] = itemsize
    dist['description'] = description
    dist['choices-outlines'] = outlines
    dist['choices'] = choices
    dist['pkg-refs'] = root_pkgrefs
    return dist


def getRestartInfo(distfile):
    '''Returns RestartInfo for distfile'''
    restartAction = "None"
    proc = subprocess.Popen(["/usr/sbin/installer",
                            "-query", "RestartAction",
                            "-pkg", distfile],
                            bufsize=1,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    (out, unused_err) = proc.communicate()
    if out:
        restartAction = out.rstrip('\n')
    return restartAction


def actionWeight(action):
    '''Returns an integer representing the weight of an
    onConclusion action'''
    weight = {}
    weight['RequireShutdown'] = 4
    weight['RequireRestart'] = 3
    weight['RecommendRestart'] = 2
    weight['RequireLogout'] = 1
    weight['None'] = 0
    return weight.get(action, 'None')


def deDupPkgRefList(pkgref_list):
    '''some dists have the same package file listed
       more than once with different attributes
       we need to de-dupe the list'''

    deduped_list = []
    for pkg_ref in pkgref_list:
        matchingitems = [item for item in deduped_list
            if item['package_file'] == pkg_ref['package_file']]
        if matchingitems:
            # we have a duplicate; we should keep the one that has
            # the higher weighted 'onConclusion' action
            if (actionWeight(pkg_ref.get('onConclusion', 'None')) >
                actionWeight(matchingitems[0].get('onConclusion', 'None'))):
                deduped_list.remove(matchingitems[0])
                deduped_list.append(pkg_ref)
            else:
                # keep existing item in deduped_list
                pass
        else:
            deduped_list.append(pkg_ref)
    return deduped_list


def getPkgsToInstall(dist, pkgdir=None):
    '''Given a processed dist dictionary (from parseDist()),
    Returns a list of pkg-ref dictionaries in the order of install'''

    # Distribution_XML_Ref.html
    #
    # The name of the application that is to display the choices specified by
    # this element. Values: "Installer" (default), "SoftwareUpdate", or
    # "Invisible".
    # "invisible" seems to be in use as well...
    if 'SoftwareUpdate' in dist['choices-outlines']:
        ui_names = ['SoftwareUpdate', 'invisible', 'Invisible']
    else:
        ui_names = ['Installer', 'invisible', 'Invisible']

    pkgref_list = []
    for ui_name in ui_names:
        if ui_name in dist['choices-outlines']:
            outline = dist['choices-outlines'][ui_name]
            choices = dist['choices']
            for line in outline:
                if line in choices:
                    for pkg_ref in choices[line].get('pkg-refs', []):
                        if 'package_file' in pkg_ref:
                            if pkgdir:
                                # make sure pkg is present in dist_dir
                                # before adding to the list
                                package_path = os.path.join(pkgdir,
                                    pkg_ref['package_file'])
                                if os.path.exists(package_path):
                                    pkgref_list.append(pkg_ref)
                            else:
                                # just add it
                                pkgref_list.append(pkg_ref)

    return deDupPkgRefList(pkgref_list)


def makeFakeDist(title, pkg_refs_to_install):
    '''Builds a dist script for the list of pkg_refs_to_install
       Returns xml object'''
    xmlout = minidom.parseString(
'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<installer-gui-script minSpecVersion="1">
    <options hostArchitectures="ppc,i386" customize="never"></options>
    <title></title>
    <platforms>
        <client arch="ppc,i386"></client><server arch="ppc,i386"></server>
    </platforms>
    <choices-outline ui="SoftwareUpdate">
        <line choice="su"></line>
    </choices-outline>
    <choices-outline>
        <line choice="su"></line>
    </choices-outline>
    <choice id="su" title="">
    </choice>
</installer-gui-script>
''')
    xmlinst = xmlout.getElementsByTagName('installer-gui-script')[0]
    xmlchoice = xmlinst.getElementsByTagName('choice')[0]
    xmltitle = xmlinst.getElementsByTagName('title')[0]
    for pkg_ref in pkg_refs_to_install:
        node = xmlout.createElement('pkg-ref')
        node.setAttribute("id", pkg_ref['id'])
        if 'auth' in pkg_ref:
            node.setAttribute('auth', pkg_ref['auth'])
        if 'onConclusion' in pkg_ref:
            node.setAttribute('onConclusion', pkg_ref['onConclusion'])
        node.appendChild(
            xmlout.createTextNode(pkg_ref.get('package_file','')))
        # add to choice
        xmlchoice.appendChild(node)

        node = xmlout.createElement("pkg-ref")
        node.setAttribute("id", pkg_ref['id'])
        if 'installKBytes' in pkg_ref:
            node.setAttribute('installKBytes', pkg_ref['installKBytes'])
        if 'version' in pkg_ref:
            node.setAttribute('version', pkg_ref['version'])
        # add to root of installer-gui-script
        xmlinst.appendChild(node)

    xmlchoice.setAttribute("title", title)
    xmltitle.appendChild(xmlout.createTextNode(title))

    return xmlout


class AppleUpdateParseError(Exception):
    '''We raise this exception when we encounter something
    unexpected in the update processing'''
    pass


def processSoftwareUpdateDownload(appleupdatedir,
                            verifypkgsexist=True, writefile=True):
    '''Given a directory containing an update downloaded by softwareupdate -d
    or SoftwareUpdateCheck, attempts to create a simplified .dist file that
    /usr/sbin/installer can use to successfully install the downloaded
    update.
    Returns dist info as dictionary and path to generated dist
    or raises AppleUpdateParseError exception.'''

    osvers = int(os.uname()[2].split('.')[0])
    if osvers == 9:
        # Under Leopard, everything is one directory down...
        appleupdatedir = os.path.join(appleupdatedir, "Packages")

    availabledists = []
    availablepkgs = []
    generated_dist_file = os.path.join(appleupdatedir, 'MunkiGenerated.dist')
    try:
        os.unlink(generated_dist_file)
    except OSError:
        pass

    # What files do we have to work with? Do we have an appropriate quantity?
    diritems = munkicommon.listdir(appleupdatedir)
    for diritem in diritems:
        if diritem.endswith('.dist'):
            availabledists.append(diritem)
        elif diritem.endswith('.pkg') or diritem.endswith('.mpkg'):
            availablepkgs.append(diritem)

    if len(availabledists) != 1:
        raise AppleUpdateParseError(
            'Multiple .dist files in update directory %s' % appleupdatedir)
    if verifypkgsexist and len(availablepkgs) < 1:
        raise AppleUpdateParseError(
            'No packages in update directory %s' % appleupdatedir)

    appledistfile = os.path.join(appleupdatedir, availabledists[0])
    try:
        dist = parseDist(appledistfile)
    except (ExpatError, IOError):
        raise AppleUpdateParseError(
            'Could not parse .dist file %s' % appleupdatedir)

    if verifypkgsexist:
        pkg_refs_to_install = getPkgsToInstall(dist, appleupdatedir)
    else:
        pkg_refs_to_install = getPkgsToInstall(dist)

    if len(pkg_refs_to_install) == 0:
        raise AppleUpdateParseError(
            'Nothing was found to install in %s' % appleupdatedir)

    if verifypkgsexist:
        pkg_files_to_install = [item['package_file']
                                for item in pkg_refs_to_install]
        for pkg in availablepkgs:
            if not pkg in pkg_files_to_install:
                raise AppleUpdateParseError(
                    'Package %s missing from list of packages to install '
                    'in %s' % (pkg, appleupdatedir))

    # combine info from the root pkg-refs and the ones to be installed
    for choice_pkg_ref in pkg_refs_to_install:
        root_match = [item for item in dist['pkg-refs']
                      if choice_pkg_ref['id'] == item['id']]
        for item in root_match:
            for key in item.keys():
                choice_pkg_ref[key] = item[key]

    xmlout = makeFakeDist(dist['title'], pkg_refs_to_install)
    if writefile:
        f = open(generated_dist_file, 'w')
        f.write(xmlout.toxml('utf-8'))
        f.close()

    return (dist, generated_dist_file)


def getSoftwareUpdateInfo():
    '''Parses the Software Update index.plist and the downloaded updates,
    extracting info in the format munki expects. Returns an array of
    installeritems like those found in munki's InstallInfo.plist'''

    updatesdir = "/Library/Updates"
    updatesindex = os.path.join(updatesdir, "index.plist")
    if not os.path.exists(updatesindex):
        # no updates index, so bail
        return []

    suLastResultCode = softwareUpdatePrefs().get('LastResultCode')
    if suLastResultCode == 0:
        # successful and updates found
        pass
    elif suLastResultCode == 2:
        # no updates found/needed on last run
        return []
    elif suLastResultCode == 100:
        # couldn't contact the SUS on the most recent attempt.
        # see if the index.plist corresponds to the
        # LastSuccessfulDate
        lastSuccessfulDateString = str(
            softwareUpdatePrefs().get('LastSuccessfulDate', ''))
        if not lastSuccessfulDateString:
            # was never successful
            return []
        try:
            lastSuccessfulDate = NSDate.dateWithString_(
                                                    lastSuccessfulDateString)
        except (ValueError, TypeError):
            # bad LastSuccessfulDate string, bail
            return []
        updatesIndexDate = NSDate.dateWithTimeIntervalSince1970_(
                                              os.stat(updatesindex).st_mtime)
        secondsDiff = updatesIndexDate.timeIntervalSinceDate_(
                                                          lastSuccessfulDate)
        if abs(secondsDiff) > 30:
            # index.plist mod time doesn't correspond with LastSuccessfulDate
            return []
    else:
        # unknown LastResultCode
        return []

    # if we get here, either the LastResultCode was 0 or
    # the index.plist mod time was within 30 seconds of the LastSuccessfulDate
    # so the index.plist is _probably_ valid...
    infoarray = []
    plist = FoundationPlist.readPlist(updatesindex)
    if 'ProductPaths' in plist:
        products = plist['ProductPaths']
        for product_key in products.keys():
            updatename = products[product_key]
            installitem = os.path.join(updatesdir, updatename)
            if os.path.exists(installitem) and os.path.isdir(installitem):
                try:
                    (dist, generated_dist_path) = \
                        processSoftwareUpdateDownload(installitem)
                except AppleUpdateParseError, e:
                    munkicommon.display_error('%s' % e)
                else:
                    iteminfo = {}
                    iteminfo["installer_item"] = \
                        generated_dist_path[len(updatesdir)+1:]
                    iteminfo["name"] = dist['su_name']
                    iteminfo["description"] = (
                        dist['description'] or "Updated Apple software.")
                    iteminfo["version_to_install"] = dist['version']
                    iteminfo['display_name'] = dist['title']
                    iteminfo['installed_size'] = dist['installed_size']
                    restartAction = getRestartInfo(generated_dist_path)
                    if restartAction != "None":
                        iteminfo['RestartAction'] = restartAction
                    infoarray.append(iteminfo)

    return infoarray


def writeAppleUpdatesFile():
    '''Writes a file used by Managed Software Update.app to display
    available updates'''
    appleUpdates = getSoftwareUpdateInfo()
    if appleUpdates:
        plist = {}
        plist['AppleUpdates'] = appleUpdates
        FoundationPlist.writePlist(plist, appleUpdatesFile)
        return True
    else:
        try:
            os.unlink(appleUpdatesFile)
        except (OSError, IOError):
            pass
        return False


def displayAppleUpdateInfo():
    '''Prints Apple update information'''
    try:
        updatelist = FoundationPlist.readPlist(appleUpdatesFile)
    except FoundationPlist.FoundationPlistException:
        return
    else:
        appleupdates = updatelist.get('AppleUpdates', [])
        if len(appleupdates):
            munkicommon.display_info(
            "The following Apple Software Updates are available to install:")
        for item in appleupdates:
            munkicommon.display_info("    + %s-%s" %
                                        (item.get('display_name',''),
                                         item.get('version_to_install','')))
            if item.get('RestartAction') == 'RequireRestart' or \
               item.get('RestartAction') == 'RecommendRestart':
                munkicommon.display_info("       *Restart required")
                munkicommon.report['RestartRequired'] = True
            if item.get('RestartAction') == 'RequireLogout':
                munkicommon.display_info("       *Logout required")
                munkicommon.report['LogoutRequired'] = True


def appleSoftwareUpdatesAvailable(forcecheck=False, suppresscheck=False):
    '''Checks for available Apple Software Updates, trying not to hit the SUS
    more than needed'''

    if suppresscheck:
        # typically because we're doing a logout install; if
        # there are no waiting Apple Updates we shouldn't
        # trigger a check for them.
        pass
    elif forcecheck:
        # typically because user initiated the check from
        # Managed Software Update.app
        unused_retcode = checkForSoftwareUpdates()
    else:
        # have we checked recently?  Don't want to check with
        # Apple Software Update server too frequently
        now = NSDate.new()
        nextSUcheck = now
        lastSUcheckString = str(
            softwareUpdatePrefs().get('LastSuccessfulDate', ''))
        if lastSUcheckString:
            try:
                lastSUcheck = NSDate.dateWithString_(lastSUcheckString)
                interval = 24 * 60 * 60
                nextSUcheck = lastSUcheck.dateByAddingTimeInterval_(interval)
            except (ValueError, TypeError):
                pass
        if now.timeIntervalSinceDate_(nextSUcheck) >= 0:
            unused_retcode = checkForSoftwareUpdates()
        else:
            munkicommon.log('Skipping Apple Software Update check because '
                            'we last checked on %s...' % lastSUcheck)

    if writeAppleUpdatesFile():
        displayAppleUpdateInfo()
        return True
    else:
        return False


def clearAppleUpdateInfo():
    '''Clears Apple update info. Called after performing munki updates
    because the Apple updates may no longer be relevant.'''
    updatesindexfile = '/Library/Updates/index.plist'
    try:
        os.unlink(updatesindexfile)
        os.unlink(appleUpdatesFile)
    except (OSError, IOError):
        pass


def installAppleUpdates():
    '''Uses /usr/sbin/installer to install updates previously
    downloaded.'''

    restartneeded = False
    appleupdatelist = getSoftwareUpdateInfo()

    # did we find some Apple updates?
    if appleupdatelist:
        munkicommon.report['AppleUpdateList'] = appleupdatelist
        munkicommon.savereport()
        (restartneeded, unused_skipped_installs) = \
                installer.installWithInfo("/Library/Updates",
                                          appleupdatelist,
                                          applesus=True)
        if restartneeded:
            munkicommon.report['RestartRequired'] = True
        munkicommon.savereport()
        clearAppleUpdateInfo()

    return restartneeded



# define this here so we can access it in multiple functions
appleUpdatesFile = os.path.join(munkicommon.pref('ManagedInstallDir'),
                                'AppleUpdates.plist')


def main():
    '''Placeholder'''
    pass


if __name__ == '__main__':
    main()

