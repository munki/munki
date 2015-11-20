#!/usr/bin/env python
# encoding: utf-8
# Copyright 2009 Greg Neagle.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# 
#      https://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
getmanifest.py

Created by Greg Neagle on 2008-10-30.
A simple CGI.  Returns a text file of the same name
as the host, or as the arbitrary string passed to it:

http://webserver/cgi-bin/getmanifest.py?arbitrarystring

arbitrarystring could be the hostname, a UUID, a username...

This could be extended to do wildcard matching, or to
read another file that mapped hostnames/strings to manifest
files
"""

import os
import socket
import sys
import cgi
import time
        
hostname = ""
if 'QUERY_STRING' in os.environ:
    hostname = os.environ['QUERY_STRING']
    
if hostname == "":
    ip = os.environ['HTTP_PC_REMOTE_ADDR']
    if ip == "":
         ip = os.environ['REMOTE_ADDR']
    try:
        lookup = socket.gethostbyaddr(ip)
        hostname = lookup[0]
    except:
        hostname = ip
        
# the manifestdir is a local path to wherever you keep the manifests;
# must be readable by the webserver process
manifestdir = "/Library/WebServer/Documents/repo/manifests"

manifest = os.path.join(manifestdir, hostname)
if os.path.exists(manifest):
    statinfo = os.stat(manifest)
    modtime = statinfo.st_mtime
    inode = statinfo.st_ino
    size = statinfo.st_size
    print "Content-type: text/plain"
    print "Content-length: %s" % size
    print "Last-modified:", time.strftime("%a, %d %b %Y %H:%M:%S GMT",time.gmtime(modtime))
    # Generate ETag the same way Apache does on OS X...
    print "ETag:", '"%s-%s-%s"' % (hex(int(inode))[2:], hex(int(size))[2:], hex(int(modtime))[2:])
    print

    f = open(manifest, mode='r', buffering=1)
    if f:
        for line in f.readlines():
            print line.rstrip('\n')
        f.close()
else:
    print "Content-type: text/plain"
    print "Content-length: 0"
    print
