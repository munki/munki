#!/usr/bin/env python
# encoding: utf-8
#
# Copyright 2009-2010 Greg Neagle.
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
makeChoices.py

Created by Greg Neagle on 2008-11-10.
"""

import sys
import os
import plistlib
import subprocess
import tempfile
import optparse

def getchoicestatus(p,choiceID):
    (enabled, selected) = (False, -2)
    for plitem in p:
        if choiceID == plitem['choiceIdentifier']:
            return (plitem['choiceIsEnabled'], plitem['choiceIsSelected'])
        else:
            (enabled, selected) = getchoicestatus(plitem['childItems'],
                                                                    choiceID)
            if selected <> -2:
                return (enabled, selected)
    return (enabled, selected)
    

def choiceItemHasChildren(p, choice):
    for item in p:
        if item['choiceIdentifier'] == choice:
            if len(item['childItems']):
                return 1
            else:
                return 0
        childreturn = choiceItemHasChildren(item['childItems'], choice)
        if childreturn != -1:
            return childreturn
    return -1
    
    
def getChoicesXML(pkgpath, target):
    cmd = ['/usr/sbin/installer', '-showChoicesXML', '-pkg', pkgpath, "-target", target]
    p = subprocess.Popen(cmd, shell=False, bufsize=1, stdin=subprocess.PIPE, 
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (plist, err) = p.communicate()
    if p.returncode == 0:
        if plist:
           return plistlib.readPlistFromString(plist)
           
    return ''
    
    
def OLDmakeChoiceForID(choicesxml, choiceID, desiredState, choiceArray):
    if choicesxml:
        (choiceEnabled, choiceSelected) = getchoicestatus(choicesxml,
                                                            choiceID)
        #print choiceID, choiceEnabled, choiceSelected
        if choiceSelected == -2:
            print >>sys.stderr, "%s is not a valid choice." % choiceID
            exit(1)
        # if choice is not enabled, we can't change it
        if choiceEnabled:
            if choiceSelected == desiredState:
                # no clicks needed
                return
            if not choiceSelected == -1:
                # current state is not mixed, so one click
                # to invert
                choiceArray.append(choiceID)
                return
            # current state is mixed
            if desiredState == 1:
                # one click to go from mixed to on
                choiceArray.append(choiceID)
                return
            else:
                # two clicks to go from mixed to off
                choiceArray.append(choiceID)
                choiceArray.append(choiceID)
                return
            
        else:
            if choiceSelected != desiredState:
                print >>sys.stderr, "Warning: Choice '%s' is not enabled; you cannot modify its selection state. Ignoring." % choiceID
                

def makeChoiceForID(choicesxml, choiceID, desiredState, choiceArray):
    choice = {}
    choice['attributeSetting'] = (desiredState!=0)
    choice['choiceAttribute'] = "selected"
    choice['choiceIdentifier'] = choiceID
    choiceArray.append(choice)
    return


def selectionInfo(enabled, selected, identifier, description):
    selChar = ' '
    required = ' '
    requiredText = ''
    if selected == 0:
        selChar = "O"
    if selected == 1:
        selChar = "X"
    if selected == -1:
        selChar = "-"
    if selected and not enabled:
        required = '!'
        requiredText = "REQUIRED"
    if not selected and not enabled:
        required = '!'
        requiredText = "NOT APPLICABLE"
    return "%s%s %s\t%s\t%s" % (required, selChar, identifier, requiredText, description)


#def getPkgInfo(path):
#    if path.startswith("file://localhost") and path.endswith('.pkg'):
#        p = path[16:]
#        if os.path.exists(p):
#            if os.path.isfile(p):             # new flat package
#                info = getPackageInfo.getFlatPackageInfo(p)
#            if os.path.isdir(p):              # bundle-style package
#                info = getPackageInfo.getBundlePackageInfo(p)
#            if len(info):
#                return info[0]
#    
#    return {}


def printchoices(p,indent,hideunselected=False,verbose=False):
    indentspace = "    "
    for plitem in p:
        choice = {}
        choice['Identifier'] = plitem['choiceIdentifier']
        choice['IsEnabled'] = plitem.get('choiceIsEnabled', False)
        choice['IsSelected'] = plitem.get('choiceIsSelected', False)
        choice['IsVisible'] = plitem.get('choiceIsVisible', False)
        choice['pkgPaths'] = plitem.get('pathsOfActivePackagesInChoice')
        if 'choiceDescription' in plitem:
            choice['Description'] = plitem['choiceDescription']
        else:
            choice['Description'] = ''
        
        if (not choice['IsSelected'] and hideunselected) or not choice['IsVisible']:
            pass
        else:
            print indentspace*indent, selectionInfo(choice['IsEnabled'],
                    choice['IsSelected'], choice['Identifier'].encode('UTF-8'), choice['Description'].encode('UTF-8'))
            if verbose:
                for item in choice['pkgPaths']:
                    print indentspace*(indent+1), item.encode('UTF-8')
                    #pkginfo = getPkgInfo(item)
                    #if pkginfo:
                        #print indentspace*(indent+1), "pkgid: %s\tversion: %s" % (pkginfo['id'], pkginfo['version'])
        
        if 'childItems' in plitem:        
            printchoices(plitem['childItems'],indent+1,hideunselected)               


def getTopLevelEnabledSelectedChoices(p):
    choicelist = []
    for plitem in p:
        if plitem['choiceIsEnabled'] and plitem['choiceIsSelected'] and plitem['choiceIsVisible'] and plitem['choiceIdentifier'] != '__ROOT_CHOICE_IDENT__':
            choicelist.append(plitem['choiceIdentifier'])
        if plitem['choiceIdentifier'] == '__ROOT_CHOICE_IDENT__':
            for item in plitem['childItems']:
                if item['choiceIsEnabled'] and item['choiceIsSelected'] and item['choiceIsVisible']:
                    choicelist.append(item['choiceIdentifier'])

    return choicelist


def main():
    p = optparse.OptionParser()
    p.set_usage("""Usage: %prog [options]
Examples: 
    %prog --pkg /path/to/some.pkg --listchoices
    %prog --pkg /path/to/some.pkg --doinstall CHOICEID
    %prog --pkg /path/to/some.pkg --doinstall CHOICEID1 --dontinstall CHOICEID2""")
    
    p.add_option("--pkg", help="Path to package.")
    p.add_option('--target', default='/', 
                    help="Installer target. Defaults to /")
    p.add_option("--doinstall", action="append", 
                    help="Optional choices to install.")
    p.add_option("--dontinstall", action="append", 
                    help="Optional choices not to install.")
    p.add_option('--onlyinstall', 
                    help="Deselects all available choices except this one, selects this choice.")
    p.add_option("--listchoices", action='store_true', 
                    help="List the available choices.")
    p.add_option("--listselectedchoices", action='store_true', 
                    help="List only the selected choices.")
    p.add_option('--verbose', action='store_true', help='More output.')
    
    # Get our options and our package path
    options, arguments = p.parse_args()
    if not options.pkg:
        print >>sys.stderr, "Must specify a package!"
        exit(1)
        
    choicesxml = getChoicesXML(options.pkg, options.target)
    if choicesxml == '':
        print >>sys.stderr, "Error getting choicesxml."
        exit(1)
        
    if options.listchoices:
        printchoices(choicesxml,0,False,options.verbose)
        exit(0)
    
    if options.listselectedchoices:
        printchoices(choicesxml,0,True,options.verbose)
        exit(0)
    
    choiceArray = []
    
    if options.onlyinstall:
        selectedChoices = getTopLevelEnabledSelectedChoices(choicesxml)
        for item in selectedChoices:
            if not item == options.onlyinstall:
                makeChoiceForID(choicesxml, item, 0, choiceArray)
        
        makeChoiceForID(choicesxml, options.onlyinstall, 1, choiceArray)
        
    else:
        if options.doinstall:
            for item in options.doinstall:
                makeChoiceForID(choicesxml, item, 1, choiceArray)
        if options.dontinstall:
            for item in options.dontinstall:
                makeChoiceForID(choicesxml, item, 0, choiceArray)
    
    mytmpdir = tempfile.mkdtemp()
    choicesxmlfile = os.path.join(mytmpdir, "choices.xml")
    plistlib.writePlist(choiceArray, choicesxmlfile)
    
    print "Current choices:"
    cmd = ['/usr/sbin/installer', '-showChoicesAfterApplyingChangesXML',
            choicesxmlfile, '-pkg', options.pkg, "-target", options.target]
    p = subprocess.Popen(cmd, shell=False, bufsize=1, stdin=subprocess.PIPE, 
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (plist, err) = p.communicate()
    if p.returncode == 0:
        if plist:
            pl = plistlib.readPlistFromString(plist)
            printchoices(pl,0,False,options.verbose)
    else:
        print >>sys.stderr, err
        
    print "choicesxmlfile at:", choicesxmlfile
    


if __name__ == '__main__':
    main()

