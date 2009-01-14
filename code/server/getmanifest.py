#!/usr/bin/env python
# encoding: utf-8
"""
getmanifest.py

Created by Greg Neagle on 2008-10-30.
A simple CGI.  Returns a text file of the same name
as the host, or as the arbitrary string passed to it:

http://webserver/cgi-bin/getmanifest.py?arbitrarystring

arbitrarystring could be the hostname, a UUID, a username...

You can call this from the client with getcatalog.py
This could be extended to do wildcard matching, or to
read another file that mapped hostnames/strings to catalog
files
"""

import os
import socket
import sys
import cgi
	
print "Content-type: text/plain"
print

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

# path to manifests: this is the local file path, not the web-relative
# path.  Must be readable by whatever process is running the CGI        
manifestdir = "/Library/WebServer/Documents/swrepo/catalogs"

manifest = os.path.join(manifestdir, hostname)
if os.path.exists(manifest):
    f = open(manifest, mode='r', buffering=1)
    if f:
        for line in f.readlines():
            print line
        f.close()
