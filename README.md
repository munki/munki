munki
=====

_Managed software installation for OS X_

####Introduction

Munki is a set of tools that, used together with a webserver-based repository of packages and package metadata, can be used by OS X administrators to manage software installs (and in many cases removals) on OS X client machines.

Munki can install software packaged in the Apple package format, and also supports Adobe CS3/CS4/CS5/CS6 Enterprise Deployment "packages", and drag-and-drop disk images as installer sources.

Additionally, Munki can be configured to install Apple Software Updates, either from Apple's server, or yours.

Munki is currently in use at organizations all over the world, managing software for tens of thousands of Macs.

####Get started

Get started with Munki here: [Getting Started with Munki](https://github.com/munki/munki/wiki/)

Check out the Wiki for some notes and documentation, and browse and/or check out the source. See the [releases page](https://github.com/munki/munki/releases) for pre-built installer packages of supported releases, or [munkibuilds.org](https://munkibuilds.org) for packages built from the current Git revision, which may contain development, testing, or work-in-progress code.

####Get help

If you have questions, or need additional help getting started, the [munki-discuss](https://groups.google.com/group/munki-discuss) group is the best place to start. Please don't post support questions as comments on wiki documentation pages, or as GitHub code issues.

Issues with MunkiWebAdmin should be discussed in its group: [munki-web-admin](https://groups.google.com/group/munki-web-admin).

![](https://github.com/munki/munki/wiki/images/managed_software_center.png)

###Announcement
An exploit has been discovered against Munki tools older than version 2.1.

Untrusted input can be passed to the curl binary, causing arbitrary files to be downloaded to arbitrary locations.

Recommendation is to update to Munki 2.1 or later, which is not susceptible to this exploit, as version 2.1 and later no longer use the curl binary for http/https communication.

This vulnerability has been assigned a CVE ID: CVE-2015-2211

If you cannot update to Munki 2.1, there is a patch for Munki 2.0.1 here:
https://github.com/munki/munki/releases/tag/v2.0.1.2254

And another for Munki 1.0.0 here:
https://github.com/munki/munki/releases/tag/v1.0.0.1896.0
