#!/usr/bin/python

'''
Wraps the ibtool commandline to generate nibs from .strings files.
An md5 checksum of the base nibs is stored in a Localize.ini file,
if a checksum for the file does not exist or the check does not match
a new localized nib is created.

Based on Philippe Casgrain's 'Automatically localize your nibs when building'
    http://developer.casgrain.com/?p=94

And Wil Shipley's 'Pimp My Code, Part 17: Lost in Translations'
    http://wilshipley.com/blog/2009/10/pimp-my-code-part-17-lost-in.html

Written by David Keegan for Murky
    https://bitbucket.org/snej/murky

Usage:
    Localize.py -help

    Localize nibs:
        Localize.py --from English --to "French|German" --nibs "MainMenu|Projects|Repo"

    Generate Strings:
        Localize.py --to English --genstrings "./**/*.[hm]"

    Use the '--utf8' flag to convert the strings files from utf-16 to utf-8.

The MIT License

Copyright David Keegan 2009-1010

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
'''

from __future__ import with_statement

import time
import codecs
import os, re
import sys, glob
import subprocess
from optparse import OptionParser
from shutil import copyfile

k_valueParse = re.compile('(?P<key>.+)=(?P<value>.+)$', re.UNICODE)
k_localizePath = os.path.abspath('Localize.ini')

class LocalizationError(Exception):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return str(self.value)

def detectEncoding(filepath):
    '''
    Try to detect the file's encoding.
    If it's not utf-16 assume it's utf-8, this should work for ascii
    files because the first 128 characters are the same...
    '''

    f = open(filepath, 'r')
    firstBytes = f.read(2)
    f.close()

    if firstBytes == codecs.BOM_UTF16_BE:
        return 'utf_16_be'
    elif firstBytes == codecs.BOM_UTF16_LE:
        return 'utf_16_le'
    #use sig just encase there is a BOM in the file
    return 'utf_8_sig'

def fileToUtf8(stringFile):
    '''
    Convert the .strings file from utf-16 to utf-8
    This will allow files diffs
    '''
    if os.path.isfile(stringFile):
        tempStrings = stringFile+'temp'
        stringsEncoding = detectEncoding(stringFile)
        #if the file is not already utf-8 re-encode it
        if stringsEncoding != 'utf_8_sig':
            fromFile = codecs.open(stringFile, 'rU', stringsEncoding)
            toFile = codecs.open(tempStrings, 'w', 'utf_8')
            for eachLine in fromFile:
                toFile.write(eachLine)

            toFile.close()
            fromFile.close()

            os.remove(stringFile)
            os.rename(tempStrings, stringFile)

def runCommand(command, args):
    '''Run shell commands'''
    commandAndArgs = '%s %s' % (command, args)
    proc = subprocess.Popen(commandAndArgs, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = proc.communicate()
    if proc.returncode:
        raise LocalizationError(commandAndArgs + ' : ' + stderr)
    return stdout

def md5(file):
    '''Get the md5 checksum of a file'''
    md5Sum = runCommand('/usr/bin/openssl md5', file)
    return md5Sum.split('=')[1].strip()

def langProjName(language):
    return language.strip()+'.lproj'

def nibToStringFileName(nibFile):
    return nibFile.rstrip('.xib')+'.strings'

def ibtoolsGenerateStringsFile(nibFile, utf8=False):
    '''
    Generate a .strings file from a nib
    If utf8 is True the .strings files will be re-encoded as utf-8
    '''
    nibFileStrings = nibToStringFileName(nibFile)
    runCommand('ibtool', '--generate-strings-file %s %s' % (nibFileStrings, nibFile))

    if utf8:
        fileToUtf8(nibFileStrings)

    print '  ', nibFileStrings, 'updated'

def ibtoolsWriteNib(fromFile, toFile, utf8=False):
    '''convert one localized nib from one language to another'''
    toStrings = nibToStringFileName(toFile)
    runCommand('ibtool', '--strings-file %s --write %s %s' % (toStrings, toFile, fromFile))

    if utf8:
        fileToUtf8(toStrings)

    print '  ', toFile, 'updated'

def genStrings(toLangs, globString, utf8=False):
    for eachToLang in toLangs:
        toLangLproj = langProjName(eachToLang)
        runCommand('genstrings', '-o %s %s' % (toLangLproj, globString))
        localizableStrings = os.path.join(toLangLproj, 'Localizable.strings')
        if utf8:
            fileToUtf8(localizableStrings)

        print '  ', localizableStrings, 'updated'

def getDict():
    '''Read the values from Localize.ini and return a dictionary'''
    localizeDict = {}
    if not os.path.isfile(k_localizePath):
        return localizeDict

    with open(k_localizePath, 'rU') as localizeFile:
        for line in localizeFile:
            line = line.strip()
            match = k_valueParse.match(line)
            if match:
                localizeDict[match.group('key')] = match.group('value')
    return localizeDict

def writeDict(dict):
    '''Write a dictionary to Localize.ini'''
    with open(k_localizePath, 'w') as localizeFile:
        for key, value in sorted(dict.iteritems()):
            localizeFile.write('%s=%s\n' % (key, value))

def localizeNibs(fromLang, toLangs, nibs=None, utf8=False, ignore=False):
    '''Localize nibs from one language to others'''

    #get the data from the ini file
    iniData = getDict()

    fromLangLproj = langProjName(fromLang)

    #if nibs is none, get all the nibs in the from language project
    if nibs is None:
        nibs = []
        for eachNib in glob.glob('%s/*.xib' % fromLangLproj):
            nibs.append(eachNib.lstrip(fromLangLproj+'/').rstrip('.xib'))

    for eachNib in nibs:
        eachNib = eachNib.strip()
        if not eachNib.endswith('.xib'):
            eachNib += '.xib'
        fromNib = os.path.join(fromLangLproj, eachNib)

        #get md5 and update the ini data
        fromNibMd5 = md5(fromNib)
        #check if the strings for the fromNib need to the updated
        if not os.path.isfile(nibToStringFileName(fromNib)) or fromNib not in iniData or iniData[fromNib] != fromNibMd5:
            ibtoolsGenerateStringsFile(fromNib, utf8)

        #write the localized nibs
        for eachToLang in toLangs:
            toLangLproj = langProjName(eachToLang)
            toNib = os.path.join(toLangLproj, eachNib)
            toStrings = nibToStringFileName(toNib)
            #if there is no localized string file for the nib copy it from the 'from language'
            if not os.path.isfile(toStrings):
                fromStrings = nibToStringFileName(fromNib)
                copyfile(fromStrings, toStrings)
            toStringsMd5 = md5(toStrings)
            if (not os.path.isfile(toNib) or fromNib not in iniData or iniData[fromNib] != fromNibMd5 or
                toStrings not in iniData or iniData[toStrings] != toStringsMd5):
                ibtoolsWriteNib(fromNib, toNib, utf8)
                iniData[toStrings] = toStringsMd5

        iniData[fromNib] = fromNibMd5

    #update Localize.ini
    writeDict(iniData)

if __name__ == '__main__':
    '''Command line options'''
    startTime = time.time()

    opts = OptionParser()
    opts.add_option('--from', '-f', dest='fromLang', help='The language to localize from.', metavar='LANG')
    opts.add_option('--to', '-t', dest='toLangs', help="An array of languages to localize to, separated by '|'.", metavar='LANGS')
    opts.add_option('--nibs', '-n', dest='nibs', help="An array of nibs to localize, separated by '|', .xib can be left off. If this flag is left out all the nibs in the from language will be used.", metavar='NIBS')
    opts.add_option('--utf8', '-u', dest='utf8', help='If this flag is present the .strings files will be re-encoded as utf-8.', action="store_true", default=False)
    opts.add_option('--ignore', '-i', dest='ignore', help='If this flag is present the md5 checksums will be ignored.', action="store_true", default=False)
    opts.add_option('--genstrings', '-g', dest='genstrings', help='File name or glob string. If this argument is present the genstrings command line will be called.', metavar='GLOB', default=None)
    options, arguments = opts.parse_args()

    if options.genstrings != None:
        genStrings(options.toLangs.split('|'), options.genstrings, options.utf8)
        print 'Strings updated in %.2f seconds' % (time.time()-startTime)
    else:
        nibs = options.nibs
        if nibs != None:
            nibs = options.nibs.split('|')
        localizeNibs(options.fromLang, options.toLangs.split('|'), nibs, options.utf8, options.ignore)
        print 'Nibs updated in %.2f seconds' % (time.time()-startTime)
